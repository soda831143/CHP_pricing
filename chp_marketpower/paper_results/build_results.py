"""Consolidate archived computations; optimize only missing G1 self schedules."""
import argparse
import csv
from pathlib import Path

import numpy as np

from engine import load_case
from benchmarks.unit_self_schedule import dispatch_cost
from price_vulnerability.scalar_markup import apply_generator_adder
from price_vulnerability.oracle_compression import query_compact
from run_profit_range import physical_regions
from strategic_market_simulation.profit_sweep import _settle_target
from mechanism_study import runtime
from mechanism_study.runtime import ROOT,Stage,read,write,digest
from mechanism_study.run_study import load_inputs,ORACLE,PHYSICAL
from mechanism_study.constraint_attribution import treatment
from mechanism_study.profit_identity import ledger
from paper_results.components import price_components,transmission_adjustment,interpolate

PAPER=ROOT/'paper_results'
DATA=PAPER/'source_data'
PREVIOUS=ROOT/'results/mechanism_20261019'


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))


def table(name,data):
    with (DATA/name).open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)


def main(resume=False):
    DATA.mkdir(parents=True,exist_ok=True)
    gens,net,compact,report,critical,adjacent,ab=load_inputs()
    inputs=set()
    def source(path):inputs.add(path);return read(path)
    for name in ('oracle.npz','compact.npz','model_identity.json'):inputs.add(ORACLE/name)
    for name in ('physical_plans.npz','profit_range.json'):inputs.add(PHYSICAL/name)
    old_tex=ROOT.parent.parent/'chp_5th.tex'
    text=old_tex.read_text(encoding='utf-8-sig')
    assert all(s in text for s in ('eq:chp-lmp','eq:total-settlement','subsec:three-dispatches'))
    inputs.add(old_tex)
    manifest=source(ROOT/'results/finalization_20261017/figures/input_manifest.json')
    unused_historical_changes=[]
    for relative,expected in manifest.items():
        path=ROOT/relative
        if 'hour1_0to50/' in relative or '/localized_economics/' in relative:
            if digest(path)!=expected:unused_historical_changes.append(relative)
            continue
        assert digest(path)==expected,relative
        inputs.add(path)
    economic=source(ROOT/'results/figure_study_20261016/economic_source_audit.json')
    assert economic['compact_sha256']==digest(ORACLE/'compact.npz')
    assert economic['profit_report_sha256']==digest(PHYSICAL/'profit_range.json')
    with np.load(PHYSICAL/'physical_plans.npz') as z:
        physical={float(d):(z['outputs'][j].copy(),z['commitments'][j].copy()) for j,d in enumerate(z['deltas'])}
    # The balance rows are the final T equalities; network inequalities are the final 2LT rows.
    with np.load(ORACLE/'oracle.npz') as z:
        boundaries=z['boundaries'].copy();assert np.all(z['price_ready'])
        energy,congestion,mu=price_components(z['eq_duals'],z['ineq_duals'],net.PTDF,net.T)
        nodal=z['prices'].copy()
    max_projection=float(np.max(abs(energy[:,None,:]+congestion-nodal)))
    assert max_projection<1e-7
    parts=lambda d,side='right':tuple(interpolate(boundaries,a,d,side) for a in (energy,congestion,mu))
    price=lambda d:query_compact(d,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1]
    compact_error=max(float(np.max(abs(price(float(d))-p))) for d,p in zip(boundaries,nodal))
    assert compact_error<1e-6
    reference=(np.flatnonzero(np.max(abs(net.PTDF),axis=0)<1e-12)+1).tolist()
    assert reference==[1] and net.gen_bus_idx(0)==0
    np.savez_compressed(DATA/'price_components.npz',delta=boundaries,lambda_E=energy,
        lambda_C=congestion,lambda_CHP=nodal,mu_positive=mu,PTDF=net.PTDF,capacity=net.F_max)
    price_rows=[]
    for j,d in enumerate(boundaries):
        for bus in [net.gen_bus_idx(g) for g in range(len(gens))]:
            for t in range(net.T):price_rows.append(dict(delta=float(d),bus=bus+1,hour=t+1,
                lambda_E=float(energy[j,t]),lambda_C=float(congestion[j,bus,t]),lambda_CHP=float(nodal[j,bus,t])))
    table('nodal_price_components.csv',price_rows)
    continuity=[]
    for d in boundaries[1:-1]:
        left,right=parts(float(d),'left'),parts(float(d),'right')
        continuity.append(dict(delta=float(d),max_energy_jump=float(np.max(abs(left[0]-right[0]))),
            max_congestion_jump=float(np.max(abs(left[1]-right[1]))),
            max_nodal_jump=float(np.max(abs(left[0][None,:]+left[1]-right[0][None,:]-right[1])))))
    table('price_boundary_continuity.csv',continuity)
    assert max(r['max_nodal_jump'] for r in continuity)<1e-7

    timing=[];prefixes=[]
    construction=rows(ROOT/'results/finalization_20261017/figures/table1_oracle_construction.csv')
    inputs.add(ROOT/'results/finalization_20261017/figures/table1_oracle_construction.csv')
    for label,path in [('30-G1',ROOT/'results/figure_study_20261016/trace_30_G1_q1000.json'),
            ('30-G2',ROOT/'results/figure_study_20261016/trace_30_G2_q1000.json'),
            ('118-G11',ROOT/'results/presentation_revision_20261016/trace_118_G11_q200.json')]:
        trace=source(path);direct=np.array(trace['same_model_cumulative_seconds']);lookup=np.array(trace['oracle_cumulative_online_seconds'])
        fixed=sum(trace[k] for k in ('oracle_offline_seconds_prior_run','postprocessing_seconds','oracle_file_load_seconds'))
        assert len(direct)==trace['n_queries'] and direct[-1]==trace['same_model_reoptimization_batch_seconds']
        assert np.all(np.diff(direct)>=0) and np.all(np.diff(lookup)>=0)
        q=np.arange(1,len(direct)+1);hits=np.flatnonzero(direct>=fixed+lookup)
        c=next(c for c in construction if c['instance']==label)
        uc_count=joint_count=candidate_count='not assessed'
        if label=='30-G1':uc_count=len(report['physical_regions']);joint_count=len(report['joint_intervals']);candidate_count=len(report['candidate_bids'])
        elif label=='30-G2':
            p=source(ROOT/'results/dashboard_uc_regions/30-G2-all/physical_regions.json')
            assert all(r['ready'] for r in p['physical_regions']);uc_count=len(p['physical_regions'])
        timing.append(dict(instance=label,price_intervals=int(c['selected_price_segments']),value_intervals=int(c['value_intervals']),
            lp_variables=int(c['lp_variables']),lp_rows=int(c['lp_rows']),chp_construction_solves=int(c['chp_solves']),
            common_UC_regions=uc_count,joint_regions=joint_count,profit_candidates=candidate_count,
            queries=len(direct),offline_seconds=trace['oracle_offline_seconds_prior_run'],postprocessing_seconds=trace['postprocessing_seconds'],
            load_seconds=trace['oracle_file_load_seconds'],online_seconds=float(lookup[-1]),
            direct_seconds=float(direct[-1]),parametric_total_seconds=float(fixed+lookup[-1]),
            direct_over_parametric=float(direct[-1]/(fixed+lookup[-1])),first_amortized_query=int(hits[0]+1) if len(hits) else 'not reached'))
        prefixes.extend(dict(instance=label,queries=int(n),delta=float(d),direct_seconds=float(t),
            parametric_seconds=float(fixed+o)) for n,d,t,o in zip(q,trace['query_deltas'],direct,lookup))
    table('table_I_computation.csv',timing);table('fig1_measured_query_prefixes.csv',prefixes)

    archived=rows(ROOT/'results/figure_study_20261016/generator_settlements.csv')
    inputs.add(ROOT/'results/figure_study_20261016/generator_settlements.csv')
    winner=report['maximizing_candidate'];table_ii=[];settlement_checks=[]
    for state,d,plan_delta in [('truthful',0.,0.),('best_offer',critical,winner['physical_plan_delta'])]:
        p,u=physical[plan_delta];e,c,m=parts(d);offered_cost=0.;uplift_total=0.
        selected=e[None,:]+c
        for g,gen in enumerate(gens):
            old=economic['baseline'][g] if state=='truthful' else next(r for r in archived if int(r['generator_index'])==g and float(r['delta'])==d and int(r['physical_region'])==winner['physical_region'])
            acc=ledger(gen,p[g],u[g],selected[net.gen_bus_idx(g)],d if g==0 else 0.,float(old['best_reported_surplus']))
            for key,oldkey in [('energy_revenue_usd','energy_revenue'),('loc_usd','reported_uplift'),('true_cost_usd','true_cost'),('true_profit_usd','true_profit')]:
                assert abs(acc[key]-float(old[oldkey]))<1e-5,(state,g,key)
            row=dict(state=state,unit=f'G{g+1}',delta=d,Q=acc['exposure_mwh'],generation_mwh=acc['generation_mwh'],
                R=acc['energy_revenue_usd'],R_E=float(e@p[g]),R_C=float(c[net.gen_bus_idx(g)]@p[g]),
                U=acc['loc_usd'],C=acc['true_cost_usd'],Pi=acc['true_profit_usd'])
            table_ii.append(row);offered_cost+=acc['reported_cost_usd'];uplift_total+=row['U']
        flow=net.PTDF_Gen@p-net.PTDF@net.demand;tx=transmission_adjustment(m,net.F_max,flow)
        chp_value=query_compact(d,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[0]
        residual=uplift_total+tx-offered_cost+chp_value
        assert abs(residual)<1e-5
        settlement_checks.append(dict(state=state,delta=d,total_uplift=uplift_total,transmission_adjustment=tx,
            offered_UC_cost=offered_cost,offered_CHP_cost=chp_value,network_identity_residual=residual))
    table('absolute_generator_settlements.csv',table_ii)
    changes=[]
    for g in range(len(gens)):
        base,best=table_ii[g],table_ii[len(gens)+g]
        changes.append(dict(unit=base['unit'],delta_R=best['R']-base['R'],delta_U=best['U']-base['U'],
            delta_C=best['C']-base['C'],delta_Pi=best['Pi']-base['Pi'],delta_R_E=best['R_E']-base['R_E'],delta_R_C=best['R_C']-base['R_C']))
    table('table_II_settlement_changes.csv',changes);table('network_settlement_identity.csv',settlement_checks)

    # Reuse the original 38 witnesses and their exact chosen plans on the profitable path.
    prior=PREVIOUS/'P1_profit_path_io_recovery';prior_manifest=source(prior/'manifest.json')
    cache={}
    for name,entry in prior_manifest['jobs'].items():
        path=prior/(name+'.json');assert digest(path)==entry['json_sha256'];inputs.add(path)
        item=read(path);cache[item['delta']]=item
    old_pieces=rows(prior/'continuous_channels.csv');inputs.add(prior/'continuous_channels.csv')
    runtime.OUTPUT=PAPER/'supplement'
    stage=Stage('missing_self_schedules',budgets=dict(self_schedule=150),seconds=600.,resume=resume,
        plan=dict(reason='Only missing full-range unit response witnesses for certified profit/uplift curves',
            source_report=digest(PHYSICAL/'profit_range.json'),source_map=digest(ORACLE/'compact.npz'),code=digest(Path(__file__))))
    initial_cache=len(cache)
    def ss_at(d):
        d=float(d)
        if d in cache:return cache[d]
        name='ss_'+d.hex().replace('.','_').replace('+','p');item=stage.cached(name)
        if item is None:
            p,u=physical[0.]
            ss=stage.call('self_schedule',name,lambda:_settle_target(gens[0],apply_generator_adder(gens,0,d)[0],price(d)[net.gen_bus_idx(0)],p[0],u[0],mip_gap=0.))
            assert ss['self_schedule_gap_usd']<1e-6
            item=dict(delta=d,best=ss['best_reported_profit'],upper=ss['self_schedule_upper_bound'],
                p=ss['self_output_mw'].tolist(),u=ss['self_commitment'].tolist(),
                true_cost=float(dispatch_cost(gens[0],ss['self_output_mw'],ss['self_commitment'])),
                exposure=float(np.sum(ss['self_output_mw']-gens[0].P_min*ss['self_commitment'])))
            stage.save(name,item,dict(p=ss['self_output_mw'],u=ss['self_commitment']))
        cache[d]=item;return item
    curves=[];full_pieces=[];base_profit=float(economic['baseline'][0]['true_profit'])
    with stage.solvers():
        for j,joint in enumerate(report['joint_intervals']):
            a,b=joint['left'],joint['right'];region=report['physical_regions'][joint['physical_region']]
            p,u=physical[region['witness_delta']];Q=float(np.sum(p[0]-gens[0].P_min*u[0]))
            k=max(0,min(int(np.searchsorted(compact['price_boundaries'],(a+b)/2))-1,len(compact['prices'])-2))
            b0,b1=compact['price_boundaries'][k:k+2]
            slope=(compact['prices'][k+1,net.gen_bus_idx(0)]-compact['prices'][k,net.gen_bus_idx(0)])/(b1-b0)
            intercept=compact['prices'][k,net.gen_bus_idx(0)]-b0*slope
            existing=[r for r in old_pieces if int(r['joint_interval'])==j]
            if existing:
                regions=[dict(left=float(r['left']),right=float(r['right']),witness_delta=float(r['self_witness_delta']),common_plan_gap_usd=float(r['common_ss_gap_usd'])) for r in existing]
            else:
                def solve(d):
                    item=ss_at(d)
                    return dict(intercept=item['true_cost']-float(intercept@item['p']),exposure=item['exposure']-float(slope@item['p']),lower_bound=-item['upper'])
                _,regions=physical_regions(solve,a,b,max_solves=20,tolerance=1e-6)
                if not all(r['ready'] for r in regions):raise RuntimeError(f'Incomplete full-range response interval {j}')
            for r in regions:
                item=ss_at(r['witness_delta']);piece=len(full_pieces)
                for d in (r['left'],r['right']):
                    endpoint=ss_at(d);value=float(price(d)[net.gen_bus_idx(0)]@item['p']-item['true_cost']-d*item['exposure'])
                    assert abs(value-endpoint['upper'])<1e-6
                    account=ledger(gens[0],p[0],u[0],price(d)[net.gen_bus_idx(0)],d,value)
                    curves.append(dict(piece=piece,joint_interval=j,physical_region=joint['physical_region'],delta=d,
                        Q_UC=Q,Q_SS=item['exposure'],R=account['energy_revenue_usd'],U=account['loc_usd'],C=account['true_cost_usd'],
                        Pi=account['true_profit_usd'],delta_Pi=account['true_profit_usd']-base_profit))
                full_pieces.append(dict(piece=piece,joint_interval=j,physical_region=joint['physical_region'],
                    left=r['left'],right=r['right'],self_witness_delta=r['witness_delta'],common_SS_gap=r['common_plan_gap_usd']))
    stage.finish();table('fig3_profit_uplift_curves.csv',curves);table('certified_full_range_pieces.csv',full_pieces)
    # Refine at full-dual boundaries even where compact nodal-price segments were merged.
    hours=np.zeros((net.T,2));spread_lines=np.zeros((net.N_line,net.T));component_rows=[]
    for r in full_pieces:
        if r['left']>=critical:continue
        a,b=r['left'],min(r['right'],critical);item=ss_at(r['self_witness_delta']);weight=np.array(item['p'])
        cuts=np.unique(np.r_[a,b,boundaries[(boundaries>a)&(boundaries<b)]])
        for lo,hi in zip(cuts[:-1],cuts[1:]):
            ea,ca,ma=parts(float(lo));eb,cb,mb=parts(float(hi))
            en=weight*(eb-ea);co=weight*(cb[net.gen_bus_idx(0)]-ca[net.gen_bus_idx(0)])
            hours[:,0]+=en;hours[:,1]+=co
            ds=(mb[...,0]-mb[...,1])-(ma[...,0]-ma[...,1])
            spread_lines+=-(net.PTDF[:,net.gen_bus_idx(0)]-net.PTDF[:,net.gen_bus_idx(4)])[:,None]*ds*weight
            component_rows.append(dict(left=float(lo),right=float(hi),energy_effect=float(en.sum()),congestion_effect=float(co.sum())))
    table('price_effect_subintervals.csv',component_rows)
    table('price_effect_by_hour.csv',[dict(hour=t+1,system_load_mw=float(net.sys_demand[t]),energy_effect=float(v[0]),congestion_effect=float(v[1]),total_price_effect=float(v.sum())) for t,v in enumerate(hours)])
    table('line_effect_on_G1_G5_spread.csv',[dict(line=l+1,hour=t+1,weighted_price_spread_effect=float(spread_lines[l,t]),
        note='G1 SS weights applied to G1-G5 price spread; not a G5 profit or G1 congestion-profit allocation') for l in range(net.N_line) for t in range(net.T)])
    path=source(PREVIOUS/'P1_profit_path_io_recovery/summary.json')
    assert abs(hours.sum()-path['channels']['price_channel_usd'])<1e-5

    counter=ROOT/'results/mechanism_20261018/followup/E4_causal_recovery_02'
    intervention=source(counter/'intervention_before_treatment.json')['intervention']
    _,relaxed=treatment(gens,net,intervention);network_rows=[];network_prices=[];line_rows=[]
    for scenario,nn in [('original',net),('relaxed',relaxed)]:
        for bid in range(3):
            path0=counter/f'{scenario}_bid{bid}.json';record=source(path0)['settlement'];inputs.add(counter/f'{scenario}_bid{bid}.npz')
            with np.load(counter/f'{scenario}_bid{bid}.npz') as z:
                e,c,m=price_components(z['eq_dual'],z['ineq_dual'],nn.PTDF,nn.T)
                assert np.max(abs(e[None,:]+c-z['price']))<1e-7
                p,u=z['p'],z['u'];flow=nn.PTDF_Gen@p-nn.PTDF@nn.demand;lp_flow=z['chp_flows']
            network_rows.append(dict(scenario=scenario,bid=bid,delta=record['delta'],generation_mwh=record['generation_mwh'],
                R=record['energy_revenue_usd'],R_E=float(e@p[0]),R_C=float(c[nn.gen_bus_idx(0)]@p[0]),
                U=record['loc_usd'],C=record['true_cost_usd'],Pi=record['true_profit_usd'],
                delta_Pi=record['true_profit_usd']-read(counter/f'{scenario}_bid0.json')['settlement']['true_profit_usd'],
                lambda_E_h1=float(e[0]),lambda_E_h19=float(e[18]),lambda_C_G1_h19=float(c[nn.gen_bus_idx(0),18]),lambda_C_G5_h19=float(c[nn.gen_bus_idx(4),18]),
                line30_UC_max_abs_flow=float(np.max(abs(flow[29]))),line30_CHP_max_abs_flow=float(np.max(abs(lp_flow[29]))),line30_max_mu=float(np.max(m[29]))))
            for t in range(net.T):
                network_prices.append(dict(scenario=scenario,bid=bid,delta=record['delta'],hour=t+1,lambda_E=float(e[t]),
                    lambda_C_G1=float(c[nn.gen_bus_idx(0),t]),lambda_C_G5=float(c[nn.gen_bus_idx(4),t]),
                    lambda_CHP_G1=float(e[t]+c[nn.gen_bus_idx(0),t]),lambda_CHP_G5=float(e[t]+c[nn.gen_bus_idx(4),t]),
                    cleared_G1=float(p[0,t]),cleared_G5=float(p[4,t])))
                line_rows.append(dict(scenario=scenario,bid=bid,hour=t+1,line=30,capacity=float(nn.F_max[29]),
                    UC_flow=float(flow[29,t]),CHP_flow=float(lp_flow[29,t]),CHP_mu_plus=float(m[29,t,0]),CHP_mu_minus=float(m[29,t,1])))
    table('network_counterfactual_settlements.csv',network_rows);table('network_counterfactual_hourly_prices.csv',network_prices);table('network_pricing_duals_vs_physical_flows.csv',line_rows)
    source(PREVIOUS/'P0_threshold_io_recovery/summary.json');source(PREVIOUS/'P2_held_out/summary.json');source(PREVIOUS/'P2_startup_cost_control/summary.json')
    source(PREVIOUS/'network_lower_envelope.json')
    for case in ('P0_threshold_io_recovery','P2_held_out'):
        inputs.add(PREVIOUS/case/'thresholds.csv')
    # An algebraic re-reference is a sensitivity check, not a second selected-price model.
    shift=0.
    for r in full_pieces:
        if r['left']>=critical:continue
        weight=np.array(ss_at(r['self_witness_delta'])['p']);a,b=r['left'],min(r['right'],critical)
        shift+=float(weight@(parts(b)[1][net.gen_bus_idx(4)]-parts(a)[1][net.gen_bus_idx(4)]))
    summary=dict(status='passed',reference_bus=reference[0],G1_bus=net.gen_bus_idx(0)+1,G5_bus=net.gen_bus_idx(4)+1,
        price_projection_max_error=max_projection,compact_price_max_error=compact_error,max_selected_price_jump=max(r['max_nodal_jump'] for r in continuity),
        price_effect=dict(energy=float(hours[:,0].sum()),congestion=float(hours[:,1].sum()),total=float(hours.sum())),
        reference_sensitivity=dict(algebraic_reference_bus=net.gen_bus_idx(4)+1,energy=float(hours[:,0].sum()+shift),
            congestion=float(hours[:,1].sum()-shift),total=float(hours.sum()),scope='Same nodal prices and SS, algebraic reference change only'),
        path=path['channels'],path_total_extra_profit=path['total_extra_profit'],timing=timing,
        reused_SS_witnesses=initial_cache,new_SS_solves=len(stage.state['calls']),full_range_SS_pieces=len(full_pieces),
        six_unit_table=changes,network=network_rows,old_tex=str(old_tex),old_tex_sha256=digest(old_tex),
        stop_conditions=dict(computational_evidence=True,energy_congestion_profit_reconciliation=True,physical_network_mechanism=True),
        unused_historical_source_changes=unused_historical_changes,
        statement='Energy/congestion accounting is reference-dependent; nodal prices and profits are invariant. No new system UC, CHP or timing.')
    write(PAPER/'analysis_summary.json',summary)
    write(PAPER/'input_manifest.json',{str(p):digest(p) for p in sorted(inputs)})
    print(summary['price_effect']);print('New SS solves:',summary['new_SS_solves'],'pieces:',len(full_pieces))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume',action='store_true')
    main(parser.parse_args().resume)
