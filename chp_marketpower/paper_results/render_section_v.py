"""Compact Section V figures, using archived observations and Origin-style axes."""
from pathlib import Path
import csv, json, hashlib, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import AutoMinorLocator
import numpy as np
P=Path(__file__).resolve().parent
OUT=P.parent/'manuscript/figures'
sys.path.insert(0,str(Path.home()/'.codex/skills/nature-figure/scripts'))
from audit_panel_alignment import require_matplotlib_panel_alignment
INPUTS={}
BLUE,RED,GRAY='#2374C6','#E54B4B','#555555'
plt.rcParams.update({'font.family':'serif','font.serif':['Times New Roman','DejaVu Serif'],
 'font.size':9,'axes.labelsize':9,'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':8,
 'axes.spines.top':True,'axes.spines.right':True,'axes.linewidth':.8,'pdf.fonttype':42,'svg.fonttype':'none'})
def rows(name):
 p=P/name;INPUTS[name]=hashlib.sha256(p.read_bytes()).hexdigest()
 return list(csv.DictReader(p.open(encoding='utf-8-sig')))
def n(r,k):return float(r[k])
def style(ax):
 ax.tick_params(which='both',direction='in',top=False,right=False)
 ax.xaxis.set_minor_locator(AutoMinorLocator(2));ax.yaxis.set_minor_locator(AutoMinorLocator(2))
def panel(ax,label):ax.text(.5,-.35,label,transform=ax.transAxes,ha='center',va='top',fontsize=10)
def save(fig,name,axes):
 for a in np.ravel(axes):style(a)
 require_matplotlib_panel_alignment(fig,axes=list(np.ravel(axes)),json_out=OUT/(name+'.alignment.json'),strict=True)
 for ext in ['.pdf','.svg','.png']:fig.savefig(OUT/(name+ext),dpi=600)
 plt.close(fig)
def profits():
 price=[r for r in rows('source_data/nodal_price_components.csv') if r['bus']=='1']
 offers=sorted({n(r,'delta') for r in price});lookup={(n(r,'delta'),int(r['hour'])):n(r,'lambda_CHP') for r in price}
 z=np.array([[lookup[d,h]-lookup[0.,h] for d in offers] for h in range(1,25)])
 assert z.shape==(24,len(offers)) and np.isfinite(z).all()
 fig,ax=plt.subplots(1,2,figsize=(182/25.4,76/25.4))
 fig.subplots_adjust(left=.07,right=.98,bottom=.34,top=.87,wspace=.48)
 bound=max(abs(z.min()),abs(z.max()))
 mesh=ax[0].pcolormesh(np.array(offers)/41.982*100,range(1,25),z,shading='nearest',cmap='RdBu_r',norm=TwoSlopeNorm(vmin=-bound,vcenter=0,vmax=bound),rasterized=True)
 cax=fig.add_axes([.075,.91,.35,.025]);fig.colorbar(mesh,cax=cax,orientation='horizontal',ticks=[-30,0,30]);cax.xaxis.set_ticks_position('top');cax.tick_params(labelsize=7,pad=1)
 ax[0].set(xlabel='Offer adder (% of reference slope)',ylabel='Hour',yticks=[1,6,12,18,24],xlim=(0,50))
 panel(ax[0],'(a) Price change (USD/MWh)')
 curve=rows('source_data/fig3_profit_uplift_curves.csv')
 for piece in sorted({int(r['piece']) for r in curve}):
  rr=[r for r in curve if int(r['piece'])==piece]
  ax[1].plot([n(r,'delta')/41.982*100 for r in rr],[n(r,'delta_Pi')/1000 for r in rr],'-o',color=BLUE,ms=2,lw=.9)
 ax[1].plot(13.2040804436/41.982*100,7.811555102,'*',color=RED,ms=8)
 ax[1].axhline(0,color=GRAY,lw=.5)
 ax[1].set(xlabel='Offer adder (% of reference slope)',ylabel='Additional profit (thousand USD)',xlim=(0,50))
 panel(ax[1],'(b) Actual profit')
 save(fig,'fig_v1_price_profit',ax)
def substitution():
 data=rows('source_data/fig4_generation_substitution.csv')
 fig,ax=plt.subplots(figsize=(88.9/25.4,64/25.4));fig.subplots_adjust(left=.18,right=.97,bottom=.20,top=.96)
 changes=[]
 for unit,color,mark in [('G1',BLUE,'o'),('G3',GRAY,'s'),('G5',RED,'^')]:
  a=[n(r,'p_UC') for r in data if r['plan']=='A_left' and r['unit']==unit]
  b=[n(r,'p_UC') for r in data if r['plan']=='B_right' and r['unit']==unit]
  change=np.array(b)-a;changes.append(change)
  ax.plot(range(1,7),change,'-'+mark,color=color,ms=3,lw=1,label=unit)
 assert np.max(abs(np.sum(changes,axis=0)))<1e-7
 ax.axhline(0,color=GRAY,lw=.5)
 ax.set(xlabel='Hour',ylabel='Generation B minus A (MW)',xticks=range(1,7),ylim=(-29,34))
 ax.legend(loc='upper right',ncol=3,handlelength=1,columnspacing=.7,frameon=False)
 save(fig,'fig_v3_substitution',[ax])
def timing():
 rr=rows('revision_20261020/source_data/fig1_independent_query_streams.csv')
 fig,ax=plt.subplots(1,2,figsize=(182/25.4,76/25.4));fig.subplots_adjust(left=.09,right=.98,bottom=.34,top=.88,wspace=.40)
 cross=[]
 for a,sid,label in zip(ax,['30-G1-Q1000','118-G11-Q500'],['(a) IEEE30-G1','(b) IEEE118-G11']):
  data=sorted([r for r in rr if r['stream_id']==sid],key=lambda r:n(r,'queries'))
  assert [int(n(r,'queries')) for r in data]==list(range(1,len(data)+1))
  hit=next(r for r in data if n(r,'direct_seconds')>=n(r,'parametric_seconds'));q=int(n(hit,'queries'))
  selected=[r for r in data if int(n(r,'queries'))%100==0 or int(n(r,'queries')) in (1,q-1,q)]
  for key,color,mark,label2 in [('direct_seconds',GRAY,'s','Direct CHP'),('parametric_seconds',RED,'o','CHP oracle')]:
   a.plot([n(r,'queries') for r in selected],[n(r,key) for r in selected],'-'+mark,color=color,ms=3,lw=1,label=label2)
  # Locate the crossing from consecutive measured queries, not the coarse display polyline.
  prev=data[q-2];difference=n(hit,'direct_seconds')-n(hit,'parametric_seconds');before=n(prev,'direct_seconds')-n(prev,'parametric_seconds')
  xc=q-1-before/(difference-before);yc=n(prev,'parametric_seconds')+(xc-(q-1))*(n(hit,'parametric_seconds')-n(prev,'parametric_seconds'))
  a.plot(xc,yc,'*',color=BLUE,ms=8)
  a.annotate('N = '+str(q),(xc,yc),xytext=((5,27) if q<200 else (-48,15)),textcoords='offset points',fontsize=8)
  a.set(xlabel='Number of CHP queries',ylabel='Cumulative time (s)',xlim=(0,len(data)*1.02))
  panel(a,label);cross.append({'stream':sid,'first_amortized_integer_query':q,'interpolated_crossing':xc,'displayed_queries':[int(n(r,'queries')) for r in selected]})
 fig.legend(*ax[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.55,1.01),ncol=2,frameon=False)
 save(fig,'fig_v5_timing',ax)
 return cross
if __name__=='__main__':
 profits();substitution();cross=timing()
 m=OUT/'section_v_sources.json';old=json.loads(m.read_text()) if m.exists() else {}
 old.update(inputs_sha256=INPUTS,figures_in_main_text=['fig_v1_price_profit','fig_v3_substitution','fig_v5_timing'],
  presentation='Origin-style frame; inward ticks on bottom/left; percent-normalized additive offers; preserved archived data.',
  timing_display=cross,timing_selection='Only Q1000 30-G1 and Q500 118-G11 in main figure. Q200 and G2 retained in source archives; Every 100th cumulative observation, first query, and observations adjacent to the crossing displayed. Crossing uses full measured prefix.',qa=[])
 m.write_text(json.dumps(old,indent=2)+'\n')
