"""Two replacement main figures: a predicted threshold and the complete profit path."""
import csv
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from mechanism_study.runtime import read,write
from mechanism_study.predictive_mechanism import OUTPUT

SCRIPTS=Path(r'C:/Users/250010153/.codex/skills/nature-figure/scripts')
sys.path.insert(0,str(SCRIPTS))
from audit_panel_alignment import require_matplotlib_panel_alignment

BLUE,ORANGE,GRAY,GREEN='#326A92','#B87533','#616974','#378471'


def save(fig,name):
    out=OUTPUT/'paper_figures';out.mkdir(exist_ok=True)
    require_matplotlib_panel_alignment(fig,json_out=out/(name+'.alignment.json'),strict=True)
    fig.savefig(out/(name+'.pdf'))
    fig.savefig(out/(name+'.svg'))
    fig.savefig(out/(name+'.png'),dpi=600)
    plt.close(fig)


def main():
    assert read(OUTPUT/'independent_verification.json')['status']=='passed'
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':8,'axes.titlesize':9,'axes.labelsize':8,'legend.fontsize':7,
        'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,
        'axes.linewidth':.7,'legend.frameon':False})
    plan=read(OUTPUT/'protocol_before_predictions.json');a,b=plan['candidate_lines']
    fig,axes=plt.subplots(1,2,figsize=(183/25.4,78/25.4))
    fig.subplots_adjust(left=.10,right=.98,bottom=.27,top=.84,wspace=.43)
    values=(np.array(b['unit_cost'])-a['unit_cost'])/1000
    axes[0].bar(range(4),[values[0],values[2],values[4],sum(values)],color=[BLUE,BLUE,ORANGE,GRAY],width=.6)
    axes[0].axhline(0,color=GRAY,lw=.6)
    axes[0].set(xticks=range(4),xticklabels=['G1','G3','G5','System'],ylabel='True cost B minus A (thousand USD)',
        ylim=(-5.8,8.8),title='a  The cost of replacing G1 output')
    for j,v in enumerate([values[0],values[2],values[4],sum(values)]):
        axes[0].text(j,v+(.35 if v>=0 else -.35),f'{v:+.2f}',ha='center',va='bottom' if v>=0 else 'top',fontsize=7)
    rows=read(OUTPUT/'P0_threshold_io_recovery/summary.json')['records']+read(OUTPUT/'P2_held_out/summary.json')['records']
    eps=np.array([r['epsilon'] for r in rows]);pred=np.array([r['predicted_critical'] for r in rows])
    axes[1].plot(eps,plan['predicted_critical']+eps*plan['predicted_slope'],color=GRAY,lw=1,label='Predeclared prediction')
    axes[1].scatter(eps[:3],pred[:3],s=23,color=BLUE,label='Global UC support')
    axes[1].scatter(eps[3:],pred[3:],s=30,marker='D',color=ORANGE,label='Held-out perturbation',zorder=4)
    axes[1].set(xlabel='G5 true no-load cost change\n(USD/online hour)',ylabel='Critical bid adder (USD/MWh)',
        xticks=[-1,0,1,5],title='b  Predicting the replacement threshold')
    axes[1].legend(loc='upper left',bbox_to_anchor=(-.01,1.02))
    save(fig,'figure3_predictable_substitution')

    summary=read(OUTPUT/'P1_profit_path_io_recovery/summary.json')
    with (OUTPUT/'P1_profit_path_io_recovery/continuous_channels.csv').open() as stream:pieces=list(csv.DictReader(stream))
    x=[0.];pc=[0.];ec=[0.];jc=[0.];total=[0.]
    jumps={r['delta']:r['profit_jump'] for r in summary['physical_jumps']}
    for row in pieces:
        left,right=float(row['left']),float(row['right'])
        if left in jumps:
            x.append(left);pc.append(pc[-1]);ec.append(ec[-1]);jc.append(jc[-1]+jumps[left]);total.append(pc[-1]+ec[-1]+jc[-1])
        x.append(right);pc.append(pc[-1]+float(row['price_channel_usd']));ec.append(ec[-1]+float(row['exposure_channel_usd']))
        jc.append(jc[-1]);total.append(pc[-1]+ec[-1]+jc[-1])
    assert abs(total[-1]-summary['total_extra_profit'])<1e-3
    fig,axes=plt.subplots(1,2,figsize=(183/25.4,78/25.4))
    fig.subplots_adjust(left=.10,right=.98,bottom=.29,top=.84,wspace=.43)
    for values,label,color,width in [(pc,'Price channel',GREEN,1.),(ec,'Continuous exposure',ORANGE,1.),
            (jc,'UC switches',GRAY,1.),(total,'Total extra profit',BLUE,1.8)]:
        axes[0].plot(x,np.asarray(values)/1000,label=label,color=color,lw=width)
    axes[0].axhline(0,color=GRAY,lw=.5)
    axes[0].set(xlabel='G1 all-day bid adder (USD/MWh)',ylabel='Cumulative change (thousand USD)',title='a  From truthful bid to the best candidate')
    axes[0].legend(ncols=2,loc='upper left',bbox_to_anchor=(-.12,-.22),columnspacing=.8,handlelength=1.5)
    values=np.array([pc[-1],ec[-1],jc[-1],total[-1]])/1000
    axes[1].bar(range(4),values,color=[GREEN,ORANGE,GRAY,BLUE],width=.6)
    axes[1].axhline(0,color=GRAY,lw=.6)
    axes[1].set(xticks=range(4),xticklabels=['Price','Continuous\nexposure','UC\nswitches','Net'],
        ylabel='Change (thousand USD)',ylim=(-2.,10.1),title='b  The complete gain reconciles')
    for j,v in enumerate(values):axes[1].text(j,v+(.35 if v>=0 else -.35),f'{v:+.2f}',ha='center',va='bottom' if v>=0 else 'top',fontsize=7)
    save(fig,'figure2_complete_profit_path')
    write(OUTPUT/'paper_figures/figure_contract.json',dict(
        conclusion='Operating substitution costs predict a local UC threshold; the complete gain is a reconciled path, not a boundary-profit share',
        backend='python',dimensions_mm=[183,78],png_dpi=600,
        uncertainty='Deterministic COPT global-bound and accounting tolerances; four perturbations are not statistical replicates',
        prediction='Analytic, declared before treatment; line is not a fitted regression',
        path='Piecewise affine certified SS witnesses and explicit physical jumps; no sampled interpolation of profit',
        scope='Conditional selector and UC rule; held-out no-load perturbation is not an independent system'))


if __name__=='__main__':main()
