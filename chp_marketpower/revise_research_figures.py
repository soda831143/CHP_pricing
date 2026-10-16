"""Price response -> computational reuse -> profitable bidding; archived inputs only."""
import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np

from make_research_figures import (ROOT, MAIN, PROFIT, REF, COLORS, read, write_json,
                                  write_csv, load_rows, values, first_amortized_query)
from price_vulnerability.oracle_compression import load_matched_compact, query_compact

OLD = ROOT/'results/figure_study_20261016'
HOUR_CASE = '30_G1_hour1_0to50'


def selected_prices(compact, deltas):
    args = [compact[k] for k in ('value_boundaries', 'values', 'price_boundaries', 'prices')]
    return np.stack([query_compact(float(d), *args)[1] for d in deltas])


def price_heatmap(compact, reference, bus=0):
    """Exact selector samples on cells resolving every saved affine boundary."""
    boundaries = compact['price_boundaries']
    assert np.all(np.diff(boundaries) > 0)
    edges = np.unique(np.r_[boundaries, np.linspace(boundaries[0], boundaries[-1], 401)])
    centers = (edges[:-1]+edges[1:])/2
    change = selected_prices(compact, centers)[:, bus, :]-compact['prices'][0, bus]
    return 100*edges/reference, centers, change.T


def settlement_table(rows, baseline, winner):
    chosen = [r for r in rows if float(r['delta']) == winner['delta']
              and int(r['physical_region']) == winner['physical_region']]
    if len(chosen) != len(baseline):
        raise ValueError('Missing units at the declared winning physical plan')
    result = []
    for r in chosen:
        base = baseline[int(r['generator_index'])]
        row = dict(unit=r['unit'])
        for key in ('energy_revenue', 'reported_uplift', 'true_cost', 'true_profit'):
            row[f'{key}_baseline'] = float(base[key])
            row[f'{key}_best_bid'] = float(r[key])
            row[f'{key}_change'] = float(r[key])-float(base[key])
        assert abs(row['energy_revenue_change']+row['reported_uplift_change']
                   -row['true_cost_change']-row['true_profit_change']) < 1e-5
        result.append(row)
    return result


def render(output, qa_tools=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.colors import TwoSlopeNorm

    plt.rcParams.update({'font.family':'sans-serif', 'font.sans-serif':['Arial', 'DejaVu Sans'],
        'font.size':9, 'axes.labelsize':9, 'axes.titlesize':9, 'xtick.labelsize':8,
        'ytick.labelsize':8, 'legend.fontsize':8, 'svg.fonttype':'none', 'pdf.fonttype':42,
        'axes.spines.top':False, 'axes.spines.right':False, 'axes.linewidth':.7,
        'lines.linewidth':1.5, 'savefig.dpi':400})
    if qa_tools:
        sys.path.insert(0, str(qa_tools))
        from audit_panel_alignment import require_matplotlib_panel_alignment
    _, compression, compact = load_matched_compact(MAIN)
    hourly_audit, hourly_compression, hourly = load_matched_compact(output/HOUR_CASE)
    if hourly_audit['scope'].get('bid_hour_1based') != 1:
        raise ValueError('The localized experiment must use hour 1, not an all-day map')
    validation = read(output/HOUR_CASE/'validation.json')
    if validation['status'] != 'passed':
        raise ValueError('Localized selector needs independent direct validation')
    report = read(PROFIT/'profit_range.json')
    source = read(OLD/'economic_source_audit.json')
    if (source['compact_sha256'] != hashlib.sha256((MAIN/'compact.npz').read_bytes()).hexdigest()
            or source['profit_report_sha256'] != hashlib.sha256((PROFIT/'profit_range.json').read_bytes()).hexdigest()):
        raise ValueError('Archived settlements belong to a different price/profit version')
    rows = load_rows(OLD/'generator_settlements.csv')
    winner = report['maximizing_candidate']
    best_x = 100*winner['rho']
    baseline_profit = source['baseline'][0]['true_profit']
    output.mkdir(parents=True, exist_ok=True)
    bundle = PdfPages(output/'all_figures.pdf')

    def save(fig, name, axes):
        fig.canvas.draw()
        if qa_tools:
            require_matplotlib_panel_alignment(fig, axes=axes, json_out=output/f'{name}.alignment.json',
                tolerance_pt=1.5, gutter_tolerance_pt=1.5, strict=True)
        fig.savefig(output/f'{name}.pdf')
        fig.savefig(output/f'{name}.svg')
        fig.savefig(output/f'{name}.png', dpi=400)
        bundle.savefig(fig)
        plt.close(fig)

    def label(ax, letter, title):
        ax.text(-.125, 1.07, letter, transform=ax.transAxes, fontsize=10, weight='bold')
        ax.set_title(title, loc='left', pad=12)
        ax.set_axisbelow(True)

    pb, prices = compact['price_boundaries'], compact['prices']
    buses = [0, 1, 21, 26, 22, 12]
    spatial = []
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.5))
    fig.subplots_adjust(left=.14, right=.85, bottom=.12, top=.93, hspace=.68)
    for i, bus in enumerate(buses):
        change = prices[:, bus, 0]-prices[0, bus, 0]
        axes[0].plot(100*pb/REF, change, color=COLORS[i], ls=['-', '--', '-.', ':', '-', '--'][i],
                     label=f'G{i+1}: bus {bus+1}', linewidth=1.7 if i == 0 else 1.15)
    axes[0].plot(100*pb/REF, prices[:, 14, 0]-prices[0, 14, 0], color='#202A35',
                 ls=(0, (4, 1, 1, 1)), label='Bus 15 (no generator)', linewidth=1.2)
    axes[0].set(xlim=(0, 50), ylabel='Price change ($/MWh)', xlabel='All-day G1 bid adder / reference slope (%)')
    axes[0].axhline(0, color='#ADB8BD', linewidth=.6)
    label(axes[0], 'a', 'Spatial response at hour 1')
    axes[0].legend(loc='lower left', bbox_to_anchor=(-.02, 1.22), ncol=3, frameon=False,
                   fontsize=8, columnspacing=1.3, handlelength=2.5)
    # Leave the legend a dedicated top strip instead of masking price curves.
    fig.subplots_adjust(top=.79, bottom=.10, hspace=.67)
    edges, centers, heat = price_heatmap(compact, REF)
    limit = float(np.max(np.abs(heat)))
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0., vmax=limit)
    image = axes[1].pcolormesh(edges, np.arange(.5, 25.5), heat, cmap='RdBu_r', norm=norm,
                             shading='flat', rasterized=True)
    axes[1].set(yticks=[1, 6, 12, 18, 24], ylim=(24.5, .5), xlim=(0, 50),
                ylabel='Market hour', xlabel='All-day G1 bid adder / reference slope (%)')
    label(axes[1], 'b', 'Temporal response at bus 1 (G1 location)')
    position = axes[1].get_position()
    color_ax = fig.add_axes([.885, position.y0, .018, position.height])
    fig.colorbar(image, cax=color_ax).set_label('Price change ($/MWh)', fontsize=8)
    save(fig, 'figure1_spatial_temporal_prices', list(axes))
    for k, delta in enumerate(pb):
        for bus in buses+[14]:
            spatial.append(dict(delta=float(delta), rho=float(delta/REF), bus=bus+1, hour=1,
                price=float(prices[k, bus, 0]), change=float(prices[k, bus, 0]-prices[0, bus, 0])))
    write_csv(output/'figure1_spatial_prices.csv', spatial)
    np.savez_compressed(output/'price_heatmaps.npz', all_day_edges_percent=edges,
        all_day_cell_centers_delta=centers, all_day_bus1_change=heat)

    fig, axes = plt.subplots(1, 3, figsize=(7.2, 3.1))
    fig.subplots_adjust(left=.10, right=.98, bottom=.23, top=.83, wspace=.38)
    timing, timing_rows = [], []
    for ax, name, path, letter in zip(axes, ['30-G1', '30-G2', '118-G11'],
            [OLD/'trace_30_G1_q1000.json', OLD/'trace_30_G2_q1000.json', output/'trace_118_G11_q200.json'], 'abc'):
        trace = read(path)
        direct, online = map(np.asarray, (trace['same_model_cumulative_seconds'], trace['oracle_cumulative_online_seconds']))
        fixed = trace['oracle_offline_seconds_prior_run']+trace['postprocessing_seconds']+trace['oracle_file_load_seconds']
        if len(direct) != trace['n_queries'] or direct[-1] != trace['same_model_reoptimization_batch_seconds']:
            raise ValueError('Trace must contain every measured query prefix from one batch')
        first = first_amortized_query(direct, online, fixed)
        q = np.arange(1, len(direct)+1)
        ax.plot(np.r_[0, q], np.r_[0., direct], color='#294861', label='Persistent CHP reoptimization')
        ax.plot(np.r_[0, q], np.r_[fixed, fixed+online], color='#007F7A', linewidth=1.9,
                 label='Parametric Oracle (offline included)')
        step = 100 if len(q) == 1000 else 20
        mark = np.arange(step, len(q)+1, step)
        ax.plot(mark, direct[mark-1], 'o', ms=2.5, color='#294861')
        if first:
            ax.vlines(first, 0, direct[first-1], color='#ADB8BD', ls=':', linewidth=.7)
            ax.plot(first, direct[first-1], 'o', ms=4, mfc='white', mec='#007F7A')
        ax.text(0., 1.02, f'First amortized Q: {first}' if first else 'Not amortized (Q = 200)',
                transform=ax.transAxes, fontsize=8)
        ax.set(xlim=(0, len(q)), ylim=(0, max(direct[-1], fixed+online[-1])*1.12), xlabel='Price queries Q')
        ax.set_xticks([0, 500, 1000] if len(q) == 1000 else [0, 100, 200])
        ax.text(-.20, 1.18, letter, transform=ax.transAxes, fontsize=10, weight='bold')
        ax.set_title(name, loc='left', pad=29)
        timing.append(dict(instance=name, queries=len(q), first_amortized_query=first,
            offline_postprocess_load_seconds=fixed, reoptimization_seconds=float(direct[-1]),
            oracle_total_seconds=float(fixed+online[-1]), speedup=float(direct[-1]/(fixed+online[-1]))))
        timing_rows.extend(dict(instance=name, queries=int(k), reoptimization_seconds=float(d),
            oracle_total_seconds=float(fixed+o)) for k, d, o in zip(q, direct, online))
    axes[0].set_ylabel('Cumulative computation time (s)')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center', ncol=2, frameon=False,
               bbox_to_anchor=(.54, .005), fontsize=8)
    save(fig, 'figure2_cumulative_time', list(axes))
    write_csv(output/'table_computation.csv', timing)
    write_csv(output/'figure2_measured_prefixes.csv', timing_rows)
    write_json(output/'timing_summary.json', dict(rows=timing,
        interpretation='Single recorded query streams; no extrapolated 118-bus crossing. Archived construction plus measured load and lookup cost.'))

    fig, axes = plt.subplots(3, 1, figsize=(7.2, 7.0))
    fig.subplots_adjust(left=.14, right=.97, bottom=.13, top=.94, hspace=.76)
    candidates = report['candidate_bids']
    axes[0].scatter([100*r['rho'] for r in candidates],
        [r['extra_profit_vs_truthful']/1000 for r in candidates], s=9, color='#4D6878', linewidths=0,
        label='Finite endpoint candidates')
    axes[0].plot(best_x, winner['extra_profit_vs_truthful']/1000, '*', ms=10, color=COLORS[0],
                 label='Upper boundary / supremum estimate')
    axes[0].set(xlim=(0, 50), ylabel='Extra true profit ($1000)', xlabel='All-day G1 bid adder / reference slope (%)')
    label(axes[0], 'a', 'Strategic G1: profitable offers over the complete range')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center', ncol=2,
               bbox_to_anchor=(.55, .005), frameon=False, fontsize=8)
    axes[0].annotate(f'{best_x:.4f}%; +${winner["extra_profit_vs_truthful"]:,.0f}',
        xy=(best_x, winner['extra_profit_vs_truthful']/1000), xytext=(.10, .85), textcoords='axes fraction',
        fontsize=8, color='#955517')
    for i in range(1, 6):
        unit = [r for r in rows if int(r['generator_index']) == i]
        # Non-strategic profit is independent of the physical tie at a fixed price.
        unique = {float(r['delta']):r for r in unit}
        sample = [unique[d] for d in sorted(unique)]
        axes[1].plot(100*values(sample, 'rho'), values(sample, 'true_profit_change'),
                     color=COLORS[i], ls=['-', '-', '-', ':', '--', '-.'][i], marker='.', ms=1.7,
                     linewidth=1.25 if i < 3 else .8, label=f'G{i+1}')
    axes[1].set(xlim=(0, 50), ylabel='Extra true profit ($)', xlabel='All-day G1 bid adder / reference slope (%)')
    label(axes[1], 'b', 'Other generators: directly evaluated samples, separate scale')
    axes[1].legend(frameon=False, loc='upper left', ncol=5, fontsize=8)
    for ax in axes[:2]:
        ax.axvline(best_x, color='#AAB3B9', ls=':', linewidth=.7)
        ax.axhline(0, color='#AAB3B9', linewidth=.6)
    local = read(PROFIT/'direct_validation.json')['points']
    local = [r for r in local if abs(100*r['delta']/REF-best_x) < .001]
    if len(local) != 3:
        raise ValueError('Need the original left/boundary/right direct UC checks')
    for side in (-1, 1):
        branch = [r for r in local if side*(r['delta']-winner['delta']) > 0]
        root_profit = (winner['true_profit'] if side == -1 else
            min(r['true_profit'] for r in candidates if r['delta'] == winner['delta']))
        axes[2].plot([100*branch[0]['delta']/REF, best_x],
                     [(branch[0]['solver_dispatch_profit_at_same_price']-baseline_profit)/1000,
                      (root_profit-baseline_profit)/1000], color=COLORS[0])
        axes[2].plot(100*branch[0]['delta']/REF,
                     (branch[0]['solver_dispatch_profit_at_same_price']-baseline_profit)/1000,
                     'o', ms=4, color=COLORS[0])
        if side == 1:
            axes[2].plot(best_x, (root_profit-baseline_profit)/1000, 'o', ms=5,
                         mfc='white', mec=COLORS[0], zorder=4)
    axes[2].scatter([best_x], [(winner['true_profit']-baseline_profit)/1000], marker='*', s=90, color=COLORS[0], zorder=4)
    axes[2].axvline(best_x, color='#AAB3B9', ls=':', linewidth=.7)
    axes[2].set(xlim=(best_x-.0007, best_x+.0007), ylabel='Extra true profit ($1000)',
                xlabel='All-day G1 bid adder / reference slope (%)')
    axes[2].ticklabel_format(axis='x', useOffset=False)
    axes[2].set_xticks([best_x-.0005, best_x, best_x+.0005],
                      [f'{best_x-.0005:.4f}', f'{best_x:.4f}', f'{best_x+.0005:.4f}'])
    label(axes[2], 'c', 'UC switch: G5 starts in hours 1–5; G1 loses 105.07 MWh')
    axes[2].text(.05, .60, 'Same boundary price; two optimal UC plans\nTrue-profit difference: $1,387.35',
                 transform=axes[2].transAxes, fontsize=8)
    save(fig, 'figure3_profitable_bid', list(axes))
    write_csv(output/'table2_settlement_decomposition.csv', settlement_table(rows, source['baseline'], winner))
    write_csv(output/'table1_oracle_construction.csv', load_rows(OLD/'table1_oracle_construction.csv'))

    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.0))
    fig.subplots_adjust(left=.14, right=.97, bottom=.12, top=.92, hspace=.55)
    slopes = load_rows(OLD/'figure1_value_slopes.csv')
    se = [float(slopes[0]['left_rho'])]+[float(r['right_rho']) for r in slopes]
    axes[0].stairs(values(slopes, 'derivative_wrt_absolute_adder_mwh'), 100*np.array(se),
                   baseline=None, color='#007F7A', label='CHP relaxed value slope')
    point_lookup = {p['delta']:p for p in report['physical_points']}
    regions = report['physical_regions']
    pe = [regions[0]['left']]+[r['right'] for r in regions]
    axes[0].stairs([point_lookup[r['witness_delta']]['exposure'] for r in regions],
                   100*np.array(pe)/REF, baseline=None, color=COLORS[0], ls='--', label='Physical UC exposure')
    axes[0].set(xlim=(0, 50), ylabel='Bid exposure (MWh)', xlabel='All-day G1 bid adder / reference slope (%)')
    label(axes[0], 'a', 'Convexified cost sensitivity is not physical UC execution')
    axes[0].legend(frameon=False, fontsize=8)
    for k, region in enumerate(regions):
        sample = [r for r in rows if r['generator_index'] == '0' and int(r['physical_region']) == k]
        for field, color, style, title in [('best_reported_surplus', '#007F7A', '-', 'Reported self-schedule surplus'),
            ('bid_wedge', COLORS[0], '--', 'Bid wedge: adder × UC exposure')]:
            axes[1].plot(100*values(sample, 'rho'), values(sample, field)/1000, color=color, ls=style,
                         label=title if k == 0 else None)
    axes[1].set(xlim=(0, 50), ylabel='Profit components ($1000)', xlabel='All-day G1 bid adder / reference slope (%)')
    label(axes[1], 'b', 'True profit equals reported surplus plus the physical bid wedge')
    axes[1].legend(frameon=False, fontsize=8, loc='center left')
    save(fig, 'figureS1_value_profit_components', list(axes))

    he, hc, hh = price_heatmap(hourly, REF)
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.1))
    fig.subplots_adjust(left=.14, right=.85, bottom=.12, top=.92, hspace=.50)
    for ax, e, h, letter, title in zip(axes, [edges, he], [heat, hh], 'ab',
            ['All-day G1 offer change', 'Only hour 1 changes: no resolved price response']):
        image = ax.pcolormesh(e, np.arange(.5, 25.5), h, cmap='RdBu_r', norm=norm,
                             shading='flat', rasterized=True)
        ax.set(yticks=[1, 6, 12, 18, 24], ylim=(24.5, .5), xlim=(0, 50),
               ylabel='Market hour', xlabel='G1 bid adder / reference slope (%)')
        label(ax, letter, title)
    color_ax = fig.add_axes([.885, .12, .018, .80])
    fig.colorbar(image, cax=color_ax).set_label('Bus 1 price change ($/MWh)', fontsize=8)
    save(fig, 'figureS2_localized_bid_comparison', list(axes))
    dp = hourly['prices']-hourly['prices'][0]
    max_by_hour = np.max(abs(dp), axis=(0, 1))
    full_dp = prices-prices[0]
    write_json(output/'price_response_summary.json', dict(reference_slope=REF,
        parameter='Absolute increment, all 24 hours unless bid_hour_1based is declared; rho=delta/reference',
        all_day_value_regions=compression['merged_value_intervals'], all_day_price_segments=compression['selected_price_intervals'],
        all_day_max_abs_price_change_by_hour=np.max(abs(full_dp), axis=(0, 1)).tolist(),
        localized_value_regions=hourly_compression['merged_value_intervals'],
        localized_price_segments=hourly_compression['selected_price_intervals'],
        localized_chp_solves=hourly_audit['chp_solves'], localized_offline_seconds=hourly_audit['offline_seconds'],
        localized_max_abs_price_change_by_hour=max_by_hour.tolist(), localized_response_threshold_usd_per_mwh=1e-6,
        localized_responding_hours_1based=(np.flatnonzero(max_by_hour > 1e-6)+1).tolist(),
        interpretation='Only one continuous optimal dual selector; zero resolved response is not price uniqueness or absence of intertemporal coupling. Hour 1 was chosen from the earlier UC switch, not by a significance search.'))
    np.savez_compressed(output/'localized_price_heatmap.npz', edges_percent=he, cell_centers_delta=hc,
                        bus1_change=hh, max_abs_price_change_by_hour=max_by_hour)
    inputs = [MAIN/'compact.npz', PROFIT/'profit_range.json', PROFIT/'direct_validation.json',
        OLD/'economic_source_audit.json', OLD/'generator_settlements.csv',
        OLD/'trace_30_G1_q1000.json', OLD/'trace_30_G2_q1000.json',
        output/'trace_118_G11_q200.json', output/HOUR_CASE/'oracle.npz', output/HOUR_CASE/'validation.json']
    write_json(output/'input_manifest.json', {p.resolve().relative_to(ROOT).as_posix():
        hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
    bundle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--qa-tools', type=Path)
    args = parser.parse_args()
    render(args.out_dir, args.qa_tools)


if __name__ == '__main__':
    main()
