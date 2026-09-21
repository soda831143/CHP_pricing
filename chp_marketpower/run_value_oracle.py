"""Reconstruct and validate the scalar CHP value function under an offer adder."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from pathlib import Path

from engine import load_case
from price_vulnerability.value_oracle import (
    reconstruct_value_regimes,
    solve_value_point,
    validate_value_regimes,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("6", "30"), default="6")
    parser.add_argument("--network", choices=("single", "ptdf"), default="ptdf")
    parser.add_argument("--congestion", choices=("tight", "moderate", "relaxed"), default="tight")
    parser.add_argument("--T", type=int, default=24)
    parser.add_argument("--segments", type=int, choices=(1, 3), default=3)
    parser.add_argument("--generator", type=int, required=True, help="0-based generator index")
    parser.add_argument("--hour", type=int, help="Optional 0-based offer hour; omit for all-day adder")
    parser.add_argument("--lower", type=float, default=0.0)
    parser.add_argument("--upper", type=float, default=0.1)
    parser.add_argument("--value-tolerance", type=float, default=1e-7)
    parser.add_argument("--slope-tolerance", type=float, default=1e-4)
    parser.add_argument("--max-points", type=int, default=100)
    parser.add_argument("--out-dir", type=Path, default=Path("results/value_oracle"))
    return parser.parse_args()


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = _arguments()
    generators, network = load_case(
        args.case, args.network, args.T, args.segments, args.congestion
    )
    solve = lambda delta: solve_value_point(  # noqa: E731
        generators, network, args.generator, delta, args.hour
    )
    regimes, points = reconstruct_value_regimes(
        solve,
        args.lower,
        args.upper,
        value_tolerance=args.value_tolerance,
        slope_tolerance=args.slope_tolerance,
        max_points=args.max_points,
    )
    validation = validate_value_regimes(
        regimes,
        solve,
        value_tolerance=args.value_tolerance,
        slope_tolerance=args.slope_tolerance,
    )
    _write(args.out_dir / "value_regimes.csv", [asdict(item) for item in regimes])
    _write(args.out_dir / "value_points.csv", [asdict(item) for item in points])
    _write(args.out_dir / "validation_points.csv", [asdict(item) for item in validation])
    failures = sum(not item.passed for item in validation)
    print(
        f"{len(regimes)} value regime(s), {len(points)} reconstruction solve(s), "
        f"{len(validation)} direct validation solve(s), {failures} failure(s)."
    )
    if failures:
        raise SystemExit("Value-regime validation failed")


if __name__ == "__main__":
    main()
