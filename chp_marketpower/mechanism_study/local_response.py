"""E2: certified common-self-schedule local profit channels, not fitted curves."""
from types import SimpleNamespace
import csv

import numpy as np

from engine import ScheduleRunMILP
from price_vulnerability.persistent_chp import PersistentCHP
from price_vulnerability.oracle_compression import query_compact
from price_vulnerability.scalar_markup import apply_generator_adder
from strategic_market_simulation.profit_sweep import _settle_target
from run_initial_condition_audit import schedule_residuals
from mechanism_study.run_study import load_inputs, selected_dual_audit, ORACLE
from mechanism_study.profit_identity import ledger
from mechanism_study.runtime import Stage, write
from benchmarks.unit_self_schedule import dispatch_cost


def price_segment(compact, delta, side='right'):
    b = compact['price_boundaries']
    k = min(int(np.searchsorted(b,delta,side=side))-1,len(b)-2)
    k = max(k,0)
    return k,(compact['prices'][k+1]-compact['prices'][k])/(b[k+1]-b[k])


def protocol(compact, report, critical):
    regions = report['physical_regions']
    first = regions[1]
    next_price = compact['price_boundaries'][compact['price_boundaries']>first['left']][0]
    queries = [('truthful_right',0.),('first_uc_response',(first['left']+min(first['right'],next_price))/2),
        ('critical_left',critical-.001),('critical_right',critical+.001),('rho40',.4*41.982),('rho45',.45*41.982)]
    result=[]
    for label,d in queries:
        region=next(r for r in regions if r['left']<=d<r['right'])
        k,slope=price_segment(compact,d)
        a=max(region['left'],float(compact['price_boundaries'][k]))
        b=min(region['right'],float(compact['price_boundaries'][k+1]))
        h=min(.001, (b-d)/10) if d==0 else min(.001,(d-a)/10,(b-d)/10)
        if h<1e-7:
            raise ValueError('Prespecified query too close to a structural boundary')
        result.append(dict(label=label,delta=d,step=h,joint_interval=[a,b],
            witness_delta=region['witness_delta'],price_segment=k,
            differences='forward_only' if d==0 else 'left_and_right',
            sample_deltas=[d,d+h,d+2*h] if d==0 else [d-h,d,d+h]))
    return result


def classify(price, exposure):
    threshold=1e-6
    if abs(price)<threshold and abs(exposure)<threshold:
        return 'near_zero'
    if price*exposure<0 and min(abs(price),abs(exposure))>.25*max(abs(price),abs(exposure)):
        return 'opposing_channels'
    if abs(price)>=2*abs(exposure):return 'price_dominated'
    if abs(exposure)>=2*abs(price):return 'exposure_dominated'
    return 'mixed'


def run(*,resume=False,seconds=600.,dry_run=False):
    gens,net,compact,report,critical,regions,plans=load_inputs()
    plan=protocol(compact,report,critical)
    if dry_run:
        return plan
    stage=Stage('E2_local',budgets=dict(uc=6,chp=6,self_schedule=18,auxiliary=0),
                seconds=seconds,resume=resume,plan=plan)
    with np.load(ORACLE/'oracle.npz') as rawfile:
        raw={k:rawfile[k].copy() for k in ('boundaries','price_ready','primals','objectives',
                 'eq_duals','ineq_duals','lower_duals','upper_duals','prices')}
    rows=[]
    with stage.solvers():
        for query in plan:
            name,d=query['label'],query['delta']
            cached=stage.cached(name)
            if cached:
                rows.append(cached);continue
            print(f'E2 {name}: delta={d:.12g}',flush=True)
            reported=apply_generator_adder(gens,0,d)
            uc=ScheduleRunMILP(reported,net)
            p,u,value=stage.call('uc',name,lambda:uc.solve(require_optimal=True,mip_gap=0.))
            residual=schedule_residuals(gens,net,p,u)
            with np.load(ORACLE.parent.parent/'targeted_study_20261016/30_G1_profit_0to50/physical_plans.npz') as saved:
                j=np.flatnonzero(saved['deltas']==query['witness_delta'])[0]
                p,u=saved['outputs'][j].copy(),saved['commitments'][j].copy()
            gap=sum(dispatch_cost(g,p[i],u[i]) for i,g in enumerate(reported))-uc.solve_info['lower_bound']
            if abs(gap)>1e-5 or max(schedule_residuals(gens,net,p,u).values())>1e-7:
                raise ValueError('Fresh UC bound does not support the fixed archived plan')
            chp=PersistentCHP(gens,net,0)
            direct=stage.call('chp',name,lambda:chp.solve(d))
            _,slope=price_segment(compact,d)
            samples=[];arrays=dict(physical_p=p,physical_u=u,price_slope=slope)
            for index,x in enumerate(query['sample_deltas']):
                v,price=query_compact(x,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])
                certificate,dual=selected_dual_audit(chp,raw,compact,x,
                    direct if x==d else SimpleNamespace(objective=chp.c0+x*chp.direction,value=v,price=price))
                if x!=d:certificate.pop('fresh_price_difference_usd_per_mwh')
                ss=stage.call('self_schedule',f'{name}_{index}',lambda x=x,price=price:
                    _settle_target(gens[0],apply_generator_adder(gens,0,x)[0],price[net.gen_bus_idx(0)],p[0],u[0],mip_gap=0.))
                account=ledger(gens[0],p[0],u[0],price[net.gen_bus_idx(0)],x,ss['best_reported_profit'])
                if abs(account['true_profit_usd']-ss['true_profit'])>1e-6 or ss['self_schedule_gap_usd']>1e-6:
                    raise ValueError('Direct local settlement or self-schedule bound failed')
                sample=dict(delta=x,self_best=ss['best_reported_profit'],self_bound=ss['self_schedule_upper_bound'],
                    self_exposure=float(np.sum(ss['self_output_mw']-gens[0].P_min*ss['self_commitment'])),
                    **account,selected_dual_audit=certificate)
                arrays[f'price_{index}']=price
                arrays[f'self_p_{index}']=ss['self_output_mw'];arrays[f'self_u_{index}']=ss['self_commitment']
                samples.append(sample)
            # A common optimal SS witness at both ends proves affine surplus between them,
            # including uniqueness of its objective slope at interior points despite dispatch ties.
            common=[]
            for i,sample in enumerate(samples):
                ss_p,ss_u=arrays[f'self_p_{i}'],arrays[f'self_u_{i}']
                true_cost=dispatch_cost(gens[0],ss_p,ss_u)
                gaps=[s['self_bound']-(arrays[f'price_{j}'][net.gen_bus_idx(0)]@ss_p-true_cost-s['delta']*sample['self_exposure'])
                      for j,s in enumerate(samples)]
                common.append(max(abs(v) for v in gaps))
            witness=int(np.argmin(common));ordinary=min(common)<=1e-6 and d>0
            derivatives=[]
            sides=[('right',0,1),('right_confirmation',1,2)] if d==0 else [('left',0,1),('right',1,2)]
            for side,i,j in sides:
                ds=samples[j]['delta']-samples[i]['delta']
                # If no common witness, retain direct one-sided secants and do not call them derivatives.
                si=witness if min(common)<=1e-6 else (i if side=='left' else j)
                pc=float(arrays[f'self_p_{si}']@slope[net.gen_bus_idx(0)])
                ec=float(samples[si]['exposure_mwh']-samples[si]['self_exposure'])
                actual=(samples[j]['true_profit_usd']-samples[i]['true_profit_usd'])/ds
                energy=(samples[j]['energy_revenue_usd']-samples[i]['energy_revenue_usd'])/ds
                loc=(samples[j]['loc_usd']-samples[i]['loc_usd'])/ds
                derivatives.append(dict(side=side,price_channel=pc,exposure_channel=ec,predicted=pc+ec,
                    finite_difference=actual,residual=actual-pc-ec,energy_derivative=energy,loc_derivative=loc,
                    energy_plus_loc_residual=energy+loc-actual,channel_class=classify(pc,ec)))
            passed=min(common)<=1e-6 and max(abs(r['residual']) for r in derivatives)<1e-4
            result=dict(**query,status='passed' if passed else 'unresolved_self_schedule_switch',
                derivative_kind='ordinary' if ordinary else 'right_domain_derivative' if passed else 'secants_only',
                common_ss_witness=witness,common_ss_endpoint_gap_usd=min(common),
                uc_global_info=uc.solve_info,archived_plan_cost_gap_usd=float(gap),fresh_uc_residuals=residual,
                samples=samples,derivatives=derivatives)
            stage.save(name,result,arrays);rows.append(result)
        records=[]
        for row in rows:
            for derivative in row['derivatives']:
                records.append(dict(query=row['label'],delta=row['delta'],rho=row['delta']/41.982,
                    derivative_kind=row['derivative_kind'],status=row['status'],
                    common_ss_gap_usd=row['common_ss_endpoint_gap_usd'],**derivative))
        with (stage.out/'profit_channels.csv').open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
        summary=dict(status='passed' if all(r['status']=='passed' for r in rows) else 'partial',
            queries=rows,max_channel_derivative_residual=max(abs(r['residual']) for r in records),
            scope='Only declared neighborhoods; no derivative through the physical jump; no fitted profit curve.')
        write(stage.out/'summary.json',summary)
        stage.finish(summary['status'])
    return summary
