"""Reconstruct network offer responses and physical switching from archived solves."""
import csv
import numpy as np

from mechanism_study.runtime import ROOT, digest, read, write

PAPER = ROOT / 'paper_results'
OUT = PAPER / 'revision_20261021'
COUNTER = ROOT / 'results/mechanism_20261018/followup/E4_causal_recovery_02'
PHYSICAL = ROOT / 'results/targeted_study_20261016/30_G1_profit_0to50'


def save(name, records):
    path = OUT / 'source_data' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main():
    inputs = [COUNTER / f'{s}_bid{b}.{ext}' for s in ('original', 'relaxed')
              for b in range(3) for ext in ('json', 'npz')]
    inputs += [PHYSICAL / 'profit_range.json', PHYSICAL / 'physical_plans.npz',
               PAPER / 'source_data/network_counterfactual_settlements.csv',
               PAPER / 'source_data/network_counterfactual_hourly_prices.csv',
               ROOT / 'results/mechanism_20261019/P0_threshold_io_recovery/summary.json']
    fingerprints = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    write(OUT / 'input_manifest.json', fingerprints)
    with inputs[-3].open(encoding='utf-8-sig') as stream:
        archived = {(r['scenario'], int(r['bid'])): r for r in csv.DictReader(stream)}
    with inputs[-2].open(encoding='utf-8-sig') as stream:
        hourly = {(r['scenario'], int(r['bid']), int(r['hour'])): r
                  for r in csv.DictReader(stream)}
    accounts, arrays, ledger_errors = {}, {}, []
    for scenario in ('original', 'relaxed'):
        for bid in range(3):
            key = scenario, bid
            account = read(COUNTER / f'{scenario}_bid{bid}.json')['settlement']
            with np.load(COUNTER / f'{scenario}_bid{bid}.npz') as z:
                arrays[key] = {k: z[k].copy() for k in ('price', 'p', 'u')}
            a = arrays[key]
            revenue = float(a['price'][0] @ a['p'][0])
            residual = revenue + account['loc_usd'] - account['true_cost_usd'] - account['true_profit_usd']
            ledger_errors.append(abs(residual))
            assert abs(residual) < 1e-6
            assert abs(revenue - account['energy_revenue_usd']) < 1e-6
            assert abs(account['true_profit_usd'] - account['best_reported_profit_usd']
                       - account['delta'] * account['exposure_mwh']) < 1e-6
            pmin = account['pmin_committed_mwh'] / account['online_hours']
            assert abs(float(np.sum(a['p'][0] - pmin * a['u'][0])) - account['exposure_mwh']) < 1e-6
            for raw_key, table_key in [('energy_revenue_usd', 'R'), ('loc_usd', 'U'),
                                       ('true_cost_usd', 'C'), ('true_profit_usd', 'Pi')]:
                assert abs(account[raw_key] - float(archived[key][table_key])) < 1e-6
            for t in range(24):
                record = hourly[scenario, bid, t + 1]
                for bus, unit in [(0, 'G1'), (22, 'G5')]:
                    assert abs(a['price'][bus, t] - float(record[f'lambda_CHP_{unit}'])) < 1e-7
                    assert abs(a['price'][bus, t] - float(record['lambda_E'])
                               - float(record[f'lambda_C_{unit}'])) < 1e-7
            accounts[key] = account

    responses, settlements, contrasts = [], [], []
    for bid in (1, 2):
        changes = {}
        for scenario in ('original', 'relaxed'):
            base, offered = accounts[scenario, 0], accounts[scenario, bid]
            assert offered['delta'] == accounts['original', bid]['delta']
            a, b = arrays[scenario, 0], arrays[scenario, bid]
            change = {key: offered[key] - base[key] for key in
                      ('energy_revenue_usd', 'loc_usd', 'true_cost_usd', 'true_profit_usd',
                       'generation_mwh', 'exposure_mwh')}
            # Exact ordered revenue identity; these terms are accounting, not causal shares.
            price_term = float(a['p'][0] @ (b['price'][0] - a['price'][0]))
            output_term = float(b['price'][0] @ (b['p'][0] - a['p'][0]))
            assert abs(price_term + output_term - change['energy_revenue_usd']) < 1e-6
            settlements.append(dict(scenario=scenario, bid=bid, delta=offered['delta'],
                baseline_Pi=base['true_profit_usd'], offered_Pi=offered['true_profit_usd'],
                delta_R=change['energy_revenue_usd'], delta_U=change['loc_usd'],
                delta_C=change['true_cost_usd'], delta_Pi=change['true_profit_usd'],
                delta_generation=change['generation_mwh'], delta_Q=change['exposure_mwh'],
                baseline_output_price_term=price_term, offered_price_output_term=output_term))
            changes[scenario] = change
        contrast = {key: changes['relaxed'][key] - changes['original'][key] for key in changes['original']}
        residual = (contrast['energy_revenue_usd'] + contrast['loc_usd']
                    - contrast['true_cost_usd'] - contrast['true_profit_usd'])
        assert abs(residual) < 1e-6
        contrasts.append(dict(bid=bid, delta=accounts['original', bid]['delta'],
            DDelta_R=contrast['energy_revenue_usd'], DDelta_U=contrast['loc_usd'],
            minus_DDelta_C=-contrast['true_cost_usd'], DDelta_Pi=contrast['true_profit_usd'],
            DDelta_generation=contrast['generation_mwh'], DDelta_Q=contrast['exposure_mwh'],
            ledger_residual=residual))
        for node in range(30):
            for t in range(24):
                price_changes, energy_changes = {}, {}
                for scenario in ('original', 'relaxed'):
                    price_changes[scenario] = float(arrays[scenario, bid]['price'][node, t]
                                                    - arrays[scenario, 0]['price'][node, t])
                    energy_changes[scenario] = (float(hourly[scenario, bid, t + 1]['lambda_E'])
                                                 - float(hourly[scenario, 0, t + 1]['lambda_E']))
                dd_price = price_changes['relaxed'] - price_changes['original']
                dd_energy = energy_changes['relaxed'] - energy_changes['original']
                responses.append(dict(bid=bid, delta=accounts['original', bid]['delta'], bus=node+1,
                    hour=t+1, original_offer_response=price_changes['original'],
                    relaxed_offer_response=price_changes['relaxed'], network_response_contrast=dd_price,
                    original_energy_response=energy_changes['original'],
                    relaxed_energy_response=energy_changes['relaxed'],
                    energy_response_contrast=dd_energy, congestion_response_contrast=dd_price-dd_energy))
    save('network_offer_responses.csv', responses)
    save('network_settlement_responses.csv', settlements)
    save('network_response_contrasts.csv', contrasts)

    regions = read(PHYSICAL / 'profit_range.json')['physical_regions']
    with np.load(PHYSICAL / 'physical_plans.npz') as z:
        plans = []
        for region in regions:
            indices = np.flatnonzero(np.isclose(z['deltas'], region['witness_delta'], atol=1e-10, rtol=0))
            assert len(indices) == 1 and region['ready']
            k = indices[0]
            plans.append((float(z['intercepts'][k]), float(z['exposures'][k])))
    jumps = []
    for k in range(1, len(regions)):
        boundary = regions[k]['left']
        assert abs(regions[k-1]['right'] - boundary) < 1e-10
        c0, q0 = plans[k-1]
        c1, q1 = plans[k]
        assert q1 <= q0 + 1e-7
        tie_error = c1 + boundary*q1 - c0 - boundary*q0
        assert abs(tie_error) < 1e-5
        jump = boundary*(q1-q0)
        assert jump <= 1e-6 and abs(jump+c1-c0) < 1e-5
        jumps.append(dict(boundary=boundary, incoming_Q=q0, outgoing_Q=q1,
                          incoming_actual_system_cost=c0, outgoing_actual_system_cost=c1,
                          pure_physical_profit_jump=jump, replacement_cost=c1-c0,
                          offered_system_cost_tie_error=tie_error))
    save('physical_switching_costs.csv', jumps)
    # Raw A/B costs give a second check on the highlighted same-price execution contrast.
    protocol = read(inputs[-1])['protocol']
    ca, cb = protocol['candidate_lines']
    critical = protocol['original_critical']
    tie_gap = abs(cb['cost']-ca['cost']-critical*(ca['exposure']-cb['exposure']))
    assert tie_gap < 1e-5
    assert all(digest(ROOT/path) == sha for path, sha in fingerprints.items())
    verification = dict(status='passed', input_hashes=len(fingerprints), network_cases=6,
        nodal_response_comparisons=len(responses), physical_regions=len(regions),
        physical_boundaries=len(jumps), max_settlement_residual=max(ledger_errors),
        max_offered_cost_tie_residual=max(abs(r['offered_system_cost_tie_error']) for r in jumps),
        highlighted_tie_cost_residual=tie_gap, new_optimization_solves=0,
        scope='Deterministic contrasts at two fixed offers; no relaxed-network profit maximum or causal-share estimate.')
    write(OUT / 'verification.json', verification)
    print(verification)
    print('Near-left contrast:', contrasts[0])


if __name__ == '__main__':
    main()
