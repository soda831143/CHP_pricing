"""Reuse independent Q500 timing and the certified one-hour offer comparison.

No optimization is called. Earlier figures, source tables and manifests stay intact.
"""
import csv
import sys
from pathlib import Path

import numpy as np

from engine import load_case
from benchmarks.unit_self_schedule import dispatch_cost
from mechanism_study.runtime import ROOT, digest, read, write
from paper_results.build_results import PAPER, rows
from price_vulnerability.model_identity import check_model_identity
from price_vulnerability.oracle_compression import load_matched_compact, query_compact
from run_initial_condition_audit import schedule_residuals

OUT = PAPER/'revision_20261020'
DATA = OUT/'source_data'


def save_csv(name, records):
    with (DATA/name).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    inputs = set()

    def source(relative):
        path = ROOT/relative
        inputs.add(path)
        return read(path)

    original_rows = rows(PAPER/'source_data/table_I_computation.csv')
    inputs.add(PAPER/'source_data/table_I_computation.csv')
    traces = [
        ('30-G1-Q1000', '30-G1', 'results/figure_study_20261016/trace_30_G1_q1000.json'),
        ('30-G2-Q1000', '30-G2', 'results/figure_study_20261016/trace_30_G2_q1000.json'),
        ('118-G11-Q500', '118-G11', 'results/dashboard_study_20261017/trace_118_G11_q500.json'),
        ('118-G11-Q200', '118-G11', 'results/presentation_revision_20261016/trace_118_G11_q200.json'),
    ]
    timing, prefixes, streams = [], [], {}
    for stream_id, instance, relative in traces:
        trace = source(relative)
        direct = np.asarray(trace['same_model_cumulative_seconds'])
        online = np.asarray(trace['oracle_cumulative_online_seconds'])
        bids = np.asarray(trace['query_deltas'])
        assert len(direct) == len(online) == len(bids) == trace['n_queries']
        assert np.isfinite([direct, online, bids]).all()
        assert np.all(np.diff(direct) >= 0) and np.all(np.diff(online) >= 0)
        fixed = sum(trace[k] for k in ('oracle_offline_seconds_prior_run', 'postprocessing_seconds', 'oracle_file_load_seconds'))
        total = fixed+online
        assert abs(total[-1]-trace['oracle_total_with_offline_seconds']) < 1e-10
        assert direct[-1] == trace['same_model_reoptimization_batch_seconds']
        assert online[-1] == trace['oracle_online_batch_seconds']
        assert trace['max_value_discrepancy_usd'] < 1e-6
        hit = np.flatnonzero(direct >= total)
        record = dict(next(r for r in original_rows if r['instance'] == instance))
        record.update(stream_id=stream_id, queries=len(direct),
            offline_seconds=trace['oracle_offline_seconds_prior_run'], postprocessing_seconds=trace['postprocessing_seconds'],
            load_seconds=trace['oracle_file_load_seconds'], online_seconds=float(online[-1]),
            direct_seconds=float(direct[-1]), parametric_total_seconds=float(total[-1]),
            direct_over_parametric=float(direct[-1]/total[-1]), first_amortized_query=int(hit[0]+1) if len(hit) else 'not reached',
            source=relative, source_sha256=digest(ROOT/relative))
        timing.append(record)
        prefixes.extend(dict(stream_id=stream_id, instance=instance, queries=i+1, delta=float(d),
            direct_seconds=float(a), parametric_seconds=float(b)) for i, (d, a, b) in enumerate(zip(bids, direct, total)))
        streams[stream_id] = trace
    old, new = streams['118-G11-Q200'], streams['118-G11-Q500']
    assert old['scope'] == new['scope'] and old['seed'] == new['seed'] and old['order'] == new['order']
    assert old['query_deltas'] != new['query_deltas'][:200]
    assert old['same_model_cumulative_seconds'] != new['same_model_cumulative_seconds'][:200]
    assert timing[2]['first_amortized_query'] == 224 and timing[3]['first_amortized_query'] == 'not reached'
    save_csv('table_I_four_workloads.csv', timing)
    save_csv('fig1_independent_query_streams.csv', prefixes)

    local_dir = ROOT/'results/presentation_revision_20261016/30_G1_hour1_0to50'
    local = source('results/finalization_20261017/localized_economics/localized_economic_followup.json')
    initial = source('results/finalization_20261017/initial_audit/initial_condition_audit.json')
    validation = source(str((local_dir/'validation.json').relative_to(ROOT)))
    for name in ('audit.json', 'compression.json', 'compact.npz', 'oracle.npz', 'model_identity.json'):
        inputs.add(local_dir/name)
    audit, _, compact = load_matched_compact(local_dir)
    gens, net = load_case('30', 'ptdf', 24, 3, 'tight')
    assert check_model_identity(local_dir, gens, net, audit)
    assert audit['scope']['bid_hour_1based'] == 1 and validation['status'] == 'passed'
    assert validation['source_sha256'] == digest(local_dir/'oracle.npz')
    assert len(compact['price_boundaries']) == 2
    price_change = float(np.max(abs(compact['prices'][-1]-compact['prices'][0])))
    assert price_change < 1e-6
    plans_path = ROOT/'results/finalization_20261017/localized_economics/physical_plans.npz'
    inputs.add(plans_path)
    with np.load(plans_path) as z:
        plans = {float(d): (z['outputs'][i], z['commitments'][i]) for i, d in enumerate(z['deltas'])}
    points = {r['delta']: r for r in local['physical_points']}
    for d, (p, u) in plans.items():
        assert max(schedule_residuals(gens, net, p, u).values()) < 1e-6
        cost = sum(dispatch_cost(g, p[i], u[i]) for i, g in enumerate(gens))
        assert abs(cost-points[d]['intercept']) < 1e-6
        assert abs(p[0, 0]-gens[0].P_min*u[0, 0]-points[d]['exposure']) < 1e-6
    regions = local['physical_regions']
    assert len(regions) == 2 and regions[0]['left'] == 0 and regions[-1]['right'] == 20.991
    assert regions[0]['right'] == regions[1]['left'] and all(r['ready'] for r in regions)
    certificates = []
    for i, region in enumerate(regions):
        p = points[region['witness_delta']]
        errors = [abs(p['intercept']+d*p['exposure']-points[d]['lower_bound']) for d in (region['left'], region['right'])]
        assert max(errors) < 1e-6
        certificates.append(dict(physical_region=i, left=region['left'], right=region['right'],
            witness_delta=region['witness_delta'], exposure=p['exposure'], maximum_endpoint_bound_gap=max(errors)))
    save_csv('hour1_common_UC_certificates.csv', certificates)
    baseline = local['baseline_true_profit']
    all_day = source('results/targeted_study_20261016/30_G1_profit_0to50/profit_range.json')
    assert abs(baseline-initial['localized_economics']['endpoint_uc_checks'][0]['units'][0]['true_profit']) < 1e-6
    candidates, accounting_error = [], 0.
    for row in local['target_candidates']:
        region = regions[row['physical_region']]
        assert row['delta'] in (region['left'], region['right'])
        p, u = plans[region['witness_delta']]
        price = query_compact(row['delta'], *[compact[k] for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')])[1]
        Q = float(p[0, 0]-gens[0].P_min*u[0, 0])
        C = dispatch_cost(gens[0], p[0], u[0]); R = float(price[net.gen_bus_idx(0)]@p[0])
        reported = C+row['delta']*Q
        U = row['best_reported_profit']-R+reported
        Pi = R+U-C
        error = max(abs(R-row['energy_revenue']), abs(C-row['true_cost']), abs(reported-row['reported_cost']),
            abs(U-row['reported_uplift']), abs(Pi-row['true_profit']), abs(row['self_schedule_upper_bound']-row['best_reported_profit']))
        assert error < 1e-6
        accounting_error = max(accounting_error, error)
        candidates.append(dict(delta=row['delta'], physical_region=row['physical_region'], Q=Q, R=R, U=U, C=C,
            Pi=Pi, delta_Pi=Pi-baseline, best_reported_surplus=row['best_reported_profit'], reconstruction_error=error))
    assert len(candidates) == 4 and abs(max(r['delta_Pi'] for r in candidates)) < 1e-6
    save_csv('hour1_profit_candidates_verified.csv', candidates)
    truthful = rows(PAPER/'source_data/absolute_generator_settlements.csv')[0]
    inputs.add(PAPER/'source_data/absolute_generator_settlements.csv')
    assert abs(float(truthful['Pi'])-baseline) < 1e-6
    contrast = [dict(offer_direction='All 24 hours', lower=0., upper=20.991, price_intervals=83,
        common_UC_regions=17, candidate_records=116, baseline_profit=baseline,
        maximum_additional_profit=all_day['maximizing_candidate']['true_profit']-baseline),
        dict(offer_direction='Hour 1 only', lower=0., upper=20.991, price_intervals=1,
        common_UC_regions=2, candidate_records=4, baseline_profit=baseline,
        maximum_additional_profit=max(r['delta_Pi'] for r in candidates))]
    save_csv('temporal_offer_comparison.csv', contrast)
    table = '# Table I. Parametric CHP representation and independent pricing workloads\n\n'
    table += '|Instance|Queries|Price intervals|Direct (s)|Parametric, all costs (s)|Direct / parametric|First amortized query|\n|---|---:|---:|---:|---:|---:|---:|\n'
    for r in timing:
        table += f"|{r['instance']}|{r['queries']}|{r['price_intervals']}|{r['direct_seconds']:.2f}|{r['parametric_total_seconds']:.2f}|{r['direct_over_parametric']:.2f}×|{r['first_amortized_query']}|\n"
    table += '\nIndependent measured streams. IEEE118 Q500 is the principal long-workload result; Q200 is a separately measured short-workload comparison, not its prefix. Construction, postprocessing, file loading and online lookup are included. System UC and uplift evaluation are excluded. G1 has 17 common UC regions, 99 joint intervals and 116 candidate records at 100 distinct offers. No timing was newly measured.\n'
    (OUT/'TABLE_I.md').write_text(table, encoding='utf-8')
    result = dict(status='passed', new_optimization_solves=0, new_timing_runs=0,
        timing=timing, independent_118_streams=True, hour1_price_max_change=price_change,
        hour1_physical_regions=len(regions), hour1_candidate_records=len(candidates), hour1_full_domain=True,
        hour1_profit_maximum=float(max(r['delta_Pi'] for r in candidates)),
        hour1_accounting_max_error=accounting_error, shared_truthful_baseline=baseline,
        certificate_scope='Continuous-domain numerical upper bound under the archived affine CHP selector and chosen common UC witnesses, using convex profit and all regional endpoints; not every legal price or dispatch tie.',
        self_schedule_scope='Saved exact-solver bounds are reused; no new independent self-schedule optimization is claimed.')
    write(OUT/'verification.json', result)
    write(OUT/'input_manifest.json', {str(p.relative_to(ROOT)): digest(p) for p in sorted(inputs)})
    plot_timing(timing, prefixes)
    print({k: v for k, v in result.items() if k != 'timing'})


def plot_timing(timing, prefixes):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    sys.path.insert(0, str(Path(r'C:/Users/250010153/.codex/skills/nature-figure/scripts')))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    plt.rcParams.update({'font.family':'sans-serif', 'font.sans-serif':['Arial', 'DejaVu Sans'],
        'font.size':8, 'axes.titlesize':9, 'axes.labelsize':8, 'legend.fontsize':7,
        'pdf.fonttype':42, 'svg.fonttype':'none', 'axes.spines.top':False, 'axes.spines.right':False,
        'axes.linewidth':.7, 'legend.frameon':False, 'xtick.labelsize':7, 'ytick.labelsize':7})
    fig, axes = plt.subplots(1, 3, figsize=(183/25.4, 82/25.4))
    fig.subplots_adjust(left=.08, right=.98, bottom=.32, top=.81, wspace=.42)
    for ax, record, letter in zip(axes, timing[:3], 'abc'):
        data = [r for r in prefixes if r['stream_id'] == record['stream_id']]
        fixed = record['offline_seconds']+record['postprocessing_seconds']+record['load_seconds']
        ax.plot([0]+[r['queries'] for r in data], [0.]+[r['direct_seconds'] for r in data], color='#326A92', label='Persistent CHP reoptimization')
        ax.plot([0]+[r['queries'] for r in data], [fixed]+[r['parametric_seconds'] for r in data], color='#278373', label='Parametric CHP (all costs)')
        hit = record['first_amortized_query']
        assert isinstance(hit, int)
        ax.plot(hit, data[hit-1]['direct_seconds'], 'o', ms=4, mfc='white', mec='#278373')
        ax.set(xlabel='Price queries', title=f"{letter}  IEEE {record['instance']}", xlim=(0, record['queries']), ylim=(0, record['direct_seconds']*1.12))
        ax.text(.03, .97, f"{record['direct_over_parametric']:.2f}×; first N = {hit}", transform=ax.transAxes, fontsize=7, va='top')
    short = [r for r in prefixes if r['stream_id'] == '118-G11-Q200']
    axes[2].plot([0]+[r['queries'] for r in short], [0.]+[r['direct_seconds'] for r in short], color='#326A92', ls='--', lw=.8)
    short_fixed = sum(timing[3][k] for k in ('offline_seconds', 'postprocessing_seconds', 'load_seconds'))
    axes[2].plot([0]+[r['queries'] for r in short], [short_fixed]+[r['parametric_seconds'] for r in short], color='#278373', ls='--', lw=.8)
    axes[2].text(.02, -.35, 'Solid: independent Q500 stream\nDashed: independent Q200 stream\nQ200: 0.90×; not amortized', transform=axes[2].transAxes, va='top', fontsize=7)
    axes[0].set_ylabel('Cumulative computation time (s)')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower left', bbox_to_anchor=(.08, .01), ncols=1)
    folder = OUT/'figures'; folder.mkdir(exist_ok=True)
    name = folder/'fig1_cumulative_pricing_time'
    require_matplotlib_panel_alignment(fig, axes=axes, json_out=name.with_suffix('.alignment.json'), strict=True)
    fig.savefig(name.with_suffix('.pdf')); fig.savefig(name.with_suffix('.svg')); fig.savefig(name.with_suffix('.png'), dpi=600)
    plt.close(fig)


if __name__ == '__main__':
    main()
