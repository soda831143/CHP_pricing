"""Compare two valid CHP price selections on the same physical UC dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from engine import ScheduleRunMILP, load_case
from price_vulnerability.affine_oracle import dual_audit_passed, query, solve_endpoint
from price_vulnerability.scalar_markup import apply_generator_adder
from strategic_market_simulation.profit_sweep import _settle_target


def compare(oracle_dir: Path, delta: float) -> dict:
    report = json.loads((oracle_dir / "audit.json").read_text(encoding="utf-8"))
    if report["status"] not in {"numerically_validated", "numerically_validated_partial"}:
        raise ValueError("oracle audit did not pass")
    scope = report["scope"]
    if scope.get('bid_hour_1based') is not None:
        raise ValueError('This physical settlement comparison supports all-day adders only')
    generators, network = load_case(
        scope["case"], scope["network"], scope["T"],
        scope["segments"], scope["congestion"],
    )
    g = scope["generator_index"]
    with np.load(oracle_dir / "oracle.npz") as data:
        boundaries = data["boundaries"]
        ready = data["price_ready"] if "price_ready" in data else np.ones(len(boundaries) - 1, bool)
        if not np.isfinite(delta) or not boundaries[0] < delta < boundaries[-1]:
            raise ValueError("delta must lie in the oracle interior")
        k = int(np.searchsorted(boundaries, delta, side="right")) - 1
        if not ready[k]:
            raise ValueError("delta is outside price-ready intervals")
        selected_value, selected_price = query(
            delta, boundaries, data["values"], data["prices"], ready,
        )
    direct = solve_endpoint(generators, network, g, delta)
    if not dual_audit_passed(direct):
        raise RuntimeError("direct CHP complete-dual audit failed")
    if abs(selected_value - direct.value) > 1e-6:
        raise RuntimeError("oracle and direct CHP values disagree")
    reported = apply_generator_adder(generators, g, delta)
    physical_p, physical_u, uc_value = ScheduleRunMILP(reported, network).solve(require_optimal=True)
    bus = network.gen_bus_idx(g)
    settlements = {}
    for name, price in (("affine_selector", selected_price), ("direct_simplex", direct.price)):
        item = _settle_target(
            generators[g], reported[g], price[bus], physical_p[g], physical_u[g],
        )
        settlements[name] = {
            key: float(item[key]) for key in (
                "energy_revenue", "reported_uplift", "reported_cost", "true_cost",
                "true_profit", "best_reported_profit",
            )
        }
        if abs(settlements[name]["true_profit"] - (
            settlements[name]["energy_revenue"]
            + settlements[name]["reported_uplift"]
            - settlements[name]["true_cost"]
        )) > 1e-6:
            raise RuntimeError("settlement accounting identity failed")
    return {
        "scope": scope, "delta": delta, "interval": k + 1,
        "uc_objective_reported": float(uc_value),
        "chp_value": direct.value,
        "scheduled_generation_mwh": float(np.sum(physical_p[g])),
        "scheduled_commitment_hours": int(np.sum(physical_u[g])),
        "node_price_max_gap_usd_per_mwh": float(np.max(np.abs(
            selected_price[bus] - direct.price[bus],
        ))),
        "all_node_price_max_gap_usd_per_mwh": float(np.max(np.abs(
            selected_price - direct.price,
        ))),
        "direct_complete_dual_gap_usd": direct.audit["duality_gap"],
        "settlements": settlements,
        "selector_minus_direct": {
            key: settlements["affine_selector"][key] - settlements["direct_simplex"][key]
            for key in settlements["affine_selector"]
        },
        "interpretation": "Identical reported-bid physical UC; only the valid CHP dual price selection changes.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-dir", type=Path, required=True)
    parser.add_argument("--delta", type=float, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(args.oracle_dir, args.delta)
    if args.output is not None:
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
