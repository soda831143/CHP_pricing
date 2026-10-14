"""Matched CHP/fixed-UC-LMP settlement around the 6- and 30-bus profit windows."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from engine import PrimalCHPLP, load_case
from strategic_market_simulation.profit_sweep import paired_profit_at_adder


def _write(path: Path, rows: list[dict], fieldnames=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames or rows[0])
        writer.writeheader()
        writer.writerows(rows)


def _raw_price_at(generators, network, generator_index: int, delta: float,
                  method: int, crossover: int) -> np.ndarray:
    from gurobi_compat import GRB

    adders = np.zeros((len(generators), network.T))
    adders[generator_index] = delta
    model = PrimalCHPLP(generators, network, bid_adders=adders,
                        method=method, crossover=crossover)
    _, _, success = model.solve()
    if not success or model._model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"Local-response CHP solve failed at delta={delta}")
    return model.raw_nodal_price.copy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("6", "30"), required=True)
    parser.add_argument("--generator", type=int, required=True, help="0-based index")
    parser.add_argument("--rho", type=float, nargs="+", required=True)
    parser.add_argument("--congestion", choices=("tight", "relaxed"), default="tight")
    parser.add_argument("--chp-method", type=int, choices=(1, 2), default=2)
    parser.add_argument("--crossover", type=int, choices=(0, 1), default=0)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.rho or any(not np.isfinite(x) or x < 0 for x in args.rho):
        raise ValueError("rho must contain finite nonnegative values")

    generators, network = load_case(args.case, "ptdf", 24, 3, args.congestion)
    if not 0 <= args.generator < len(generators):
        raise IndexError("generator out of range")
    target = generators[args.generator]
    reference_slope = float(target.pwl_slopes[len(target.pwl_slopes) // 2])
    if reference_slope <= 0:
        raise ValueError("reference slope must be positive")

    summary, schedules, hourly, nodal, lines = [], [], [], [], []
    baseline = previous = None
    for rho in sorted(set((0.0, *args.rho))):
        result = paired_profit_at_adder(generators, network, args.generator, rho * reference_slope,
                                        args.chp_method, args.crossover)
        p, u = result["physical_output_mw"], result["physical_commitment"]
        if baseline is None:
            baseline = result
        previous_p = p if previous is None else previous["physical_output_mw"]
        previous_u = u if previous is None else previous["physical_commitment"]
        common = {
            "case": args.case, "congestion": args.congestion, "T": network.T,
            "generator": target.unit_id or f"G{args.generator + 1}",
            "chp_method": args.chp_method, "chp_crossover": args.crossover,
            "rho": rho, "delta_usd_per_mwh": result["delta"],
            "reference_slope_usd_per_mwh": reference_slope,
        }
        exposure = result["offer_exposure_mwh"]
        if abs(result["bid_wedge_usd"] - result["delta"] * exposure) > 1e-4:
            raise RuntimeError("Bid wedge does not equal adder times physical offer exposure")

        for rule, settled in result["settlements"].items():
            base = baseline["settlements"][rule]
            prices = result["prices"][rule]
            summary.append({
                **common, "pricing_rule": rule,
                "uc_objective_reported_usd": result["uc_objective_reported"],
                "pricing_lp_objective_usd": result["pricing_values"][rule],
                "true_profit_usd": settled["true_profit"],
                "profit_change_usd": settled["true_profit"] - base["true_profit"],
                "best_reported_self_profit_usd": settled["best_reported_profit"],
                "self_profit_change_usd": settled["best_reported_profit"] - base["best_reported_profit"],
                "bid_wedge_usd": result["bid_wedge_usd"],
                "physical_offer_exposure_mwh": exposure,
                "chp_offer_exposure_mwh": result["chp_offer_exposure_mwh"],
                "target_generation_mwh": float(p[args.generator].sum()),
                "self_generation_mwh": float(settled["self_output_mw"].sum()),
                "energy_revenue_usd": settled["energy_revenue"],
                "reported_uplift_usd": settled["reported_uplift"],
                "true_cost_usd": settled["true_cost"],
                "price_shift_rms_usd_per_mwh": float(np.sqrt(np.mean(
                    (prices - baseline["prices"][rule]) ** 2
                ))),
                "target_p_max_change_from_previous_mw": float(np.max(np.abs(
                    p[args.generator] - previous_p[args.generator]
                ))),
                "system_p_max_change_from_previous_mw": float(np.max(np.abs(p - previous_p))),
                "system_commitment_changes_from_previous": int(np.count_nonzero(u != previous_u)),
                "chp_legacy_raw_price_max_gap": result["legacy_raw_price_max_gap"],
                "lmp_legacy_raw_price_max_gap": result["lmp_legacy_raw_price_max_gap"],
                "chp_raw_energy_dual_min": result["raw_energy_dual_min"],
            })
            bus = network.gen_bus_idx(args.generator)
            for t in range(network.T):
                hourly.append({
                    **common, "pricing_rule": rule, "hour": t + 1,
                    "target_bus": bus + 1, "target_price_usd_per_mwh": float(prices[bus, t]),
                    "physical_output_mw": float(p[args.generator, t]),
                    "physical_commitment": int(u[args.generator, t]),
                    "self_output_mw": float(settled["self_output_mw"][t]),
                    "self_commitment": int(settled["self_commitment"][t]),
                })
            for bus_index, t in np.ndindex(prices.shape):
                nodal.append({**common, "pricing_rule": rule, "bus": bus_index + 1,
                              "hour": t + 1, "price_usd_per_mwh": float(prices[bus_index, t])})

        for i, gen in enumerate(generators):
            for t in range(network.T):
                schedules.append({**common, "unit": gen.unit_id or f"G{i + 1}",
                                  "hour": t + 1, "output_mw": float(p[i, t]),
                                  "commitment": int(u[i, t]),
                                  "chp_lp_output_mw": float(result["chp_lp_output_mw"][i, t]),
                                  "chp_lp_commitment": float(result["chp_lp_commitment"][i, t])})
        load_flow = network.PTDF @ network.demand
        physical_flow = network.PTDF_Gen @ p - load_flow
        chp_flow = network.PTDF_Gen @ result["chp_lp_output_mw"] - load_flow
        duals = result["raw_line_duals"]
        upper_slack = network.F_max[:, None] - chp_flow
        lower_slack = network.F_max[:, None] + chp_flow
        if min(float(np.min(upper_slack)), float(np.min(lower_slack))) < -1e-5 or max(
            float(np.max(np.abs(duals[:, :, 0]) * upper_slack)),
            float(np.max(np.abs(duals[:, :, 1]) * lower_slack)),
        ) > 1e-4:
            raise RuntimeError("CHP line duals do not complement the convexified LP flow")
        for line, t in np.argwhere(
            (np.abs(np.abs(chp_flow) - network.F_max[:, None]) <= 1e-5)
            | (np.max(np.abs(duals), axis=-1) > 1e-6)
        ):
            lines.append({**common, "line": int(line) + 1, "hour": int(t) + 1,
                          "physical_flow_mw": float(physical_flow[line, t]),
                          "chp_flow_mw": float(chp_flow[line, t]),
                          "limit_mw": float(network.F_max[line]),
                          "upper_dual": float(duals[line, t, 0]),
                          "lower_dual": float(duals[line, t, 1])})
        print(f"{args.case}-bus {common['generator']} {args.congestion} rho={rho:g}: "
              f"CHP profit change={summary[-2]['profit_change_usd']:.2f}, "
              f"LMP profit change={summary[-1]['profit_change_usd']:.2f}", flush=True)
        previous = result

    step = 1e-4 * reference_slope
    base_prices = baseline["prices"]["CHP"]
    local = []
    for epsilon in (step, step / 2):
        derivative = (_raw_price_at(generators, network, args.generator, epsilon,
                                    args.chp_method, args.crossover)
                      - base_prices) / epsilon
        local.append({"case": args.case, "generator": common["generator"],
                      "congestion": args.congestion, "chp_method": args.chp_method,
                      "chp_crossover": args.crossover, "epsilon_usd_per_mwh": epsilon,
                      "right_price_derivative_rms": float(np.sqrt(np.mean(derivative ** 2)))})

    for name, rows in (("summary", summary), ("physical_schedule", schedules),
                       ("target_hourly", hourly), ("nodal_prices", nodal),
                       ("active_lines", lines), ("local_right_response", local)):
        fields = (tuple(common) + ("line", "hour", "physical_flow_mw", "chp_flow_mw",
                                   "limit_mw", "upper_dual", "lower_dual")) if name == "active_lines" else None
        _write(args.out_dir / f"{name}.csv", rows, fields)
    print(f"Saved matched pricing evidence in {args.out_dir}")


if __name__ == "__main__":
    main()
