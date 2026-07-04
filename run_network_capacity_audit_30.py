"""Audit 30-bus benchmark timings under standard and relaxed PTDF limits.

Scenario:
  - relaxed: PTDF network retained, but line limits set to a very large value

The paper main case uses congestion="tight" (= 1.3 * rateA for case30).  This
audit keeps separate outputs so it does not overwrite paper-main artifacts.
"""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path

import numpy as np

from benchmarks.comparison_runner import run_comparison
from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.schedule_run import ScheduleRunMILP
from models.generator import load_all_case30ww_generators
from models.network import build_ptdf_network_from_case30ww
from run_experiments import apply_load_scenario, apply_ramp_scenario


OUT_DIR = Path("results/network_capacity_audit_30_seg3")
METHODS = ["lmp", "mirp", "level", "dwp", "dwp_incremental", "xiao"]
ORDER = ["lmp", "mirp", "level", "dwp", "dwp_incremental", "xiao", "chp"]
LABELS = {
    "lmp": "LMP",
    "mirp": "IRP",
    "level": "LVM",
    "dwp": "DWP",
    "dwp_incremental": "DWP-inc",
    "xiao": "S-CHP",
    "chp": "D-CHP",
}


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _line_stats(network, p_dispatch: np.ndarray) -> dict:
    flow = network.PTDF_Gen @ p_dispatch - network.PTDF @ network.demand
    denom = np.maximum(network.F_max[:, None], 1e-9)
    util = np.abs(flow) / denom
    return {
        "max_line_utilization": float(util.max()),
        "near_binding_line_hours": int(np.sum(util >= 0.999)),
        "binding_line_hours_1e_5": int(np.sum(np.abs(np.abs(flow) - network.F_max[:, None]) <= 1e-5)),
    }


def _scenario_network(name: str):
    if name == "relaxed":
        return build_ptdf_network_from_case30ww(T=24, congestion="relaxed")
    raise ValueError(name)


def run_scenario(name: str) -> tuple[list[dict], list[dict]]:
    gens = load_all_case30ww_generators(T=24, n_segments=3)
    gens = apply_ramp_scenario(gens, "base")
    network = _scenario_network(name)
    network = apply_load_scenario(network, "base")

    try:
        milp = ScheduleRunMILP(gens, network)
        p_dispatch, u_dispatch, milp_obj = milp.solve()
    except Exception as exc:
        return (
            [
                {
                    "scenario": name,
                    "method": "",
                    "label": "",
                    "status": f"schedule_infeasible_or_failed: {type(exc).__name__}: {exc}",
                }
            ],
            [],
        )

    stats = _line_stats(network, p_dispatch)
    chp = PrimalCHPLP(gens, network)
    t0 = time.time()
    chp_lmp, chp_obj, ok = chp.solve()
    chp_time = time.time() - t0
    if not ok:
        raise RuntimeError(f"D-CHP failed in scenario {name}")

    results = run_comparison(
        generators=gens,
        network=network,
        p_dispatch=p_dispatch,
        u_dispatch=u_dispatch,
        milp_obj=milp_obj,
        chp_lp_obj=chp_obj,
        chp_lmp_matrix=chp_lmp,
        chp_uplifts=[],
        chp_ptdf_alpha=chp._ptdf_alpha,
        chp_ptdf_beta_=chp._ptdf_beta_,
        methods=METHODS,
        lr_max_iter=500,
        lr_verbose=False,
        chp_solve_time=chp_time,
    )

    rows: list[dict] = []
    hist_rows: list[dict] = []
    for method in ORDER:
        if method not in results:
            continue
        r = results[method]
        rows.append(
            {
                "scenario": name,
                "method": method,
                "label": LABELS[method],
                "status": "ok",
                "milp_obj": milp_obj,
                "pricing_obj": r.get("pricing_obj", ""),
                "duality_gap": r.get("duality_gap", ""),
                "gen_uplift": r.get("gen_uplift", ""),
                "ftr_cost": r.get("ftr_cost", ""),
                "total_uplift": r.get("total_uplift", ""),
                "settlement_error": (
                    abs(float(r["total_uplift"]) - float(r["duality_gap"]))
                    if math.isfinite(float(r.get("duality_gap", float("nan"))))
                    else ""
                ),
                "time_s": r.get("solve_time", ""),
                "n_iter": r.get("n_iter", ""),
                "n_columns": r.get("n_columns", ""),
                "converged": r.get("converged", ""),
                "stop_reason": r.get("stop_reason", ""),
                "n_states": r.get("n_states", ""),
                "n_arcs": r.get("n_arcs", ""),
                **stats,
            }
        )
        history = r.get("history", {})
        if method == "level":
            for item in history:
                hist_rows.append(
                    {
                        "scenario": name,
                        "method": method,
                        "iteration": item["iter"],
                        "elapsed_s": item["elapsed_s"],
                        "objective": item["best_dual"],
                        "gap_to_d_chp": float(chp_obj) - float(item["best_dual"]),
                    }
                )
        elif method in {"dwp", "dwp_incremental"}:
            for item in history:
                obj = float(
                    item.get(
                        "best_certified_dual",
                        item.get("certified_lower_bound", item.get("dual_bound", np.nan)),
                    )
                )
                hist_rows.append(
                    {
                        "scenario": name,
                        "method": method,
                        "iteration": item["iter"],
                        "elapsed_s": item.get("elapsed_s", ""),
                        "objective": obj,
                        "gap_to_d_chp": float(chp_obj) - obj,
                        "rmp_obj": item.get("rmp_obj", ""),
                        "min_reduced_cost": item.get("min_reduced_cost", ""),
                        "columns": item.get("columns", ""),
                    }
                )
    return rows, hist_rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    all_hist: list[dict] = []
    for scenario in ["relaxed"]:
        rows, hist = run_scenario(scenario)
        all_rows.extend(rows)
        all_hist.extend(hist)
        _write_csv(OUT_DIR / f"summary_{scenario}.csv", rows)
        _write_csv(OUT_DIR / f"history_{scenario}.csv", hist)
    _write_csv(OUT_DIR / "summary_all.csv", all_rows)
    _write_csv(OUT_DIR / "history_all.csv", all_hist)
    print(f"Saved network capacity audit under {OUT_DIR}")


if __name__ == "__main__":
    main()
