"""E3: physical/CHP minimum required generation and unit-removal costs."""
import csv
from pathlib import Path

import numpy as np
from coptpy import COPT

from engine import load_case,ScheduleRunMILP
from price_vulnerability.persistent_chp import PersistentCHP
from price_vulnerability.model_identity import check_model_identity,model_identity
from price_vulnerability.oracle_compression import load_matched_compact,query_compact
from price_vulnerability.scalar_markup import apply_generator_adder
from run_initial_condition_audit import schedule_residuals
from mechanism_study.runtime import Stage,OUTPUT,ROOT,read,write
from mechanism_study.linear_audit import primal_lp_audit
from mechanism_study.profit_identity import ledger
from strategic_market_simulation.profit_sweep import _settle_target
from benchmarks.unit_self_schedule import dispatch_cost


def map_for(g):
    if g==0:return ROOT/'results/scope_study_20261016/30_bracket_repeat1'
    if g==1:return ROOT/'results/targeted_study_20261016/30_G2_bracket_0to50'
    candidates=[]
    for p in (ROOT/'results/dashboard_precompute').rglob('audit.json'):
        a=read(p);s=a.get('scope',{})
        if (s.get('case')=='30' and s.get('generator_index')==g and s.get('bid_hour_1based') is None
                and a.get('status')=='numerically_validated' and (p.parent/'compact.npz').exists()):
            candidates.append(p.parent)
    if not candidates:raise ValueError('No validated archived all-day map for comparison unit')
    return sorted(candidates)[0]


def cost_and_gap(gens,p,u,objective,lower):
    cost=float(sum(dispatch_cost(g,p[i],u[i]) for i,g in enumerate(gens)))
    if abs(cost-objective)>1e-6 or objective-lower>1e-5:
        raise ValueError('Removal objective / global bound reconstruction failed')
    return cost


def run(*,resume=False,seconds=600.,dry_run=False):
    if read(OUTPUT/'E2_local/summary.json')['status']!='passed':
        raise ValueError('E3 requires the E2 local-response gate')
    plan=dict(generators_0based=[0,4,1],hours_1based=[1,5,19],control_rule='Previously selected baseline least-online positive-incremental unit G2',
        finite_profit_rhos=[0.,.31451766098802286,.5],
        profit_scope='Same finite normalized bid set, chosen from existing G1 case before G2/G5 evaluation; not a global profit ranking',
        additional_budget_reason='Six G2/G5 full settlements are necessary to compare structural quantities with actual profitable opportunities; registered before their results')
    if dry_run:return plan
    stage=Stage('E3_pivotal',budgets=dict(uc=18,chp=16,self_schedule=6,auxiliary=0),
                seconds=seconds,resume=resume,plan=plan)
    gens,net=load_case('30','ptdf',24,3,'tight')
    base=read(ROOT/'results/mechanism_20261018/baseline.json')
    identity=read(ROOT/'results/mechanism_20261018/manifest.json')['model_identity']
    if model_identity(gens,net)['model_sha256']!=identity['model_sha256']:
        raise ValueError('Changed model cannot inherit baseline removal cost')
    baseline_cost=base['uc_solve_info']['objective']
    records=[];removals=[];economics=[]
    with stage.solvers():
        # An original cost solve compiles the exact original CHP feasible domain.
        chp=PersistentCHP(gens,net,0)
        stage.call('chp','construct_original_feasible_lp',lambda:chp.solve(0.))
        variables=chp.solver._model.getVars()
        for g in plan['generators_0based']:
            for hour in plan['hours_1based']:
                t=hour-1;name=f'mrg_G{g+1}_h{hour}'
                old=stage.cached(name)
                if old:records.append(old);continue
                print('E3 '+name,flush=True)
                uc=ScheduleRunMILP(gens,net)
                p,u,m_uc=stage.call('uc',name,lambda:uc.solve(require_optimal=True,mip_gap=0.,minimize_output=(g,t)))
                residual=schedule_residuals(gens,net,p,u)
                if max(residual.values())>1e-7 or abs(p[g,t]-m_uc)>1e-6:
                    raise ValueError('Physical minimum-output objective or feasible domain failed')
                objective=np.zeros(len(variables))
                dag=chp.solver.dags[g];idx=chp.solver._idx
                for k,iv in enumerate(dag.on_intervals):
                    if iv.a<=t<=iv.b:objective[idx.q(g,k,t-iv.a)]=1.
                model=chp.solver._model
                model.setInfo(COPT.Info.Obj,variables,objective.tolist())
                stage.call('chp',name,model.optimize)
                if model.getAttr(COPT.Attr.LpStatus)!=COPT.OPTIMAL:
                    raise RuntimeError('Convexified MRG did not solve optimally')
                lp_residual,arrays=primal_lp_audit(chp)
                m_chp=float(model.objval)
                if not -1e-7<=m_chp<=m_uc+1e-6:
                    raise ValueError('F_UC subset F_CHP inequality violated')
                result=dict(unit=gens[g].unit_id,hour=hour,mrg_uc_mw=float(m_uc),
                    mrg_chp_mw=m_chp,physical_lower_bound_mw=uc.solve_info['lower_bound'],
                    physical_gap_mw=float(m_uc-uc.solve_info['lower_bound']),physical_residuals=residual,
                    convex_kkt_residuals=lp_residual,status='passed')
                stage.save(name,result,dict(uc_p=p,uc_u=u,**arrays));records.append(result)
            name=f'removal_G{g+1}';old=stage.cached(name)
            if old:removals.append(old)
            else:
                uc=ScheduleRunMILP(gens,net)
                try:
                    p,u,value=stage.call('uc',name,lambda:uc.solve(require_optimal=True,mip_gap=0.,force_off=(g,)))
                    cost=cost_and_gap(gens,p,u,value,uc.solve_info['lower_bound'])
                    if max(schedule_residuals(gens,net,p,u).values())>1e-7 or np.max(abs(u[g]))>1e-7:
                        raise ValueError('Removal did not enforce whole-unit outage')
                    result=dict(unit=gens[g].unit_id,status='optimal',removed_true_cost_usd=cost,
                        lower_bound_usd=uc.solve_info['lower_bound'],baseline_cost_usd=baseline_cost,
                        kappa_usd=cost-baseline_cost,objective_gap_usd=value-uc.solve_info['lower_bound'])
                    stage.save(name,result,dict(p=p,u=u))
                except RuntimeError as error:
                    if getattr(uc,'_model',None) is None or uc._model.getAttr(COPT.Attr.MipStatus)!=COPT.INFEASIBLE:
                        raise
                    result=dict(unit=gens[g].unit_id,status='infeasible_pivotal',removed_true_cost_usd=None,
                        lower_bound_usd=None,baseline_cost_usd=baseline_cost,kappa_usd=None,error=str(error))
                    stage.save(name,result)
                removals.append(result)
        # Same finite bid set: never label these lower bounds as full-domain maxima.
        legacy=read(ROOT/'results/targeted_study_20261016/30_G1_profit_0to50/profit_range.json')
        for g in plan['generators_0based']:
            directory=map_for(g)
            audit,_,compact=load_matched_compact(directory)
            if not check_model_identity(directory,gens,net,audit):raise ValueError('Unbound economic comparison map')
            reference=gens[g].pwl_slopes[len(gens[g].pwl_slopes)//2]
            baseline_price=query_compact(0.,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1]
            for rho in plan['finite_profit_rhos']:
                d=rho*reference;name=f'profit_G{g+1}_rho{rho:.12g}';old=stage.cached(name)
                if old:economics.append(old);continue
                if g==0:
                    if rho==0:
                        row=dict(rho=rho,delta=d,true_profit_usd=legacy['baseline_true_profit'],
                                 source='inherited_verified_original_G1_full_domain')
                    else:
                        options=[x for x in legacy['candidate_bids'] if abs(x['delta']-d)<1e-10]
                        selected=max(options,key=lambda x:x['true_profit'])
                        row=dict(rho=rho,delta=d,true_profit_usd=selected['true_profit'],
                                 source='inherited_verified_original_G1_full_domain')
                    row.update(unit='G1',price_response_l2=None,reference_slope=reference)
                    stage.save(name,row);economics.append(row);continue
                print('E3 '+name,flush=True)
                reported=apply_generator_adder(gens,g,d)
                uc=ScheduleRunMILP(reported,net)
                p,u,v=stage.call('uc',name,lambda:uc.solve(require_optimal=True,mip_gap=0.))
                cp=PersistentCHP(gens,net,g)
                point=stage.call('chp',name,lambda:cp.solve(d))
                # Retain original archived selector, independently audit its full dual.
                from mechanism_study.run_study import selected_dual_audit
                with np.load(directory/'oracle.npz') as rawfile:
                    raw={k:rawfile[k] for k in ('boundaries','price_ready','primals','objectives','eq_duals',
                         'ineq_duals','lower_duals','upper_duals','prices')}
                    cert,dual=selected_dual_audit(cp,raw,compact,d,point)
                price=dual['price']
                ss=stage.call('self_schedule',name,lambda:_settle_target(gens[g],reported[g],price[net.gen_bus_idx(g)],p[g],u[g],mip_gap=0.))
                account=ledger(gens[g],p[g],u[g],price[net.gen_bus_idx(g)],d,ss['best_reported_profit'])
                if ss['self_schedule_gap_usd']>1e-6 or max(schedule_residuals(gens,net,p,u).values())>1e-7:
                    raise ValueError('Finite-bid comparison SS or physical feasibility failed')
                cost_and_gap(reported,p,u,v,uc.solve_info['lower_bound'])
                row=dict(unit=gens[g].unit_id,rho=rho,delta=d,reference_slope=reference,
                    price_response_l2=float(np.linalg.norm(price-baseline_price)),
                    source=str(directory.relative_to(ROOT)),selected_dual_audit=cert,**account)
                stage.save(name,row,dict(price=price,p=p,u=u,self_p=ss['self_output_mw'],self_u=ss['self_commitment']))
                economics.append(row)
        summary=dict(status='passed',mrg=records,removals=removals,economics=economics,
            model_identity=model_identity(gens,net),strategy_scope=plan['profit_scope'])
        write(stage.out/'summary.json',summary)
        with (stage.out/'structural_indispensability.csv').open('w',newline='',encoding='utf-8') as stream:
            rows=[{k:v for k,v in r.items() if not isinstance(v,dict)} for r in records]
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        stage.finish()
    return summary
