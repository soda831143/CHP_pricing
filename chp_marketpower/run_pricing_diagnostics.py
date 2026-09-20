"""Inspect pricing-LP intervals, active ramps and line duals; optionally save physical UC separately."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, controlled_case
from price_vulnerability.diagnostics import physical_uc_schedule, pricing_mechanism_diagnostics
from run_hourly_vulnerability import _write_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("6", "30"), default="6")
    parser.add_argument("--scenario", choices=("C0", "C1", "C2", "C2N", "C3"), default="C2")
    parser.add_argument("--congestion", choices=("tight", "moderate", "relaxed"), default="tight")
    parser.add_argument("--T", type=int, default=24)
    parser.add_argument("--load-scale", type=float, default=1.0, help="Uniform multiplier on all nodal loads")
    parser.add_argument("--load-shift", type=float, nargs=3, metavar=("FROM_BUS", "TO_BUS", "FRACTION"),
                        help="Move a fraction of each hour's load between 1-based buses; total load is unchanged")
    parser.add_argument("--warmup-initial-state", action="store_true",
                        help="Use one physical-UC day to construct the modeled day's initial conditions")
    parser.add_argument("--segments", type=int, choices=(1, 3), default=3)
    parser.add_argument("--include-uc", action="store_true")
    parser.add_argument("--dual-audit", action="store_true",
                        help="Compare simplex/barrier prices; agreement is not a uniqueness proof")
    parser.add_argument("--out-dir", type=Path, default=Path("results/mechanism_diagnostics"))
    args = parser.parse_args()

    if args.T < 1:
        raise ValueError("T must be positive")
    if args.scenario != "C3" and args.congestion != "tight":
        raise ValueError("--congestion applies only to C3; C2N always has relaxed limits")
    load_shift = tuple(args.load_shift) if args.load_shift else None
    generators, network = controlled_case(
        args.case, args.scenario, args.T, args.segments, args.congestion, args.load_scale,
        load_shift, args.warmup_initial_state,
    )
    result = pricing_mechanism_diagnostics(generators, network)
    for key, name in (("arcs", "pricing_on_intervals.csv"),
                      ("off_arcs", "pricing_off_arcs.csv"),
                      ("lines", "pricing_lines.csv")):
        _write_csv(args.out_dir / name, result[key])
    if args.include_uc:
        _write_csv(args.out_dir / "physical_uc_schedule.csv", physical_uc_schedule(generators, network))
    if args.dual_audit:
        from gurobi_compat import GRB
        rows = []
        for method, crossover in ((-1, 0), (1, 0), (2, 1)):
            solver = PrimalCHPLP(generators, network, method=method, crossover=crossover)
            price, obj, success = solver.solve()
            if not success or solver._model.Status != GRB.OPTIMAL:
                raise RuntimeError(f"Dual audit failed with Method={method}, Crossover={crossover}")
            rows.append({
                "method": method, "crossover": crossover, "objective": obj,
                "max_price_gap_vs_default": float(np.max(np.abs(price - result["prices"]))),
                "max_primal_violation": solver.primal_violation,
            })
        _write_csv(args.out_dir / "dual_audit.csv", rows)
    _write_csv(args.out_dir / "summary.csv", [{
        "case": args.case, "scenario": args.scenario, "T": args.T, "load_scale": args.load_scale,
        "load_shift_from_bus": "" if load_shift is None else int(load_shift[0]),
        "load_shift_to_bus": "" if load_shift is None else int(load_shift[1]),
        "load_shift_fraction": "" if load_shift is None else load_shift[2],
        "warmup_initial_state": args.warmup_initial_state,
        "congestion": "relaxed" if args.scenario == "C2N" else args.congestion,
        "chp_objective": result["objective"],
        "max_primal_violation": result["primal_violation"],
        "max_nodal_price_spread": float(np.ptp(result["prices"], axis=0).max()),
        "positive_on_intervals": len(result["arcs"]),
        "price_setting_line_hours": sum(row["price_setting"] for row in result["lines"]),
    }])
    print(f"{args.scenario}: {len(result['arcs'])} positive ON intervals, "
          f"{sum(row['price_setting'] for row in result['lines'])} price-setting line-hours")


if __name__ == "__main__":
    main()
