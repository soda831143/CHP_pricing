"""Bounded tests of substitution thresholds and a certified profit-path ledger."""
import argparse
import csv
from dataclasses import replace

import numpy as np

from engine import ScheduleRunMILP
from benchmarks.unit_self_schedule import dispatch_cost
from price_vulnerability.scalar_markup import apply_generator_adder
from price_vulnerability.persistent_chp import PersistentCHP
from price_vulnerability.model_identity import model_identity
from price_vulnerability.oracle_compression import query_compact
from run_initial_condition_audit import schedule_residuals
from run_profit_range import physical_regions
from strategic_market_simulation.profit_sweep import _settle_target
from mechanism_study import runtime
from mechanism_study.runtime import Stage, ROOT, read, write, digest
from mechanism_study.run_study import load_inputs, PHYSICAL, ORACLE
from mechanism_study.profit_identity import hourly_cost, ledger
from mechanism_study.linear_audit import primal_lp_audit

OUTPUT = ROOT/'results/mechanism_20261019'


def table(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def crossing(cost_a, cost_b, exposure_a, exposure_b):
    values=np.asarray([cost_a,cost_b,exposure_a,exposure_b],dtype=float)
    if not np.isfinite(values).all() or abs(exposure_a-exposure_b)<1e-8:
        raise ValueError('Need finite, distinct candidate exposures')
    return float((cost_b-cost_a)/(exposure_a-exposure_b))


def candidate_lines(gens, plans):
    rows=[]
    for label,(p,u) in plans.items():
        unit_cost=[float(hourly_cost(g,p[i],u[i]).sum()) for i,g in enumerate(gens)]
        previous=np.r_[gens[4].initial_status,u[4,:-1]]
        rows.append(dict(plan=label,cost=sum(unit_cost),unit_cost=unit_cost,
            exposure=float(np.sum(p[0]-gens[0].P_min*u[0])),
            g5_online_hours=float(u[4].sum()),g5_starts=float(np.maximum(u[4]-previous,0).sum())))
    return rows


def declared_plan():
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    a,b=candidate_lines(gens,plans)
    predicted=crossing(a['cost'],b['cost'],a['exposure'],b['exposure'])
    assert abs(predicted-critical)<1e-8
    return dict(date='2026-10-19',original_critical=critical,candidate_lines=[a,b],
        predicted_critical=predicted,
        predicted_slope=(b['g5_online_hours']-a['g5_online_hours'])/(a['exposure']-b['exposure']),
        training_epsilons_usd_per_online_hour=[-1.,0.,1.],held_out_epsilon=5.,
        threshold_half_width=.001,uc_cost_tolerance_usd=1e-5,
        selector='Cold COPT dual simplex, single thread, seed 20261018; fixed separately for every changed model',
        inputs={str(p.relative_to(ROOT)):digest(p) for p in
            (PHYSICAL/'profit_range.json',PHYSICAL/'physical_plans.npz',ORACLE/'compact.npz')},
        scope='Fixed original A/B candidates; third-plan domination is a recorded falsification, not an excuse to scan',
        path_budget_self_schedule=400,path_per_interval_budget=20,path_cost_tolerance_usd=1e-6,
        external_scope='Held-out economic perturbation, not an independent system or statistical validation')


def solve_uc(stage,name,gens,net,delta,plans):
    cached=stage.cached(name)
    if cached:
        with np.load(stage.out/(name+'.npz')) as z:return cached,z['p'],z['u']
    reported=apply_generator_adder(gens,0,delta)
    uc=ScheduleRunMILP(reported,net)
    p,u,value=stage.call('uc',name,lambda:uc.solve(require_optimal=True,mip_gap=0.))
    residual=schedule_residuals(gens,net,p,u)
    cost=sum(dispatch_cost(g,p[i],u[i]) for i,g in enumerate(reported))
    if abs(cost-value)>1e-6 or max(residual.values())>1e-7:
        raise ValueError('Fresh physical cost/feasibility audit failed')
    lines=candidate_lines(gens,plans)
    row=dict(delta=delta,value=value,lower_bound=uc.solve_info['lower_bound'],solver_info=uc.solve_info,
        residual=residual,candidate_gaps=[x['cost']+delta*x['exposure']-uc.solve_info['lower_bound'] for x in lines],
        selected_exposure=float(np.sum(p[0]-gens[0].P_min*u[0])),g5_online_hours=float(u[4].sum()))
    stage.save(name,row,dict(p=p,u=u))
    return row,p,u


def threshold_study(plan, *, held_out=False, resume=False):
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    epsilons=[plan['held_out_epsilon']] if held_out else plan['training_epsilons_usd_per_online_hour']
    stage=Stage('P2_held_out' if held_out else 'P0_threshold_io_recovery',budgets=dict(uc=4*len(epsilons),
        chp=2*len(epsilons),self_schedule=2*len(epsilons)),seconds=600.,resume=resume,plan=plan)
    rows=[]
    with stage.solvers():
        for epsilon in epsilons:
            changed=list(gens);changed[4]=replace(gens[4],cost_nl=gens[4].cost_nl+epsilon)
            a,b=candidate_lines(changed,plans)
            pred=crossing(a['cost'],b['cost'],a['exposure'],b['exposure'])
            outcomes={};profits={}
            for label,delta in [('baseline',0.),('left',pred-.001),('tie',pred),('right',pred+.001)]:
                name=f'epsilon{epsilon:g}_{label}'
                result,p,u=solve_uc(stage,name,changed,net,delta,plans)
                outcomes[label]=result
                if label not in ('baseline','left'):continue
                pricing_name=name+'_settlement'
                settled=stage.cached(pricing_name)
                if settled is None:
                    cp=PersistentCHP(changed,net,0)
                    point=stage.call('chp',name,lambda:cp.solve(delta))
                    audit,arrays=primal_lp_audit(cp)
                    ss=stage.call('self_schedule',name,lambda:_settle_target(changed[0],
                        apply_generator_adder(changed,0,delta)[0],point.price[net.gen_bus_idx(0)],p[0],u[0],mip_gap=0.))
                    if ss['self_schedule_gap_usd']>1e-6:raise ValueError('Uncertified self-schedule')
                    account=ledger(changed[0],p[0],u[0],point.price[net.gen_bus_idx(0)],delta,ss['best_reported_profit'])
                    settled=dict(**account,lp_audit=audit,self_schedule_upper_bound=ss['self_schedule_upper_bound'],
                        self_schedule_gap_usd=ss['self_schedule_gap_usd'],model_identity=model_identity(changed,net),
                        old_oracle_reused=False)
                    stage.save(pricing_name,settled,dict(**arrays,price=point.price,self_p=ss['self_output_mw'],self_u=ss['self_commitment']))
                profits[label]=settled['true_profit_usd']
            gaps=[outcomes['left']['candidate_gaps'][0],*outcomes['tie']['candidate_gaps'],outcomes['right']['candidate_gaps'][1]]
            supported=max(abs(x) for x in gaps)<=1e-5
            row=dict(epsilon=epsilon,predicted_critical=pred,predicted_shift=pred-critical,
                candidate_true_cost_difference=b['cost']-a['cost'],exposure_difference=a['exposure']-b['exposure'],
                online_hour_difference=b['g5_online_hours']-a['g5_online_hours'],startup_difference=b['g5_starts']-a['g5_starts'],
                max_candidate_gap_to_global_bound=max(abs(x) for x in gaps),
                supported=supported,truthful_profit=profits['baseline'],near_left_profit=profits['left'],
                near_left_extra_profit=profits['left']-profits['baseline'],outcomes=outcomes)
            rows.append(row)
            print(f'Threshold epsilon={epsilon:g}: predicted={pred:.12g}, supported={supported}, max gap={row["max_candidate_gap_to_global_bound"]:.3g}',flush=True)
    status='passed' if all(r['supported'] for r in rows) else 'candidate_prediction_falsified'
    summary=dict(status=status,protocol=plan,records=rows,
        scope='A/B common-plan optimality certified by endpoint global-bound chords only on the stated narrow neighborhoods')
    write(stage.out/'summary.json',summary)
    table(stage.out/'thresholds.csv',[{k:v for k,v in r.items() if k!='outcomes'} for r in rows])
    stage.finish(status)
    return summary


def path_study(plan, *, resume=False):
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    stage=Stage('P1_profit_path_io_recovery',budgets=dict(self_schedule=plan['path_budget_self_schedule']),
        seconds=600.,resume=resume,plan=plan)
    with np.load(PHYSICAL/'physical_plans.npz') as z:
        physical={float(d):(z['outputs'][i],z['commitments'][i]) for i,d in enumerate(z['deltas'])}
    solved={};pieces=[];jumps=[]
    pb=compact['price_boundaries'];price_path=compact['prices'][:,net.gen_bus_idx(0)]
    price_at=lambda d:query_compact(d,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1][net.gen_bus_idx(0)]
    def settle(delta):
        delta=float(delta)
        if delta in solved:return solved[delta]
        name='ss_'+float(delta).hex().replace('.','_').replace('+','p')
        item=stage.cached(name)
        if item is None:
            p,u=physical[report['physical_regions'][0]['witness_delta']]
            ss=stage.call('self_schedule',name,lambda:_settle_target(gens[0],apply_generator_adder(gens,0,delta)[0],price_at(delta),p[0],u[0],mip_gap=0.))
            if ss['self_schedule_gap_usd']>1e-6:raise ValueError('Uncertified path self-schedule')
            item=dict(delta=delta,best=ss['best_reported_profit'],upper=ss['self_schedule_upper_bound'],
                p=ss['self_output_mw'].tolist(),u=ss['self_commitment'].tolist(),
                true_cost=float(dispatch_cost(gens[0],ss['self_output_mw'],ss['self_commitment'])),
                exposure=float(np.sum(ss['self_output_mw']-gens[0].P_min*ss['self_commitment'])))
            stage.save(name,item,dict(p=ss['self_output_mw'],u=ss['self_commitment'],price=price_at(delta)))
        solved[delta]=item
        return item
    previous_exposure=None
    with stage.solvers():
        for j,joint in enumerate(report['joint_intervals']):
            a,b=joint['left'],min(joint['right'],critical)
            if a>=critical:break
            if not b>a:continue
            region=report['physical_regions'][joint['physical_region']]
            p,u=physical[region['witness_delta']]
            duc=float(np.sum(p[0]-gens[0].P_min*u[0]))
            k=min(max(int(np.searchsorted(pb,(a+b)/2))-1,0),len(pb)-2)
            slope=(price_path[k+1]-price_path[k])/(pb[k+1]-pb[k])
            intercept=price_path[k]-pb[k]*slope
            def negative_surplus(delta):
                ss=settle(delta)
                return dict(intercept=ss['true_cost']-float(intercept@ss['p']),
                    exposure=ss['exposure']-float(slope@ss['p']),lower_bound=-ss['upper'])
            points,regions=physical_regions(negative_surplus,a,b,max_solves=plan['path_per_interval_budget'],tolerance=plan['path_cost_tolerance_usd'])
            if not all(r['ready'] for r in regions):
                raise RuntimeError(f'Self-schedule envelope incomplete in joint interval {j}; no extrapolation')
            if previous_exposure is not None and abs(duc-previous_exposure)>1e-7:
                jumps.append(dict(delta=a,old_exposure=previous_exposure,new_exposure=duc,
                    profit_jump=a*(duc-previous_exposure),price_jump=0.))
            previous_exposure=duc
            for r in regions:
                ss=settle(r['witness_delta']);width=r['right']-r['left']
                price=float(np.asarray(ss['p'])@slope)*width
                exposure=(duc-ss['exposure'])*width
                direct=settle(r['right'])['best']-settle(r['left'])['best']+width*duc
                pieces.append(dict(joint_interval=j,left=r['left'],right=r['right'],
                    physical_region=joint['physical_region'],self_witness_delta=r['witness_delta'],
                    common_ss_gap_usd=r['common_plan_gap_usd'],physical_gap_usd=region['common_plan_gap_usd'],
                    price_channel_usd=price,exposure_channel_usd=exposure,direct_change_usd=direct,
                    residual_usd=price+exposure-direct,D_UC=duc,D_SS=ss['exposure']))
            print(f'Profit path {j}: [{a:.9g}, {b:.9g}], SS pieces={len(regions)}',flush=True)
    winner=report['maximizing_candidate']
    endpoint_jump=critical*(winner['physical_exposure_mwh']-previous_exposure)
    if abs(endpoint_jump)>1e-7:
        jumps.append(dict(delta=critical,old_exposure=previous_exposure,new_exposure=winner['physical_exposure_mwh'],profit_jump=endpoint_jump,price_jump=0.))
    sums={name:sum(r[name] for r in pieces) for name in ('price_channel_usd','exposure_channel_usd')}
    sums['physical_jump_usd']=sum(r['profit_jump'] for r in jumps)
    actual=settle(critical)['best']+critical*winner['physical_exposure_mwh']-settle(0.)['best']
    residual=sum(sums.values())-actual
    if abs(residual)>1e-3 or max(abs(r['residual_usd']) for r in pieces)>1e-4:
        raise ValueError('Complete profit-path reconciliation failed')
    summary=dict(status='passed',protocol=plan,channels=sums,total_extra_profit=actual,
        reconciliation_residual=residual,max_piece_residual=max(abs(r['residual_usd']) for r in pieces),
        interval_count=len({r['joint_interval'] for r in pieces}),self_schedule_piece_count=len(pieces),
        self_schedule_solves=len(solved),physical_jumps=jumps,
        scope='Accounting along the archived continuous selected-price path and stated UC rule; channel integrals are not independent causal effects')
    write(stage.out/'summary.json',summary);table(stage.out/'continuous_channels.csv',pieces)
    if jumps:table(stage.out/'physical_jumps.csv',jumps)
    stage.finish()
    return summary


def network_envelope_audit():
    from mechanism_study.constraint_attribution import treatment
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    old=ROOT/'results/mechanism_20261018/followup/E4_causal_recovery_02'
    intervention=read(old/'intervention_before_treatment.json')['intervention']
    _,relaxed=treatment(gens,net,intervention)
    lines=candidate_lines(gens,plans);rows=[]
    for j in range(3):
        record=read(old/f'relaxed_bid{j}.json')['settlement']
        with np.load(old/f'relaxed_bid{j}.npz') as z:
            delta=record['delta'];p,u=z['p'],z['u']
            optimum=sum(dispatch_cost(g,p[i],u[i]) for i,g in enumerate(apply_generator_adder(gens,0,delta)))
            treated_flow=relaxed.PTDF_Gen@p-relaxed.PTDF@relaxed.demand
        if abs(optimum-record['uc_global_bound_usd'])>1e-5:
            raise ValueError('Archived treated plan lacks its global UC bound')
        for line,(label,(p0,u0)) in zip(lines,plans.items()):
            residual=schedule_residuals(gens,relaxed,p0,u0)
            flow=relaxed.PTDF_Gen@p0-relaxed.PTDF@relaxed.demand
            rows.append(dict(bid_index=j,delta=delta,original_plan=label,
                original_plan_feasible=max(residual.values())<1e-7,
                candidate_reported_cost=line['cost']+delta*line['exposure'],treated_optimal_cost=optimum,
                excess_over_treated_optimum=line['cost']+delta*line['exposure']-optimum,
                original_plan_line30_max_abs_flow=float(np.max(abs(flow[29]))),
                treated_line30_limit=float(relaxed.F_max[29]),
                treated_uc_global_bound=record['uc_global_bound_usd'],
                treated_plan_line30_max_abs_flow=float(np.max(abs(treated_flow[29]))),
                treated_plan_violates_original_limit=bool(np.max(abs(treated_flow[29]))>net.F_max[29]+1e-7),
                candidate_cost_intercept=line['cost'],candidate_exposure=line['exposure']))
    OUTPUT.mkdir(parents=True,exist_ok=True)
    table(OUTPUT/'network_lower_envelope.csv',rows)
    write(OUTPUT/'network_lower_envelope.json',dict(records=rows,
        scope='Existing fixed A/B cost lines and exposures are unchanged by line relaxation; test feasibility and loss of optimality against archived rebuilt UC, not a new global map'))
    return rows


def startup_control():
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    changed=list(gens);changed[4]=replace(gens[4],cost_su=gens[4].cost_su+50.)
    a,b=candidate_lines(changed,plans)
    pred=crossing(a['cost'],b['cost'],a['exposure'],b['exposure'])
    plan=dict(treatment='G5 true startup cost +50 USD/start, not a strategic startup bid',
        expected_critical=critical,predicted_from_fixed_cost_lines=pred,
        reason='A and B each start G5 once; the pairwise relative cost is unchanged',
        deltas=[critical-.001,critical,critical+.001],scope='Negative control of the physical threshold only; no new price/profit claim')
    destination=OUTPUT/'startup_control_protocol_before_run.json'
    if destination.exists():raise ValueError('Preserve the existing startup control')
    write(destination,plan)
    stage=Stage('P2_startup_cost_control',budgets=dict(uc=3),seconds=180.,plan=plan)
    rows=[]
    with stage.solvers():
        for label,d in zip(('left','tie','right'),plan['deltas']):
            row,p,u=solve_uc(stage,label,changed,net,d,plans);rows.append(row)
    gap=max(abs(v) for v in [rows[0]['candidate_gaps'][0],*rows[1]['candidate_gaps'],rows[2]['candidate_gaps'][1]])
    status='passed' if gap<1e-5 else 'candidate_prediction_falsified'
    result=dict(status=status,protocol=plan,max_candidate_gap=gap,records=rows)
    write(stage.out/'summary.json',result);stage.finish(status);print(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['plan','threshold','path','held-out','network','startup-control'])
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();runtime.OUTPUT=OUTPUT
    plan=declared_plan();OUTPUT.mkdir(parents=True,exist_ok=True)
    destination=OUTPUT/'protocol_before_predictions.json'
    if destination.exists():
        if read(destination)!=plan:raise ValueError('Protocol changed; preserve this study and choose a new output directory')
    else:write(destination,plan)
    if args.stage=='threshold':threshold_study(plan,resume=args.resume)
    elif args.stage=='path':path_study(plan,resume=args.resume)
    elif args.stage=='held-out':threshold_study(plan,held_out=True,resume=args.resume)
    elif args.stage=='network':network_envelope_audit()
    elif args.stage=='startup-control':startup_control()
    else:print(plan)


if __name__=='__main__':main()
