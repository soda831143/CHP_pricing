"""E4: one preregistered constraint intervention, rebuilt UC/CHP/LOC throughout."""
from dataclasses import replace
import csv

import numpy as np

from engine import load_case, PTDFNetwork, ScheduleRunMILP
from price_vulnerability.persistent_chp import PersistentCHP
from price_vulnerability.model_identity import model_identity, check_model_identity
from price_vulnerability.oracle_compression import load_matched_compact, query_compact
from price_vulnerability.scalar_markup import apply_generator_adder
from run_initial_condition_audit import schedule_residuals
from strategic_market_simulation.profit_sweep import _settle_target
from mechanism_study.profit_identity import ledger
from mechanism_study.runtime import ROOT, OUTPUT, Stage, read, write, CAUSAL_STAGE
from mechanism_study.structural_pivotality import cost_and_gap
from mechanism_study.linear_audit import price_face_extremes


CRITICAL = 13.204080443599175
ARCHIVE = ROOT/'results/scope_study_20261016/30_bracket_repeat1'


def choose_intervention(gens, net, mu):
    """Choose using original constraint duals, before looking at treatment profit."""
    line = np.asarray(mu)[-2*net.N_line*net.T:].reshape(net.N_line,net.T,2)
    scores = np.sum(abs(line[:,:5,:]),axis=(1,2))*abs(net.PTDF_Gen[:,0]-net.PTDF_Gen[:,4])
    if float(np.max(scores)) > 1e-9:
        k = int(np.argmax(scores))  # first index breaks ties
        bound = float(abs(net.PTDF_Gen[k])@np.array([g.P_max for g in gens])
                      + np.max(abs(net.PTDF[k]@net.demand))+1.)
        return dict(kind='line_capacity',line_index_0based=k,line_number_1based=k+1,
            old_capacity_mw=float(net.F_max[k]),new_capacity_mw=bound,
            score=float(scores[k]),scores=scores.tolist(),hours_used_1based=[1,2,3,4,5],
            scope='Both flow directions, all 24 hours; all other model data fixed')
    return dict(kind='startup_ramp',unit='G1',old_capacity_mw=float(gens[0].SU_ramp),
                new_capacity_mw=float(gens[0].P_max),scores=scores.tolist())


def treatment(gens,net,intervention):
    if intervention['kind']=='line_capacity':
        cap=net.F_max.copy();cap[intervention['line_index_0based']]=intervention['new_capacity_mw']
        return gens, PTDFNetwork(net.demand.copy(),net.PTDF.copy(),cap,
            [net.gen_bus_idx(i) for i in range(len(gens))],net.PTDF_Gen.copy())
    changed=list(gens);changed[0]=replace(gens[0],SU_ramp=gens[0].P_max)
    return changed,net


def settle(stage,name,gens,reported,net,p,u,price,delta):
    ss=stage.call('self_schedule',name,lambda:_settle_target(gens[0],reported[0],
        price[net.gen_bus_idx(0)],p[0],u[0],mip_gap=0.))
    if ss['self_schedule_gap_usd']>1e-6:raise ValueError('Uncertified self-schedule maximum')
    account=ledger(gens[0],p[0],u[0],price[net.gen_bus_idx(0)],delta,ss['best_reported_profit'])
    if abs(account['identity_residual_usd'])>1e-6:raise ValueError('Full accounting identity failed')
    return account,ss


def run(*,resume=False,seconds=600.,dry_run=False):
    for name in ['E2_local','E3_pivotal']:
        if read(OUTPUT/name/'summary.json')['status']!='passed':raise ValueError('Previous stage gate failed')
    gens,net=load_case('30','ptdf',24,3,'tight')
    with np.load(ROOT/'results/mechanism_20261018/boundary.npz') as z:
        intervention=choose_intervention(gens,net,z['ineq_dual'])
    plan=dict(intervention=intervention,deltas=[0.,CRITICAL-.001,CRITICAL+.001],
        selector='Fresh cold-start COPT dual simplex (method=1,crossover=1), threads=1, seed=20261018',
        physical_selector='Fresh UC optimizer, zero relative gap, absolute gap 1e-8; no favorable boundary tie selection',
        dual_face_scope='Two coherent extrema of ONE frozen truthful G1 SS price functional, not profit extrema')
    if dry_run:return plan
    plan['dual_face_formulation']='Complementarity with a certified optimal primal; full unscaled strong-duality equality independently checked'
    stage=Stage(CAUSAL_STAGE,budgets=dict(uc=6,chp=6,self_schedule=14,auxiliary=8),
        seconds=seconds,resume=resume,plan=plan)
    write(stage.out/'intervention_before_treatment.json',plan)
    treated_g,treated_n=treatment(gens,net,intervention)
    audit,_,compact=load_matched_compact(ARCHIVE)
    if not check_model_identity(ARCHIVE,gens,net,audit):
        raise ValueError('Original model has no verified Oracle binding')
    # Rejection is the expected guard outcome; unrelated binding errors still fail.
    try:
        check_model_identity(ARCHIVE,treated_g,treated_n,audit)
    except ValueError as error:
        if str(error) != 'Oracle model data or initial conditions changed; rebuild or revalidate the map':
            raise
    else:
        raise ValueError('Original Oracle incorrectly accepted a changed feasible set')
    with np.load(ROOT/'results/mechanism_20261018/baseline.npz') as z:weight=z['self_p'].copy()
    rows=[];faces=[];activities=[]
    with stage.solvers():
        for scenario,gg,nn in [('original',gens,net),('relaxed',treated_g,treated_n)]:
            for j,delta in enumerate(plan['deltas']):
                name=f'{scenario}_bid{j}';cached=stage.cached(name)
                if cached:
                    rows.append(cached['settlement']);faces.extend(cached['faces']);activities.extend(cached['activity']);continue
                print('E4 '+name,flush=True)
                reported=apply_generator_adder(gg,0,delta)
                uc=ScheduleRunMILP(reported,nn)
                p,u,value=stage.call('uc',name,lambda:uc.solve(require_optimal=True,mip_gap=0.))
                residual=schedule_residuals(gg,nn,p,u)
                if max(residual.values())>1e-7:raise ValueError('Counterfactual UC feasibility failed')
                cost_and_gap(reported,p,u,value,uc.solve_info['lower_bound'])
                cp=PersistentCHP(gg,nn,0)
                point=stage.call('chp',name,lambda:cp.solve(delta))
                account,ss=settle(stage,name,gg,reported,nn,p,u,point.price,delta)
                row=dict(scenario=scenario,bid_index=j,delta=delta,**account,
                    self_schedule_upper_bound_usd=ss['self_schedule_upper_bound'],self_schedule_gap_usd=ss['self_schedule_gap_usd'],
                    reported_system_cost_usd=value,uc_global_bound_usd=uc.solve_info['lower_bound'],
                    uc_residuals=residual,chp_kkt_residuals=point.audit,chp_value_usd=point.value,
                    model_identity=model_identity(gg,nn))
                if scenario=='original':
                    old_price=query_compact(delta,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1]
                    row['max_price_difference_to_archived_selector']=float(np.max(abs(point.price-old_price)))
                arrays=dict(price=point.price,p=p,u=u,primal=point.primal,objective=point.objective,
                    eq_dual=point.eq_dual,ineq_dual=point.ineq_dual,lower_dual=point.lower_dual,
                    upper_dual=point.upper_dual,self_p=ss['self_output_mw'],self_u=ss['self_commitment'],frozen_weight=weight)
                local_faces=[]
                if j in [0,2]:
                    for endpoint in price_face_extremes(cp,point,weight,stage,name):
                        face=dict(scenario=scenario,bid_index=j,delta=delta,
                            **{k:v for k,v in endpoint.items() if not isinstance(v,np.ndarray)})
                        if endpoint['status']=='optimal':
                            acc,ssface=settle(stage,name+'_face_'+endpoint['extreme'],gg,reported,nn,p,u,endpoint['price'],delta)
                            face.update(acc)
                            face.update(self_schedule_upper_bound_usd=ssface['self_schedule_upper_bound'],self_schedule_gap_usd=ssface['self_schedule_gap_usd'])
                            for k,v in endpoint.items():
                                if isinstance(v,np.ndarray):arrays['face_'+endpoint['extreme']+'_'+k]=v
                            arrays['face_'+endpoint['extreme']+'_self_p']=ssface['self_output_mw']
                            arrays['face_'+endpoint['extreme']+'_self_u']=ssface['self_commitment']
                        local_faces.append(face)
                active=[]
                if intervention['kind']=='line_capacity':
                    k=intervention['line_index_0based'];uc_flow=nn.PTDF_Gen@p-nn.PTDF@nn.demand
                    lp_p=cp.solver.lp_dispatch();lp_flow=nn.PTDF_Gen@lp_p-nn.PTDF@nn.demand
                    lines=point.ineq_dual[-2*nn.N_line*nn.T:].reshape(nn.N_line,nn.T,2)
                    arrays.update(uc_flows=uc_flow,chp_flows=lp_flow)
                    for t in range(nn.T):
                        active.append(dict(scenario=scenario,bid_index=j,hour=t+1,line_number=k+1,
                            capacity_mw=float(nn.F_max[k]),uc_flow_mw=float(uc_flow[k,t]),
                            chp_flow_mw=float(lp_flow[k,t]),upper_dual=float(lines[k,t,0]),lower_dual=float(lines[k,t,1]),
                            price_G1=float(point.price[nn.gen_bus_idx(0),t]),price_G5=float(point.price[nn.gen_bus_idx(4),t])))
                stage.save(name,dict(settlement=row,faces=local_faces,activity=active),arrays)
                rows.append(row);faces.extend(local_faces);activities.extend(active)
    effects=[]
    for j in [1,2]:
        get=lambda s,k:next(x for x in rows if x['scenario']==s and x['bid_index']==k)
        original=get('original',j)['true_profit_usd']-get('original',0)['true_profit_usd']
        relaxed=get('relaxed',j)['true_profit_usd']-get('relaxed',0)['true_profit_usd']
        effects.append(dict(bid_index=j,delta=plan['deltas'][j],original_extra_profit_usd=original,
            relaxed_extra_profit_usd=relaxed,change_in_extra_profit_usd=relaxed-original))
    status='passed' if all(f['status']=='optimal' for f in faces) else 'partial_price_face'
    summary=dict(status=status,protocol=plan,settlements=rows,dual_face_checks=faces,
        effects=effects,old_oracle_rejected=True,
        scope='Three fixed bids, one chosen constraint; coherent directional dual-face checks do not bound all profits')
    write(stage.out/'summary.json',summary)
    for filename,data in [('line_activity.csv',activities),('treatment_effect.csv',effects)]:
        if data:
            with (stage.out/filename).open('w',newline='',encoding='utf-8') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    stage.finish(status)
    return summary
