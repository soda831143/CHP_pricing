"""Bounded CHP/UC/settlement consistency audit, not an initial-state sensitivity sweep."""
import argparse
import hashlib
from pathlib import Path

import numpy as np

from engine import load_case, ScheduleRunMILP
from benchmarks.unit_self_schedule import dispatch_cost
from make_research_figures import ROOT, MAIN, STUDY, PROFIT, read, write_json, write_csv
from price_vulnerability.affine_oracle import bid_adder_matrix, solve_endpoint, dual_audit_passed
from price_vulnerability.model_identity import model_identity, check_model_identity
from price_vulnerability.oracle_compression import load_matched_compact, query_compact
from strategic_market_simulation.profit_sweep import _settle_target

LOCAL = ROOT/'results/presentation_revision_20261016/30_G1_hour1_0to50'


def schedule_residuals(generators, network, p, u):
    """Reconstruct the actual UC constraints, including pre-horizon and terminal rules."""
    p, u = np.asarray(p), np.asarray(u)
    if p.shape != u.shape or p.shape != (len(generators), network.T) or not np.isfinite([p, u]).all():
        raise ValueError('Expected finite generator-by-hour physical schedules')
    residual = dict(balance=float(np.max(abs(p.sum(axis=0)-network.sys_demand))),
        binary=float(max(np.max(abs(u-np.round(u))), np.max(-u), np.max(u-1))), capacity=0., initial_ramp=0., later_ramp=0.,
        residual_initial_duration=0., minimum_up_down=0., line_capacity=0.)
    for i, g in enumerate(generators):
        prev_u = np.r_[g.initial_status, u[i, :-1]]
        prev_p = np.r_[g.initial_power, p[i, :-1]]
        su, sd = np.maximum(u[i]-prev_u, 0.), np.maximum(prev_u-u[i], 0.)
        ramp = np.maximum(p[i]-prev_p-g.R_up*prev_u-g.SU_ramp*su,
                          prev_p-p[i]-g.R_down*u[i]-g.SD_ramp*sd)
        residual['capacity'] = max(residual['capacity'], float(np.max(g.P_min*u[i]-p[i])),
                                   float(np.max(p[i]-g.P_max*u[i])))
        residual['initial_ramp'] = max(residual['initial_ramp'], float(ramp[0]))
        residual['later_ramp'] = max(residual['later_ramp'], float(np.max(ramp[1:], initial=0.)))
        remaining = max(0, (g.T_on_min-g.initial_up_time) if g.initial_status else (g.T_off_min-g.initial_down_time))
        residual['residual_initial_duration'] = max(residual['residual_initial_duration'],
            float(np.max(abs(u[i, :remaining]-g.initial_status), initial=0.)))
        for t in range(network.T):
            if g.T_on_min > 1:
                residual['minimum_up_down'] = max(residual['minimum_up_down'],
                    float(g.T_on_min*su[t]-u[i, t:min(t+g.T_on_min, network.T)].sum()))
            if g.T_off_min > 1:
                residual['minimum_up_down'] = max(residual['minimum_up_down'],
                    float(g.T_off_min*sd[t]-(1-u[i, t:min(t+g.T_off_min, network.T)]).sum()))
    if not network.is_single_node:
        flow = network.PTDF_Gen@p-network.PTDF@network.demand
        residual['line_capacity'] = max(0., float(np.max(abs(flow)-network.F_max[:, None])))
    return residual


def audited_point(gens, net, g, delta, compact, *, hour=None, aggregate_output=False):
    adders = bid_adder_matrix(len(gens), net.T, g, delta, hour)
    uc = ScheduleRunMILP(gens, net, bid_adders=adders)
    p, u, uc_value = uc.solve(require_optimal=True, mip_gap=0.)
    chp = solve_endpoint(gens, net, g, delta, hour=hour, aggregate_output=aggregate_output)
    if not dual_audit_passed(chp):
        raise RuntimeError('Direct CHP failed its complete primal-dual audit')
    value, price = query_compact(delta, *[compact[k] for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')])
    residual = schedule_residuals(gens, net, p, u)
    costs = [dispatch_cost(gen, p[i], u[i], bid_adders=adders[i]) for i, gen in enumerate(gens)]
    settlements = [_settle_target(gen, gen, price[net.gen_bus_idx(i)], p[i], u[i],
                   mip_gap=0., bid_adders=adders[i]) for i, gen in enumerate(gens)]
    row = dict(delta=delta, bid_hour_1based=hour+1 if hour is not None else None,
        physical_residuals=residual, chp_full_dual_residuals=chp.audit,
        uc_solve_info=uc.solve_info, uc_objective=uc_value, chp_objective=chp.value,
        archived_value_gap_usd=abs(value-chp.value), reported_cost_reconstruction_usd=abs(sum(costs)-uc_value),
        chp_above_uc_lower_bound_usd=max(0., chp.value-uc.solve_info['lower_bound']),
        max_settlement_identity_residual_usd=max(abs(s['energy_revenue']+s['reported_uplift']-s['true_cost']-s['true_profit']) for s in settlements),
        max_bid_wedge_residual_usd=max(abs(s['reported_cost']-s['true_cost']-float(adders[i]@(p[i]-gens[i].P_min*u[i]))) for i, s in enumerate(settlements)),
        units=[dict(unit=gen.unit_id, **{k:s[k] for k in ('energy_revenue', 'reported_uplift', 'reported_cost', 'true_cost', 'true_profit', 'best_reported_profit', 'self_schedule_gap_usd')}) for gen, s in zip(gens, settlements)])
    if (max(residual.values()) > 1e-6 or row['archived_value_gap_usd'] > 1e-6
            or row['reported_cost_reconstruction_usd'] > 1e-5 or row['chp_above_uc_lower_bound_usd'] > 1e-5
            or row['max_bid_wedge_residual_usd'] > 1e-5 or row['max_settlement_identity_residual_usd'] > 1e-5):
        raise RuntimeError(f'Initial-condition / cost / archive audit failed at delta={delta}: {row}')
    return row, p, u


def bind_legacy(directory, identity, deltas, report_path):
    path = directory/'model_identity.json'
    if path.exists():
        previous = read(path)
        if (previous['model_identity']['model_sha256'] != identity['model_sha256']
                or previous['oracle_sha256'] != hashlib.sha256((directory/'oracle.npz').read_bytes()).hexdigest()):
            raise ValueError('Existing binding differs; do not silently rebind a different model')
        return
    write_json(path, dict(model_identity=identity,
        oracle_sha256=hashlib.sha256((directory/'oracle.npz').read_bytes()).hexdigest(),
        binding_kind='retrospective after current-data direct value/physical audit at declared bids; not a contemporaneous historical snapshot',
        directly_rechecked_deltas=deltas, audit_report=str(report_path.relative_to(ROOT))))


def run(output):
    if output.exists():
        raise ValueError('Use a new audit directory; preserve previous reports')
    output.mkdir(parents=True)
    winner = read(PROFIT/'profit_range.json')['maximizing_candidate']
    records, identities = {}, {}
    sources = [('30-G1', MAIN, [0., winner['delta'], 20.991]),
               ('118-G11', ROOT/'results/scope_study_20261016/118_sparse_bracket_0to50', [0.])]
    for name, directory, deltas in sources:
        audit, _, compact = load_matched_compact(directory)
        scope = audit['scope']
        gens, net = load_case(scope['case'], scope['network'], scope['T'], scope['segments'], scope['congestion'])
        identity = model_identity(gens, net)
        if any(g.initial_status or g.initial_power or g.initial_down_time < g.T_off_min for g in gens):
            raise RuntimeError('The archived experiment is not the declared cold-start case')
        identities[name] = identity
        records[name] = []
        for delta in deltas:
            row, _, _ = audited_point(gens, net, scope['generator_index'], delta, compact,
                                      aggregate_output=scope.get('aggregate_output', False))
            records[name].append(row)
            write_json(output/'audit.progress.json', dict(status='in_progress', records=records))
            print(f'{name}: delta={delta:.8g}; physical / CHP / costs / all-unit settlement passed', flush=True)

    # The first-hour economic question is bounded to two UC endpoint solves.
    audit, _, compact = load_matched_compact(LOCAL)
    gens, net = load_case('30', 'ptdf', 24, 3, 'tight')
    endpoint_rows, plans = [], []
    for delta in [0., 20.991]:
        row, p, u = audited_point(gens, net, 0, delta, compact, hour=0)
        endpoint_rows.append(row)
        plans.append((p, u))
    common_gaps = []
    for p, u in plans:
        common_gaps.append([max(0., sum(dispatch_cost(gen, p[i], u[i],
            bid_adders=bid_adder_matrix(len(gens), net.T, 0, r['delta'], 0)[i]) for i, gen in enumerate(gens))
            -r['uc_solve_info']['lower_bound']) for r in endpoint_rows])
    chosen = int(np.argmin(np.max(common_gaps, axis=1)))
    localized = dict(endpoint_uc_checks=endpoint_rows, endpoint_common_plan_gaps_usd=common_gaps,
                     common_plan_found=bool(max(common_gaps[chosen]) <= 1e-5))
    if localized['common_plan_found']:
        p, u = plans[chosen]
        chosen_settlements = []
        for delta in [0., 20.991]:
            price = query_compact(delta, *[compact[k] for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')])[1]
            adders = bid_adder_matrix(len(gens), net.T, 0, delta, 0)
            s = _settle_target(gens[0], gens[0], price[net.gen_bus_idx(0)], p[0], u[0], mip_gap=0., bid_adders=adders[0])
            chosen_settlements.append(dict(delta=delta, **{k:v for k, v in s.items() if not isinstance(v, np.ndarray)}))
        localized.update(chosen_witness_endpoint=chosen, common_plan_target_settlements=chosen_settlements,
            maximum_profit_on_declared_common_plan=max(s['true_profit'] for s in chosen_settlements),
            extra_profit_endpoint_max=max(s['true_profit'] for s in chosen_settlements)-chosen_settlements[0]['true_profit'],
            theorem='A common globally optimal feasible UC plan at both endpoints is optimal throughout; self-schedule surplus is convex along the affine price/objective path. Endpoint maxima apply to this declared common-plan rule, not all dispatch tie-breaks.')
    else:
        localized['interpretation'] = 'No common endpoint plan; no full-range profit maximum claimed. No automatic expansion into a new strategic study.'
    np.savez_compressed(output/'localized_endpoint_plans.npz', outputs=np.stack([p for p, u in plans]),
                        commitments=np.stack([u for p, u in plans]), deltas=np.array([0., 20.991]))
    result = dict(status='passed', initial_condition_source='GeneratorParams default cold start; no previous-day warmup used',
        model_identities=identities, records=records, localized_economics=localized,
        scope='Checks these fixed cases and representative bids; not a warm-start sensitivity study or universal initial-state validation.')
    # Same baseline model, different offer direction: independently check one G2 interior bid.
    directory = STUDY/'30_G2_bracket_0to50'
    audit, _, compact = load_matched_compact(directory)
    delta = float(compact['value_boundaries'][-1]/2)
    endpoint = solve_endpoint(gens, net, 1, delta)
    archived_value = query_compact(delta, *[compact[k] for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')])[0]
    if not dual_audit_passed(endpoint) or abs(endpoint.value-archived_value) > 1e-6:
        raise RuntimeError('G2 model binding failed its direct interior value check')
    result['g2_binding_check'] = dict(delta=delta, direct_value=endpoint.value,
        archived_value=archived_value, value_gap_usd=abs(endpoint.value-archived_value), complete_dual_audit=endpoint.audit)
    write_json(output/'initial_condition_audit.json', result)
    for name, source_dir, deltas in sources:
        bind_legacy(source_dir, identities[name], deltas, output/'initial_condition_audit.json')
    bind_legacy(LOCAL, identities['30-G1'], [0., 20.991], output/'initial_condition_audit.json')
    bind_legacy(directory, identities['30-G1'], [delta], output/'initial_condition_audit.json')
    print(f"Audit complete. Localized common plan: {localized['common_plan_found']}", flush=True)


def localized_followup(audit_dir, output):
    """Reuse both endpoint UC solves; allow at most two extra intersection probes."""
    from run_profit_range import physical_regions
    if output.exists():
        raise ValueError('Preserve earlier localized economic results')
    source = read(audit_dir/'initial_condition_audit.json')
    if source['status'] != 'passed':
        raise ValueError('Need the completed initial-state audit')
    audit, _, compact = load_matched_compact(LOCAL)
    gens, net = load_case('30', 'ptdf', 24, 3, 'tight')
    check_model_identity(LOCAL, gens, net, audit)
    records = source['localized_economics']['endpoint_uc_checks']
    with np.load(audit_dir/'localized_endpoint_plans.npz') as archive:
        plans = {float(d):(archive['outputs'][i], archive['commitments'][i]) for i, d in enumerate(archive['deltas'])}
    bounds = {r['delta']:r['uc_solve_info']['lower_bound'] for r in records}
    output.mkdir(parents=True)

    def solve(delta):
        if delta not in plans:
            adders = bid_adder_matrix(len(gens), net.T, 0, delta, 0)
            uc = ScheduleRunMILP(gens, net, bid_adders=adders)
            p, u, value = uc.solve(require_optimal=True, mip_gap=0.)
            if max(schedule_residuals(gens, net, p, u).values()) > 1e-6:
                raise RuntimeError('Localized intersection schedule is not feasible')
            plans[delta], bounds[delta] = (p, u), uc.solve_info['lower_bound']
        p, u = plans[delta]
        return dict(intercept=sum(dispatch_cost(gen, p[i], u[i]) for i, gen in enumerate(gens)),
            exposure=float(p[0, 0]-gens[0].P_min*u[0, 0]), lower_bound=bounds[delta])

    points, regions = physical_regions(solve, 0., 20.991, max_solves=4)
    candidates = []
    for k, region in enumerate(regions):
        if not region['ready']:
            continue
        p, u = plans[region['witness_delta']]
        for delta in [region['left'], region['right']]:
            price = query_compact(delta, *[compact[key] for key in ('value_boundaries', 'values', 'price_boundaries', 'prices')])[1]
            s = _settle_target(gens[0], gens[0], price[net.gen_bus_idx(0)], p[0], u[0], mip_gap=0.,
                               bid_adders=bid_adder_matrix(len(gens), net.T, 0, delta, 0)[0])
            candidates.append(dict(delta=delta, rho=delta/41.982, physical_region=k,
                exposure_mwh=points[region['witness_delta']]['exposure'],
                **{key:value for key, value in s.items() if not isinstance(value, np.ndarray)}))
    complete = all(r['ready'] for r in regions)
    baseline = records[0]['units'][0]['true_profit']
    report = dict(status='numerically_validated' if complete else 'partial',
        price_map=str(LOCAL.relative_to(ROOT)), physical_regions=regions,
        physical_points=list(points.values()), total_uc_solves=len(points), new_uc_solves=len(points)-2,
        inherited_endpoint_uc_solves=2, target_candidates=candidates,
        baseline_true_profit=baseline, full_range_common_region_coverage=complete,
        maximum_candidate_profit=max(r['true_profit'] for r in candidates) if candidates else None,
        maximum_additional_profit=(max(r['true_profit'] for r in candidates)-baseline) if complete else None,
        interpretation='Conditional on saved affine selector and chosen optimal physical witnesses. Convex profit on each common-plan region reduces its maximum to endpoints. No claim about all dispatch ties or all legal CHP price selections.')
    write_json(output/'localized_economic_followup.json', report)
    if candidates:
        write_csv(output/'localized_profit_candidates.csv', candidates)
    ordered = sorted(plans)
    np.savez_compressed(output/'physical_plans.npz', deltas=np.array(ordered),
        outputs=np.stack([plans[d][0] for d in ordered]), commitments=np.stack([plans[d][1] for d in ordered]))
    print(f'{len(points)-2} extra UC solves; {len(regions)} physical regions; complete={complete}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-dir', type=Path, help='Reuse endpoint audit for bounded localized follow-up')
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.audit_dir:
        localized_followup(args.audit_dir, args.out_dir)
    else:
        run(args.out_dir.resolve())
