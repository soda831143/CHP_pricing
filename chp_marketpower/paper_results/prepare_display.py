"""Prepare the remaining figure sources and two readable tables without solving."""
import numpy as np
from mechanism_study.run_study import load_inputs
from mechanism_study.runtime import ROOT,read
from paper_results.build_results import PAPER,DATA,rows,table


def main():
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    dispatch=[]
    for label,(p,u) in plans.items():
        for g in (0,2,4):
            for t in range(6):dispatch.append(dict(plan=label,unit=f'G{g+1}',hour=t+1,p_UC=float(p[g,t]),u_UC=float(u[g,t])))
    table('fig4_generation_substitution.csv',dispatch)
    prediction=read(ROOT/'results/mechanism_20261019/protocol_before_predictions.json')
    a,b=prediction['candidate_lines'];costs=[]
    for d in [max(adjacent[0]['left'],critical-.2),critical,min(adjacent[1]['right'],critical+.2)]:
        ca=a['cost']+d*a['exposure'];cb=b['cost']+d*b['exposure'];mean=(ca+cb)/2
        costs.append(dict(delta=d,offered_cost_A=ca,offered_cost_B=cb,relative_cost_A=ca-mean,relative_cost_B=cb-mean))
    assert abs(costs[1]['relative_cost_A'])<1e-6 and abs(costs[1]['relative_cost_B'])<1e-6
    table('fig4_cost_competition.csv',costs)
    cases=[]
    for folder in ('P0_threshold_io_recovery','P2_held_out'):
        for r in read(ROOT/'results/mechanism_20261019'/folder/'summary.json')['records']:
            cases.append(dict(cost_change=r['epsilon'],predicted_critical=r['predicted_critical'],
                global_UC_support=r['supported'],max_cost_gap=r['max_candidate_gap_to_global_bound']))
    table('fig4_threshold_predictions.csv',cases)
    with np.load(DATA/'price_components.npz') as z:
        all_mu=z['mu_positive'];ptdf=z['PTDF'];bids=z['delta']
        active=np.flatnonzero(np.max(abs(all_mu),axis=(0,2,3))>1e-7)
        line_data=[]
        for j,d in enumerate(bids):
            for l in active:
                for t in range(24):
                    m=all_mu[j,l,t]
                    line_data.append(dict(delta=float(d),line=int(l+1),hour=t+1,node=23,
                        mu_plus=float(m[0]),mu_minus=float(m[1]),
                        congestion_price_contribution=float(-ptdf[l,22]*(m[0]-m[1]))))
    table('active_line_congestion_prices_at_G5.csv',line_data)
    timing=rows(PAPER/'revision_20261020/source_data/table_I_four_workloads.csv');change=rows(DATA/'table_II_settlement_changes.csv')
    content='# Current Table II. Parametric CHP representation and computational performance\n\n'
    content+='|Instance|Price intervals|Common UC regions|Queries|Direct (s)|Parametric, all costs (s)|Direct / parametric|First amortized query|\n|---|---:|---:|---:|---:|---:|---:|---:|\n'
    for r in timing:
        content+=f"|{r['instance']}|{r['price_intervals']}|{r['common_UC_regions']}|{r['queries']}|{float(r['direct_seconds']):.2f}|{float(r['parametric_total_seconds']):.2f}|{float(r['direct_over_parametric']):.2f}×|{r['first_amortized_query']}|\n"
    content+='\nHistorical filename TABLE_I.md is retained for existing links; the current manuscript numbers this computation table II. Four measured streams include independent 118-bus Q500 and Q200 workloads; the latter is not amortized. Totals include construction, postprocessing, file loading and online lookup. These are CHP-pricing costs; system UC and uplift evaluation are separate. G1 has 99 joint intervals, 100 unique candidate offers and 116 offer/physical-plan candidates. G2 has six archived common UC regions; its full profit domain and the 118-bus physical/profit domain are not assessed here.\n'
    (PAPER/'TABLE_I.md').write_text(content,encoding='utf-8')
    content='# Current Table I. Changes in generator revenues, uplift, actual costs and profits\n\n'
    content+='|Generator|ΔR (USD)|ΔU (USD)|ΔC (USD)|ΔΠ (USD)|\n|---|---:|---:|---:|---:|\n'
    for r in change:content+='|'+r['unit']+'|'+ '|'.join(f"{float(r[k]):+,.2f}" for k in ('delta_R','delta_U','delta_C','delta_Pi'))+'|\n'
    content+='\nHistorical filename TABLE_II.md is retained for existing links; the current manuscript numbers this settlement table I. Each change is best-offer minus truthful bidding for the same market conditions and declared upper-profit boundary plan. Before rounding, ΔΠ=ΔR+ΔU−ΔC. U is full reported lost-opportunity-cost uplift. Negative ΔC means lower actual operating cost. Absolute amounts and energy/congestion components are in source_data/absolute_generator_settlements.csv; the component allocation uses the original bus 1 PTDF reference.\n'
    (PAPER/'TABLE_II.md').write_text(content,encoding='utf-8')


if __name__=='__main__':main()
