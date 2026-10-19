"""Four main figures from the consolidated source tables, with editable exports."""
from pathlib import Path
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from mechanism_study.runtime import read,write
from paper_results.build_results import PAPER,DATA,rows
from paper_results.components import interpolate

SCRIPTS=Path(r'C:/Users/250010153/.codex/skills/nature-figure/scripts')
sys.path.insert(0,str(SCRIPTS))
from audit_panel_alignment import require_matplotlib_panel_alignment

BLUE,TEAL,ORANGE,GRAY='#326A92','#278373','#B87533','#616974'


def save(fig,name,axes):
    out=PAPER/'figures';out.mkdir(exist_ok=True)
    require_matplotlib_panel_alignment(fig,axes=list(np.ravel(axes)),json_out=out/(name+'.alignment.json'),strict=True)
    fig.savefig(out/(name+'.pdf'))
    fig.savefig(out/(name+'.svg'))
    fig.savefig(out/(name+'.png'),dpi=600)
    plt.close(fig)


def main():
    summary=read(PAPER/'analysis_summary.json');assert summary['status']=='passed'
    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':8,'axes.titlesize':9,'axes.labelsize':8,'legend.fontsize':7,
        'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,
        'axes.linewidth':.7,'legend.frameon':False,'xtick.labelsize':7,'ytick.labelsize':7})
    timing=rows(DATA/'fig1_measured_query_prefixes.csv')
    fig,axes=plt.subplots(1,3,figsize=(183/25.4,74/25.4))
    fig.subplots_adjust(left=.08,right=.98,bottom=.28,top=.80,wspace=.42)
    for ax,r,letter in zip(axes,summary['timing'],'abc'):
        data=[d for d in timing if d['instance']==r['instance']]
        x=[0]+[int(d['queries']) for d in data]
        fixed=r['offline_seconds']+r['postprocessing_seconds']+r['load_seconds']
        ax.plot(x,[0.]+[float(d['direct_seconds']) for d in data],color=BLUE,label='Persistent CHP reoptimization')
        ax.plot(x,[fixed]+[float(d['parametric_seconds']) for d in data],color=TEAL,label='Parametric CHP (all costs)')
        hit=r['first_amortized_query']
        if isinstance(hit,int):
            value=float(data[hit-1]['direct_seconds']);ax.plot(hit,value,'o',ms=4,mfc='white',mec=TEAL)
        ax.set(xlabel='Price queries',title=f"{letter}  IEEE {r['instance']}",xlim=(0,r['queries']),ylim=(0,max(r['direct_seconds'],r['parametric_total_seconds'])*1.12))
        ax.text(.03,.97,f"{r['direct_over_parametric']:.2f}×; first N = {hit}" if isinstance(hit,int) else f"{r['direct_over_parametric']:.2f}×; not amortized",transform=ax.transAxes,fontsize=7,va='top')
    axes[0].set_ylabel('Cumulative computation time (s)')
    fig.legend(*axes[0].get_legend_handles_labels(),loc='lower center',bbox_to_anchor=(.54,.01),ncols=2)
    save(fig,'fig1_cumulative_pricing_time',axes)

    with np.load(DATA/'price_components.npz') as z:
        bids=z['delta'];energy=z['lambda_E'];congestion=z['lambda_C'];nodal=z['lambda_CHP']
    fig,axes=plt.subplots(1,3,figsize=(183/25.4,78/25.4))
    fig.subplots_adjust(left=.09,right=.98,bottom=.30,top=.83,wspace=.48)
    for t,color in [(0,ORANGE),(1,BLUE),(18,TEAL)]:axes[0].plot(bids,nodal[:,0,t],color=color,label=f'Hour {t+1}')
    axes[0].set(xlabel='Offer adder δ (USD/MWh)',ylabel='CHP at G1 (USD/MWh)',title='a  Nonuniform price responses')
    axes[0].legend(loc='upper left',bbox_to_anchor=(0,-.25),ncols=2)
    axes[1].plot(bids,energy[:,18],color=BLUE,label='System energy')
    axes[1].plot(bids,congestion[:,22,18],color=ORANGE,label='Congestion at G5')
    axes[1].plot(bids,nodal[:,22,18],color=TEAL,label='CHP at G5')
    axes[1].axhline(0,color=GRAY,lw=.5)
    axes[1].set(xlabel='Offer adder δ (USD/MWh)',ylabel='Price component (USD/MWh)',title='b  Nodal decomposition: hour 19')
    axes[1].legend(loc='upper left',bbox_to_anchor=(-.05,-.25),ncols=1)
    byhour=rows(DATA/'price_effect_by_hour.csv');v=np.array([float(r['total_price_effect']) for r in byhour])/1000
    axes[2].bar(np.arange(1,25),v,color=np.where(v>=0,BLUE,ORANGE),width=.8)
    axes[2].axhline(0,color=GRAY,lw=.5)
    axes[2].set(xlabel='Market hour',ylabel='G1 price effect (thousand USD)',xticks=[1,6,12,18,24],title='c  Hourly contributions to profit')
    axes[2].text(.03,-.33,'Energy: +8.742 thousand USD\nCongestion at G1: 0 (bus 1 reference)',transform=axes[2].transAxes,va='top',fontsize=7)
    save(fig,'fig2_energy_congestion_prices',axes)

    curves=rows(DATA/'fig3_profit_uplift_curves.csv');critical=13.204080443599175
    fig,axes=plt.subplots(2,1,figsize=(183/25.4,116/25.4),sharex=True)
    fig.subplots_adjust(left=.12,right=.97,bottom=.13,top=.91,hspace=.40)
    for index,key in enumerate(('delta_Pi','U')):
        previous=None
        for piece in sorted({int(r['piece']) for r in curves}):
            values=[r for r in curves if int(r['piece'])==piece]
            axes[index].plot([float(r['delta']) for r in values],[float(r[key])/1000 for r in values],color=BLUE if index==0 else ORANGE,lw=1.5)
            if previous is not None and previous['physical_region']!=values[0]['physical_region']:
                x=float(values[0]['delta']);old=float(previous[key])/1000;new=float(values[0][key])/1000
                axes[index].vlines(x,min(old,new),max(old,new),color=GRAY,ls=':',lw=.6)
                axes[index].plot(x,new,'o',ms=2.5,mfc='white',mec=GRAY,mew=.6)
            previous=values[-1]
        axes[index].axvline(critical,color=GRAY,ls='--',lw=.7)
        axes[index].set_ylabel('Additional profit (thousand USD)' if index==0 else 'Uplift payment (thousand USD)')
        axes[index].set_title('a  Strategic profit over the complete offer range' if index==0 else 'b  Uplift follows its own settlement response',loc='left')
    axes[0].plot(critical,summary['path_total_extra_profit']/1000,'*',color=TEAL,ms=8)
    axes[0].text(critical+.4,summary['path_total_extra_profit']/1000+.35,'Best offer\nδ = 13.2041 USD/MWh',fontsize=7,va='bottom')
    axes[0].axhline(0,color=GRAY,lw=.5)
    axes[1].set(xlabel='G1 all-day offer adder δ (USD/MWh)',xlim=(0,max(float(r['delta']) for r in curves)))
    save(fig,'fig3_strategic_profit_uplift',axes)

    dispatch=rows(DATA/'fig4_generation_substitution.csv');costs=rows(DATA/'fig4_cost_competition.csv');pred=rows(DATA/'fig4_threshold_predictions.csv')
    fig,axes=plt.subplots(1,3,figsize=(183/25.4,78/25.4))
    fig.subplots_adjust(left=.09,right=.98,bottom=.30,top=.83,wspace=.47)
    for offset,g,color in [(-.24,'G1',BLUE),(0.,'G3',GRAY),(.24,'G5',ORANGE)]:
        p=lambda label:np.array([float(r['p_UC']) for r in dispatch if r['plan']==label and r['unit']==g])
        axes[0].bar(np.arange(1,7)+offset,p('B_right')-p('A_left'),.24,label=g,color=color)
    axes[0].axhline(0,color=GRAY,lw=.5)
    axes[0].set(xlabel='Hour',ylabel='Cleared generation B − A (MW)',xticks=range(1,7),title='a  Earlier G5 operation replaces G1')
    axes[0].legend(loc='upper left',bbox_to_anchor=(-.02,-.25),ncols=3,columnspacing=.8,handlelength=1.2)
    for name,color,style in [('A',BLUE,'-'),('B',ORANGE,'--')]:axes[1].plot([float(r['delta']) for r in costs],[float(r['relative_cost_'+name]) for r in costs],color=color,ls=style,label='Schedule '+name)
    axes[1].axhline(0,color=GRAY,lw=.5);axes[1].axvline(critical,color=GRAY,lw=.5,ls=':')
    axes[1].set(xlabel='Offer adder δ (USD/MWh)',ylabel='Offered cost minus pair mean (USD)',title='b  Competing system-cost lines')
    axes[1].legend(loc='upper left',bbox_to_anchor=(-.02,-.25))
    x=np.array([float(r['cost_change']) for r in pred]);y=np.array([float(r['predicted_critical']) for r in pred])
    axes[2].plot(x,y,color=GRAY,lw=1,label='Analytical prediction')
    axes[2].scatter(x,y,color=[BLUE]*3+[ORANGE],s=23,zorder=3,label='Global UC support')
    axes[2].set(xlabel='G5 online-cost change\n(USD/online hour)',ylabel='Critical offer adder (USD/MWh)',xticks=[-1,0,1,5],title='c  Predicting the offer threshold')
    axes[2].legend(loc='upper left',bbox_to_anchor=(-.02,-.25))
    save(fig,'fig4_substitution_threshold',axes)
    write(PAPER/'figures/figure_contract.json',dict(main_figure_count=4,main_tables=2,backend='python',width_mm=183,png_dpi=600,
        uncertainty='Single measured timing streams and deterministic optimization; no statistical replication or confidence bands',
        reference='Original PTDF reference bus 1; G1 congestion component is zero by this convention',
        price_hours='Hour 1 physical start, hour 2 a tied largest positive price-effect hour, hour 19 baseline peak demand',
        profit_curve='Certified common self-schedules on all 99 joint intervals; lines never bridge a physical jump',
        fig4_cost_display='Same δ-dependent pair-mean subtracted from both actual cost lines; the crossing is unchanged',
        startup_control='G5 true startup cost +50 USD/start leaves the supported threshold unchanged; not a strategic-offer experiment'))


if __name__=='__main__':main()
