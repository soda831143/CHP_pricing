"""A fixed 2x2 test of substitution-cost shifts and feasible-competitor entry."""
import argparse
from dataclasses import replace

import numpy as np

from engine import ScheduleRunMILP
from price_vulnerability.persistent_chp import PersistentCHP
from price_vulnerability.scalar_markup import apply_generator_adder
from price_vulnerability.model_identity import model_identity, check_model_identity
from run_initial_condition_audit import schedule_residuals
from strategic_market_simulation.profit_sweep import _settle_target
from mechanism_study import runtime
from mechanism_study.runtime import ROOT, Stage, read, write, digest
from mechanism_study.run_study import load_inputs, PHYSICAL, ORACLE
from mechanism_study.constraint_attribution import treatment
from mechanism_study.predictive_mechanism import candidate_lines, crossing, table
from mechanism_study.profit_identity import ledger, hourly_cost
from mechanism_study.linear_audit import primal_lp_audit

OUT = ROOT / 'results/competition_regimes_20261102'
NETWORK = ROOT / 'results/mechanism_20261018/followup/E4_causal_recovery_02'
HELD = ROOT / 'results/mechanism_20261019/P2_held_out'


def prepare():
    gens, net, compact, report, critical, adjacent, plans = load_inputs()
    intervention = read(NETWORK / 'intervention_before_treatment.json')['intervention']
    _, relaxed = treatment(gens, net, intervention)
    with np.load(NETWORK / 'relaxed_bid1.npz') as z:
        plans = {**plans, 'C_relaxed_frozen': (z['p'].copy(), z['u'].copy())}
    held = read(HELD / 'summary.json')['records'][0]
    assert held['epsilon'] == 5. and held['supported']
    quotes = [critical - .001, held['predicted_critical'] - .001]
    inputs = [PHYSICAL / 'profit_range.json', PHYSICAL / 'physical_plans.npz',
              NETWORK / 'intervention_before_treatment.json', HELD / 'summary.json',
              HELD / 'manifest.json']
    inputs += [NETWORK / f'{s}_bid{b}.{ext}' for s in ('original', 'relaxed')
               for b in (0, 1) for ext in ('json', 'npz')]
    inputs += [HELD / f'epsilon5_{name}.{ext}' for name in
               ('baseline', 'baseline_settlement', 'left', 'left_settlement')
               for ext in ('json', 'npz')]
    predictions = []
    for epsilon in (0., 5.):
        changed = list(gens)
        changed[4] = replace(gens[4], cost_nl=gens[4].cost_nl + epsilon)
        a, b, c = candidate_lines(changed, plans)
        threshold = crossing(a['cost'], b['cost'], a['exposure'], b['exposure'])
        for label, (p, u) in plans.items():
            residual = schedule_residuals(changed, relaxed, p, u)
            assert max(residual.values()) < 1e-7
        for delta in (0., 20.991, threshold, *quotes):
            value_c = c['cost'] + delta*c['exposure']
            predictions.append(dict(epsilon=epsilon, delta=delta, pair_crossing=threshold,
                A_minus_frozen_C=a['cost']+delta*a['exposure']-value_c,
                B_minus_frozen_C=b['cost']+delta*b['exposure']-value_c,
                C_exposure=c['exposure'], C_online_G5=c['g5_online_hours']))
    protocol = dict(date='2026-11-02', epsilon_usd_per_G5_online_hour=[0., 5.],
        fixed_quotes=quotes, baselines=[0.], offer_domain=[0., 20.991],
        intervention=intervention, frozen_plan_C_source=str((NETWORK/'relaxed_bid1.npz').relative_to(ROOT)),
        predictions=predictions, budgets=dict(uc=5, chp=6, self_schedule=6), seconds=600.,
        selector='Fresh cold COPT dual simplex at each new pricing point; threads=1, seed=20261018. Reused archival points follow the same cold selector.',
        physical_selection='Archived globally supported schedules when available; fresh global UC at new points. Quotes avoid the tested A/B ties.',
        original_new_point='Use the certified original physical region at quote 2; rebuild CHP and self-scheduling, and compare with its certified settlement curve.',
        prediction_scope='Frozen feasible C may disqualify A/B without being globally optimal. No new network price map or full-domain profit search.',
        inputs={str(p.relative_to(ROOT)): digest(p) for p in inputs})
    return gens, net, relaxed, report, plans, protocol


def fresh(stage, name, gens, net, delta, plans, physical=None):
    cached = stage.cached(name)
    if cached is not None:
        with np.load(stage.out/(name+'.npz')) as z:
            return cached, {k: z[k].copy() for k in ('p', 'u', 'price')}
    reported = apply_generator_adder(gens, 0, delta)
    if physical is None:
        uc = ScheduleRunMILP(reported, net)
        p, u, value = stage.call('uc', name, lambda: uc.solve(require_optimal=True, mip_gap=0.))
        lower = uc.solve_info['lower_bound']
    else:
        p, u, value, lower = physical
    residual = schedule_residuals(gens, net, p, u)
    lines = candidate_lines(gens, {'selected': (p, u), **plans})
    assert max(residual.values()) < 1e-7
    assert abs(lines[0]['cost']+delta*lines[0]['exposure']-value) < 1e-6
    assert -1e-6 < value-lower < 1e-5
    cp = PersistentCHP(gens, net, 0)
    point = stage.call('chp', name, lambda: cp.solve(delta))
    audit, arrays = primal_lp_audit(cp)
    ss = stage.call('self_schedule', name, lambda: _settle_target(
        gens[0], reported[0], point.price[net.gen_bus_idx(0)], p[0], u[0], mip_gap=0.))
    assert ss['self_schedule_gap_usd'] < 1e-6
    account = ledger(gens[0], p[0], u[0], point.price[net.gen_bus_idx(0)],
                     delta, ss['best_reported_profit'])
    record = dict(delta=delta, **account, reported_system_cost_usd=value, uc_global_bound_usd=lower,
        selected_actual_system_cost=lines[0]['cost'], selected_G5_online_hours=float(u[4].sum()),
        candidate_gaps=[line['cost']+delta*line['exposure']-lower for line in lines[1:]],
        feasibility=residual, lp_audit=audit, self_schedule_gap_usd=ss['self_schedule_gap_usd'],
        model_identity=model_identity(gens, net), source=name, old_oracle_reused=False)
    stage.save(name, record, dict(**arrays, p=p, u=u, price=point.price,
        self_p=ss['self_output_mw'], self_u=ss['self_commitment']))
    return record, dict(p=p, u=u, price=point.price)


def archived(network, epsilon, quote):
    if epsilon == 0.:
        path = NETWORK / f'{network}_bid{0 if quote == 0 else 1}'
        record = read(path.with_suffix('.json'))['settlement']
        with np.load(path.with_suffix('.npz')) as z:
            arrays = {k: z[k].copy() for k in ('p', 'u', 'price')}
    else:
        label = 'baseline' if quote == 0 else 'left'
        path = HELD / f'epsilon5_{label}'
        record = {**read(path.with_suffix('.json')),
                  **read(HELD/f'epsilon5_{label}_settlement.json'), 'delta': quote}
        record['reported_system_cost_usd'] = record['value']
        record['uc_global_bound_usd'] = record['lower_bound']
        with np.load(path.with_suffix('.npz')) as z:
            arrays = {k: z[k].copy() for k in ('p', 'u')}
        with np.load(HELD/f'epsilon5_{label}_settlement.npz') as z:
            arrays['price'] = z['price'].copy()
    record = dict(record, source=str(path.relative_to(ROOT)))
    assert abs(record['delta']-quote) < 1e-9
    return record, arrays


def run(resume=False, plan_only=False):
    gens, net, relaxed, report, plans, protocol = prepare()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'protocol_before_run.json'
    if path.exists():
        assert read(path) == protocol, 'Preserve the protocol and its input snapshots'
    else:
        write(path, protocol)
    table(OUT/'frozen_competition_predictions.csv', protocol['predictions'])
    if plan_only:
        print('Registered quotes:', protocol['fixed_quotes'])
        print('Predicted A/B exclusion by frozen C:', protocol['predictions'])
        return
    runtime.OUTPUT = OUT
    stage = Stage('factorial', budgets=protocol['budgets'], seconds=protocol['seconds'],
                  resume=resume, plan=protocol)
    cases, price_rows = [], []
    q0, q1 = protocol['fixed_quotes']
    with stage.solvers():
        for network, nn in [('original', net), ('relaxed', relaxed)]:
            for epsilon in (0., 5.):
                changed = list(gens)
                changed[4] = replace(gens[4], cost_nl=gens[4].cost_nl + epsilon)
                if network != 'original' or epsilon != 0.:
                    try:
                        check_model_identity(ORACLE, changed, nn)
                    except ValueError as error:
                        assert str(error) == 'Oracle model data or initial conditions changed; rebuild or revalidate the map'
                    else:
                        raise AssertionError('Changed model accepted the original price map')
                for index, delta in enumerate((0., q0, q1)):
                    name = f'{network}_epsilon{epsilon:g}_quote{index}'
                    print(name, flush=True)
                    physical = None
                    reuse = ((epsilon == 0. and index < 2)
                             or (network == 'original' and epsilon == 5. and index != 1))
                    if reuse:
                        record, arrays = archived(network, epsilon, delta)
                    else:
                        if network == 'original' and epsilon == 0.:
                            region = next(r for r in report['physical_regions'] if r['left'] < delta < r['right'])
                            with np.load(PHYSICAL/'physical_plans.npz') as z:
                                k = np.flatnonzero(np.isclose(z['deltas'], region['witness_delta'], atol=1e-10, rtol=0)).item()
                                value = float(z['intercepts'][k]+delta*z['exposures'][k])
                                physical = (z['outputs'][k].copy(), z['commitments'][k].copy(),
                                            value, value-region['common_plan_gap_usd'])
                        record, arrays = fresh(stage, name, changed, nn, delta, plans, physical)
                    p, u, price = (arrays[k] for k in ('p', 'u', 'price'))
                    assert max(schedule_residuals(changed, nn, p, u).values()) < 1e-7
                    account = ledger(changed[0], p[0], u[0], price[0], delta, record['best_reported_profit_usd'])
                    for key in ('true_profit_usd', 'loc_usd', 'energy_revenue_usd', 'true_cost_usd'):
                        assert abs(account[key]-record[key]) < 1e-6
                    lines = candidate_lines(changed, {'selected': (p, u), **plans})
                    offered = lines[0]['cost']+delta*lines[0]['exposure']
                    assert abs(offered-record['reported_system_cost_usd']) < 1e-6
                    gaps = [line['cost']+delta*line['exposure']-record['uc_global_bound_usd'] for line in lines[1:]]
                    cases.append(dict(network=network, epsilon=epsilon, quote=index, delta=delta,
                        R=account['energy_revenue_usd'], U=account['loc_usd'], C=account['true_cost_usd'],
                        Pi=account['true_profit_usd'], Q=account['exposure_mwh'], generation=account['generation_mwh'],
                        actual_system_cost=lines[0]['cost'], reported_system_cost=offered,
                        uc_gap=offered-record['uc_global_bound_usd'], G5_online_hours=float(u[4].sum()),
                        A_gap=gaps[0], B_gap=gaps[1], frozen_C_gap=gaps[2], source=record['source']))
                    for bus, unit in [(0, 'G1'), (22, 'G5')]:
                        for t in range(24):
                            price_rows.append(dict(network=network, epsilon=epsilon, quote=index,
                                delta=delta, unit=unit, hour=t+1, price=float(price[bus,t]), output=float(p[0 if unit=='G1' else 4,t])))
    for row in cases:
        base = next(r for r in cases if r['network']==row['network'] and r['epsilon']==row['epsilon'] and r['quote']==0)
        for key in ('R', 'U', 'C', 'Pi', 'Q', 'generation'):
            row['delta_'+key] = row[key]-base[key]
        assert abs(row['delta_R']+row['delta_U']-row['delta_C']-row['delta_Pi']) < 1e-6
    for row in price_rows:
        base = next(r for r in price_rows if r['network']==row['network'] and r['epsilon']==row['epsilon']
                    and r['quote']==0 and r['unit']==row['unit'] and r['hour']==row['hour'])
        row['offer_response'] = row['price']-base['price']
    assert all(digest(ROOT/p)==sha for p, sha in protocol['inputs'].items())
    table(OUT/'factorial_settlements.csv', cases)
    table(OUT/'factorial_hourly_responses.csv', price_rows)
    counts = {kind: sum(c['kind']==kind for c in stage.state['calls']) for kind in protocol['budgets']}
    summary = dict(status='passed', cases=cases, new_solve_counts=counts,
        new_optimization_solves=sum(counts.values()), inputs_unchanged=True,
        scope='Two fixed offers and own truthful baselines in four conditions. Frozen C tests A/B eligibility; no global profit maximum in changed conditions.')
    write(OUT/'summary.json', summary)
    stage.finish()
    print('Completed:', counts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    run(resume=args.resume, plan_only=args.plan_only)
