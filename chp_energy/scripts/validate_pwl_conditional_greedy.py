"""Audit the PWL conditional-greedy interval routine on the current 30-bus case.

This is an internal verification script, not a paper-result generator.  It
uses the already exported D-CHP nodal prices and compares every ordinary ON
interval against the exact compact interval LP.  An initially-online interval
is deliberately excluded because its inherited-output boundary uses the LP
path directly in production.

Run from ``chp_project``::

    python scripts/validate_pwl_conditional_greedy.py

The script writes a row-level audit CSV and a short Markdown summary under
``results/tps_revision_validation``.  It does not overwrite any main-paper
tables or figures.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from chp_core.graph_builder import DAGBuilder
from chp_solver.vertex_oracle import VertexOracle
from run_experiments import (
    apply_initial_conditions,
    apply_load_scenario,
    apply_ramp_scenario,
    derive_warm_start_initial_conditions,
    load_case,
)


PRICE_FILE = PROJECT_DIR / "results" / "paper_main" / "prices_schedule_all_units_30base.csv"
OUT_DIR = PROJECT_DIR / "results" / "tps_revision_validation"
ROW_FILE = OUT_DIR / "pwl_conditional_greedy_30base.csv"
SUMMARY_FILE = OUT_DIR / "pwl_conditional_greedy_30base.md"

T = 24
TOLERANCE = 1e-5


def _load_dchp_prices() -> dict[int, np.ndarray]:
    """Read one D-CHP nodal-price trajectory per bus from the current export."""
    values: dict[int, dict[int, float]] = {}
    with PRICE_FILE.open("r", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["method"] != "chp":
                continue
            bus = int(row["bus"])
            hour = int(row["hour"]) - 1
            price = float(row["price"])
            existing = values.setdefault(bus, {}).get(hour)
            if existing is not None and abs(existing - price) > 1e-7:
                raise ValueError(
                    f"Inconsistent D-CHP price at bus {bus}, hour {hour + 1}: "
                    f"{existing} versus {price}"
                )
            values[bus][hour] = price

    prices: dict[int, np.ndarray] = {}
    for bus, by_hour in values.items():
        if set(by_hour) != set(range(T)):
            raise ValueError(f"D-CHP price export is incomplete for bus {bus}")
        prices[bus] = np.array([by_hour[t] for t in range(T)], dtype=float)
    return prices


def _load_current_generators():
    """Recreate the 48-hour warm-start protocol used by the exported BASE case."""
    generators, network = load_case(
        "30", "ptdf", T, 3, congestion="tight", fmax_scale=1.0
    )
    generators = apply_ramp_scenario(generators, "base")
    network = apply_load_scenario(network, "base")
    u0, p0, on_time, off_time = derive_warm_start_initial_conditions(
        "30",
        "ptdf",
        3,
        "tight",
        1.0,
        ramp_scenario="base",
        load_scenario="base",
        warmup_load_factor=0.98,
    )
    return apply_initial_conditions(generators, u0, p0, on_time, off_time)


def _write_rows(rows: list[dict]) -> None:
    fields = list(rows[0])
    with ROW_FILE.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if not PRICE_FILE.exists():
        raise FileNotFoundError(f"Expected current D-CHP price export: {PRICE_FILE}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    prices_by_bus = _load_dchp_prices()
    generators = _load_current_generators()
    rows: list[dict] = []
    skipped_initial_online = 0

    for index, generator in enumerate(generators, start=1):
        prices = prices_by_bus[generator.node_bus]
        for interval in DAGBuilder.build(generator).on_intervals:
            if interval.initial_online:
                skipped_initial_online += 1
                continue

            start = perf_counter()
            greedy = VertexOracle._solve_interval_pwl_conditional_greedy(
                generator,
                interval.a,
                interval.b,
                prices,
                c_fix=interval.c_fix,
            )
            greedy_seconds = perf_counter() - start

            start = perf_counter()
            lp_output, lp_profit = VertexOracle._solve_interval_pwl_lp(
                generator,
                interval.a,
                interval.b,
                prices,
                c_fix=interval.c_fix,
            )
            lp_seconds = perf_counter() - start

            if greedy is None:
                greedy_output = np.full(interval.duration, np.nan)
                greedy_profit = np.nan
                iterations = np.nan
                gap = np.nan
                certified = False
                max_output_difference = np.nan
                profit_difference = np.nan
            else:
                greedy_output, greedy_profit, iterations, gap = greedy
                certified = True
                max_output_difference = float(
                    np.max(np.abs(greedy_output - lp_output))
                )
                profit_difference = float(abs(greedy_profit - lp_profit))

            rows.append(
                {
                    "unit": generator.unit_id or f"G{index}",
                    "bus": generator.node_bus,
                    "start_hour": interval.a + 1,
                    "end_hour": interval.b + 1,
                    "duration": interval.duration,
                    "certified": certified,
                    "conditional_greedy_profit": greedy_profit,
                    "interval_lp_profit": lp_profit,
                    "absolute_profit_difference": profit_difference,
                    "maximum_output_difference_MW": max_output_difference,
                    "iterations": iterations,
                    "final_linearization_gap": gap,
                    "conditional_greedy_time_s": greedy_seconds,
                    "interval_lp_time_s": lp_seconds,
                }
            )

    _write_rows(rows)
    certified = [row for row in rows if row["certified"]]
    uncertified = [row for row in rows if not row["certified"]]
    max_profit_difference = max(
        (float(row["absolute_profit_difference"]) for row in certified), default=0.0
    )
    max_gap = max(
        (float(row["final_linearization_gap"]) for row in certified), default=0.0
    )
    max_output_difference = max(
        (float(row["maximum_output_difference_MW"]) for row in certified), default=0.0
    )

    # Certification is intentionally optional: an interval without a
    # conditional-greedy certificate is handled by the exact LP in the
    # production implementation.  The diagnostic passes when every certified
    # candidate agrees with that LP to the stated tolerance.
    status = "ACCEPTED AS AN INTERNAL DIAGNOSTIC" if max_profit_difference <= TOLERANCE else "NOT ACCEPTED"

    summary = f"""# PWL Conditional-Greedy Audit: Current 30-Bus BASE Case

- Status: **{status}**
- D-CHP price source: `{PRICE_FILE.relative_to(PROJECT_DIR)}`
- Cost representation: three-segment convex PWL costs; 24-period horizon.
- Ordinary ON intervals tested: {len(rows)}
- Initially-online intervals excluded from this diagnostic: {skipped_initial_online}
- Certified conditional-greedy intervals: {len(certified)}
- Intervals without a conditional-greedy certificate (handled by the exact LP): {len(uncertified)}
- Maximum absolute interval-profit difference from the exact LP: {max_profit_difference:.3e} dollars
- Maximum certified linearization gap: {max_gap:.3e}
- Maximum output-vector difference: {max_output_difference:.6f} MW
- Median conditional-greedy time: {median(float(row['conditional_greedy_time_s']) for row in rows):.6f} s
- Median exact interval-LP time: {median(float(row['interval_lp_time_s']) for row in rows):.6f} s

The acceptance criterion is interval-profit agreement within {TOLERANCE:.0e} dollars
for every interval that obtains a conditional-greedy certificate.
Output vectors may differ at degenerate optima; the profit comparison is the
relevant criterion for ON-arc evaluation and the outer alternating-path
calculation.  The production routine uses the exact compact LP for PWL costs;
this conditional-greedy procedure is retained only as a structural diagnostic.
"""
    SUMMARY_FILE.write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Saved row-level audit to {ROW_FILE}")

    if status == "NOT ACCEPTED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
