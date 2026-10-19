"""Minimal E5 evidence on the already declared three-unit, three-bid set.

One SS solve supplies G1's missing rho=0.5 exposure witness; no new UC/CHP.
"""
import numpy as np
from engine import load_case
from price_vulnerability.model_identity import check_model_identity
from price_vulnerability.oracle_compression import load_matched_compact,query_compact
from price_vulnerability.scalar_markup import apply_generator_adder
from strategic_market_simulation.profit_sweep import _settle_target
from mechanism_study.profit_identity import ledger
from mechanism_study.runtime import ROOT,OUTPUT,Stage,read,write,CAUSAL_STAGE
from mechanism_study.run_study import ORACLE,PHYSICAL


def main():
    assert read(OUTPUT/CAUSAL_STAGE/'summary.json')['status']=='passed'
    stage=Stage('E5_finite_screen',budgets=dict(self_schedule=1,uc=0,chp=0,auxiliary=0),seconds=60.,
        plan=dict(units=['G1','G5','G2'],rhos=[0.,.31451766098802286,.5],
            threshold=1e-6,scope='Existing finite set only; zero MIP, no learned classifier, no continuous-domain or deployment claim'))
    gens,net=load_case('30','ptdf',24,3,'tight')
    audit,_,compact=load_matched_compact(ORACLE)
    assert check_model_identity(ORACLE,gens,net,audit)
    candidate=next(r for r in read(PHYSICAL/'profit_range.json')['candidate_bids'] if abs(r['delta']-20.991)<1e-10)
    with np.load(PHYSICAL/'physical_plans.npz') as z:
        index=np.flatnonzero(z['deltas']==candidate['physical_plan_delta'])[0]
        p,u=z['outputs'][index],z['commitments'][index]
    d=candidate['delta'];price=query_compact(d,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1]
    with stage.solvers():
        ss=stage.call('self_schedule','G1_rho50',lambda:_settle_target(gens[0],apply_generator_adder(gens,0,d)[0],price[net.gen_bus_idx(0)],p[0],u[0],mip_gap=0.))
    account=ledger(gens[0],p[0],u[0],price[net.gen_bus_idx(0)],d,ss['best_reported_profit'])
    assert ss['self_schedule_gap_usd']<1e-6 and abs(account['true_profit_usd']-candidate['true_profit'])<1e-6
    stage.save('G1_rho50',dict(delta=d,self_schedule_upper_bound_usd=ss['self_schedule_upper_bound'],**account),
        dict(p=p,u=u,price=price,self_p=ss['self_output_mw'],self_u=ss['self_commitment']))
    study=read(OUTPUT/'E3_pivotal/summary.json');rows=[]
    for unit in stage.state['identity']['plan']['units']:
        observed=[r for r in study['economics'] if r['unit']==unit]
        baseline=next(r['true_profit_usd'] for r in observed if r['rho']==0.)
        gain=max(r['true_profit_usd']-baseline for r in observed)
        mrg=next(r for r in study['mrg'] if r['unit']==unit and r['hour']==19)
        rows.append(dict(unit=unit,mrg_uc_h19_mw=mrg['mrg_uc_mw'],mrg_chp_h19_mw=mrg['mrg_chp_mw'],
            removal_status='infeasible_pivotal',kappa_usd=None,observed_best_extra_profit_usd=gain,
            mrg_flag=mrg['mrg_uc_mw']>1e-6,positive_gain_in_declared_finite_set=gain>1e-6,
            interpretation='Potential false positive relative only to this finite strategy set' if gain<=1e-6 else 'Observed profitable opportunity'))
    write(stage.out/'summary.json',dict(status='passed',records=rows,
        conclusion='MRG and removal pivotality flag all three units but only G1/G5 profit on the declared set; G2 outside this set is unresolved',
        true_cost_scope='Known synthetic benchmark costs; this is not a deployable regulatory index',
        price_scope='Use matching intervention price responses; do not compare incompatible historical Jacobian ranks'))
    stage.finish();print('Finite-set screening evidence saved; no new strategy search')


if __name__=='__main__':main()
