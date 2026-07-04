"""Run the current 30-bus fmax-scale benchmark and export paper-style plots.

This script intentionally writes to a dated current-results directory instead of
``results/paper_main`` so older paper artifacts are not mixed with the current
data revision.  Only the segment-3 paper methods are exported.
"""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np

from benchmarks.comparison_runner import run_comparison
from benchmarks.comparison_runner import compute_milp_line_flows
from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.schedule_run import ScheduleRunMILP
from run_experiments import (
    apply_initial_conditions,
    apply_load_scenario,
    apply_ramp_scenario,
    derive_warm_start_initial_conditions,
    load_case,
)


CASE_TAG = "30base"
CONGESTION = "tight"
FMAX_SCALE = 1.0
WARM_START_FROM_UC = True
WARMUP_LOAD_FACTOR = 0.98

OUT_DIR = Path("results/current_30base_seg3")
FIG_DIR = OUT_DIR / "figures"

METHODS = ["lmp", "mirp", "level", "lrp", "dwp", "xiao"]
METHOD_LABEL = {
    "lmp": "LMP",
    "mirp": "IRP",
    "level": "LVM",
    "lrp": "LRP",
    "dwp": "DWP",
    "xiao": "S-CHP",
    "chp": "D-CHP",
}
PLOT_ORDER = ["lmp", "mirp", "level", "lrp", "dwp", "xiao", "chp"]
ITERATIVE_METHODS = ["level", "lrp", "dwp"]
GEN_LABELS = ["G1", "G2", "G3", "G4", "G5", "G6"]


def _write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fmt_money(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "--"


def _fmt_float(value, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "--"


def _fmt_int(value) -> str:
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return "--"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_benchmark_table(rows: list[dict]) -> None:
    lines = [
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        r"Method & $C^{\mathrm{LP}}$ (\$) & Gen. LOC (\$) & FTR (\$) & Total uplift (\$) & Time (s) & Iter. \\",
        r"\midrule",
    ]
    for row in rows:
        iter_text = _fmt_int(row.get("n_iter")) if row.get("n_iter") not in ("", None) else "--"
        lines.append(
            " & ".join(
                [
                    str(row["label"]),
                    _fmt_money(row.get("pricing_obj")),
                    _fmt_money(row.get("gen_uplift")),
                    _fmt_money(row.get("ftr_cost")),
                    _fmt_money(row.get("total_uplift")),
                    _fmt_float(row.get("time_s"), 2),
                    iter_text,
                ]
            )
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    _write_text(OUT_DIR / f"table_benchmark_results_{CASE_TAG}.tex", "\n".join(lines))


def _write_unit_loc_table(rows: list[dict], method: str = "chp") -> None:
    selected = [row for row in rows if row.get("method") == method]
    lines = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Unit & Scheduled profit (\$) & Best-response profit (\$) & LOC (\$) \\",
        r"\midrule",
    ]
    for row in selected:
        lines.append(
            " & ".join(
                [
                    str(row["unit"]),
                    _fmt_money(row.get("scheduled_profit")),
                    _fmt_money(row.get("best_response_profit")),
                    _fmt_money(row.get("loc")),
                ]
            )
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    _write_text(OUT_DIR / f"table_unit_profit_loc_{CASE_TAG}.tex", "\n".join(lines))


def _write_ramping_table(rows: list[dict]) -> None:
    lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Ramping case & S-CHP states & S-CHP arcs & D-CHP intervals & Arc growth & Time S/D (s) \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(
            " & ".join(
                [
                    str(row["ramping_case"]),
                    _fmt_int(row.get("s_chp_states")),
                    _fmt_int(row.get("s_chp_transition_arcs")),
                    _fmt_int(row.get("d_chp_on_intervals")),
                    f"{_fmt_float(row.get('s_chp_arc_growth'), 1)}$\\times$",
                    f"{_fmt_float(row.get('s_chp_time_s'), 2)}/{_fmt_float(row.get('d_chp_time_s'), 2)}",
                ]
            )
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    _write_text(OUT_DIR / f"table_ramping_diagnostic_{CASE_TAG}.tex", "\n".join(lines))


def _history_rows(method: str, history, exact_value: float) -> list[dict]:
    rows: list[dict] = []
    if method == "level":
        for item in history:
            obj = float(item["best_dual"])
            rows.append(
                {
                    "method": method,
                    "iteration": item["iter"],
                    "elapsed_s": item["elapsed_s"],
                    "objective": obj,
                    "gap_to_exact": exact_value - obj,
                    "trace": "best_level_dual",
                    "upper_bound": item.get("upper_bound", ""),
                    "rel_gap": item.get("rel_gap", ""),
                }
            )
    elif method == "lrp":
        iters = history.get("iter", [])
        elapsed = history.get("elapsed_s", [])
        best_dual = history.get("best_dual", history.get("dual_bound", []))
        grad_norm = history.get("grad_norm", [])
        step = history.get("step", [])
        for idx, k in enumerate(iters):
            obj = float(best_dual[idx])
            rows.append(
                {
                    "method": method,
                    "iteration": k,
                    "elapsed_s": elapsed[idx] if idx < len(elapsed) else "",
                    "objective": obj,
                    "gap_to_exact": exact_value - obj,
                    "trace": "best_lagrangian_dual",
                    "grad_norm": grad_norm[idx] if idx < len(grad_norm) else "",
                    "step": step[idx] if idx < len(step) else "",
                }
            )
    elif method == "dwp":
        for item in history:
            obj = float(
                item.get(
                    "best_certified_dual",
                    item.get("certified_lower_bound", item["dual_bound"]),
                )
            )
            rows.append(
                {
                    "method": method,
                    "iteration": item["iter"],
                    "elapsed_s": item.get("elapsed_s", ""),
                    "objective": obj,
                    "gap_to_exact": exact_value - obj,
                    "trace": "best_certified_dual",
                    "rmp_obj": item.get("rmp_obj", ""),
                    "min_reduced_cost": item.get("min_reduced_cost", ""),
                    "columns": item.get("columns", ""),
                }
            )
    return rows


def _generator_rows(gens) -> list[dict]:
    rows = []
    for idx, g in enumerate(gens):
        rows.append(
            {
                "unit": GEN_LABELS[idx] if idx < len(GEN_LABELS) else f"G{idx+1}",
                "bus": g.node_bus,
                "Pmin_MW": g.P_min,
                "Pmax_MW": g.P_max,
                "R_up_MW_h": g.R_up,
                "R_down_MW_h": g.R_down,
                "SU_ramp_MW": g.SU_ramp,
                "SD_ramp_MW": g.SD_ramp,
                "min_up_h": g.T_on_min,
                "min_down_h": g.T_off_min,
                "online_cost_per_h": g.cost_nl,
                "startup_cost": g.cost_su,
                "shutdown_cost": g.cost_sd,
                "pwl_slopes": ";".join(f"{x:.6g}" for x in g.pwl_slopes),
                "pwl_widths": ";".join(f"{x:.6g}" for x in g.pwl_widths),
                "initial_status": g.initial_status,
                "initial_power_MW": g.initial_power,
                "initial_up_time_h": g.initial_up_time,
                "initial_down_time_h": g.initial_down_time,
            }
        )
    return rows


def _summary_rows(results: dict, milp_obj: float) -> list[dict]:
    rows = []
    for method in PLOT_ORDER:
        if method not in results:
            continue
        r = results[method]
        rows.append(
            {
                "method": method,
                "label": METHOD_LABEL.get(method, method),
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
            }
        )
    return rows


def _export_price_data(gens, p_dispatch, results: dict) -> list[dict]:
    rows = []
    for i, g in enumerate(gens):
        unit = GEN_LABELS[i] if i < len(GEN_LABELS) else f"G{i+1}"
        bus_idx = g.node_bus - 1
        for method in PLOT_ORDER:
            if method not in results:
                continue
            lmp_matrix = results[method]["lmp_matrix"]
            for t in range(g.T):
                rows.append(
                    {
                        "hour": t + 1,
                        "unit": unit,
                        "bus": g.node_bus,
                        "method": method,
                        "label": METHOD_LABEL.get(method, method),
                        "price": float(lmp_matrix[bus_idx, t]),
                        "scheduled_output_MW": float(p_dispatch[i, t]),
                    }
                )
    return rows


def _unit_profit_rows(results: dict) -> list[dict]:
    rows = []
    for method in PLOT_ORDER:
        if method not in results:
            continue
        per_unit = results[method].get("per_unit", {})
        sched = per_unit.get("disp_profits", [])
        best = per_unit.get("max_profits", [])
        loc = per_unit.get("uplifts", [])
        for i in range(min(len(sched), len(best), len(loc))):
            rows.append(
                {
                    "method": method,
                    "label": METHOD_LABEL.get(method, method),
                    "unit": GEN_LABELS[i] if i < len(GEN_LABELS) else f"G{i+1}",
                    "scheduled_profit": float(sched[i]),
                    "best_response_profit": float(best[i]),
                    "loc": float(loc[i]),
                }
            )
    return rows


def _schedule_summary_rows(gens, p_dispatch, u_dispatch) -> list[dict]:
    rows = []
    for i, g in enumerate(gens):
        u = np.asarray(u_dispatch[i, :], dtype=float)
        p = np.asarray(p_dispatch[i, :], dtype=float)
        prev = float(g.initial_status)
        stops = 0
        starts = 0
        for val in u:
            on = float(val) > 0.5
            if on and prev < 0.5:
                starts += 1
            if (not on) and prev > 0.5:
                stops += 1
            prev = 1.0 if on else 0.0
        rows.append(
            {
                "unit": GEN_LABELS[i] if i < len(GEN_LABELS) else f"G{i+1}",
                "initial_status": g.initial_status,
                "initial_power_MW": g.initial_power,
                "hours_on": int(np.sum(u > 0.5)),
                "energy_MWh": float(np.sum(p)),
                "starts": starts,
                "stops": stops,
                "max_output_MW": float(np.max(p)),
            }
        )
    return rows


def _line_utilization_rows(network, p_dispatch) -> list[dict]:
    if getattr(network, "is_single_node", False):
        return []
    flows = compute_milp_line_flows(network, p_dispatch)
    if flows.size == 0:
        return []
    limits = np.asarray(network.F_max, dtype=float)
    loading = np.abs(flows) / limits[:, None]
    max_idx = np.unravel_index(int(np.argmax(loading)), loading.shape)
    binding_tol = 1e-5
    return [
        {
            "max_loading_pct": 100.0 * float(loading[max_idx]),
            "critical_line": int(max_idx[0] + 1),
            "critical_hour": int(max_idx[1] + 1),
            "critical_flow_MW": float(flows[max_idx]),
            "critical_limit_MW": float(limits[max_idx[0]]),
            "binding_line_hours": int(np.sum(loading >= 1.0 - binding_tol)),
        }
    ]


def _plot_price_profiles(price_rows: list[dict]) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    by_unit = {unit: [] for unit in GEN_LABELS}
    for row in price_rows:
        by_unit.setdefault(row["unit"], []).append(row)

    colors = {
        "lmp": "#4d4d4d",
        "mirp": "#0072B2",
        "level": "#009E73",
        "lrp": "#CC79A7",
        "dwp": "#D55E00",
        "xiao": "#56B4E9",
        "chp": "#000000",
    }
    styles = {
        "lmp": (0, (1, 1)),
        "mirp": "--",
        "level": "-.",
        "lrp": (0, (3, 1, 1, 1)),
        "dwp": "-",
        "xiao": (0, (2, 2)),
        "chp": "-",
    }
    markers = {
        "lmp": "o",
        "mirp": "s",
        "level": "^",
        "lrp": "v",
        "dwp": "D",
        "xiao": "x",
        "chp": ".",
    }

    fig, axes = plt.subplots(2, 3, figsize=(10.8, 4.9), sharex=True)
    axes = axes.ravel()
    hours = np.arange(1, 25)
    legend_handles = []
    legend_labels = []

    for ax, unit in zip(axes, GEN_LABELS):
        rows = by_unit.get(unit, [])
        ax2 = ax.twinx()
        output = None
        for method in PLOT_ORDER:
            mrows = [r for r in rows if r["method"] == method]
            if not mrows:
                continue
            mrows = sorted(mrows, key=lambda r: int(r["hour"]))
            price = np.array([float(r["price"]) for r in mrows])
            line, = ax.plot(
                hours,
                price,
                color=colors[method],
                linestyle=styles[method],
                marker=markers[method],
                markersize=3.0,
                linewidth=1.15 if method != "chp" else 1.55,
                markevery=3,
                label=METHOD_LABEL[method],
                zorder=4 if method in {"xiao", "chp"} else 2,
            )
            if METHOD_LABEL[method] not in legend_labels:
                legend_handles.append(line)
                legend_labels.append(METHOD_LABEL[method])
            if output is None:
                output = np.array([float(r["scheduled_output_MW"]) for r in mrows])

        if output is not None:
            ax2.step(hours, output, where="mid", color="#777777", linewidth=1.15, alpha=0.55)
            max_output = float(np.max(output))
            if max_output <= 1e-8:
                ax2.set_ylim(0.0, 1.0)
                ax2.set_yticks([0.0, 1.0])
            else:
                ax2.set_ylim(0.0, 1.10 * max_output)
        ax.set_title(unit, fontsize=9)
        ax.grid(True, linewidth=0.3, alpha=0.35)
        ax.set_xlim(1, 24)
        ax.tick_params(labelsize=8)
        ax2.tick_params(labelsize=8, colors="#666666")
        if ax in axes[::3]:
            ax.set_ylabel("Price ($/MWh)", fontsize=8)
        if ax in axes[2::3]:
            ax2.set_ylabel("Output (MW)", fontsize=8, color="#666666")

    fig.legend(
        legend_handles,
        legend_labels,
        loc="upper center",
        ncol=6,
        fontsize=8,
        frameon=False,
        bbox_to_anchor=(0.5, 1.02),
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(FIG_DIR / f"prices_schedule_all_units_{CASE_TAG}_seg3.pdf", bbox_inches="tight")
    fig.savefig(FIG_DIR / f"prices_schedule_all_units_{CASE_TAG}_seg3.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def _plot_convergence(summary_rows: list[dict], history_rows: list[dict], exact_value: float) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in history_rows:
        try:
            t = float(r["elapsed_s"])
            y = float(r["objective"])
        except (TypeError, ValueError):
            continue
        rows.append({**r, "elapsed_s": t, "objective": y})
    for r in summary_rows:
        method = r["method"]
        if method in ITERATIVE_METHODS:
            continue
        try:
            t = float(r["time_s"])
            y = float(r["pricing_obj"])
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "method": method,
                "iteration": 1,
                "elapsed_s": t,
                "objective": y,
                "gap_to_exact": y - exact_value,
                "trace": "one_shot_objective",
            }
        )
    _write_csv(OUT_DIR / f"convergence_profiles_{CASE_TAG}.csv", rows)

    colors = {
        "level": "#009E73",
        "lrp": "#CC79A7",
        "dwp": "#D55E00",
        "lmp": "#4d4d4d",
        "mirp": "#0072B2",
        "xiao": "#56B4E9",
        "chp": "#000000",
    }
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    xmax = max(float(r["elapsed_s"]) for r in rows) * 1.03

    final_offsets = {
        "level": (8, -15),
        "lrp": (8, 12),
        "dwp": (-42, 8),
    }
    for method in ITERATIVE_METHODS:
        mrows = sorted([r for r in rows if r["method"] == method], key=lambda r: float(r["elapsed_s"]))
        if not mrows:
            continue
        ax.plot(
            [float(r["elapsed_s"]) for r in mrows],
            [float(r["objective"]) for r in mrows],
            label=METHOD_LABEL[method],
            color=colors[method],
            linewidth=1.35,
            marker="o",
            markersize=2.2,
            markevery=max(1, len(mrows) // 12),
        )
        last = mrows[-1]
        ax.annotate(
            f"{METHOD_LABEL[method]} {float(last['elapsed_s']):.1f}s",
            xy=(float(last["elapsed_s"]), float(last["objective"])),
            xytext=final_offsets.get(method, (6, 6)),
            textcoords="offset points",
            fontsize=7,
            color=colors[method],
        )

    one_shot_offsets = {
        "lmp": (8, 12),
        "mirp": (8, -20),
        "xiao": (8, 24),
        "chp": (10, 12),
    }
    for method in ["lmp", "mirp", "xiao", "chp"]:
        mrows = [r for r in rows if r["method"] == method]
        if not mrows:
            continue
        r = mrows[0]
        t = float(r["elapsed_s"])
        y = float(r["objective"])
        ax.scatter([t], [y], color=colors[method], s=34, zorder=5, label=METHOD_LABEL[method])
        ax.hlines(y, t, xmax, color=colors[method], linestyle="--", linewidth=0.9, alpha=0.65)
        ax.annotate(
            f"{METHOD_LABEL[method]} {t:.2f}s",
            xy=(t, y),
            xytext=one_shot_offsets.get(method, (5, 4)),
            textcoords="offset points",
            fontsize=7,
            color=colors[method],
        )

    visible = []
    for r in summary_rows:
        try:
            visible.append(float(r["pricing_obj"]))
        except (TypeError, ValueError):
            pass
    visible.append(exact_value)
    upper_gap = max(500.0, max((v - exact_value for v in visible), default=0.0) * 1.15)
    lower_gap = max(500.0, max((exact_value - v for v in visible), default=0.0) * 2.0)
    ax.axhline(exact_value, color="#111111", linewidth=0.8, alpha=0.65)
    ax.set_xlim(left=0, right=xmax)
    ax.set_ylim(exact_value - lower_gap, exact_value + upper_gap)
    ax.set_xlabel("Cumulative time (s)")
    ax.set_ylabel("Pricing objective ($)")
    ax.grid(True, linewidth=0.35, alpha=0.35)
    ax.legend(ncol=2, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / f"convergence_time_{CASE_TAG}_seg3.pdf", bbox_inches="tight")
    fig.savefig(FIG_DIR / f"convergence_time_{CASE_TAG}_seg3.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def _count_on_intervals(chp: PrimalCHPLP) -> int:
    return int(sum(dag.n_on for dag in chp.dags))


def _run_case(ramp_scenario: str, methods: list[str]) -> tuple:
    gens, network = load_case("30", "ptdf", 24, 3, congestion=CONGESTION, fmax_scale=FMAX_SCALE)
    gens = apply_ramp_scenario(gens, ramp_scenario)
    network = apply_load_scenario(network, "base")
    if WARM_START_FROM_UC:
        u0, p0, on_time, off_time = derive_warm_start_initial_conditions(
            "30",
            "ptdf",
            3,
            CONGESTION,
            FMAX_SCALE,
            ramp_scenario=ramp_scenario,
            load_scenario="base",
            warmup_load_factor=WARMUP_LOAD_FACTOR,
        )
        gens = apply_initial_conditions(gens, u0, p0, on_time, off_time)

    milp = ScheduleRunMILP(gens, network)
    p_dispatch, u_dispatch, milp_obj = milp.solve()

    chp = PrimalCHPLP(gens, network)
    t0 = time.time()
    chp_lmp, chp_obj, ok = chp.solve()
    chp_solve_time = time.time() - t0
    if not ok:
        raise RuntimeError(f"D-CHP LP failed for ramp scenario {ramp_scenario}")

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
        methods=methods,
        lr_max_iter=500,
        lr_verbose=False,
        chp_solve_time=chp_solve_time,
    )
    return gens, network, p_dispatch, u_dispatch, milp_obj, chp_obj, chp, results


def _ramping_diagnostic_rows(base_results: dict, base_chp: PrimalCHPLP) -> list[dict]:
    _, _, _, _, _, _, hetero_chp, hetero_results = _run_case("heterogeneous", ["xiao"])

    cases = [
        ("base", base_results, base_chp),
        ("heterogeneous", hetero_results, hetero_chp),
    ]
    base_xiao_arcs = float(base_results["xiao"].get("n_arcs", 0.0))
    rows = []
    for name, results, chp in cases:
        xiao = results["xiao"]
        dchp = results["chp"]
        xiao_arcs = float(xiao.get("n_arcs", 0.0))
        rows.append(
            {
                "ramping_case": name,
                "s_chp_states": xiao.get("n_states", ""),
                "s_chp_transition_arcs": xiao.get("n_arcs", ""),
                "d_chp_on_intervals": _count_on_intervals(chp),
                "s_chp_arc_growth": (
                    xiao_arcs / base_xiao_arcs if base_xiao_arcs > 0 else ""
                ),
                "s_chp_time_s": xiao.get("solve_time", ""),
                "d_chp_time_s": dchp.get("solve_time", ""),
                "s_chp_total_uplift": xiao.get("total_uplift", ""),
                "d_chp_total_uplift": dchp.get("total_uplift", ""),
            }
        )
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    gens, network, p_dispatch, u_dispatch, milp_obj, chp_obj, chp, results = _run_case(
        "base", METHODS
    )

    _write_csv(OUT_DIR / f"generator_params_{CASE_TAG}.csv", _generator_rows(gens))
    _write_csv(OUT_DIR / f"schedule_summary_{CASE_TAG}.csv", _schedule_summary_rows(gens, p_dispatch, u_dispatch))
    _write_csv(OUT_DIR / f"line_utilization_audit_{CASE_TAG}.csv", _line_utilization_rows(network, p_dispatch))

    summary = _summary_rows(results, milp_obj)
    _write_csv(OUT_DIR / f"benchmark_summary_{CASE_TAG}.csv", summary)
    _write_benchmark_table(summary)

    unit_rows = _unit_profit_rows(results)
    _write_csv(OUT_DIR / f"unit_level_profit_loc_{CASE_TAG}.csv", unit_rows)
    _write_unit_loc_table(unit_rows)

    history = []
    for method, result in results.items():
        history.extend(_history_rows(method, result.get("history", {}), float(chp_obj)))
    _write_csv(OUT_DIR / f"iterative_history_{CASE_TAG}.csv", history)

    price_rows = _export_price_data(gens, p_dispatch, results)
    _write_csv(OUT_DIR / f"prices_schedule_all_units_{CASE_TAG}.csv", price_rows)

    _plot_price_profiles(price_rows)
    _plot_convergence(summary, history, float(chp_obj))
    ramping_rows = _ramping_diagnostic_rows(results, chp)
    _write_csv(OUT_DIR / f"ramping_diagnostic_{CASE_TAG}.csv", ramping_rows)
    _write_ramping_table(ramping_rows)

    print(f"Saved current 30-bus {CONGESTION} segment-3 outputs under {OUT_DIR}")


if __name__ == "__main__":
    main()
