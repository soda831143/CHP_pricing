"""Matched all-day offer, CHP price, and realized-profit evidence for 30-bus G1/G5."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from engine import load_case, solve_chp
from price_vulnerability.scalar_markup import apply_generator_markup, scalar_sensitivity
from strategic_market_simulation.profit_sweep import profit_at_markup


def main() -> None:
    generators, network = load_case("30", "ptdf", 24, 3, "tight")
    base_prices = solve_chp(generators, network)
    if base_prices.solver_status != "optimal":
        raise RuntimeError("Baseline CHP did not reach OPTIMAL")

    rows = []
    for generator_index in (0, 4):  # G1 and G5: the pre-existing VI/profit contrast.
        baseline = profit_at_markup(generators, network, generator_index, 0.0)
        if baseline["generation_mwh"] <= 0:
            raise RuntimeError("A selected paper unit has no baseline output")
        baseline_output = np.asarray(json.loads(baseline["scheduled_output_mw"]))
        bus = network.gen_bus_idx(generator_index)
        base_local = base_prices.lmp[bus]
        sensitivity = scalar_sensitivity(generators, network, generator_index, 0.001)
        if abs(float(base_local @ baseline_output) - baseline["energy_revenue"]) > 1e-4:
            raise RuntimeError("Baseline price and energy revenue do not reconcile")

        for beta in (0.05, 0.10):
            profit = profit_at_markup(generators, network, generator_index, beta)
            prices = solve_chp(apply_generator_markup(generators, generator_index, beta), network)
            if prices.solver_status != "optimal":
                raise RuntimeError(f"CHP did not reach OPTIMAL for G{generator_index + 1}, beta={beta}")
            output = np.asarray(json.loads(profit["scheduled_output_mw"]))
            local = prices.lmp[bus]
            price_effect = float(baseline_output @ (local - base_local))
            quantity_effect = float(local @ (output - baseline_output))
            revenue_change = profit["energy_revenue"] - baseline["energy_revenue"]
            uplift_change = profit["reported_uplift"] - baseline["reported_uplift"]
            cost_change = profit["true_cost"] - baseline["true_cost"]
            profit_change = profit["true_profit"] - baseline["true_profit"]
            if max(
                abs(price_effect + quantity_effect - revenue_change),
                abs(revenue_change + uplift_change - cost_change - profit_change),
                abs(float(local @ output) - profit["energy_revenue"]),
            ) > 1e-4:
                raise RuntimeError("Price, settlement, and profit accounting do not reconcile")
            rows.append({
                "generator": profit["generator"], "beta": beta,
                "all_node_local_sensitivity_l2": sensitivity.score,
                "all_node_direct_price_change_l2": float(np.linalg.norm(prices.lmp - base_prices.lmp)),
                "local_linear_price_max_error": float(np.max(np.abs(
                    prices.lmp - (base_prices.lmp + beta * sensitivity.derivative)
                ))),
                "own_node_price_effect_usd": price_effect,
                "quantity_effect_usd": quantity_effect,
                "energy_revenue_change_usd": revenue_change,
                "reported_uplift_change_usd": uplift_change,
                "true_cost_change_usd": cost_change,
                "true_profit_change_usd": profit_change,
                "baseline_generation_mwh": baseline["generation_mwh"],
                "profit_gain_per_baseline_mwh": profit_change / baseline["generation_mwh"],
                "generation_change_mwh": profit["generation_mwh"] - baseline["generation_mwh"],
            })

    output_path = Path(__file__).resolve().parent / "results" / "paper_case30_g1_g5.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)
    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
