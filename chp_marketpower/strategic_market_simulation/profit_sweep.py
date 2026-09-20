"""Small, auditable scalar-bid profit check using the existing market engines."""

from __future__ import annotations

import json
import numpy as np

from engine import solve_chp
from price_vulnerability.scalar_markup import apply_generator_markup
from chp_solver.schedule_run import ScheduleRunMILP
from benchmarks.unit_self_schedule import UnitSelfScheduleMILP, dispatch_cost


def profit_at_markup(true_generators, network, generator_index: int, beta: float) -> dict:
    """Re-clear UC and CHP at the reported bid; account profit at true cost."""
    if not 0 <= generator_index < len(true_generators):
        raise IndexError(f"generator_index out of range: {generator_index}")
    if beta < 0:
        raise ValueError("The pilot strategy grid allows nonnegative markups only")
    reported = apply_generator_markup(true_generators, generator_index, beta)
    p, u, uc_objective = ScheduleRunMILP(reported, network).solve(require_optimal=True)
    prices = solve_chp(reported, network)
    if prices.solver_status != "optimal":
        raise RuntimeError(f"CHP status at beta={beta}: {prices.solver_status}")

    g = reported[generator_index]
    nodal_price = prices.lmp[network.gen_bus_idx(generator_index)]
    _, _, best_reported_profit = UnitSelfScheduleMILP.solve(g, nodal_price, require_optimal=True)
    uplift = UnitSelfScheduleMILP.uplift(
        g, nodal_price, p[generator_index], u[generator_index], best_reported_profit
    )
    energy_revenue = float(np.dot(nodal_price, p[generator_index]))
    true_cost = dispatch_cost(true_generators[generator_index], p[generator_index], u[generator_index])
    reported_cost = dispatch_cost(g, p[generator_index], u[generator_index])
    return {
        "generator": true_generators[generator_index].unit_id or f"G{generator_index + 1}",
        "generator_index": generator_index,
        "beta": beta,
        "energy_revenue": energy_revenue,
        "reported_uplift": uplift,
        "reported_cost": reported_cost,
        "true_cost": true_cost,
        "true_profit": energy_revenue + uplift - true_cost,
        "uc_objective_reported": uc_objective,
        "chp_objective_reported": prices.objective,
        "generation_mwh": float(p[generator_index].sum()),
        "scheduled_output_mw": json.dumps(p[generator_index].tolist()),
        "scheduled_commitment": json.dumps(u[generator_index].astype(int).tolist()),
    }
