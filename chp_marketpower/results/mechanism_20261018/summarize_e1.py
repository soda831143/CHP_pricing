"""Reproduce E1 cost attribution and the sole scientific figure; no optimizations.

Run from chp_marketpower: python results/mechanism_20261018/summarize_e1.py
"""
import csv
import json
from pathlib import Path
import sys
from dataclasses import asdict

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT))
from engine import load_case
from benchmarks.unit_self_schedule import dispatch_cost
from mechanism_study.profit_identity import hourly_cost


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    gens, network = load_case('30', 'ptdf', 24, 3, 'tight')
    evidence = json.loads((OUT/'identity_validation.json').read_text())
    manifest = json.loads((OUT/'manifest.json').read_text())
    if evidence['status'] != 'passed' or manifest['status'] != 'passed':
        raise ValueError('Need completed E0-E1 evidence before plotting')
    (OUT/'model_snapshot.json').write_text(json.dumps(dict(generators=[asdict(g) for g in gens],
        model_identity=manifest['model_identity'], duration_hours=1.,
        price_selector=manifest['definitions']['price'], settlement=manifest['definitions']['loc']),
        indent=2),encoding='utf-8')
    np.savez_compressed(OUT/'model_snapshot.npz',demand=network.demand,PTDF=network.PTDF,
        PTDF_Gen=network.PTDF_Gen,F_max=network.F_max,
        generator_bus_indices=[network.gen_bus_idx(i) for i in range(len(gens))])
    pair = evidence['P2']
    delta = evidence['boundary_ledger']['A_left']['delta']
    rows = []
    with np.load(OUT/'boundary.npz') as data:
        differences = data['p_A_left']-data['p_B_right']
        for label in ('A_left', 'B_right'):
            p, u = data[f'p_{label}'], data[f'u_{label}']
            for i, g in enumerate(gens):
                previous = np.r_[g.initial_status, u[i,:-1]]
                true = float(dispatch_cost(g, p[i], u[i]))
                exposure = float(np.sum(p[i]-g.P_min*u[i]))
                if abs(hourly_cost(g, p[i], u[i]).sum()-true) > 1e-6:
                    raise ValueError('Unit cost reconstruction failed')
                rows.append(dict(plan=label, unit=g.unit_id, generation_mwh=float(p[i].sum()),
                    exposure_mwh=exposure, online_hours=float(u[i].sum()),
                    startup_hours=json.dumps((np.flatnonzero(u[i]>previous)+1).tolist()),
                    shutdown_hours=json.dumps((np.flatnonzero(u[i]<previous)+1).tolist()),
                    true_cost_usd=true, reported_cost_usd=true+(delta*exposure if i==0 else 0.),
                    minimum_up_hours=g.T_on_min, minimum_down_hours=g.T_off_min,
                    pmin_mw=g.P_min, startup_cost_usd=g.cost_su))
    with (OUT/'boundary_system_costs.csv').open('w', newline='', encoding='utf-8') as stream:
        writer=csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    a,b = evidence['boundary_ledger']['A_left'], evidence['boundary_ledger']['B_right']
    corollary = dict(true_system_cost_B_minus_A_usd=b['system_true_cost_usd']-a['system_true_cost_usd'],
        reported_system_cost_A_minus_B_usd=a['system_reported_cost_usd']-b['system_reported_cost_usd'])
    corollary['profit_minus_true_system_cost_saving_usd'] = pair['observed_profit_difference_usd']-corollary['true_system_cost_B_minus_A_usd']
    corollary['two_archived_cost_line_crossing_delta'] = corollary['true_system_cost_B_minus_A_usd']/pair['exposure_difference_mwh']
    corollary['crossing_minus_archived_delta'] = corollary['two_archived_cost_line_crossing_delta']-delta
    corollary['G5_extra_minimum_output_hours'] = 5
    corollary['G5_extra_online_cost_usd'] = 5*gens[4].cost_nl
    corollary['G5_startup_count_difference'] = 0
    if abs(corollary['profit_minus_true_system_cost_saving_usd']) > 1e-6:
        raise ValueError('Common-offer-cost corollary failed')
    (OUT/'boundary_cost_corollary.json').write_text(json.dumps(corollary,indent=2),encoding='utf-8')
    figures = OUT/'paper_figures';figures.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False,
                         'svg.fonttype':'none'})
    fig, axes=plt.subplots(1,2,figsize=(12,4.2),layout='constrained',gridspec_kw={'width_ratios':[1,1.25]})
    hours=np.arange(1,7);width=.24
    for offset,i,color in [(-width,0,'#227fa8'),(0.,2,'#7d9b57'),(width,4,'#cf7c38')]:
        axes[0].bar(hours+offset,differences[i,:6],width=width,label=gens[i].unit_id,color=color)
    axes[0].axhline(0,color='#555555',linewidth=.7)
    axes[0].set(xlabel='Hour',ylabel='Output A minus B (MW)',xticks=hours,
                ylim=(-29,36),title='(a) G5 early commitment replaces G1 / G3')
    axes[0].legend(ncols=3,loc='upper right',frameon=False)
    effects=[pair['energy_revenue_difference_usd'],-pair['true_cost_difference_usd'],pair['loc_difference_usd']]
    starts=[0.,effects[0],sum(effects[:2])];total=sum(effects)
    for k,(start,value) in enumerate(zip(starts,effects)):
        axes[1].bar(k,value,bottom=start,color='#227fa8' if value>0 else '#cf7c38',width=.64)
        end=start+value
        axes[1].text(k,max(start,end)+180,f'{value:+,.2f}',ha='center',fontsize=9)
        axes[1].plot([k+.32,k+.68],[end,end],color='#888888',linewidth=.7)
    axes[1].bar(3,total,color='#385067',width=.64)
    axes[1].text(3,total+180,f'{total:+,.2f}',ha='center',fontsize=9,fontweight='bold')
    axes[1].set(xticks=range(4),xticklabels=['Energy revenue','− True cost','LOC','True profit'],
                ylabel='A minus B (USD)',ylim=(0,7100),title='(b) Common-price settlement difference')
    axes[1].text(.98,.93,'δ × (Dᴬ − Dᴮ) = $1,387.3469913',ha='right',va='top',
                 transform=axes[1].transAxes,fontsize=10)
    fig.suptitle('IEEE30 G1: two UC optima at the same bid and selected CHP price',fontsize=12)
    for ext in ('png','svg'):
        fig.savefig(figures/f'figure1_boundary_mechanism.{ext}',dpi=220)
    svg=figures/'figure1_boundary_mechanism.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
    plt.close(fig)
    print('Rebuilt boundary_system_costs.csv, cost corollary and one figure; zero solver calls')


if __name__=='__main__':
    main()
