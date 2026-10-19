"""Independent saved-witness accounting and hash audit; no optimization."""
from dataclasses import replace
import re

import numpy as np

from engine import SingleNodeNetwork
from benchmarks.unit_self_schedule import dispatch_cost
from price_vulnerability.scalar_markup import apply_generator_adder
from price_vulnerability.oracle_compression import query_compact
from run_initial_condition_audit import schedule_residuals
from mechanism_study.run_study import load_inputs, PHYSICAL
from mechanism_study.runtime import ROOT, read, write, digest
from mechanism_study.profit_identity import ledger
from mechanism_study.predictive_mechanism import OUTPUT


def ss_check(gen,p,u,price,delta,best,upper):
    assert max(schedule_residuals([gen],SingleNodeNetwork(np.asarray(p)),np.asarray(p)[None,:],np.asarray(u)[None,:]).values())<1e-7
    d=float(np.sum(p-gen.P_min*np.asarray(u)))
    surplus=float(np.asarray(price)@p-dispatch_cost(gen,p,u)-delta*d)
    assert abs(surplus-best)<1e-6
    assert abs(upper-best)<1e-6


def main():
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    protocol=read(OUTPUT/'protocol_before_predictions.json')
    assert all(digest(ROOT/p)==sha for p,sha in protocol['inputs'].items())
    files=jobs=0
    for name in ('P0_threshold_io_recovery','P1_profit_path_io_recovery','P2_held_out','P2_startup_cost_control'):
        stage=OUTPUT/name;manifest=read(stage/'manifest.json');assert manifest['status']=='passed'
        for job,entry in manifest['jobs'].items():
            for ext,key in (('.json','json_sha256'),('.npz','npz_sha256')):
                assert digest(stage/(job+ext))==entry[key];files+=1
            data=read(stage/(job+'.json'));jobs+=1
            with np.load(stage/(job+'.npz')) as z:
                if job.startswith('ss_'):
                    ss_check(gens[0],z['p'],z['u'],z['price'],data['delta'],data['best'],data['upper'])
                    price=query_compact(data['delta'],*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1][net.gen_bus_idx(0)]
                    assert np.max(abs(z['price']-price))<1e-9
                    assert np.max(abs(z['p']-data['p']))<1e-9 and np.max(abs(z['u']-data['u']))<1e-9
                    continue
                changed=list(gens)
                if name=='P2_startup_cost_control':
                    changed[4]=replace(gens[4],cost_su=gens[4].cost_su+50.)
                else:
                    epsilon=float(re.match(r'epsilon([-0-9.]+)_',job).group(1))
                    changed[4]=replace(gens[4],cost_nl=gens[4].cost_nl+epsilon)
                delta=data.get('delta')
                if not job.endswith('_settlement'):
                    assert max(schedule_residuals(changed,net,z['p'],z['u']).values())<1e-7
                    reported=apply_generator_adder(changed,0,delta)
                    cost=sum(dispatch_cost(g,z['p'][i],z['u'][i]) for i,g in enumerate(reported))
                    assert abs(cost-data['value'])<1e-6 and abs(cost-data['lower_bound'])<1e-5
                else:
                    uc_name=job.removesuffix('_settlement');uc=read(stage/(uc_name+'.json'));delta=uc['delta']
                    ss_check(changed[0],z['self_p'],z['self_u'],z['price'][net.gen_bus_idx(0)],delta,
                        data['best_reported_profit_usd'],data['self_schedule_upper_bound'])
                    with np.load(stage/(uc_name+'.npz')) as raw:
                        acc=ledger(changed[0],raw['p'][0],raw['u'][0],z['price'][net.gen_bus_idx(0)],delta,data['best_reported_profit_usd'])
                    assert max(abs(acc[k]-data[k]) for k in acc)<1e-6
                    assert max(data['lp_audit'].values())<1e-6 and not data['old_oracle_reused']
    import csv
    stage=OUTPUT/'P1_profit_path_io_recovery'
    with (stage/'continuous_channels.csv').open() as stream:pieces=list(csv.DictReader(stream))
    price_total=exposure_total=0.
    for row in pieces:
        a,b,w=map(float,(row['left'],row['right'],row['self_witness_delta']))
        key='ss_'+w.hex().replace('.','_').replace('+','p')
        ss=read(stage/(key+'.json'))
        price=lambda d:query_compact(d,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1][net.gen_bus_idx(0)]
        pc=float(np.asarray(ss['p'])@(price(b)-price(a)))
        ec=(float(row['D_UC'])-ss['exposure'])*(b-a)
        assert abs(pc-float(row['price_channel_usd']))<1e-6
        assert abs(ec-float(row['exposure_channel_usd']))<1e-6
        for d in (a,b):
            endpoint=read(stage/('ss_'+d.hex().replace('.','_').replace('+','p')+'.json'))
            value=float(price(d)@ss['p']-ss['true_cost']-d*ss['exposure'])
            assert abs(value-endpoint['upper'])<1e-6
        region=report['physical_regions'][int(row['physical_region'])]
        with np.load(PHYSICAL/'physical_plans.npz') as z:
            j=np.flatnonzero(z['deltas']==region['witness_delta'])[0]
            duc=float(np.sum(z['outputs'][j,0]-gens[0].P_min*z['commitments'][j,0]))
        assert abs(duc-float(row['D_UC']))<1e-8
        price_total+=pc;exposure_total+=ec
    summary=read(stage/'summary.json')
    jump_total=sum(r['delta']*(r['new_exposure']-r['old_exposure']) for r in summary['physical_jumps'])
    residual=price_total+exposure_total+jump_total-report['maximizing_candidate']['extra_profit_vs_truthful']
    assert abs(residual)<1e-4
    for stage in ('P0_threshold_io_recovery','P2_held_out'):
        for row in read(OUTPUT/stage/'summary.json')['records']:
            expected=protocol['predicted_critical']+row['epsilon']*protocol['predicted_slope']
            assert abs(row['predicted_critical']-expected)<1e-10 and row['supported']
    result=dict(status='passed',checkpoint_files=files,jobs=jobs,channel_reconciliation_residual=residual,
        scope='Saved full SS/UC feasibility, cost, bounds, channel endpoint and ledger reconstruction; recorded LP audits checked, no new LP/MIP solve')
    write(OUTPUT/'independent_verification.json',result);print(result)


if __name__=='__main__':main()
