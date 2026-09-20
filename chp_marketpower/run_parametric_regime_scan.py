"""Locate candidate scalar bid-price regimes with direct COPT solves."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from engine import load_case
from price_vulnerability import scan_absolute_bid_regimes


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("6", "30"), default="6")
    parser.add_argument("--network", choices=("single", "ptdf"), default="ptdf")
    parser.add_argument("--congestion", choices=("tight", "moderate", "relaxed"), default="tight")
    parser.add_argument("--T", type=int, default=24)
    parser.add_argument("--segments", type=int, choices=(1, 3), default=3)
    parser.add_argument("--generator", type=int, required=True, help="0-based generator index")
    parser.add_argument(
        "--grid", type=float, nargs="+",
        default=[0.0, 0.025, 0.05, 0.075, 0.10],
        help="Uniform absolute marginal-cost adders in $/MWh",
    )
    parser.add_argument("--absolute-tolerance", type=float, default=1e-5)
    parser.add_argument("--relative-tolerance", type=float, default=1e-4)
    parser.add_argument("--out-dir", type=Path, default=Path("results/parametric_regime_scan"))
    return parser.parse_args()


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = _arguments()
    generators, network = load_case(
        args.case, args.network, args.T, args.segments, args.congestion
    )
    scan = scan_absolute_bid_regimes(
        generators, network, args.generator, args.grid,
        absolute_tolerance=args.absolute_tolerance,
        relative_tolerance=args.relative_tolerance,
    )
    generator = generators[args.generator]
    generator_id = generator.unit_id or f"G{args.generator + 1}"

    point_rows = []
    for adder, run in zip(scan.grid, scan.runs):
        for bus in range(run.lmp.shape[0]):
            for hour in range(run.lmp.shape[1]):
                point_rows.append({
                    "generator": generator_id,
                    "generator_index": args.generator,
                    "bid_adder": adder,
                    "bus": bus + 1,
                    "hour": hour + 1,
                    "lmp": run.lmp[bus, hour],
                    "objective": run.objective,
                    "runtime": run.runtime,
                })

    interval_rows = []
    for k, (left, right) in enumerate(zip(scan.grid[:-1], scan.grid[1:])):
        interval_rows.append({
            "generator": generator_id,
            "left_bid_adder": left,
            "right_bid_adder": right,
            "price_slope_norm": np.linalg.norm(scan.price_slopes[k]),
            "objective_slope": scan.objective_slopes[k],
        })

    breakpoint_rows = []
    for k, adder in enumerate(scan.grid[1:-1]):
        breakpoint_rows.append({
            "generator": generator_id,
            "bid_adder": adder,
            "price_slope_jump": scan.price_slope_jumps[k],
            "objective_slope_jump": scan.objective_slope_jumps[k],
            "candidate_breakpoint": bool(scan.candidate_breakpoints[k]),
        })

    _write(args.out_dir / "points.csv", point_rows)
    _write(args.out_dir / "interval_slopes.csv", interval_rows)
    _write(args.out_dir / "candidate_breakpoints.csv", breakpoint_rows)
    candidates = [float(row["bid_adder"]) for row in breakpoint_rows if row["candidate_breakpoint"]]
    print(f"{generator_id}: {len(candidates)} grid-level candidate breakpoint(s): {candidates}")
    print("These are direct-solve screening points, not certified exact critical regions.")


if __name__ == "__main__":
    main()
