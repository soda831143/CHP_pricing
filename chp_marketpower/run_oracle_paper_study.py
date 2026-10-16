"""Three focused paper artifacts: response structure, timing, range price impact."""
import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from benchmark_oracle_queries import benchmark
from engine import ScheduleRunMILP, load_case
from price_vulnerability.affine_oracle import query
from price_vulnerability.range_vulnerability import range_price_impact
from price_vulnerability.scalar_markup import apply_generator_adder
from strategic_market_simulation.profit_sweep import _settle_target
from price_vulnerability.model_identity import check_model_identity


ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def structure_tables(root, output):
    rows = []
    for path in sorted(root.glob('*/audit.json')):
        audit = read(path)
        compression = read(path.parent/'compression.json') if (path.parent/'compression.json').exists() else {}
        rows.append(dict(variant=path.parent.name, case=audit['scope']['case'],
            chp_solves=audit.get('chp_solves', audit['solved_points']),
            auxiliary_lps=audit.get('auxiliary_lps', 0),
            offline_seconds=audit['offline_seconds'], coverage=audit['price_coverage_fraction'],
            value_intervals=compression.get('merged_value_intervals'),
            selected_price_segments=compression.get('selected_price_intervals'),
            inherited_seconds=audit.get('inherited_offline_seconds', 0.),
            compact_bytes=compression.get('compact_file_bytes')))
    with (output/'algorithm_comparison.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    comparisons = []
    for first, second in [('6_persistent_bracket_complete', '6_active_cone_extended'),
                          ('30_persistent_bracket', '30_active_cone')]:
        with np.load(root/first/'compact.npz') as a, np.load(root/second/'compact.npz') as b:
            points = np.unique(np.r_[a['value_boundaries'], b['value_boundaries']])
            error = float(np.max(np.abs(np.interp(points, a['value_boundaries'], a['values'])
                                        -np.interp(points, b['value_boundaries'], b['values']))))
            if error > 1e-6:
                raise RuntimeError('Two complete value maps disagree beyond the declared tolerance')
            comparisons.append(dict(first=first, second=second,
                value_intervals=[len(a['value_boundaries'])-1, len(b['value_boundaries'])-1],
                max_value_difference_usd=error,
                max_boundary_difference=float(np.max(np.abs(a['value_boundaries']-b['value_boundaries'])))
                    if len(a['value_boundaries']) == len(b['value_boundaries']) else None))
    save(output/'structure_comparison.json', dict(rows=rows, complete_map_comparisons=comparisons,
        interpretation='All auxiliary work counts in offline time. Different legal selected-price paths need not agree; value-map consistency is checked at the union of their breakpoints.'))


def timed_batches(oracle_dir, output):
    plan = dict(queries=[24, 100, 500, 1000], repeats=3, order='shuffled', seed=20261015,
                oracle=str(oracle_dir), source_commit=subprocess.check_output(
                    ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                    'benchmark_oracle_queries.py', 'run_oracle_paper_study.py',
                    'price_vulnerability/persistent_chp.py', 'price_vulnerability/affine_oracle.py')})
    save(output/'frozen_plan.json', plan)
    rows = []
    for q in plan['queries']:
        for repeat in range(plan['repeats']):
            item = benchmark(oracle_dir, q, skip_fresh=True, order=plan['order'], seed=plan['seed'])
            item['repeat'] = repeat+1
            save(output/f'q{q}_repeat{repeat+1}.json', item)
            rows.append(item)
            print(f"Q={q}, repeat={repeat+1}: reopt={item['same_model_reoptimization_batch_seconds']:.3f}s, "
                  f"oracle={item['oracle_total_with_offline_seconds']:.3f}s", flush=True)
    summary = []
    for q in plan['queries']:
        subset = [r for r in rows if r['n_queries'] == q]
        direct = [r['same_model_reoptimization_batch_seconds'] for r in subset]
        oracle = [r['oracle_total_with_offline_seconds'] for r in subset]
        summary.append(dict(Q=q, reopt_mean_seconds=float(np.mean(direct)),
                            reopt_std_seconds=float(np.std(direct, ddof=1)),
                            oracle_mean_seconds=float(np.mean(oracle)),
                            oracle_std_seconds=float(np.std(oracle, ddof=1))))
    save(output/'timing_summary.json', dict(plan=plan, rows=summary,
        interpretation='Three actual repeated batches per Q. Offline construction measured once and included in each Oracle total; no interpolated exact break-even claim.'))


def range_assessment(oracle_dir, output):
    compression = read(oracle_dir/'compression.json')
    if compression.get('source_sha256') != hashlib.sha256((oracle_dir/'oracle.npz').read_bytes()).hexdigest():
        raise ValueError('Compact map does not match the raw version')
    with np.load(oracle_dir/'compact.npz') as data:
        report = range_price_impact(data['price_boundaries'], data['prices'])
    save(output/'range_price_impact.json', report)
    local = ROOT/'results/budgeted_oracle_30_G1_economic'
    audit = read(local/'audit.json')
    if audit['status'] != 'numerically_validated':
        raise ValueError('Economic application requires a separately complete local oracle')
    g, n = load_case('30', 'ptdf', 24, 3, 'tight')
    check_model_identity(local, g, n, audit)
    rows = []
    with np.load(local/'oracle.npz') as archive:
        if not np.allclose(archive['boundaries'][[0, -1]], [16.7928, 18.8919], rtol=0., atol=1e-10):
            raise ValueError('Expected the declared 40-45% local map')
        for rho in (.40, .425, .45):
            delta = float(np.clip(41.982*rho, archive['boundaries'][0], archive['boundaries'][-1]))
            _, price = query(delta, archive['boundaries'], archive['values'], archive['prices'], archive['price_ready'])
            reported = apply_generator_adder(g, 0, delta)
            physical_p, physical_u, uc_value = ScheduleRunMILP(reported, n).solve(require_optimal=True)
            settlement = _settle_target(g[0], reported[0], price[n.gen_bus_idx(0)], physical_p[0], physical_u[0])
            exposure = float(np.sum(physical_p[0]-g[0].P_min*physical_u[0]))
            identity_error = float(abs(settlement['true_profit']-settlement['best_reported_profit']-delta*exposure))
            if identity_error > 1e-5:
                raise RuntimeError('LOC settlement identity failed')
            rows.append(dict(rho=rho, delta=delta, uc_reported_objective=float(uc_value),
                physical_exposure_mwh=exposure, price_node_hour=price[n.gen_bus_idx(0)].tolist(),
                **{key:float(settlement[key]) for key in ('true_profit', 'best_reported_profit',
                    'energy_revenue', 'reported_uplift', 'true_cost', 'reported_cost')},
                adder_exposure_revenue=delta*exposure, identity_residual=identity_error))
            print(f"settlement rho={rho:.3f}: profit={settlement['true_profit']:.4f}", flush=True)
    save(output/'economic_settlements.json', dict(oracle_version=str(local),
        note='Separate 40-45% local map, one fixed declared selector. Only three sampled UC/self-schedule settlements; no continuous-profit optimum claim.', rows=rows))


def figures(oracle_dir, output, timing_dir, application_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    risk = read(application_dir/'range_price_impact.json')
    with np.load(oracle_dir/'compact.npz') as data:
        vb, value = data['value_boundaries'], data['values']
        pb, price = data['price_boundaries'], data['prices']
    bus, hour = risk['max_extrapolation_error_bus_1based']-1, risk['max_extrapolation_error_hour_1based']-1
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 7), sharex=True, constrained_layout=True)
    axes[0].plot(100*vb/41.982, value-value[0], 'o-', ms=3)
    axes[0].set_ylabel('CHP cost increase ($)')
    axes[1].stairs(np.diff(value)/np.diff(vb), 100*vb/41.982, baseline=None)
    axes[1].set_ylabel('CHP bid exposure (MWh)')
    axes[2].plot(100*pb/41.982, price[:, bus, hour], 'o-', ms=3)
    axes[2].set_ylabel('Selected price ($/MWh)')
    axes[2].set_xlabel('All-day bid adder / reference slope (%)')
    axes[2].set_title(f'Bus {bus+1}, hour {hour+1}: largest local-extrapolation error', fontsize=10)
    for ax in axes:
        for boundary in vb[1:-1]:
            ax.axvline(100*boundary/41.982, color='.8', lw=.6, zorder=0)
    for ext in ('png', 'pdf'):
        fig.savefig(output/f'figure_A_response_structure.{ext}', dpi=200)
    plt.close(fig)
    stats = read(timing_dir/'timing_summary.json')['rows']
    fig, ax = plt.subplots(figsize=(6.6, 4.1), constrained_layout=True)
    for prefix, label in (('reopt', 'Persistent CHP reoptimization'), ('oracle', 'Parametric Oracle (offline included)')):
        ax.errorbar([s['Q'] for s in stats], [s[f'{prefix}_mean_seconds'] for s in stats],
                    yerr=[s[f'{prefix}_std_seconds'] for s in stats], marker='o', capsize=3, label=label)
    ax.set(xlabel='Number of price queries Q', ylabel='Cumulative time (s)')
    ax.set_ylim(bottom=0)
    ax.text(.45, .15, f"Oracle construction: {read(oracle_dir/'audit.json')['offline_seconds']:.2f} s",
            transform=ax.transAxes, fontsize=9)
    ax.legend(); ax.grid(alpha=.2)
    for ext in ('png', 'pdf'):
        fig.savefig(output/f'figure_B_cumulative_time.{ext}', dpi=200)
    plt.close(fig)
    from price_vulnerability.oracle_compression import query_compact
    deltas = np.unique(np.r_[pb, np.linspace(pb[0], pb[-1], 500)])
    baseline = price[0]
    impacts = [np.max(np.abs(query_compact(d, vb, value, pb, price)[1]-baseline)) for d in deltas]
    local_slope = np.asarray(risk['local_right_derivative_per_absolute_adder'])
    local_errors = [np.max(np.abs(query_compact(d, vb, value, pb, price)[1]
                                -baseline-d*local_slope)) for d in deltas]
    fig, axes = plt.subplots(2, 1, figsize=(7, 6.7), constrained_layout=True)
    axes[0].plot(100*deltas/41.982, impacts, label='Max price impact across buses and hours')
    axes[0].plot(100*deltas/41.982, local_errors, '--', label='Max component error of local extrapolation')
    axes[0].set(xlabel='Reference adder (%) — complete 0-20% map', ylabel='Price change / error ($/MWh)')
    axes[0].legend()
    settlements = read(application_dir/'economic_settlements.json')['rows']
    for key, label in (('true_profit', 'True profit'), ('best_reported_profit', 'Reported self-schedule surplus'),
                        ('adder_exposure_revenue', 'Adder × physical exposure')):
        initial = settlements[0][key]
        axes[1].plot([100*r['rho'] for r in settlements], [r[key]-initial for r in settlements],
                     'o-', label=label)
    axes[1].set(xlabel='Reference adder (%) — separate 40-45% map', ylabel='Change from 40% bid ($)')
    axes[1].legend(fontsize=8)
    for ext in ('png', 'pdf'):
        fig.savefig(output/f'figure_C_price_and_settlement.{ext}', dpi=200)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('timing', 'application', 'figures', 'tables'), required=True)
    parser.add_argument('--oracle-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timing-dir', type=Path)
    parser.add_argument('--application-dir', type=Path)
    args = parser.parse_args()
    if args.stage in ('application', 'figures'):
        scope = read(args.oracle_dir/'audit.json')['scope']
        if scope['case'] != '30' or scope['generator_index'] != 0 or scope.get('bid_hour_1based') is not None:
            parser.error('These historical application figures use the all-day 30-G1 case only')
    if args.stage == 'figures' and (args.timing_dir is None or args.application_dir is None):
        parser.error('Figures require timing-dir and application-dir')
    if args.output.exists():
        parser.error('Use a new output directory to preserve all experiments')
    args.output.mkdir(parents=True)
    if args.stage == 'timing':
        timed_batches(args.oracle_dir, args.output)
    elif args.stage == 'application':
        range_assessment(args.oracle_dir, args.output)
    elif args.stage == 'tables':
        structure_tables(args.oracle_dir.parent, args.output)
    else:
        figures(args.oracle_dir, args.output, args.timing_dir, args.application_dir)


if __name__ == '__main__':
    main()
