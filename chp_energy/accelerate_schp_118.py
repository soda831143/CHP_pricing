from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np

from accelerate_dchp_118 import candidate_lines_from_schedule, full_flow, subset_network, warm_start_gens
from benchmarks.xiao_explicit_pricing import XiaoExplicitPricing
from chp_solver.schedule_run import ScheduleRunMILP
from run_experiments import apply_load_scale, apply_ramp_scenario, load_case


def solve_xiao_subset(gens, full_network, lines, max_states, state_step):
    net = subset_network(full_network, np.asarray(lines, dtype=int))
    t0 = time.time()
    solver = XiaoExplicitPricing(
        generators=gens,
        network=net,
        max_states_per_unit=max_states,
        state_output_step=state_step,
    )
    build_done = time.time()
    p2 = solver._solve_p2()
    p2_done = time.time()
    lmp, alpha, beta = solver._solve_step2_dual(p2)
    end = time.time()
    flows = full_flow(full_network, p2["p"])
    violation = np.maximum(np.abs(flows) - full_network.F_max[:, None], 0.0)
    max_by_line = violation.max(axis=1)
    violated = np.flatnonzero(max_by_line > 1e-5)
    return {
        "obj": float(p2["obj"]),
        "n_states": solver.n_states,
        "n_arcs": solver.n_arcs,
        "total_time": end - t0,
        "n_viol_lines": len(violated),
        "violated": violated,
        "max_violation": float(violation.max()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-scale", type=float, default=1.2)
    parser.add_argument("--fmax-scale", type=float, default=0.8)
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.95])
    parser.add_argument("--min-lines", type=int, default=1)
    parser.add_argument(
        "--ramp-scenario",
        default="base",
        choices=["base", "tight", "heterogeneous", "tight_heterogeneous"],
    )
    parser.add_argument("--xiao-max-states", type=int, default=200000)
    parser.add_argument("--xiao-state-step", type=float, default=0.0)
    parser.add_argument("--out", default="results/schp_accel_118.csv")
    args = parser.parse_args()

    gens, network = load_case("118", "ptdf", 24, 3, congestion="tight", fmax_scale=args.fmax_scale)
    gens = apply_ramp_scenario(gens, args.ramp_scenario)
    network = apply_load_scale(network, args.load_scale)
    gens = warm_start_gens(gens, network)
    p_uc, u_uc, milp_obj = ScheduleRunMILP(gens, network).solve()

    rows = []
    for threshold in args.thresholds:
        max_rounds = 5
        init_lines, max_util = candidate_lines_from_schedule(network, p_uc, threshold, args.min_lines)
        selected = set(int(x) for x in init_lines)
        t_total_start = time.time()
        for rnd in range(1, max_rounds + 1):
            lines_arr = np.array(sorted(selected), dtype=int)
            res = solve_xiao_subset(gens, network, lines_arr, args.xiao_max_states, args.xiao_state_step)
            if res["n_viol_lines"] == 0:
                break
            selected.update(int(x) for x in res["violated"])
        total_time = time.time() - t_total_start
        row = {
            "load_scale": args.load_scale,
            "fmax_scale": args.fmax_scale,
            "threshold": threshold,
            "ramp_scenario": args.ramp_scenario,
            "n_lines": len(selected),
            "rounds": rnd,
            "milp_obj": milp_obj,
            "obj": res["obj"],
            "gap": milp_obj - res["obj"],
            "n_states": res["n_states"],
            "n_arcs": res["n_arcs"],
            "total_time": total_time,
            "n_viol_lines": res["n_viol_lines"],
            "max_violation": res["max_violation"],
            "exact_by_check": int(res["n_viol_lines"] == 0),
        }
        rows.append(row)
        print(row)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
