"""Joint physical-UC and selected-price regions for a declared scalar bid range."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from engine import ScheduleRunMILP, load_case
from benchmarks.unit_self_schedule import dispatch_cost
from price_vulnerability.oracle_compression import query_compact, load_matched_compact
from price_vulnerability.scalar_markup import apply_generator_adder
from strategic_market_simulation.profit_sweep import _settle_target


def physical_regions(solve, lower, upper, *, max_solves=400, tolerance=1e-5):
    """Feasible schedule lines above v_UC, global MIP-bound chords below it.

    Concavity follows from minimizing affine costs over a FIXED feasible set;
    it does not require that the set of physical schedules be convex.
    """
    if (not np.isfinite([lower, upper, tolerance]).all() or lower >= upper
            or tolerance <= 0 or max_solves < 2):
        raise ValueError('Need a finite increasing domain, positive tolerance and at least two solves')
    points = {}

    def add(delta):
        point = solve(float(delta))
        if not np.isfinite([point['intercept'], point['exposure'], point['lower_bound']]).all():
            raise ValueError('Nonfinite physical cost line or global lower bound')
        points[float(delta)] = dict(point, delta=float(delta))

    add(lower)
    add(upper)

    def intervals():
        ordered = sorted(points)
        witnesses = list(points.values())
        intercepts = np.array([p['intercept'] for p in witnesses])
        slopes = np.array([p['exposure'] for p in witnesses])
        result = []
        for a, b in zip(ordered[:-1], ordered[1:]):
            bounds = np.array([points[a]['lower_bound'], points[b]['lower_bound']])
            residuals = intercepts[:, None]+slopes[:, None]*np.array([a, b])-bounds
            if np.min(residuals) < -tolerance:
                raise RuntimeError('Feasible physical cost is below a global MIP lower bound')
            gaps = np.max(np.abs(residuals), axis=1)
            k = int(np.argmin(gaps))
            pa, pb = points[a], points[b]
            denominator = pa['exposure']-pb['exposure']
            crossing = ((pb['intercept']-pa['intercept'])/denominator
                        if abs(denominator) > 1e-12 else (a+b)/2)
            margin = 1e-12*max(1., abs(a), abs(b))
            probe = crossing if a+margin < crossing < b-margin else (a+b)/2
            result.append(dict(left=a, right=b, witness_delta=witnesses[k]['delta'],
                common_plan_gap_usd=float(gaps[k]), ready=bool(gaps[k] <= tolerance),
                probe_delta=float(probe)))
        return result

    while len(points) < max_solves:
        pending = [r for r in intervals() if not r['ready']]
        if not pending:
            break
        target = max(pending, key=lambda r: r['common_plan_gap_usd'])
        delta = target['probe_delta']
        if not target['left'] < delta < target['right'] or delta in points:
            break
        add(delta)
    raw = intervals()
    # Remove artificial subdivisions only when one saved feasible plan covers the union.
    merged = []
    for row in raw:
        if merged and merged[-1]['ready'] and row['ready']:
            a, b = merged[-1]['left'], row['right']
            gaps = [(max(abs(p['intercept']+x*p['exposure']-points[x]['lower_bound'])
                         for x in (a, b)), d) for d, p in points.items()]
            gap, witness = min(gaps)
            if gap <= tolerance:
                merged[-1] = dict(left=a, right=b, witness_delta=witness,
                    common_plan_gap_usd=float(gap), ready=True)
                continue
        merged.append({k:v for k, v in row.items() if k != 'probe_delta'})
    return points, merged


def assess(oracle_dir, out_dir, *, max_solves=400, tolerance=1e-5):
    if out_dir.exists():
        raise ValueError('Use a new output directory; previous studies are preserved')
    audit, compression, compact = load_matched_compact(oracle_dir)
    digest = compression['source_sha256']
    scope = audit['scope']
    gens, net = load_case(scope['case'], scope['network'], scope['T'], scope['segments'], scope['congestion'])
    g = scope['generator_index']
    slopes = gens[g].pwl_slopes
    ref = float(slopes[len(slopes)//2] if slopes else gens[g].cost_var)
    vb, values, pb, prices = [compact[k] for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')]
    if vb[0] != 0 or not vb[-1] > 0:
        raise ValueError('This study requires a nonnegative adder range anchored at truthful bidding')
    out_dir.mkdir(parents=True)
    started = time.perf_counter()
    completed = []

    def solve(delta):
        reported = apply_generator_adder(gens, g, delta)
        uc = ScheduleRunMILP(reported, net)
        p, u, value = uc.solve(require_optimal=True, mip_gap=0.)
        cost = sum(dispatch_cost(unit, p[i], u[i]) for i, unit in enumerate(reported))
        if abs(cost-value) > tolerance:
            raise RuntimeError('Full physical-plan cost reconstruction failed')
        exposure = float(np.sum(p[g]-gens[g].P_min*u[g]))
        result = dict(intercept=float(cost-delta*exposure), exposure=exposure,
            lower_bound=uc.solve_info['lower_bound'], solver_info=uc.solve_info,
            output=p, commitment=u)
        completed.append(dict(result, delta=delta))
        # Preserve successful full witnesses even if a later MIP or settlement fails.
        np.savez_compressed(out_dir/'physical_plans.npz',
            deltas=[row['delta'] for row in completed],
            outputs=np.array([row['output'] for row in completed]),
            commitments=np.array([row['commitment'] for row in completed]),
            intercepts=[row['intercept'] for row in completed],
            exposures=[row['exposure'] for row in completed],
            lower_bounds=[row['lower_bound'] for row in completed],
            solver_info_json=np.array([json.dumps(row['solver_info']) for row in completed]))
        print(f'UC delta={delta:.10g}, global bound gap={value-result["lower_bound"]:.3g} USD', flush=True)
        return result

    try:
        points, regions = physical_regions(solve, float(vb[0]), float(vb[-1]),
                                           max_solves=max_solves, tolerance=tolerance)
    except Exception as error:
        (out_dir/'failure.json').write_text(json.dumps(dict(status='physical_discovery_failed',
            successful_uc_solves=len(completed), error=str(error)), indent=2), encoding='utf-8')
        raise
    ordered = sorted(points)
    complete = all(r['ready'] for r in regions)
    report = dict(scope=scope, source_oracle=str(oracle_dir), source_sha256=digest,
        compact_sha256=hashlib.sha256((oracle_dir/'compact.npz').read_bytes()).hexdigest(),
        rho_interval=[0., float(vb[-1]/ref)], physical_tolerance_usd=tolerance,
        uc_solves=len(points), physical_regions=regions,
        physical_points=[{k:v for k, v in points[d].items() if k not in ('output', 'commitment')} for d in ordered],
        status='numerically_validated_complete' if complete else 'partial_physical_coverage',
        profit_assessment_status='not_started',
        physical_discovery_seconds=time.perf_counter()-started,
        physical_selection='Each interval fixes its archived common full-system plan. At a shared boundary choose the adjacent archived plan with the higher true profit. This is a declared optimistic boundary tie-break, not a claim about an ISO rule or all optimal schedules.',
        scope_limit='Conditional on the declared CHP selector, physical tie-break, reported LOC uplift and floating-point COPT optimality/bounds. A small UC cost gap is NOT a bound on dispatch or profit error.')
    covered = sum(r['right']-r['left'] for r in regions if r['ready'])/(vb[-1]-vb[0])
    report['physical_coverage_fraction'] = float(covered)
    (out_dir/'physical_regions.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    settlements = {}

    def settle(delta):
        if delta not in settlements:
            p, u = points[0.]['output'], points[0.]['commitment']
            price = query_compact(delta, vb, values, pb, prices)[1][net.gen_bus_idx(g)]
            # M_rep depends on price and bid, not the selected physical plan.
            item = _settle_target(gens[g], apply_generator_adder(gens, g, delta)[g],
                price, p[g], u[g], mip_gap=0.)
            settlements[delta] = dict(best_reported_profit=float(item['best_reported_profit']),
                self_schedule_upper_bound=float(item['self_schedule_upper_bound']))
        return settlements[delta]

    # Use self-schedule surplus plus the bid wedge, not revenue at an arbitrary direct-solve price.
    baseline = settle(0.)['best_reported_profit']
    candidates, joint = [], []
    for region_index, region in enumerate(regions):
        if not region['ready']:
            continue
        a, b = region['left'], region['right']
        witness = points[region['witness_delta']]
        bids = np.unique(np.r_[a, pb[(a < pb) & (pb < b)], b])
        joint.extend(dict(left=float(x), right=float(y), physical_region=region_index)
                     for x, y in zip(bids[:-1], bids[1:]))
        for delta in bids:
            delta = float(delta)
            item = settle(delta)
            wedge = delta*witness['exposure']
            profit = item['best_reported_profit']+wedge
            price = query_compact(delta, vb, values, pb, prices)[1][net.gen_bus_idx(g)]
            p, u = witness['output'][g], witness['commitment'][g]
            revenue = float(price@p)
            true_cost = float(dispatch_cost(gens[g], p, u))
            reported_cost = true_cost+wedge
            uplift = max(0., item['best_reported_profit']-(revenue-reported_cost))
            if abs(revenue+uplift-true_cost-profit) > 1e-4:
                raise RuntimeError('Physical settlement and surplus-plus-wedge identity disagree')
            candidates.append(dict(delta=delta, rho=delta/ref, physical_region=region_index,
                physical_plan_delta=region['witness_delta'], physical_exposure_mwh=witness['exposure'],
                generation_mwh=float(p.sum()), energy_revenue=revenue, true_cost=true_cost,
                reported_uplift=uplift, adder_exposure_revenue=wedge, **item,
                true_profit=profit, extra_profit_vs_truthful=profit-baseline,
                profit_upper_bound=item['self_schedule_upper_bound']+wedge))
    winner = max(candidates, key=lambda row: row['true_profit']) if candidates else None
    report.update(baseline_true_profit=baseline, joint_intervals=joint, candidate_bids=candidates,
        profit_assessment_status='completed',
        unique_self_schedule_solves=len(settlements), maximizing_candidate=winner,
        conditional_maximum_is_full_range=complete,
        profit_max_solver_gap_usd=(max(0., max(row['profit_upper_bound'] for row in candidates)-winner['true_profit'])
                                   if candidates else None),
        total_seconds=time.perf_counter()-started,
        theorem='On each common physical-plan interval intersected with an affine selected-price interval, Pi_true=M_rep+delta*D. M_rep is the maximum of affine self-schedule surplus functions, hence Pi_true is convex and its maximum is at an endpoint. At physical boundaries both adjacent plan values are retained, with the stated tie-break; no continuity of profit is asserted.')
    (out_dir/'profit_range.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(f'{report["status"]}: {len(points)} UC solves, {len(regions)} physical regions, '
          f'{len(joint)} joint intervals, covered {covered:.8%}', flush=True)
    return report


def validate_existing(oracle_dir, out_dir):
    """Independent UC at physical-region interiors and the winning switch's sides."""
    destination = out_dir/'direct_validation.json'
    if destination.exists():
        raise ValueError('Preserve earlier validation results')
    report = json.loads((out_dir/'profit_range.json').read_text(encoding='utf-8'))
    audit, compression, compact = load_matched_compact(oracle_dir)
    if (report['source_sha256'] != compression['source_sha256']
            or report['compact_sha256'] != hashlib.sha256((oracle_dir/'compact.npz').read_bytes()).hexdigest()):
        raise ValueError('Validation must use the original selected-price path')
    scope = audit['scope']
    gens, net = load_case(scope['case'], scope['network'], scope['T'], scope['segments'], scope['congestion'])
    g = scope['generator_index']
    with np.load(out_dir/'physical_plans.npz') as data:
        saved = {float(delta):(data['outputs'][i], data['commitments'][i]) for i, delta in enumerate(data['deltas'])}
    regions = [r for r in report['physical_regions'] if r['ready']]
    winner = report['maximizing_candidate']
    extent = compact['value_boundaries'][-1]-compact['value_boundaries'][0]
    queries = [(r['left']+r['right'])/2 for r in regions]
    queries += [winner['delta']+offset for offset in (-1e-5*extent, 0., 1e-5*extent)]
    rows = []
    for delta in sorted(set(queries)):
        eligible = [r for r in regions if r['left'] <= delta <= r['right']]
        if not eligible:
            continue
        # Positive delta: larger exposure gives higher profit at a shared boundary.
        region = max(eligible, key=lambda r: np.sum(saved[r['witness_delta']][0][g]
                        -gens[g].P_min*saved[r['witness_delta']][1][g]))
        p, u = saved[region['witness_delta']]
        reported = apply_generator_adder(gens, g, float(delta))
        uc = ScheduleRunMILP(reported, net)
        direct_p, direct_u, value = uc.solve(require_optimal=True, mip_gap=0.)
        cost = sum(dispatch_cost(unit, p[i], u[i]) for i, unit in enumerate(reported))
        gap = cost-uc.solve_info['lower_bound']
        if abs(gap) > report['physical_tolerance_usd']:
            raise RuntimeError('Independent UC does not support the declared physical plan')
        price = query_compact(float(delta), *[compact[k] for k in (
            'value_boundaries', 'values', 'price_boundaries', 'prices')])[1][net.gen_bus_idx(g)]
        item = _settle_target(gens[g], reported[g], price, p[g], u[g], mip_gap=0.)
        if item['true_profit'] > winner['true_profit']+1e-4:
            raise RuntimeError('Independent internal point exceeds the endpoint candidate maximum')
        direct_exposure = float(np.sum(direct_p[g]-gens[g].P_min*direct_u[g]))
        rows.append(dict(delta=float(delta), physical_plan_gap_to_global_bound_usd=float(gap),
            direct_uc_objective=float(value), direct_uc_info=uc.solve_info,
            selected_physical_generation_mwh=float(p[g].sum()),
            solver_selected_physical_generation_mwh=float(direct_p[g].sum()),
            declared_profit=float(item['true_profit']),
            solver_dispatch_profit_at_same_price=float(item['best_reported_profit']+delta*direct_exposure)))
    result = dict(status='passed', points=rows,
        max_abs_physical_plan_gap_usd=max(abs(r['physical_plan_gap_to_global_bound_usd']) for r in rows),
        purpose='Independent region-interior and winning-boundary-neighborhood checks. Profit comparison keeps the same CHP selector; different UC tie choices at the switch are reported, not treated as errors. Sampling corroborates, but does not replace the endpoint-bound argument.')
    destination.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oracle-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--max-uc-solves', type=int, default=400)
    parser.add_argument('--validate-existing', action='store_true', help='Check archived region interiors and the maximizing boundary with independent UC')
    args = parser.parse_args()
    if args.validate_existing:
        result = validate_existing(args.oracle_dir, args.out_dir)
        print(f"Independent UC: {len(result['points'])} checks passed")
    else:
        assess(args.oracle_dir, args.out_dir, max_solves=args.max_uc_solves)


if __name__ == '__main__':
    main()
