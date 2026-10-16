"""Conditional continuous-range profit maximum on a shared optimal physical schedule."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from engine import ScheduleRunMILP, load_case
from benchmarks.unit_self_schedule import dispatch_cost
from price_vulnerability.oracle_compression import query_compact
from price_vulnerability.scalar_markup import apply_generator_adder
from price_vulnerability.model_identity import check_model_identity
from strategic_market_simulation.profit_sweep import _settle_target


def common_schedule_gap(costs_at_endpoints, lower_bounds):
    """Endpoint gaps bound a fixed feasible schedule's suboptimality throughout."""
    costs, bounds = np.asarray(costs_at_endpoints), np.asarray(lower_bounds)
    if costs.shape != (2,) or bounds.shape != (2,) or not np.isfinite([costs, bounds]).all():
        raise ValueError('Need two finite costs and global lower bounds')
    if np.any(costs < bounds-1e-5):
        raise ValueError('A feasible schedule cost is below the solver lower bound')
    return float(max(0., np.max(costs-bounds)))


def assess(oracle_dir, lower_rho=.4, upper_rho=.45):
    audit = json.loads((oracle_dir/'audit.json').read_text(encoding='utf-8'))
    compression = json.loads((oracle_dir/'compression.json').read_text(encoding='utf-8'))
    if (audit['status'] != 'numerically_validated'
            or compression['source_sha256'] != hashlib.sha256((oracle_dir/'oracle.npz').read_bytes()).hexdigest()):
        raise ValueError('Need a complete, source-matched oracle')
    scope = audit['scope']
    if scope.get('bid_hour_1based') is not None:
        raise ValueError('This physical-profit study supports all-day adders only')
    gens, net = load_case(scope['case'], scope['network'], scope['T'], scope['segments'], scope['congestion'])
    check_model_identity(oracle_dir, gens, net, audit)
    g = scope['generator_index']
    slopes = gens[g].pwl_slopes
    ref = float(slopes[len(slopes)//2] if slopes else gens[g].cost_var)
    a, b = ref*lower_rho, ref*upper_rho
    with np.load(oracle_dir/'compact.npz') as data:
        vb, values, pb, prices = [data[k].copy() for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')]
    if not vb[0] <= 0 <= vb[-1] or not vb[0] <= a < b <= vb[-1]:
        raise ValueError('Oracle must contain the baseline and the requested interval')

    physical = []
    for delta in (a, b):
        reported = apply_generator_adder(gens, g, delta)
        uc = ScheduleRunMILP(reported, net)
        p, u, value = uc.solve(require_optimal=True, mip_gap=0.)
        reconstructed = sum(dispatch_cost(unit, p[i], u[i]) for i, unit in enumerate(reported))
        if abs(reconstructed-value) > 1e-5:
            raise RuntimeError('Complete physical-plan cost reconstruction failed')
        physical.append((p, u, uc.solve_info))
    p, u, _ = physical[0]
    costs = [sum(dispatch_cost(unit, p[i], u[i]) for i, unit in enumerate(
                 apply_generator_adder(gens, g, delta))) for delta in (a, b)]
    lower_bounds = [entry[2]['lower_bound'] for entry in physical]
    gap = common_schedule_gap(costs, lower_bounds)
    if gap > 1e-5:
        raise RuntimeError(f'No numerically common optimal physical schedule: endpoint gap {gap:g} USD')
    # Freeze this common schedule as the physical tie-break; existence does not imply uniqueness.
    exposure = float(np.sum(p[g]-gens[g].P_min*u[g]))
    candidates = np.unique(np.r_[a, pb[(a < pb) & (pb < b)], b])

    def settle(delta, physical_p, physical_u):
        price = query_compact(float(delta), vb, values, pb, prices)[1][net.gen_bus_idx(g)]
        report = _settle_target(gens[g], apply_generator_adder(gens, g, float(delta))[g],
                                price, physical_p[g], physical_u[g], mip_gap=0.)
        return {key:float(report[key]) for key in ('true_profit', 'best_reported_profit',
            'self_schedule_upper_bound', 'self_schedule_gap_usd', 'reported_uplift', 'energy_revenue')}

    baseline_p, baseline_u, _ = ScheduleRunMILP(gens, net).solve(require_optimal=True, mip_gap=0.)
    baseline = settle(0., baseline_p, baseline_u)
    rows = [dict(delta=float(delta), rho=float(delta/ref), **settle(delta, p, u)) for delta in candidates]
    for row in rows:
        row['adder_exposure_revenue'] = row['delta']*exposure
        row['extra_profit_vs_truthful'] = row['true_profit']-baseline['true_profit']
        if abs(row['true_profit']-row['best_reported_profit']-row['adder_exposure_revenue']) > 1e-5:
            raise RuntimeError('Profit identity failed')
    winner = max(rows, key=lambda row: row['true_profit'])
    upper_profit = max(row['self_schedule_upper_bound']+row['adder_exposure_revenue'] for row in rows)
    # A midpoint is a sanity check, not the reason the continuous endpoint result holds.
    midpoint_checks = []
    for i in range(len(candidates)-1):
        delta = (candidates[i]+candidates[i+1])/2
        item = settle(delta, p, u)
        if item['true_profit'] > max(rows[i]['true_profit'], rows[i+1]['true_profit'])+1e-5:
            raise RuntimeError('Conditional profit convexity check failed')
        midpoint_checks.append(dict(delta=float(delta), **item))
    return dict(scope=scope, rho_interval=[lower_rho, upper_rho], source_oracle=str(oracle_dir),
        common_physical_schedule_gap_usd=gap, physical_selection='fixed feasible left-endpoint plan, numerically optimal throughout this interval',
        endpoint_uc_info=[entry[2] for entry in physical], common_plan_endpoint_costs=costs,
        endpoint_output_max_difference=float(np.max(np.abs(p-physical[1][0]))),
        endpoint_commitment_max_difference=float(np.max(np.abs(u-physical[1][1]))),
        common_physical_output=p.tolist(), common_physical_commitment=u.tolist(),
        physical_exposure_mwh=exposure, baseline=baseline, candidate_bids=rows, midpoint_checks=midpoint_checks,
        maximizing_candidate=winner, profit_max_upper_bound_usd=upper_profit,
        profit_max_solver_gap_usd=max(0., upper_profit-winner['true_profit']),
        theorem='For a fixed optimal feasible physical plan and an affine price selector, reported self-schedule surplus is a maximum of affine functions. Adding delta times the fixed physical exposure preserves convexity, so the maximum on each price segment is attained at an endpoint.',
        scope_limit='Conditional on this physical tie-break and declared price path, floating-point solver optimality and residuals. Not a global profit maximum on 0-50%, nor a price-independent market-power bound.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oracle-dir', type=Path, required=True)
    parser.add_argument('--lower-rho', type=float, default=.4)
    parser.add_argument('--upper-rho', type=float, default=.45)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output file')
    result = assess(args.oracle_dir, args.lower_rho, args.upper_rho)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    print(f"{len(result['candidate_bids'])} price endpoints, max extra profit "
          f"{result['maximizing_candidate']['extra_profit_vs_truthful']:.6f} USD; "
          f"physical common-plan gap {result['common_physical_schedule_gap_usd']:.3g} USD")


if __name__ == '__main__':
    main()
