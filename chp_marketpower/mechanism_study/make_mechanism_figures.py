"""Three evidence figures from recovered, validated observations; no fitted curves.

Figure contract: execution exposure transmits profit; local channels explain
responses; a single-line intervention separates total and incremental profit.
Python quantitative grids, 183 mm width, editable PDF/SVG and 600 dpi PNG.
Deterministic case studies: no sampling uncertainty or statistical error bars.
Run from chp_marketpower: python -m mechanism_study.make_mechanism_figures
"""
import argparse
from pathlib import Path
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from mechanism_study.runtime import ROOT, OUTPUT, read, write, CAUSAL_STAGE


BLUE,ORANGE,GRAY='#326A92','#B87533','#616974'


def save(fig, name, audit_scripts):
    sys.path.insert(0,str(audit_scripts))
    from audit_panel_alignment import require_matplotlib_panel_alignment
    out=OUTPUT/'paper_figures';out.mkdir(exist_ok=True)
    require_matplotlib_panel_alignment(fig,json_out=out/(name+'.alignment.json'),strict=True)
    fig.savefig(out/(name+'.pdf'))
    fig.savefig(out/(name+'.svg'))
    fig.savefig(out/(name+'.png'),dpi=600)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-scripts',type=Path,required=True)
    args=parser.parse_args()
    assert read(OUTPUT/'recovery_verification_final/summary.json')['status']=='passed'
    assert read(OUTPUT/'settlement_certification/summary.json')['status']=='passed'
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':8,'axes.titlesize':9,'axes.labelsize':8,'legend.fontsize':7,
        'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,
        'axes.linewidth':.7,'legend.frameon':False})
    e1=read(ROOT/'results/mechanism_20261018/identity_validation.json')
    assert e1['status']=='passed'
    pair=e1['P2']
    fig,axes=plt.subplots(1,2,figsize=(183/25.4,78/25.4))
    fig.subplots_adjust(left=.08,right=.98,bottom=.25,top=.85,wspace=.42)
    with np.load(ROOT/'results/mechanism_20261018/boundary.npz') as z:
        differences=z['p_A_left']-z['p_B_right']
    for offset,i,color in [(-.24,0,BLUE),(0,2,GRAY),(.24,4,ORANGE)]:
        axes[0].bar(np.arange(1,6)+offset,differences[i,:5],.24,label=f'G{i+1}',color=color)
    axes[0].axhline(0,color=GRAY,lw=.6)
    axes[0].set(xlabel='Hour',ylabel='Output A minus B (MW)',xticks=range(1,6),ylim=(-30,34),title='a  Earlier G5 commitment replaces G1')
    axes[0].legend(ncols=3,loc='upper center',bbox_to_anchor=(.5,-.24))
    values=np.array([pair['energy_revenue_difference_usd'],-pair['true_cost_difference_usd'],pair['loc_difference_usd'],pair['observed_profit_difference_usd']])/1000
    axes[1].bar(range(4),values,color=[BLUE,ORANGE,ORANGE,GRAY],width=.6)
    axes[1].axhline(0,color=GRAY,lw=.6)
    axes[1].set(xticks=range(4),xticklabels=['Energy','Cost','LOC','Profit'],ylabel='A minus B (thousand USD)',ylim=(-5.8,7.7),title='b  More profit with less LOC')
    for i,v in enumerate(values):
        axes[1].text(i,v+(.45 if v>=0 else -.45),f'{v:+.2f}',ha='center',va='bottom' if v>=0 else 'top',fontsize=7)
    save(fig,'figure1_common_price_execution',args.audit_scripts)

    local=read(OUTPUT/'E2_local/summary.json');assert local['status']=='passed'
    fig,ax=plt.subplots(figsize=(183/25.4,78/25.4))
    fig.subplots_adjust(left=.12,right=.98,bottom=.30,top=.83)
    rows=local['queries'];x=np.arange(len(rows))
    pc=[r['derivatives'][0]['price_channel'] for r in rows]
    ec=[r['derivatives'][0]['exposure_channel'] for r in rows]
    fd=[r['derivatives'][0]['finite_difference'] for r in rows]
    ax.bar(x-.18,pc,.36,label='Self-schedule price channel',color=BLUE)
    ax.bar(x+.18,ec,.36,label='Execution exposure gap',color=ORANGE)
    ax.scatter(x,fd,c=GRAY,s=18,marker='D',label='Direct profit difference',zorder=3)
    ax.axhline(0,color=GRAY,lw=.6)
    ax.set(xticks=x,xticklabels=['Truthful\nright only','First UC\nresponse','Critical\nleft','Critical\nright','40%','45%'],
        ylabel='Profit response (USD per USD/MWh)',ylim=(-180,1100),title='Six declared neighborhoods: price and execution channels')
    ax.legend(ncols=3,loc='upper center',bbox_to_anchor=(.5,-.24))
    save(fig,'figure2_local_profit_channels',args.audit_scripts)

    causal=read(OUTPUT/CAUSAL_STAGE/'summary.json')
    fig,axes=plt.subplots(1,2,figsize=(183/25.4,78/25.4))
    fig.subplots_adjust(left=.08,right=.98,bottom=.25,top=.85,wspace=.42)
    get=lambda scenario,bid:next(r for r in causal['settlements'] if r['scenario']==scenario and r['bid_index']==bid)
    for ax in axes:
        ax.set(xticks=range(3),xticklabels=['Truthful','Critical\n− 0.001','Critical\n+ 0.001'])
        ax.tick_params(axis='x',labelsize=7)
    for scenario,color,marker,label in [('original',BLUE,'o','Original line'),('relaxed',ORANGE,'s','Line 30 relaxed')]:
        profits=np.array([get(scenario,j)['true_profit_usd'] for j in range(3)])/1000
        axes[0].scatter(range(3),profits,color=color,marker=marker,s=28,label=label)
        axes[1].scatter(range(3),profits-profits[0],color=color,marker=marker,s=28)
    axes[0].set(ylabel='True profit (thousand USD)',ylim=(29,47),title='a  Total profit falls after relaxation')
    axes[1].set(ylabel='Profit above own baseline (thousand USD)',ylim=(-.5,10.2),title='b  Incremental gain rises at fixed bids')
    axes[0].legend(ncols=2,loc='upper center',bbox_to_anchor=(1.1,-.24))
    save(fig,'figure3_single_line_counterfactual',args.audit_scripts)
    write(OUTPUT/'paper_figures/figure_contract.json',dict(backend='python',width_mm=183,height_mm=78,
        figure1=dict(claim='Same bid and price: physical execution changes profit through incremental exposure',source='E1 full-system A/B arrays and ledger',uncertainty='None: deterministic paired executions'),
        figure2=dict(claim='Six certified neighborhoods resolve price and exposure channels',source='E2 raw local settlements',uncertainty='None: deterministic finite differences, not a fitted domain curve'),
        figure3=dict(claim='Total profit and markup gains respond differently to the declared single-line intervention',source='Six freshly rebuilt E4 settlements',uncertainty='None: fixed selector, six points; eight coherent directional price-face checks'),
        exclusions='None within each prespecified experiment; structural MRG values reported in the table, not a fourth figure'))
    print('Three figures exported; PDF collision and glyph audits still required')


if __name__=='__main__':main()
