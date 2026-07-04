from __future__ import annotations

import argparse
import csv
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.schedule_run import ScheduleRunMILP
from models.network import PTDFNetwork
from run_experiments import (
    apply_initial_conditions,
    apply_load_scale,
    apply_ramp_scenario,
    load_case,
    _build_two_day_warmup_network,
    _extract_initial_conditions,
)


def subset_network(network: PTDFNetwork, lines: np.ndarray, coeff_tol: float = 0.0) -> PTDFNetwork:
    lines = np.asarray(lines, dtype=int)
    ptdf = np.asarray(network.PTDF[lines, :], dtype=float).copy()
    ptdf_gen = np.asarray(network.PTDF_Gen[lines, :], dtype=float).copy()
    if coeff_tol > 0:
        ptdf[np.abs(ptdf) < coeff_tol] = 0.0
        ptdf_gen[np.abs(ptdf_gen) < coeff_tol] = 0.0
    return PTDFNetwork(
        demand_matrix=network.demand,
        PTDF=ptdf,
        F_max=network.F_max[lines],
        gen_bus_map=[network.gen_bus_idx(i) for i in range(network.PTDF_Gen.shape[1])],
        PTDF_Gen=ptdf_gen,
    )


def full_flow(network: PTDFNetwork, p_dispatch: np.ndarray) -> np.ndarray:
    return network.PTDF_Gen @ p_dispatch - network.PTDF @ network.demand


def warm_start_gens(gens, network: PTDFNetwork):
    warm_net = _build_two_day_warmup_network(network, 0.98)
    warm_gens = [replace(g, T=48) for g in gens]
    p48, u48, _ = ScheduleRunMILP(warm_gens, warm_net).solve()
    u0, p0, on_time, off_time = _extract_initial_conditions(p48, u48, 23)
    return apply_initial_conditions(gens, u0, p0, on_time, off_time)


def candidate_lines_from_schedule(network: PTDFNetwork, p_dispatch: np.ndarray, threshold: float, min_lines: int):
    flows = full_flow(network, p_dispatch)
    util = np.abs(flows) / np.maximum(network.F_max[:, None], 1e-9)
    max_util = util.max(axis=1)
    lines = np.flatnonzero(max_util >= threshold)
    if len(lines) < min_lines:
        lines = np.argsort(-max_util)[:min_lines]
    return np.sort(lines), max_util


def solve_subset(gens, full_network: PTDFNetwork, lines: np.ndarray, method: int, crossover: int, coeff_tol: float):
    net = subset_network(full_network, lines, coeff_tol=coeff_tol)
    t0 = time.time()
    chp = PrimalCHPLP(gens, net, method=method, crossover=crossover)
    _, obj, ok = chp.solve()
    elapsed = time.time() - t0
    p_lp = chp.lp_dispatch()
    flows = full_flow(full_network, p_lp)
    violation = np.maximum(np.abs(flows) - full_network.F_max[:, None], 0.0)
    max_by_line = violation.max(axis=1)
    violated = np.flatnonzero(max_by_line > 1e-5)
    return {
        "ok": ok,
        "obj": obj,
        "elapsed": elapsed,
        "build_time": chp.build_time,
        "solver_time": chp.solver_time,
        "n_lines": len(lines),
        "n_viol_lines": len(violated),
        "max_violation": float(violation.max()) if violation.size else 0.0,
        "violated": violated,
    }


def run_constraint_generation(gens, network: PTDFNetwork, init_lines: np.ndarray, method: int, crossover: int, coeff_tol: float, max_rounds: int):
    selected = set(int(x) for x in init_lines)
    rows = []
    final = None
    for rnd in range(1, max_rounds + 1):
        lines = np.array(sorted(selected), dtype=int)
        res = solve_subset(gens, network, lines, method, crossover, coeff_tol)
        res["round"] = rnd
        rows.append(res)
        final = res
        if res["n_viol_lines"] == 0:
            break
        selected.update(int(x) for x in res["violated"])
    return rows, final


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-scale", type=float, default=1.2)
    parser.add_argument("--fmax-scale", type=float, default=0.8)
    parser.add_argument(
        "--ramp-scenario",
        default="base",
        choices=["base", "tight", "heterogeneous", "tight_heterogeneous"],
    )
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.95, 0.90, 0.85])
    parser.add_argument("--min-lines", type=int, default=8)
    parser.add_argument("--method", type=int, default=2)
    parser.add_argument("--crossover", type=int, default=0)
    parser.add_argument("--coeff-tol", type=float, default=0.0)
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--out", default="results/dchp_accel_118.csv")
    args = parser.parse_args()

    gens, network = load_case("118", "ptdf", 24, 3, congestion="tight", fmax_scale=args.fmax_scale)
    gens = apply_ramp_scenario(gens, args.ramp_scenario)
    network = apply_load_scale(network, args.load_scale)
    gens = warm_start_gens(gens, network)
    p_uc, u_uc, milp_obj = ScheduleRunMILP(gens, network).solve()

    all_rows = []
    for threshold in args.thresholds:
        init_lines, max_util = candidate_lines_from_schedule(network, p_uc, threshold, args.min_lines)
        cg_rows, final = run_constraint_generation(
            gens, network, init_lines, args.method, args.crossover, args.coeff_tol, args.max_rounds
        )
        for res in cg_rows:
            row = {
                "load_scale": args.load_scale,
                "fmax_scale": args.fmax_scale,
                "threshold": threshold,
                "ramp_scenario": args.ramp_scenario,
                "method": args.method,
                "crossover": args.crossover,
                "coeff_tol": args.coeff_tol,
                "milp_obj": milp_obj,
                "round": res["round"],
                "n_lines": res["n_lines"],
                "obj": res["obj"],
                "gap": milp_obj - res["obj"],
                "elapsed": res["elapsed"],
                "build_time": res["build_time"],
                "solver_time": res["solver_time"],
                "n_viol_lines": res["n_viol_lines"],
                "max_violation": res["max_violation"],
                "exact_by_check": int(res["n_viol_lines"] == 0),
            }
            all_rows.append(row)
            print(row)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
