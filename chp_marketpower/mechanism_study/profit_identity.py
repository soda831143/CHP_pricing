"""Independent accounting checks; these functions do not optimize or select prices."""
import numpy as np


def hourly_cost(generator, p, u):
    p, u = np.asarray(p, dtype=float), np.asarray(u, dtype=float)
    if p.shape != (generator.T,) or u.shape != p.shape or not np.isfinite([p, u]).all():
        raise ValueError('Expected finite hourly output and commitment vectors')
    if np.max(np.abs(u-np.round(u))) > 1e-6 or np.min(u) < -1e-6 or np.max(u) > 1+1e-6:
        raise ValueError('Physical commitment must be binary')
    excess = p-generator.P_min*u
    if np.min(excess) < -1e-6 or np.max(p-generator.P_max*u) > 1e-6:
        raise ValueError('Output violates committed capacity')
    remaining = np.maximum(excess, 0.)
    cost = np.zeros_like(p)
    for slope, width in generator.get_pwl_segments():
        fill = np.minimum(remaining, width)
        cost += slope*fill
        remaining -= fill
    if np.max(remaining) > 1e-6:
        raise ValueError('PWL segments do not cover output')
    previous = np.r_[generator.initial_status, u[:-1]]
    startup, shutdown = np.maximum(u-previous, 0.), np.maximum(previous-u, 0.)
    return cost+generator.cost_nl*u+generator.cost_su*startup+generator.cost_sd*shutdown


def ledger(generator, p, u, price, delta, best_reported_profit, *, tolerance=1e-6):
    """Use the untruncated LOC difference, reject an inconsistent SS optimum."""
    price = np.asarray(price, dtype=float)
    if price.shape != (generator.T,) or not np.isfinite(price).all():
        raise ValueError('Expected a finite full-horizon nodal price vector')
    if not np.isfinite([delta, best_reported_profit, tolerance]).all() or tolerance <= 0:
        raise ValueError('Invalid adder, self-schedule value or tolerance')
    p, u = np.asarray(p, dtype=float), np.asarray(u, dtype=float)
    cost = float(hourly_cost(generator, p, u).sum())
    exposure = float(np.sum(p-generator.P_min*u))
    revenue = float(price@p)
    reported = cost+delta*exposure
    loc = float(best_reported_profit-(revenue-reported))
    if loc < -tolerance:
        raise ValueError('Self-schedule value is below feasible reported dispatch surplus')
    profit = revenue+loc-cost
    return dict(generation_mwh=float(p.sum()), online_hours=float(u.sum()),
        pmin_committed_mwh=float(generator.P_min*u.sum()), exposure_mwh=exposure,
        energy_revenue_usd=revenue, true_cost_usd=cost, reported_cost_usd=reported,
        reported_dispatch_surplus_usd=revenue-reported, loc_usd=loc,
        best_reported_profit_usd=float(best_reported_profit), bid_wedge_usd=delta*exposure,
        true_profit_usd=profit,
        identity_residual_usd=profit-best_reported_profit-delta*exposure)


def paired_identity(delta, left, right):
    """The caller must bind both ledgers to the SAME bid, price and SS value."""
    if abs(left['best_reported_profit_usd']-right['best_reported_profit_usd']) > 1e-6:
        raise ValueError('P2 needs the same reported self-schedule value')
    observed = left['true_profit_usd']-right['true_profit_usd']
    predicted = delta*(left['exposure_mwh']-right['exposure_mwh'])
    return dict(observed_profit_difference_usd=observed,
        predicted_profit_difference_usd=predicted, residual_usd=observed-predicted,
        exposure_difference_mwh=left['exposure_mwh']-right['exposure_mwh'],
        generation_difference_mwh=left['generation_mwh']-right['generation_mwh'],
        committed_minimum_difference_mwh=left['pmin_committed_mwh']-right['pmin_committed_mwh'],
        energy_revenue_difference_usd=left['energy_revenue_usd']-right['energy_revenue_usd'],
        loc_difference_usd=left['loc_usd']-right['loc_usd'],
        true_cost_difference_usd=left['true_cost_usd']-right['true_cost_usd'])
