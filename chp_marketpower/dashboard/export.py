"""Verify original witnesses once, then export lightweight solver-free research data."""
import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from make_research_figures import ROOT, MAIN, STUDY, PROFIT, read, load_rows, write_json, write_csv, first_amortized_query
from engine import load_case
from price_vulnerability.model_identity import check_model_identity, model_identity
from price_vulnerability.oracle_compression import load_matched_compact, query_compact
from benchmarks.unit_self_schedule import dispatch_cost

SOURCES = [('30-G1-all', MAIN, 41.982),
    ('30-G2-all', STUDY/'30_G2_bracket_0to50', 70.8786),
    ('118-G11-all', ROOT/'results/scope_study_20261016/118_sparse_bracket_0to50', 36.33),
    ('30-G1-h1', ROOT/'results/presentation_revision_20261016/30_G1_hour1_0to50', 41.982)]


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconcile_settlements(scenario, gens, net):
    """Bind archived monetary rows to the actual displayed price and physical plan."""
    maximum = 0.
    for row in scenario['settlements']:
        i = int(row['generator_index'])
        plan = scenario['physical_regions'][int(row['physical_region'])]
        p,u = np.asarray(plan['output'][i]),np.asarray(plan['commitment'][i])
        if not plan['left']-1e-9 <= row['delta'] <= plan['right']+1e-9:
            raise ValueError('Settlement outside its physical plan region')
        _,price = query_compact(row['delta'],*[np.asarray(scenario[k]) for k in
                               ('value_boundaries','values','price_boundaries','prices')])
        residual = max(abs(float(price[net.gen_bus_idx(i)]@p)-row['energy_revenue']),
            abs(dispatch_cost(gens[i],p,u)-row['true_cost']),
            abs(row['energy_revenue']+row['reported_uplift']-row['true_cost']-row['true_profit']))
        maximum = max(maximum,residual)
        if residual > 1e-5 or row['self_schedule_gap_usd'] > 1e-5:
            raise ValueError('Saved settlement does not reconcile with its displayed price/physical plan')
    return maximum


def build(output, refresh=False):
    if (output/'manifest.json').exists() and not refresh:
        raise ValueError('Use --refresh to explicitly replace this generated export')
    output.mkdir(parents=True, exist_ok=True)
    models, scenarios, source_hashes = {}, [], {}
    for identifier, directory, reference in SOURCES:
        audit, compression, compact = load_matched_compact(directory)
        scope = audit['scope']
        gens, net = load_case(scope['case'], scope['network'], scope['T'], scope['segments'], scope['congestion'])
        if not check_model_identity(directory, gens, net, audit):
            raise ValueError('Export requires an explicit model-data binding')
        stamp = model_identity(gens, net)
        from dashboard.catalog import check_validation
        check_validation(directory,audit,stamp['model_sha256'])
        models[scope['case']] = dict(generators=[asdict(g) for g in gens], demand=net.demand.tolist(),
            gen_bus_map=[net.gen_bus_idx(i) for i in range(len(gens))],
            PTDF=net.PTDF.tolist(), PTDF_Gen=net.PTDF_Gen.tolist(), F_max=net.F_max.tolist(),
            model_sha256=stamp['model_sha256'], initial_source='Default cold start, no previous-day warmup')
        row = dict(id=identifier, case=scope['case'], generator_index=scope['generator_index'],
            generator_count=len(gens), bid_hour_1based=scope.get('bid_hour_1based'),
            reference_slope=reference, rho_lower=float(compact['value_boundaries'][0]/reference),
            rho_upper=float(compact['value_boundaries'][-1]/reference), model_sha256=stamp['model_sha256'],
            price_selector_sha256=file_sha(directory/'compact.npz'), raw_witness_sha256=file_sha(directory/'oracle.npz'),
            source_oracle=directory.relative_to(ROOT).as_posix(), value_regions=compression['merged_value_intervals'],
            price_segments=compression['selected_price_intervals'], offline_seconds=audit['offline_seconds'],
            value_tolerance_usd=audit['value_tolerance_usd'], price_tolerance_usd=audit['price_tolerance_usd'],
            common_primal_tolerance_usd=audit['price_tolerance_usd'],
            price_compression_tolerance_usd_per_mwh=compression['price_tolerance_usd_per_mwh'],
            export_validation='Original raw witnesses matched compact arrays and model identity at export; not revalidated by browser',
            identity_scope='Retrospective representative-point binding for these legacy archives',
            physical_regions=[], settlements=[], profit_candidates=[])
        row.update({k:compact[k].tolist() for k in ['value_boundaries', 'values', 'price_boundaries', 'prices']})
        if identifier in ('30-G1-all', '30-G1-h1'):
            folder = PROFIT if identifier.endswith('all') else ROOT/'results/finalization_20261017/localized_economics'
            report_name = 'profit_range.json' if identifier.endswith('all') else 'localized_economic_followup.json'
            report = read(folder/report_name)
            row['physical_points'] = report['physical_points']
            if identifier.endswith('all'):
                if report['source_sha256'] != compression['source_sha256'] or report['compact_sha256'] != row['price_selector_sha256']:
                    raise ValueError('Physical/profit report belongs to another price selector')
                csv = ROOT/'results/figure_study_20261016/generator_settlements.csv'
                economic_source = read(csv.parent/'economic_source_audit.json')
                expected = dict(profit_report_sha256=file_sha(folder/report_name),
                    source_oracle_sha256=row['raw_witness_sha256'], compact_sha256=row['price_selector_sha256'],
                    physical_archive_sha256=file_sha(folder/'physical_plans.npz'))
                if any(economic_source[k] != value for k,value in expected.items()):
                    raise ValueError('Settlement CSV source audit refers to another price/physical version')
                for source in [csv,csv.parent/'economic_source_audit.json']:
                    source_hashes[source.relative_to(ROOT).as_posix()] = file_sha(source)
                for r in load_rows(csv):
                    row['settlements'].append({k:(r[k] if k == 'unit' else float(r[k])) for k in
                        ['unit', 'delta', 'physical_region', 'generator_index', 'generation_mwh', 'energy_revenue',
                         'reported_uplift', 'true_cost', 'true_profit', 'true_profit_change', 'self_schedule_gap_usd']})
                row['profit_candidates'] = report['candidate_bids']
            else:
                if report['status'] != 'numerically_validated' or not report['full_range_common_region_coverage']:
                    raise ValueError('Localized physical map is incomplete')
                initial = read(ROOT/'results/finalization_20261017/initial_audit/initial_condition_audit.json')
                if initial['status'] != 'passed' or initial['model_identities']['30-G1']['model_sha256'] != stamp['model_sha256']:
                    raise ValueError('Hourly endpoint settlement belongs to another model or failed audit')
                source = ROOT/'results/finalization_20261017/initial_audit/initial_condition_audit.json'
                source_hashes[source.relative_to(ROOT).as_posix()] = file_sha(source)
                for index, p in enumerate(initial['localized_economics']['endpoint_uc_checks']):
                    for i, s in enumerate(p['units']):
                        row['settlements'].append(dict(s, delta=p['delta'], physical_region=index,
                            generator_index=i, true_profit_change=s['true_profit']-initial['localized_economics']['endpoint_uc_checks'][0]['units'][i]['true_profit']))
                row['profit_candidates'] = report['target_candidates']
            with np.load(folder/'physical_plans.npz') as plans:
                for k, region in enumerate(report['physical_regions']):
                    if not region['ready']:
                        raise ValueError('Do not export an unvalidated physical region')
                    index = int(np.argmin(abs(plans['deltas']-region['witness_delta'])))
                    if abs(plans['deltas'][index]-region['witness_delta']) > 1e-10:
                        raise ValueError('Physical region witness is missing')
                    row['physical_regions'].append(dict(region, region_index=k,
                        output=plans['outputs'][index].tolist(), commitment=plans['commitments'][index].tolist()))
            for settled in row['settlements']:
                i = int(settled['generator_index'])
                plan = row['physical_regions'][int(settled['physical_region'])]
                p, u = np.asarray(plan['output'][i]), np.asarray(plan['commitment'][i])
                exposure = p-gens[i].P_min*u
                amount = float(exposure.sum() if row['bid_hour_1based'] is None else exposure[row['bid_hour_1based']-1])
                settled['generation_mwh'] = float(p.sum())
                settled['reported_cost'] = settled['true_cost']+(settled['delta']*amount if i==row['generator_index'] else 0.)
            row['maximum_settlement_reconciliation_usd'] = reconcile_settlements(row,gens,net)
            source_hashes[(folder/report_name).relative_to(ROOT).as_posix()] = file_sha(folder/report_name)
            source_hashes[(folder/'physical_plans.npz').relative_to(ROOT).as_posix()] = file_sha(folder/'physical_plans.npz')
        row['physical_sha256'] = hashlib.sha256(json.dumps(row['physical_regions'], sort_keys=True).encode()).hexdigest()
        from dashboard.catalog import validation_summary
        row['validation'] = validation_summary(directory,audit)
        scenarios.append(row)
        source_hashes[(directory/'oracle.npz').relative_to(ROOT).as_posix()] = row['raw_witness_sha256']
        for name in ['audit.json','compression.json','compact.npz','model_identity.json']:
            if (directory/name).exists():
                source_hashes[(directory/name).relative_to(ROOT).as_posix()] = file_sha(directory/name)
        print(f'Validated export: {identifier}', flush=True)
    timing = []
    for name, path in [('30-G1', ROOT/'results/figure_study_20261016/trace_30_G1_q1000.json'),
                        ('30-G2', ROOT/'results/figure_study_20261016/trace_30_G2_q1000.json'),
                        ('118-G11 Q200', ROOT/'results/presentation_revision_20261016/trace_118_G11_q200.json'),
                        ('118-G11 Q500', ROOT/'results/dashboard_study_20261017/trace_118_G11_q500.json')]:
        if path.exists():
            timing.append(dict(name=name, **read(path)))
            source_hashes[path.relative_to(ROOT).as_posix()] = file_sha(path)
    timing_rows, checkpoint_rows = [], []
    for r in timing:
        fixed = r['oracle_offline_seconds_prior_run']+r.get('postprocessing_seconds',0.)+r['oracle_file_load_seconds']
        direct, online = r['same_model_cumulative_seconds'], r['oracle_cumulative_online_seconds']
        crossing = first_amortized_query(direct, online, fixed)
        timing_rows.append(dict(workload=r['name'], Q=r['n_queries'], reoptimization_seconds=direct[-1],
            oracle_seconds=fixed+online[-1], cumulative_ratio=direct[-1]/(fixed+online[-1]), first_measured_crossing=crossing))
        prefixes = sorted({1,r['n_queries'],*[q for q in (100,200,300,400,500,1000,crossing) if q is not None and q<=r['n_queries']]})
        for q in prefixes:
            checkpoint_rows.append(dict(workload=r['name'], Q=q, reoptimization_seconds=direct[q-1], oracle_seconds=fixed+online[q-1]))
    write_csv(output/'timing_summary.csv',timing_rows)
    write_csv(output/'timing_checkpoints.csv',checkpoint_rows)
    payload = dict(schema=1, models=models, scenarios=scenarios, timing=timing,
        notice='One-dimensional declared bid directions; selected optimal CHP prices, not unique prices. Reported LOC simulation, not all real-market settlement rules.')
    raw = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
    (output/'data.json').write_bytes(raw)
    manifest = dict(schema=1, data_sha256=hashlib.sha256(raw).hexdigest(), source_hashes=source_hashes,
        verification='One-time local raw-witness and model-data validation; SHA-256 integrity manifest, not a cryptographic signature',
        scenarios=[{k:r[k] for k in ['id', 'case', 'generator_index', 'bid_hour_1based', 'rho_lower', 'rho_upper',
                   'model_sha256', 'price_selector_sha256', 'value_regions', 'price_segments']} for r in scenarios])
    write_json(output/'manifest.json', manifest)
    from plotly.offline import get_plotlyjs
    template = (Path(__file__).parent/'static.html').read_text(encoding='utf-8')
    html = template.replace('/*PLOTLY_BUNDLE*/', get_plotlyjs()).replace('/*EXPORTED_DATA*/', raw.decode().replace('<', r'\u003c'))
    html = html.replace('/*EXPORTED_MANIFEST*/', json.dumps(manifest).replace('<', r'\u003c'))
    (output/'explorer.html').write_text(html, encoding='utf-8')
    from dashboard.catalog import seed, register, write_inventory
    seed(payload,output)
    for directory in sorted((ROOT/'results/dashboard_precompute').glob('*')):
        if directory.is_dir() and (directory/'validation.json').exists():
            try:
                register(directory,output)
                print(f'Registered verified extension: {directory.name}',flush=True)
            except (ValueError,KeyError,OSError) as error:
                print(f'Not registered: {directory.name}: {error}',flush=True)
    write_inventory(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, default=Path(__file__).parent/'exports')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    build(args.out_dir, args.refresh)
