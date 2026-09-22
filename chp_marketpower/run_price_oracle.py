"""Scope-limited R3 audit: selected raw-price lines and basis candidates.

This does not certify the complete count of price regimes or dual uniqueness.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, load_case
from price_vulnerability.price_oracle import basis_direction
from gurobi_compat import GRB


REGIMES = Path("results/value_oracle_G2_absolute_residual_audit/value_regimes.csv")
OUTPUT = Path("results/price_oracle_G2_absolute")
PRICE_TOL = 1e-6  # $/MWh over every bus and hour


def main() -> None:
    with REGIMES.open(newline="", encoding="utf-8") as stream:
        values = list(csv.DictReader(stream))
    if len(values) != 5:
        raise ValueError("expected the five validated 6-bus G2 value regimes")
    generators, network = load_case("6", "ptdf", 24, 3, "tight")
    started = time.perf_counter()
    solves = 0

    def solve(delta: float):
        nonlocal solves
        adders = np.zeros((len(generators), network.T))
        adders[1] = delta
        solver = PrimalCHPLP(
            generators, network, bid_adders=adders, method=1, crossover=1,
            feasibility_tol=1e-9, optimality_tol=1e-9,
        )
        _, value, success = solver.solve()
        solves += 1
        if not success or solver._model.Status != GRB.OPTIMAL:
            raise RuntimeError(f"CHP not OPTIMAL at delta={delta:.12g}")
        return solver, float(value)

    lines, candidate_audits, checks = [], [], []
    for number, row in enumerate(values, 1):
        left, right = float(row["left"]), float(row["right"])
        slope_value = float(row["slope"])
        anchors = left + np.array([0.1, 0.9]) * (right - left)
        low, _ = solve(float(anchors[0]))
        high, _ = solve(float(anchors[1]))
        price_slope = (high.raw_nodal_price - low.raw_nodal_price) / (anchors[1] - anchors[0])
        lines.append({"left": left, "right": right, "value_slope": slope_value,
                      "anchor": float(anchors[0]), "price": low.raw_nodal_price.copy(),
                      "price_slope": price_slope})
        for fraction in (0.25, 0.5, 0.75):
            delta = left + fraction * (right - left)
            solver, value = solve(delta)
            predicted = lines[-1]["price"] + (delta - anchors[0]) * price_slope
            checks.append({"value_regime": number, "side": "interior", "delta": delta,
                           "max_price_error": float(np.max(np.abs(solver.raw_nodal_price - predicted))),
                           "value_error": abs(value - (float(row["intercept"]) + slope_value * delta))})
            if fraction == 0.5:
                try:
                    basis = basis_direction(solver, solver.bid_adder_direction(1))
                except RuntimeError as error:
                    candidate_audits.append({"value_regime": number, "delta": delta,
                                             "status": "unusable_basis", "reason": str(error)})
                else:
                    event = basis["next_event"]
                    kind = event[1] if event else None
                    if kind == "row_slack":
                        line_start = solver._model.NumConstrs - 2 * network.N_line * network.T
                        kind = "line_row" if event[2] >= line_start else "unit_or_pwl_row"
                    candidate_audits.append({
                        "value_regime": number, "delta": delta, "status": "screened",
                        "first_forward_candidate": delta + event[0] if event else None,
                        "first_candidate_kind": kind,
                        "candidate_count_from_basis": basis["candidate_count"],
                        "zero_distance_candidates": basis["immediate"],
                        "stationary_error": basis["stationary_error"],
                        "basic_row_error": basis["basic_row_error"],
                    })
    for number in range(1, len(lines)):
        boundary = lines[number]["left"]
        for sign, line in ((-1, lines[number - 1]), (1, lines[number])):
            delta = boundary + sign * min(1e-8, 0.01 * (line["right"] - line["left"]))
            solver, _ = solve(delta)
            predicted = line["price"] + (delta - line["anchor"]) * line["price_slope"]
            checks.append({"value_regime": number + 1, "side": "left" if sign < 0 else "right",
                           "delta": delta,
                           "max_price_error": float(np.max(np.abs(solver.raw_nodal_price - predicted)))})
    max_error = max(item["max_price_error"] for item in checks)
    max_value_error = max(item.get("value_error", 0.0) for item in checks)
    slope_gaps = [float(np.max(np.abs(a["price_slope"] - b["price_slope"])))
                  for a, b in zip(lines, lines[1:])]
    summary = {
        "scope": "6-bus PTDF tight, G2 all-day absolute adder in [0,0.1]",
        "value_regimes": 5,
        "distinct_observed_simplex_price_lines": 1 + sum(gap > 1e-6 for gap in slope_gaps),
        "complete_price_regime_count": None,
        "why_incomplete": "Degenerate zero-distance basis events prevent exhaustive continuation; numerical method agreement does not prove dual uniqueness.",
        "first_candidate_audit_checks_variables_and_inequality_rows": True,
        "min_adjacent_full_price_slope_gap": min(slope_gaps),
        "max_direct_full_price_error": max_error,
        "max_direct_value_error": max_value_error,
        "price_tolerance": PRICE_TOL,
        "direct_solves": solves,
        "offline_seconds": time.perf_counter() - started,
        "regimes": [{"number": i, "left": line["left"], "right": line["right"],
                     "value_slope": line["value_slope"]}
                    for i, line in enumerate(lines, 1)],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUTPUT / "basis_candidates.json").write_text(json.dumps(candidate_audits, indent=2), encoding="utf-8")
    (OUTPUT / "validation.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    np.savez_compressed(OUTPUT / "observed_price_lines.npz",
                        anchor=np.asarray([line["anchor"] for line in lines]),
                        price=np.stack([line["price"] for line in lines]),
                        slope=np.stack([line["price_slope"] for line in lines]))
    print(f"{summary['distinct_observed_simplex_price_lines']} distinct observed price lines; "
          f"complete count unresolved; max direct error {max_error:.3e} $/MWh")
    if max_error > PRICE_TOL or max_value_error > 1e-7:
        raise RuntimeError("direct price/value validation failed")


if __name__ == "__main__":
    main()
