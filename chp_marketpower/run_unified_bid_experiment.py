"""Matched absolute-offer CHP, physical UC, and profit scan on one network case."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from engine import load_case
from price_vulnerability.scalar_markup import scalar_sensitivity
from strategic_market_simulation.profit_sweep import profit_at_adder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("6", "30", "118"), required=True)
    parser.add_argument("--generator", type=int, required=True, help="0-based index")
    parser.add_argument("--T", type=int, default=24)
    parser.add_argument("--rho", type=float, nargs="+", default=(0, 0.025, 0.05, 0.10, 0.20))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.T < 1 or not args.rho or any(not np.isfinite(r) or r < 0 for r in args.rho):
        raise ValueError("T must be positive and rho values finite and nonnegative")
    generators, network = load_case(args.case, "ptdf", args.T, 3, "tight")
    if not 0 <= args.generator < len(generators):
        raise IndexError("generator out of range")
    target = generators[args.generator]
    reference_slope = float(
        target.pwl_slopes[len(target.pwl_slopes) // 2] if target.pwl_slopes else target.cost_var
    )
    if reference_slope <= 0:
        raise ValueError("reference marginal slope must be positive")
    local_epsilon = 1e-4 * reference_slope
    local_derivative = scalar_sensitivity(
        generators, network, args.generator, local_epsilon, "absolute"
    ).derivative

    rows = []
    baseline = None
    for rho in sorted(set((0.0, *args.rho))):
        started = time.perf_counter()
        delta = rho * reference_slope
        run = profit_at_adder(generators, network, args.generator, delta)
        prices = run.pop("nodal_prices")
        output = np.asarray(json.loads(run.pop("scheduled_output_mw")))
        commitment = np.asarray(json.loads(run.pop("scheduled_commitment")))
        if baseline is None:
            baseline = (run, prices, output)
            if run["generation_mwh"] <= 1e-6:
                raise ValueError("selected generator has no baseline physical output")
        base, base_prices, base_output = baseline
        local = prices[network.gen_bus_idx(args.generator)]
        base_local = base_prices[network.gen_bus_idx(args.generator)]
        price_effect = float(base_output @ (local - base_local))
        quantity_effect = float(local @ (output - base_output))
        revenue_change = run["energy_revenue"] - base["energy_revenue"]
        uplift_change = run["reported_uplift"] - base["reported_uplift"]
        cost_change = run["true_cost"] - base["true_cost"]
        profit_change = run["true_profit"] - base["true_profit"]
        if max(abs(price_effect + quantity_effect - revenue_change),
               abs(revenue_change + uplift_change - cost_change - profit_change),
               abs(float(local @ output) - run["energy_revenue"])) > 1e-4:
            raise RuntimeError("price, dispatch, and profit accounting do not reconcile")
        rows.append({
            "case": args.case, "T": args.T, "network": "ptdf-tight",
            "generator": run["generator"], "generator_index": args.generator,
            "reference_slope_usd_per_mwh": reference_slope,
            "rho": rho, "delta_usd_per_mwh": delta,
            "chp_value_usd": run["chp_objective_reported"],
            "price_shift_rms_usd_per_mwh": float(np.sqrt(np.mean((prices - base_prices) ** 2))),
            "local_difference_step_usd_per_mwh": local_epsilon,
            "local_price_derivative_rms": float(np.sqrt(np.mean(local_derivative ** 2))),
            "linear_price_error_rms_usd_per_mwh": float(np.sqrt(np.mean(
                (prices - base_prices - delta * local_derivative) ** 2
            ))),
            "own_node_price_effect_usd": price_effect,
            "quantity_effect_usd": quantity_effect,
            "energy_revenue_change_usd": revenue_change,
            "uplift_change_usd": uplift_change,
            "true_cost_change_usd": cost_change,
            "profit_change_usd": profit_change,
            "profit_gain_per_baseline_mwh": profit_change / base["generation_mwh"],
            "generation_change_mwh": run["generation_mwh"] - base["generation_mwh"],
            "reported_cost_delta_usd": run["reported_cost"] - run["true_cost"],
            "offer_exposure_mwh": float(np.maximum(output - target.P_min * commitment, 0).sum()),
            "runtime_s": time.perf_counter() - started,
        })
        if abs(rows[-1]["reported_cost_delta_usd"] - delta * rows[-1]["offer_exposure_mwh"]) > 1e-4:
            raise RuntimeError("reported-cost adder does not match offer exposure")
        print(f"{args.case}-bus {run['generator']} rho={rho:.3f}: "
              f"value={run['chp_objective_reported']:.4f}, "
              f"profit gain={profit_change:.4f}, elapsed={rows[-1]['runtime_s']:.1f}s", flush=True)

    slopes = [
        (right["chp_value_usd"] - left["chp_value_usd"]) /
        (right["delta_usd_per_mwh"] - left["delta_usd_per_mwh"])
        for left, right in zip(rows, rows[1:])
    ]
    if any(b > a + 1e-3 for a, b in zip(slopes, slopes[1:])):
        raise RuntimeError(f"CHP value violates expected concavity on the grid: {slopes}")
    path = args.out or Path(__file__).resolve().parent / "results" / f"unified_{args.case}_G{args.generator + 1}_T{args.T}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Value secant slopes (nonincreasing expected): {slopes}")
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
