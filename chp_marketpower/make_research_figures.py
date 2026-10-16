"""Source-backed 30/118 paper figures; no reconstruction of unobserved profits."""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
MAIN = ROOT/'results/scope_study_20261016/30_bracket_repeat1'
STUDY = ROOT/'results/targeted_study_20261016'
PROFIT = STUDY/'30_G1_profit_0to50'
REF = 41.982
COLORS = ['#C27624', '#0072B2', '#008D83', '#777777', '#9065A8', '#55A2B8']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def write_csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def first_amortized_query(reoptimization, online, fixed_cost):
    direct, lookup = np.asarray(reoptimization, float), np.asarray(online, float)
    if (direct.ndim != 1 or direct.shape != lookup.shape or not len(direct)
            or not np.isfinite([direct, lookup]).all() or not np.isfinite(fixed_cost)
            or fixed_cost < 0 or np.any(direct < 0) or np.any(lookup < 0)
            or np.any(np.diff(direct) < 0) or np.any(np.diff(lookup) < 0)):
        raise ValueError('Need finite nonnegative monotone measured prefixes')
    hits = np.flatnonzero(direct >= fixed_cost+lookup)
    return int(hits[0]+1) if len(hits) else None


def load_physical_source(gens, report):
    from benchmarks.unit_self_schedule import dispatch_cost
    with np.load(PROFIT/'physical_plans.npz') as data:
        outputs, commitments = data['outputs'], data['commitments']
        plans = {float(d):(outputs[k], commitments[k]) for k, d in enumerate(data['deltas'])}
    costs = {(d, i):float(dispatch_cost(gen, p[i], u[i]))
             for d, (p, u) in plans.items() for i, gen in enumerate(gens)}
    points = {row['delta']:row for row in report['physical_points']}
    if set(points) != set(plans):
        raise ValueError('Physical archive and region report contain different witness bids')
    for delta, (p, u) in plans.items():
        exposure = float(np.sum(p[0]-gens[0].P_min*u[0]))
        cost = sum(costs[delta, i] for i in range(len(gens)))
        if (abs(exposure-points[delta]['exposure']) > 1e-6
                or abs(cost-points[delta]['intercept']) > 1e-5):
            raise ValueError('Physical archive costs/exposure differ from the original report')
    winner = report['maximizing_candidate']
    return plans, costs, dict(physical_archive_sha256=hashlib.sha256((PROFIT/'physical_plans.npz').read_bytes()).hexdigest(),
        profit_report_sha256=hashlib.sha256((PROFIT/'profit_range.json').read_bytes()).hexdigest(),
        boundary_witnesses=[dict(physical_region=i, witness_delta=r['witness_delta'])
            for i, r in enumerate(report['physical_regions']) if r['left'] <= winner['delta'] <= r['right']],
        reconstructed_physical_witnesses=len(plans))


def prepare(output):
    from engine import load_case
    from benchmarks.unit_self_schedule import UnitSelfScheduleMILP
    from price_vulnerability.scalar_markup import apply_generator_adder
    from price_vulnerability.oracle_compression import load_matched_compact, query_compact

    if (output/'generator_settlements.csv').exists():
        raise ValueError('Use a fresh data directory; do not overwrite a completed study')
    output.mkdir(parents=True, exist_ok=True)
    report = read(PROFIT/'profit_range.json')
    audit, compression, compact = load_matched_compact(MAIN)
    if (report['source_sha256'] != compression['source_sha256']
            or report['compact_sha256'] != hashlib.sha256((MAIN/'compact.npz').read_bytes()).hexdigest()
            or not report['conditional_maximum_is_full_range']):
        raise ValueError('Need the complete original joint-region and selected-price study')
    scope = audit['scope']
    gens, net = load_case(scope['case'], scope['network'], scope['T'], scope['segments'], scope['congestion'])
    g = scope['generator_index']
    if g != 0 or abs(gens[g].pwl_slopes[1]-REF) > 1e-10:
        raise ValueError('These figures are specifically scoped to the declared 30-G1 study')
    plans, costs, provenance = load_physical_source(gens, report)
    regions = report['physical_regions']
    price_args = [compact[k] for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')]
    cache = {}

    def settle(delta, plan_delta, region_index):
        p, u = plans[plan_delta]
        price = query_compact(float(delta), *price_args)[1]
        reported = apply_generator_adder(gens, g, float(delta))
        result = []
        for i, gen in enumerate(gens):
            key = (float(delta), i)
            if key not in cache:
                _, _, best, info = UnitSelfScheduleMILP.solve(reported[i], price[net.gen_bus_idx(i)],
                    require_optimal=True, return_timing=True, mip_gap=0.)
                cache[key] = (float(best), float(info['best_bound']))
            best, bound = cache[key]
            exposure = float(np.sum(p[i]-gen.P_min*u[i]))
            wedge = delta*exposure if i == g else 0.
            true_cost = costs[plan_delta, i]
            revenue = float(price[net.gen_bus_idx(i)]@p[i])
            uplift = max(0., best-revenue+true_cost+wedge)
            profit = revenue+uplift-true_cost
            if best < revenue-true_cost-wedge-1e-4 or abs(profit-best-wedge) > 1e-4:
                raise RuntimeError('Full LOC settlement identity failed')
            result.append(dict(delta=float(delta), rho=float(delta/REF), physical_region=region_index,
                physical_plan_delta=float(plan_delta), unit=gen.unit_id, generator_index=i,
                generation_mwh=float(p[i].sum()), incremental_exposure_mwh=exposure,
                energy_revenue=revenue, reported_uplift=uplift, true_cost=true_cost,
                true_profit=profit, best_reported_surplus=best, bid_wedge=wedge,
                self_schedule_gap_usd=max(0., bound-best)))
        return result

    baseline = settle(0., 0., -1)
    rows = []
    pb = compact['price_boundaries']
    for k, region in enumerate(regions):
        a, b = region['left'], region['right']
        edges = np.unique(np.r_[a, pb[(a < pb) & (pb < b)], b])
        bids = np.unique(np.r_[edges, (edges[:-1]+edges[1:])/2])
        for delta in bids:
            for row in settle(float(delta), region['witness_delta'], k):
                i = row['generator_index']
                row['energy_revenue_change'] = row['energy_revenue']-baseline[i]['energy_revenue']
                row['true_profit_change'] = row['true_profit']-baseline[i]['true_profit']
                row['is_joint_endpoint'] = int(np.any(edges == delta))
                rows.append(row)
        print(f'Settled physical region {k+1}/{len(regions)}', flush=True)
    write_csv(output/'generator_settlements.csv', rows)
    winner = report['maximizing_candidate']
    at_switch = [r for r in rows if r['delta'] == winner['delta']]
    sides = sorted({r['physical_region'] for r in at_switch})
    if len(sides) != 2:
        raise ValueError('Expected two adjacent archived physical plans at the winning boundary')
    left = {r['generator_index']:r for r in at_switch if r['physical_region'] == sides[0]}
    right = {r['generator_index']:r for r in at_switch if r['physical_region'] == sides[1]}
    boundary = [dict(unit=gen.unit_id, generation_change_mwh=right[i]['generation_mwh']-left[i]['generation_mwh'],
        energy_revenue_change=right[i]['energy_revenue']-left[i]['energy_revenue'],
        reported_uplift_change=right[i]['reported_uplift']-left[i]['reported_uplift'],
        true_cost_change=right[i]['true_cost']-left[i]['true_cost'],
        true_profit_change=right[i]['true_profit']-left[i]['true_profit']) for i, gen in enumerate(gens)]
    write_csv(output/'table_boundary_redistribution.csv', boundary)
    p0, u0 = plans[regions[sides[0]]['witness_delta']]
    p1, u1 = plans[regions[sides[1]]['witness_delta']]
    if np.max(np.abs((p1-p0).sum(axis=0))) > 1e-6:
        raise RuntimeError('Redispatch does not conserve hourly power balance')
    write_csv(output/'boundary_hourly_redispatch.csv', [dict(unit=gen.unit_id, hour=t+1,
        output_left=float(p0[i, t]), output_right=float(p1[i, t]),
        output_change=float(p1[i, t]-p0[i, t]), commitment_left=float(u0[i, t]),
        commitment_right=float(u1[i, t])) for i, gen in enumerate(gens) for t in range(net.T)])
    flows = [net.PTDF_Gen@p-net.PTDF@net.demand for p in (p0, p1)]
    active = [np.abs(np.abs(flow)-net.F_max[:, None]) <= 1e-6 for flow in flows]
    write_json(output/'economic_source_audit.json', dict(**provenance, source_oracle_sha256=report['source_sha256'],
        compact_sha256=report['compact_sha256'], baseline=baseline, winning_delta=winner['delta'],
        physical_regions=len(regions), joint_intervals=len(report['joint_intervals']),
        self_schedule_solves=len(cache), settlement_rows=len(rows), units=len(gens),
        sampling='Every joint interval endpoint and midpoint, with both physical plans retained at shared UC boundaries. Revenue is affine within each joint interval; profit connections are guides between directly solved samples, not an exact reconstruction.',
        declared_boundary_rule=report['physical_selection'],
        active_line_hour_counts=[int(a.sum()) for a in active],
        changed_line_activity_count=int(np.sum(active[0] != active[1])),
        max_line_overload_mw=max(0., max(float(np.max(np.abs(f)-net.F_max[:, None])) for f in flows)),
        max_unit_self_schedule_gap_usd=max(r['self_schedule_gap_usd'] for r in rows),
        constraint_interpretation='Saved physical plans only: activity changes are not a causal congestion attribution.'))


def load_rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def values(rows, key):
    return np.array([float(row[key]) for row in rows])


def render(output, qa_tools=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from price_vulnerability.oracle_compression import load_matched_compact

    plt.rcParams.update({'font.family':'sans-serif', 'font.sans-serif':['Arial', 'DejaVu Sans'],
        'font.size':9, 'axes.labelsize':9, 'axes.titlesize':9, 'xtick.labelsize':8,
        'ytick.labelsize':8, 'legend.fontsize':8, 'svg.fonttype':'none', 'pdf.fonttype':42,
        'axes.spines.top':False, 'axes.spines.right':False, 'axes.linewidth':.7,
        'lines.linewidth':1.5, 'savefig.dpi':400})
    if qa_tools:
        sys.path.insert(0, str(qa_tools))
        from audit_panel_alignment import require_matplotlib_panel_alignment
    bundle = PdfPages(output/'all_figures.pdf')

    def save(fig, name, axes):
        fig.canvas.draw()
        if qa_tools:
            require_matplotlib_panel_alignment(fig, axes=axes,
                json_out=output/f'{name}.alignment.json', tolerance_pt=1.5,
                gutter_tolerance_pt=1.5, strict=True)
        fig.savefig(output/f'{name}.pdf')
        fig.savefig(output/f'{name}.svg')
        fig.savefig(output/f'{name}.png', dpi=400)
        bundle.savefig(fig)
        plt.close(fig)

    def label(ax, letter, title):
        ax.text(-.13, 1.06, letter, transform=ax.transAxes, fontsize=10, weight='bold')
        ax.set_title(title, loc='left', pad=10)
        ax.grid(axis='y', color='#E5E8EA', linewidth=.5, zorder=0)
        ax.set_axisbelow(True)

    _, compression, compact = load_matched_compact(MAIN)
    vb, pb = compact['value_boundaries'], compact['price_boundaries']
    price = compact['prices']
    with np.load(MAIN/'oracle.npz') as raw:
        slopes = raw['exposures'][compression['value_witness_raw_indices']]
    write_csv(output/'figure1_value_slopes.csv', [dict(left_rho=float(a/REF), right_rho=float(b/REF),
        derivative_wrt_absolute_adder_mwh=float(s), derivative_wrt_rho=float(REF*s))
        for a, b, s in zip(vb[:-1], vb[1:], slopes)])
    selected = [(0, 14, 'Bus 1, hour 15'), (14, 0, 'Bus 15, hour 1'), (14, 23, 'Bus 15, hour 24')]
    write_csv(output/'figure1_selected_prices.csv', [dict(delta=float(d), rho=float(d/REF),
        **{f'bus{n+1}_hour{t+1}':float(price[k, n, t]) for n, t, _ in selected}) for k, d in enumerate(pb)])
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True)
    fig.subplots_adjust(left=.14, right=.97, bottom=.17, top=.91, hspace=.38)
    axes[0].stairs(slopes, 100*vb/REF, baseline=None, color='#007F7A', linewidth=1.7)
    axes[0].set_ylabel('CHP value slope (MWh)')
    label(axes[0], 'a', 'Optimal value sensitivity over the complete bid range')
    for (n, t, title), color, style in zip(selected, [COLORS[0], COLORS[1], COLORS[4]], ['-', '--', '-.']):
        axes[1].plot(100*pb/REF, price[:, n, t], color=color, ls=style, label=title)
    axes[1].set(xlim=(0, 50), xlabel='G1 bid adder / reference slope (%)', ylabel='Selected CHP price ($/MWh)')
    label(axes[1], 'b', 'Nodal price responses need not be monotone')
    fig.legend(*axes[1].get_legend_handles_labels(), loc='lower center', ncol=3, frameon=False,
               bbox_to_anchor=(.55, .015))
    save(fig, 'figure1_parametric_response', list(axes))

    timing_rows, summaries = [], []
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))
    fig.subplots_adjust(left=.105, right=.97, bottom=.22, top=.82, wspace=.30)
    for ax, unit, letter in zip(axes, ('G1', 'G2'), ('a', 'b')):
        trace = read(output/f'trace_30_{unit}_q1000.json')
        direct = np.asarray(trace['same_model_cumulative_seconds'])
        online = np.asarray(trace['oracle_cumulative_online_seconds'])
        fixed = trace['oracle_offline_seconds_prior_run']+trace['postprocessing_seconds']+trace['oracle_file_load_seconds']
        first = first_amortized_query(direct, online, fixed)
        q = np.arange(1, len(direct)+1)
        ax.plot(np.r_[0, q], np.r_[0., direct], color='#294861', label='Persistent CHP reoptimization')
        ax.plot(np.r_[0, q], np.r_[fixed, fixed+online], color='#007F7A', linewidth=1.9,
                label='Parametric Oracle (offline included)')
        checkpoints = np.arange(100, len(q)+1, 100)
        ax.plot(checkpoints, direct[checkpoints-1], 'o', ms=3, color='#294861')
        if first is not None:
            ax.vlines(first, 0, direct[first-1], color='#ADB8BD', linestyles=':', linewidth=.8)
            ax.plot(first, direct[first-1], 'o', ms=5, mfc='white', mec='#007F7A', mew=1.3)
        ax.text(0., 1.025, f'First amortized query: {first if first else "not reached"}; '
                f'1000-query speedup: {direct[-1]/(fixed+online[-1]):.2f}×', transform=ax.transAxes,
                fontsize=7.5)
        ax.set(xlim=(0, 1000), ylim=(0, direct[-1]*1.13), xlabel='Number of price queries Q')
        ax.set_xticks([0, 200, 400, 600, 800, 1000])
        ax.set_ylabel('Cumulative computation time (s)')
        ax.text(-.13, 1.16, letter, transform=ax.transAxes, fontsize=10, weight='bold')
        ax.set_title(f'IEEE 30-bus: {unit} bid direction', loc='left', pad=26)
        ax.grid(False)
        zoom_end = 200 if unit == 'G1' else 60
        inset = ax.inset_axes([.09, .52, .35, .30])
        inset.plot(np.r_[0, q[:zoom_end]], np.r_[0., direct[:zoom_end]], color='#294861', linewidth=1.)
        inset.plot(np.r_[0, q[:zoom_end]], np.r_[fixed, fixed+online[:zoom_end]], color='#007F7A', linewidth=1.2)
        if first is not None and first <= zoom_end:
            inset.vlines(first, 0, direct[first-1], color='#ADB8BD', linestyles=':', linewidth=.7)
            inset.plot(first, direct[first-1], 'o', ms=3.5, mfc='white', mec='#007F7A')
        inset.set(xlim=(0, zoom_end), ylim=(0, direct[zoom_end-1]*1.12))
        inset.tick_params(labelsize=6.5, length=2, pad=1)
        inset.set_title('Early-query detail', fontsize=7, pad=3)
        summaries.append(dict(unit=unit, first_amortized_query=first,
            offline_plus_postprocess_load_seconds=fixed, reoptimization_q1000_seconds=float(direct[-1]),
            oracle_q1000_seconds=float(fixed+online[-1]), speedup=float(direct[-1]/(fixed+online[-1]))))
        timing_rows.extend(dict(unit=unit, queries=int(i), reoptimization_seconds=float(d),
            oracle_total_seconds=float(fixed+o)) for i, d, o in zip(q, direct, online))
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center', ncol=2, frameon=False,
               bbox_to_anchor=(.54, .015))
    save(fig, 'figure2_cumulative_time', list(axes))
    write_csv(output/'figure2_measured_prefixes.csv', timing_rows)
    write_csv(output/'table_cumulative_checkpoints.csv', [r for r in timing_rows if r['queries'] % 100 == 0])
    write_json(output/'timing_crossings.json', dict(rows=summaries,
        interpretation='First integer query at which this measured prefix costs at least the Oracle total. Not a universal break-even point; marker spacing is 100 queries, all prefixes are observed.'))

    report = read(PROFIT/'profit_range.json')
    regions = report['physical_regions']
    winner = report['maximizing_candidate']
    candidate_rows = report['candidate_bids']
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.8), sharex=True)
    fig.subplots_adjust(left=.14, right=.97, bottom=.10, top=.94, hspace=.45)
    axes[0].plot(100*pb/REF, price[:, 0, 14], color=COLORS[0], linewidth=1.7)
    axes[0].set_ylabel('Selected price ($/MWh)')
    label(axes[0], 'a', 'G1 location: bus 1, hour 15')
    point_lookup = {p['delta']:p for p in report['physical_points']}
    exposure = [point_lookup[r['witness_delta']]['exposure'] for r in regions]
    edges = [regions[0]['left']]+[r['right'] for r in regions]
    axes[1].stairs(exposure, 100*np.asarray(edges)/REF, baseline=None, color=COLORS[0], linewidth=1.7)
    axes[1].set_ylabel('UC bid exposure (MWh)')
    label(axes[1], 'b', 'Physical execution changes at 17 common-plan regions')
    axes[2].scatter([100*r['rho'] for r in candidate_rows],
        [r['extra_profit_vs_truthful']/1000 for r in candidate_rows], s=9, color='#4D6878', alpha=.8,
        linewidths=0, label='Finite endpoint candidates')
    same_bid = [r for r in candidate_rows if r['delta'] == winner['delta']]
    alternative = min(same_bid, key=lambda r:r['true_profit'])
    best_x = 100*winner['rho']
    axes[2].plot(best_x, winner['extra_profit_vs_truthful']/1000, '*', color=COLORS[0], ms=10,
                  label='Upper boundary / supremum estimate')
    axes[2].plot(best_x, alternative['extra_profit_vs_truthful']/1000, 'o', mfc='white', mec=COLORS[0], ms=5)
    axes[2].text(.72, .86, f'{best_x:.4f}%: +${winner["extra_profit_vs_truthful"]/1000:.2f}k',
                  transform=axes[2].transAxes, color='#955517', fontsize=9)
    axes[2].axhline(0, color='#AAB3B9', linewidth=.7)
    axes[2].set(xlim=(0, 50), xlabel='G1 bid adder / reference slope (%)', ylabel='Extra true profit ($1000)')
    label(axes[2], 'c', 'Finite profit candidates retain both sides of UC switches')
    for ax in axes:
        ax.axvline(best_x, color='#AAB3B9', ls=':', linewidth=.8)
    save(fig, 'figure3_profitable_bid', list(axes))

    rows = load_rows(output/'generator_settlements.csv')
    from engine import load_case
    gens, _ = load_case('30', 'ptdf', 24, 3, 'tight')
    plans, costs, provenance = load_physical_source(gens, report)
    for row in rows:
        delta, i = float(row['physical_plan_delta']), int(row['generator_index'])
        if (abs(float(row['generation_mwh'])-plans[delta][0][i].sum()) > 1e-6
                or abs(float(row['true_cost'])-costs[delta, i]) > 1e-5):
            raise ValueError('Settlement samples do not match the declared physical archive')
    source_audit = read(output/'economic_source_audit.json')
    source_audit.update(provenance)
    write_json(output/'economic_source_audit.json', source_audit)
    best_rows = [r for r in rows if float(r['delta']) == winner['delta']
                 and int(r['physical_region']) == winner['physical_region']]
    payoffs = []
    for r in best_rows:
        base = source_audit['baseline'][int(r['generator_index'])]
        payoffs.append(dict(unit=r['unit'], baseline_energy_revenue=base['energy_revenue'],
            energy_revenue_at_G1_best_bid=float(r['energy_revenue']),
            energy_revenue_change=float(r['energy_revenue_change']), baseline_true_profit=base['true_profit'],
            true_profit_at_G1_best_bid=float(r['true_profit']), true_profit_change=float(r['true_profit_change']),
            reported_uplift_at_G1_best_bid=float(r['reported_uplift'])))
    write_csv(output/'table_generator_payoffs_at_G1_best_bid.csv', payoffs)
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.4), sharex=True)
    fig.subplots_adjust(left=.14, right=.97, bottom=.16, top=.92, hspace=.38)
    for i, color in enumerate(COLORS):
        unit_rows = [r for r in rows if int(r['generator_index']) == i]
        for region_index in range(len(regions)):
            segment = [r for r in unit_rows if int(r['physical_region']) == region_index]
            for ax, field in zip(axes, ('energy_revenue_change', 'true_profit_change')):
                ax.plot(100*values(segment, 'rho'), values(segment, field)/1000, color=color,
                    linewidth=1.7 if i == 0 else 1.05, marker='.' if field == 'true_profit_change' else None,
                    markersize=1.8, label=f'G{i+1}' if region_index == 0 else None)
    for ax in axes:
        ax.axhline(0, color='#AAB3B9', linewidth=.6)
        ax.axvline(best_x, color='#BCC5CB', ls=':', linewidth=.7)
        ax.set_ylabel('Change from baseline ($1000)')
    axes[1].set(xlim=(0, 50), xlabel='G1 bid adder / reference slope (%)')
    label(axes[0], 'a', 'Energy revenue redistribution across all six generators')
    label(axes[1], 'b', 'True profit with LOC: sampled points; lines guide the eye')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center', ncol=6, frameon=False,
               bbox_to_anchor=(.55, .015))
    save(fig, 'figureS1_all_generator_payoffs', list(axes))

    hourly = load_rows(output/'boundary_hourly_redispatch.csv')
    change = values(hourly, 'output_change').reshape(6, 24)
    totals = change.sum(axis=1)
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    fig.subplots_adjust(left=.245, right=.85, bottom=.22, top=.83)
    image = ax.imshow(change, aspect='auto', cmap='RdBu_r', vmin=-max(abs(change).ravel()),
                       vmax=max(abs(change).ravel()), interpolation='nearest')
    ax.set_yticks(range(6), [f'G{i+1} ({(total if abs(total) > 1e-8 else 0.):+.2f} MWh)'
                             for i, total in enumerate(totals)])
    ax.set_xticks([0, 5, 11, 17, 23], [1, 6, 12, 18, 24])
    ax.set_xlabel('Hour')
    ax.set_title(f'Redispatch at {best_x:.4f}%: right-side plan minus left-side plan', pad=12)
    color_ax = fig.add_axes([.885, .22, .02, .61])
    fig.colorbar(image, cax=color_ax).set_label('Output change (MW)')
    save(fig, 'figureS2_boundary_redispatch', [ax])

    construction = []
    for name, folder in [('30-G1', MAIN), ('30-G2', STUDY/'30_G2_bracket_0to50'),
                         ('118-G11', ROOT/'results/scope_study_20261016/118_sparse_bracket_0to50')]:
        a, c = read(folder/'audit.json'), read(folder/'compression.json')
        construction.append(dict(instance=name, rho_range='0-50%', lp_variables=a['lp_dimensions']['variables'],
            lp_rows=a['lp_dimensions']['rows'], chp_solves=a['chp_solves'],
            value_intervals=c['merged_value_intervals'], selected_price_segments=c['selected_price_intervals'],
            offline_seconds=a['offline_seconds'], complete_price_coverage=a['price_coverage_fraction'],
            compact_bytes=c['compact_file_bytes'], timing_statistic='single archived construction'))
    write_csv(output/'table1_oracle_construction.csv', construction)
    q118 = read(STUDY/'query_118_q200.json')
    performance = [dict(instance='30-'+r['unit'], queries=1000,
        reoptimization_seconds=r['reoptimization_q1000_seconds'], oracle_total_seconds=r['oracle_q1000_seconds'],
        speedup=r['speedup'], first_amortized_query=r['first_amortized_query']) for r in summaries]
    performance.append(dict(instance='118-G11', queries=200,
        reoptimization_seconds=q118['same_model_reoptimization_batch_seconds'],
        oracle_total_seconds=q118['oracle_total_with_offline_seconds'],
        speedup=q118['same_model_reoptimization_batch_seconds']/q118['oracle_total_with_offline_seconds'],
        first_amortized_query='not established; no measured prefix trace'))
    write_csv(output/'table_computation.csv', performance)
    bundle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('prepare', 'render'), required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--qa-tools', type=Path, help='Directory containing optional external figure audit tools')
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare(args.out_dir)
    else:
        render(args.out_dir, args.qa_tools)


if __name__ == '__main__':
    main()
