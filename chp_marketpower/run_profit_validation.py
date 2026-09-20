"""Finite scalar-bid grid: observed true-profit changes, not an optimal strategy."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from engine import load_case
from strategic_market_simulation.profit_sweep import profit_at_markup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("6", "30"), default="6")
    parser.add_argument("--network", choices=("single", "ptdf"), default="single")
    parser.add_argument("--congestion", choices=("tight", "moderate", "relaxed"), default="tight")
    parser.add_argument("--T", type=int, default=6)
    parser.add_argument("--load-scale", type=float, default=1.0, help="Uniform multiplier on all nodal loads")
    parser.add_argument("--load-shift", type=float, nargs=3, metavar=("FROM_BUS", "TO_BUS", "FRACTION"),
                        help="Move a fraction of each hour's load between 1-based buses; total load is unchanged")
    parser.add_argument("--warmup-initial-state", action="store_true",
                        help="Use one physical-UC day to construct the modeled day's initial conditions")
    parser.add_argument("--segments", type=int, choices=(1, 3), default=3)
    parser.add_argument("--generators", type=int, nargs="*", help="0-based indices; default: all")
    parser.add_argument("--beta", type=float, nargs="+", default=(0, 0.02, 0.05, 0.10, 0.15, 0.20))
    parser.add_argument("--bid-cap", type=float, default=0.20,
                        help="Experimental upward-markup cap; no market mitigation is modeled")
    parser.add_argument("--include-undispatched", action="store_true",
                        help="Include zero-output baseline units when studying the uplift-only channel")
    parser.add_argument("--out", type=Path, default=Path("results/profit_validation.csv"))
    args = parser.parse_args()

    if args.T < 1 or not math.isfinite(args.bid_cap) or args.bid_cap < 0 or any(
        not math.isfinite(beta) or not 0 <= beta <= args.bid_cap for beta in args.beta
    ):
        raise ValueError("T must be positive; markups must lie in [0, bid-cap]")
    load_shift = tuple(args.load_shift) if args.load_shift else None
    generators, network = load_case(
        args.case, args.network, args.T, args.segments, args.congestion, args.load_scale,
        load_shift, args.warmup_initial_state,
    )
    selected = list(range(len(generators))) if args.generators is None else sorted(set(args.generators))
    if not selected or any(not 0 <= i < len(generators) for i in selected):
        raise ValueError("Select valid 0-based generator indices")

    rows = []
    for i in selected:
        baseline = profit_at_markup(generators, network, i, 0.0)
        if baseline["generation_mwh"] <= 1e-6 and not args.include_undispatched:
            print(f"{baseline['generator']}: skipped (zero baseline output; use --include-undispatched for uplift-only analysis)")
            continue
        for beta in sorted(set((0.0, *args.beta))):
            row = baseline if beta == 0.0 else profit_at_markup(generators, network, i, beta)
            rows.append({
                "case": args.case, "network": args.network, "congestion": args.congestion,
                "T": args.T, "segments": args.segments, "load_scale": args.load_scale,
                "load_shift_from_bus": "" if load_shift is None else int(load_shift[0]),
                "load_shift_to_bus": "" if load_shift is None else int(load_shift[1]),
                "load_shift_fraction": "" if load_shift is None else load_shift[2],
                "warmup_initial_state": args.warmup_initial_state,
                "strategy": "unilateral_upward_variable_cost", "bid_cap": args.bid_cap,
                "offer_mitigation": "not_modeled",
                **row,
                "delta_energy_revenue": row["energy_revenue"] - baseline["energy_revenue"],
                "delta_reported_uplift": row["reported_uplift"] - baseline["reported_uplift"],
                "delta_true_cost": row["true_cost"] - baseline["true_cost"],
                "delta_reported_cost": row["reported_cost"] - baseline["reported_cost"],
                "delta_true_profit": row["true_profit"] - baseline["true_profit"],
            })
        best = max(r["delta_true_profit"] for r in rows if r["generator_index"] == i)
        print(f"{baseline['generator']}: max observed profit gain on grid = {best:.6g}")

    if not rows:
        raise RuntimeError("No selected generator is dispatched at baseline; change case/horizon or use --include-undispatched")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
