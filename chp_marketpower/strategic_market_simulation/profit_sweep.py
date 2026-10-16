"""Small, auditable scalar-bid profit check using the existing market engines."""

from __future__ import annotations

import json
import numpy as np

from engine import PrimalCHPLP, solve_chp
from price_vulnerability.scalar_markup import apply_generator_adder, apply_generator_markup
from chp_solver.schedule_run import ScheduleRunMILP
from benchmarks.lmp_pricing import FixedULP
from benchmarks.unit_self_schedule import UnitSelfScheduleMILP, dispatch_cost, dispatch_profit


def profit_at_markup(true_generators, network, generator_index: int, beta: float) -> dict:
    """Re-clear UC and CHP at the reported bid; account profit at true cost."""
    if not 0 <= generator_index < len(true_generators):
        raise IndexError(f"generator_index out of range: {generator_index}")
    if beta < 0:
        raise ValueError("The pilot strategy grid allows nonnegative markups only")
    reported = apply_generator_markup(true_generators, generator_index, beta)
    return _profit_at_reported(true_generators, reported, network, generator_index, "beta", beta)


def profit_at_adder(true_generators, network, generator_index: int, delta: float) -> dict:
    """Re-clear and settle one all-day absolute marginal-offer adder."""
    reported = apply_generator_adder(true_generators, generator_index, delta)
    adders = np.zeros((len(true_generators), network.T))
    adders[generator_index] = delta
    return _profit_at_reported(
        true_generators, reported, network, generator_index, "delta", delta, adders
    )


def _profit_at_reported(true_generators, reported, network, generator_index, parameter, amount,
                        bid_adders=None):
    p, u, uc_objective = ScheduleRunMILP(reported, network).solve(require_optimal=True)
    prices = solve_chp(true_generators if bid_adders is not None else reported, network,
                       bid_adders=bid_adders)
    if prices.solver_status != "optimal":
        raise RuntimeError(f"CHP status at {parameter}={amount}: {prices.solver_status}")

    settled = _settle_target(
        true_generators[generator_index], reported[generator_index],
        prices.lmp[network.gen_bus_idx(generator_index)], p[generator_index], u[generator_index],
    )
    result = {
        "generator": true_generators[generator_index].unit_id or f"G{generator_index + 1}",
        "generator_index": generator_index,
        parameter: amount,
        **{key: settled[key] for key in (
            "energy_revenue", "reported_uplift", "reported_cost", "true_cost", "true_profit",
        )},
        "uc_objective_reported": uc_objective,
        "chp_objective_reported": prices.objective,
        "generation_mwh": float(p[generator_index].sum()),
        "scheduled_output_mw": json.dumps(p[generator_index].tolist()),
        "scheduled_commitment": json.dumps(u[generator_index].astype(int).tolist()),
    }
    if bid_adders is not None:
        result["nodal_prices"] = prices.lmp
    return result


def _settle_target(true_generator, reported_generator, nodal_price, p_dispatch, u_dispatch,
                   *, mip_gap=1e-7, bid_adders=None):
    self_u, self_p, best, self_info = UnitSelfScheduleMILP.solve(
        reported_generator, nodal_price, require_optimal=True, return_timing=True, mip_gap=mip_gap,
        bid_adders=bid_adders,
    )
    scheduled = dispatch_profit(reported_generator, nodal_price, p_dispatch, u_dispatch, bid_adders=bid_adders)
    if best < scheduled - 1e-4:
        raise RuntimeError("Physical dispatch exceeds the optimal single-unit self schedule")
    uplift = UnitSelfScheduleMILP.uplift(
        reported_generator, nodal_price, p_dispatch, u_dispatch, best, bid_adders=bid_adders,
    )
    revenue = float(np.dot(nodal_price, p_dispatch))
    true_cost = dispatch_cost(true_generator, p_dispatch, u_dispatch)
    reported_cost = dispatch_cost(reported_generator, p_dispatch, u_dispatch, bid_adders=bid_adders)
    profit = revenue + uplift - true_cost
    if abs(profit - best - (reported_cost - true_cost)) > 1e-4:
        raise RuntimeError("Reported self-schedule surplus and bid wedge do not reconcile")
    return {
        "energy_revenue": revenue, "reported_uplift": uplift,
        "reported_cost": reported_cost, "true_cost": true_cost, "true_profit": profit,
        "best_reported_profit": best, "self_output_mw": self_p, "self_commitment": self_u,
        'self_schedule_upper_bound': self_info['best_bound'],
        'self_schedule_gap_usd': max(0., self_info['best_bound']-best),
    }


def paired_profit_at_adder(true_generators, network, generator_index: int, delta: float,
                           chp_method: int = 2, crossover: int = 0) -> dict:
    """Settle the same reported-bid UC dispatch at raw CHP and fixed-UC LMP prices."""
    from gurobi_compat import GRB

    reported = apply_generator_adder(true_generators, generator_index, delta)
    p, u, uc_value = ScheduleRunMILP(reported, network).solve(require_optimal=True)
    adders = np.zeros((len(true_generators), network.T))
    adders[generator_index] = delta
    chp = PrimalCHPLP(true_generators, network, bid_adders=adders,
                      method=chp_method, crossover=crossover)
    legacy_prices, chp_value, success = chp.solve()
    if not success or chp._model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"CHP did not reach OPTIMAL at delta={delta}")
    raw_prices = chp.raw_nodal_price.copy()
    fixed_u = FixedULP(reported, network, u)
    legacy_lmp_prices, lmp_value, success = fixed_u.solve()
    if not success or fixed_u.solver_status != GRB.OPTIMAL:
        raise RuntimeError(f"Fixed-UC LMP did not reach OPTIMAL at delta={delta}")
    lmp_prices = fixed_u.raw_lmp.copy()

    bus = network.gen_bus_idx(generator_index)
    settlements = {
        "CHP": _settle_target(true_generators[generator_index], reported[generator_index],
                              raw_prices[bus], p[generator_index], u[generator_index]),
        "fixed_UC_LMP": _settle_target(true_generators[generator_index], reported[generator_index],
                                       lmp_prices[bus], p[generator_index], u[generator_index]),
    }
    wedge = settlements["CHP"]["reported_cost"] - settlements["CHP"]["true_cost"]
    if abs(settlements["CHP"]["true_profit"] - settlements["fixed_UC_LMP"]["true_profit"]
           - settlements["CHP"]["best_reported_profit"]
           + settlements["fixed_UC_LMP"]["best_reported_profit"]) > 1e-4:
        raise RuntimeError("Matched pricing-rule profit difference does not reconcile")
    return {
        "delta": delta, "physical_output_mw": p, "physical_commitment": u,
        "chp_lp_output_mw": chp.lp_dispatch(),
        "chp_lp_commitment": chp.lp_commitment(),
        "chp_offer_exposure_mwh": chp.incremental_energy_exposure(generator_index),
        "uc_objective_reported": uc_value, "bid_wedge_usd": wedge,
        "offer_exposure_mwh": float(np.maximum(
            p[generator_index] - true_generators[generator_index].P_min * u[generator_index], 0
        ).sum()),
        "prices": {"CHP": raw_prices, "fixed_UC_LMP": lmp_prices},
        "pricing_values": {"CHP": chp_value, "fixed_UC_LMP": lmp_value},
        "legacy_raw_price_max_gap": float(np.max(np.abs(legacy_prices - raw_prices))),
        "lmp_legacy_raw_price_max_gap": float(np.max(np.abs(legacy_lmp_prices - lmp_prices))),
        "raw_energy_dual_min": float(np.min(chp.raw_energy_dual)),
        "raw_line_duals": chp.raw_line_duals,
        "settlements": settlements,
    }
