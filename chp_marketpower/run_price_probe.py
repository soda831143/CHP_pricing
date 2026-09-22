"""Targeted raw-price checks inside the validated 6-bus G2 value intervals.

This is a screening test, not a price-regime enumeration or a uniqueness proof.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, load_case


def affine_midpoint_error(prices: np.ndarray) -> float:
    """Maximum full-vector deviation of the middle sample from a straight line."""
    if prices.shape[0] != 3:
        raise ValueError("expected three equally spaced price samples")
    return float(np.max(np.abs(prices[1] - 0.5 * (prices[0] + prices[2]))))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regimes", type=Path,
                        default=Path("results/value_oracle_G2_absolute_nominal/value_regimes.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("results/price_probe_G2"))
    args = parser.parse_args()

    with args.regimes.open(newline="", encoding="utf-8") as stream:
        regimes = list(csv.DictReader(stream))
    if len(regimes) != 5:
        raise ValueError("expected five validated 6-bus G2 value intervals")

    generators, network = load_case("6", "ptdf", 24, 3, "tight")
    summaries = []
    deltas, raw_prices = [], []
    previous_right = 0.0
    from gurobi_compat import GRB

    for number, regime in enumerate(regimes, 1):
        left, right = float(regime["left"]), float(regime["right"])
        if not 0 <= left < right <= 0.1 or abs(left - previous_right) > 1e-9:
            raise ValueError(f"invalid value interval {number}: [{left}, {right}]")
        previous_right = right
        samples = left + np.array([0.1, 0.5, 0.9]) * (right - left)
        selected, alternative, runtimes = [], [], []
        for delta in samples:
            adders = np.zeros((len(generators), network.T))
            adders[1] = delta
            pair = []
            for method in (1, 2):  # simplex and barrier+crossover
                solver = PrimalCHPLP(
                    generators, network, bid_adders=adders,
                    method=method, crossover=1,
                    feasibility_tol=1e-9, optimality_tol=1e-9,
                )
                _, _, success = solver.solve()
                if not success or solver._model.Status != GRB.OPTIMAL:
                    raise RuntimeError(f"price probe not OPTIMAL at delta={delta:g}")
                if not np.all(np.isfinite(solver.raw_nodal_price)):
                    raise RuntimeError(f"nonfinite raw price at delta={delta:g}")
                pair.append(solver.raw_nodal_price.copy())
                runtimes.append(solver.total_time)
            selected.append(pair[0])
            alternative.append(pair[1])
        selected = np.stack(selected)
        alternative = np.stack(alternative)
        deltas.append(samples)
        raw_prices.append(np.stack((selected, alternative)))
        summaries.append({
            "value_regime": number,
            "left": left,
            "right": right,
            "max_full_price_midpoint_error": affine_midpoint_error(selected),
            "max_method_price_gap": float(np.max(np.abs(selected - alternative))),
            "price_slope_norm": float(np.linalg.norm(
                (selected[2] - selected[0]) / (samples[2] - samples[0])
            )),
            "total_direct_solve_seconds": float(sum(runtimes)),
        })
    if abs(previous_right - 0.1) > 1e-9:
        raise ValueError("value intervals do not cover [0, 0.1]")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summaries, indent=2), encoding="utf-8"
    )
    np.savez_compressed(
        args.out_dir / "raw_prices.npz",
        deltas=np.stack(deltas),
        prices=np.stack(raw_prices),  # regime, method, sample, bus, hour
    )
    for item in summaries:
        print(
            f"value regime {item['value_regime']}: midpoint error "
            f"{item['max_full_price_midpoint_error']:.3e}, method gap "
            f"{item['max_method_price_gap']:.3e} $/MWh"
        )
    print("Targeted screening only: hidden price intervals and dual nonuniqueness remain open.")


if __name__ == "__main__":
    main()
