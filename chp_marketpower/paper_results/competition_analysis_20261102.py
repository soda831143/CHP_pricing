"""Audit the fixed factorial study and export its competition eligibility tests."""
import csv
from itertools import product

import numpy as np

from mechanism_study.runtime import ROOT, read, write, digest
from mechanism_study.run_study import load_inputs
from mechanism_study.competition_regimes import OUT, NETWORK, HELD
from mechanism_study.constraint_attribution import treatment
from mechanism_study.predictive_mechanism import candidate_lines, table
from mechanism_study.profit_identity import ledger, hourly_cost
from paper_results.components import price_components
from price_vulnerability.oracle_compression import query_compact

PAPER = ROOT / 'paper_results/revision_20261102'


def dominance_margin(pair, competitor, delta_bounds, epsilon_bounds):
    """Minimum affine cost advantage over the four corners of a closed box."""
    return min(a['cost']-competitor['cost']+d*(a['exposure']-competitor['exposure'])
               +e*(a['g5_online_hours']-competitor['g5_online_hours'])
               for a in pair for d, e in product(delta_bounds, epsilon_bounds))


def main():
    protocol = read(OUT/'protocol_before_run.json')
    summary = read(OUT/'summary.json')
    stage = read(OUT/'factorial/manifest.json')
    assert summary['status'] == stage['status'] == 'passed'
    assert summary['new_solve_counts'] == {'uc': 5, 'chp': 6, 'self_schedule': 6}
    assert all(c['status']=='completed' for c in stage['calls']) and len(stage['calls']) == 17
    assert all(digest(ROOT/p)==sha for p, sha in protocol['inputs'].items())
    assert all(digest(ROOT.parent/p)==sha for p, sha in stage['identity']['code'].items())
    for name, job in stage['jobs'].items():
        assert digest(OUT/f'factorial/{name}.json') == job['json_sha256']
        assert digest(OUT/f'factorial/{name}.npz') == job['npz_sha256']
    gens, net, compact, old_report, critical, adjacent, plans = load_inputs()
    _, relaxed = treatment(gens, net, protocol['intervention'])
    with np.load(NETWORK/'relaxed_bid1.npz') as z:
        cplan = z['p'].copy(), z['u'].copy()
    a, b, c = candidate_lines(gens, {**plans, 'C': cplan})
    cflow = net.PTDF_Gen@cplan[0]-net.PTDF@net.demand
    assert np.max(abs(cflow)-net.F_max[:,None]) > 1.
    assert np.max(abs(cflow)-relaxed.F_max[:,None]) < 1e-7
    margin = dominance_margin([a,b], c, protocol['offer_domain'], [0.,5.])
    assert abs(margin-1635.464037952188) < 1e-6 and margin > 0.
    case_rows = summary['cases']
    assert len(case_rows) == 12
    max_price_error, max_ledger_error, max_saved_residual = 0., 0., 0.
    for name in stage['jobs']:
        record = read(OUT/f'factorial/{name}.json')
        with np.load(OUT/f'factorial/{name}.npz') as z:
            if name.startswith('relaxed_') and not name.endswith('quote0'):
                assert np.max(abs(z['p']-cplan[0])) < 1e-7
                assert np.max(abs(z['u']-cplan[1])) < 1e-7
            e, congestion, mu = price_components(z['eq_dual'], z['ineq_dual'], net.PTDF, net.T)
            error = float(np.max(abs(e[None,:]+congestion-z['price'])))
            max_price_error = max(max_price_error, error)
            assert error < 1e-7
            account = ledger(gens[0], z['p'][0], z['u'][0], z['price'][0],
                             record['delta'], record['best_reported_profit_usd'])
            # Re-evaluate the self-scheduling witness using its actual piecewise cost.
            qss = float(np.sum(z['self_p']-gens[0].P_min*z['self_u']))
            best = float(z['price'][0]@z['self_p']-hourly_cost(gens[0],z['self_p'],z['self_u']).sum()-record['delta']*qss)
            assert abs(best-record['best_reported_profit_usd']) < 1e-6
            max_ledger_error = max(max_ledger_error, abs(account['true_profit_usd']-record['true_profit_usd']))
        max_saved_residual = max(max_saved_residual, *record['lp_audit'].values(), *record['feasibility'].values())
        assert max_saved_residual < 1e-6
    # The one reused original UC interior plan must recover its independently certified curve.
    with (ROOT/'paper_results/source_data/fig3_profit_uplift_curves.csv').open(encoding='utf-8-sig') as stream:
        curves = list(csv.DictReader(stream))
    quote = protocol['fixed_quotes'][1]
    curve_pair = next((curves[k],curves[k+1]) for k in range(0,len(curves),2)
                      if float(curves[k]['delta']) < quote < float(curves[k+1]['delta']))
    theta = (quote-float(curve_pair[0]['delta']))/(float(curve_pair[1]['delta'])-float(curve_pair[0]['delta']))
    original = next(r for r in case_rows if r['network']=='original' and r['epsilon']==0 and r['quote']==2)
    for field in ('R','U','C','Pi'):
        value = (1-theta)*float(curve_pair[0][field])+theta*float(curve_pair[1][field])
        assert abs(original[field]-value) < 1e-6, (field, original[field], value)
    with np.load(OUT/'factorial/original_epsilon0_quote2.npz') as z:
        selected = query_compact(quote, *[compact[k] for k in
            ('value_boundaries','values','price_boundaries','prices')])[1]
        assert np.max(abs(z['price']-selected)) < 1e-7
    PAPER.mkdir(parents=True,exist_ok=True)
    sources = PAPER/'source_data'
    sources.mkdir(exist_ok=True)
    for r in case_rows:
        r['frozen_C_feasible'] = r['network']=='relaxed'
        # The original-network C cost difference is not an optimality gap: C is infeasible there.
        if not r['frozen_C_feasible']:
            r['frozen_C_gap'] = ''
        assert abs(r['delta_R']+r['delta_U']-r['delta_C']-r['delta_Pi']) < 1e-6
    table(sources/'factorial_settlements.csv', case_rows)
    effects=[]
    for quote_index in (1,2):
        for network in ('original','relaxed'):
            before, after = [next(r for r in case_rows if r['network']==network and r['quote']==quote_index
                                  and r['epsilon']==epsilon) for epsilon in (0.,5.)]
            effects.append(dict(network=network, quote=quote_index, delta=before['delta'],
                delta_Pi_epsilon0=before['delta_Pi'], delta_Pi_epsilon5=after['delta_Pi'],
                cost_treatment_effect=after['delta_Pi']-before['delta_Pi'],
                revenue_response_effect=after['delta_R']-before['delta_R'],
                uplift_response_effect=after['delta_U']-before['delta_U'],
                minus_cost_response_effect=before['delta_C']-after['delta_C'],
                Q_epsilon0=before['Q'], Q_epsilon5=after['Q']))
    table(sources/'cost_treatment_effects.csv',effects)
    gate=[]
    previous_path = ROOT/'results/mechanism_20261019/P0_threshold_io_recovery/summary.json'
    supported_zero = next(r for r in read(previous_path)['records'] if r['epsilon']==0.)['supported']
    supported_five = read(HELD/'summary.json')['records'][0]['supported']
    assert supported_zero and supported_five
    for epsilon in (0.,5.):
        record = next(r for r in protocol['predictions'] if r['epsilon']==epsilon and r['delta']==r['pair_crossing'])
        gate.append(dict(epsilon=epsilon, predicted_pair_threshold=record['pair_crossing'],
            original_pair_supported=supported_zero if epsilon==0. else supported_five,
            relaxed_pair_supported=False,
            relaxed_frozen_C_advantage_at_crossing=record['A_minus_frozen_C'],
            original_A_G5_hours=a['g5_online_hours'],original_B_G5_hours=b['g5_online_hours'],
            relaxed_C_G5_hours=c['g5_online_hours']))
    table(sources/'threshold_eligibility.csv',gate)
    for name in ('factorial_hourly_responses.csv','frozen_competition_predictions.csv'):
        (sources/name).write_bytes((OUT/name).read_bytes())
    inputs = {**protocol['inputs'], **{str(p.relative_to(ROOT)):digest(p) for p in
        [OUT/'protocol_before_run.json',OUT/'summary.json',OUT/'factorial/manifest.json',previous_path,
         ROOT/'paper_results/source_data/fig3_profit_uplift_curves.csv']}}
    write(PAPER/'input_manifest.json',inputs)
    result = dict(status='passed', factorial_cases=12, fixed_offers=2, new_optimization_solves=17,
        new_uc_solves=5, new_chp_solves=6, new_self_schedule_solves=6,
        maximum_price_projection_error=max_price_error, maximum_ledger_error=max_ledger_error,
        maximum_saved_feasibility_or_KKT_residual=max_saved_residual,
        frozen_C_strict_dominance_margin_over_offer_cost_box=margin,
        frozen_C_G5_online_hours=c['g5_online_hours'], original_interior_curve_recovery='passed',
        input_hashes=len(inputs), new_optimizer_calls_by_this_audit=0)
    write(PAPER/'verification.json',result)
    print(result)
    print('Cost treatment effects:',effects)


if __name__ == '__main__':
    main()
