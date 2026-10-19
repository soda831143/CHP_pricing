"""Recheck recovered raw witnesses without repeating MIP experiments.

Run from chp_marketpower: python -m mechanism_study.verify_recovery
Two baseline CHP LPs reconstruct the original and treated constraint matrices.
"""
from types import SimpleNamespace
import numpy as np

from engine import load_case, SingleNodeNetwork
from benchmarks.unit_self_schedule import dispatch_cost
from price_vulnerability.model_identity import model_identity
from price_vulnerability.persistent_chp import PersistentCHP
from mechanism_study.constraint_attribution import treatment
from mechanism_study.profit_identity import ledger
from mechanism_study.runtime import ROOT, OUTPUT, Stage, read, write, digest, CAUSAL_STAGE
from mechanism_study.run_study import ORACLE, selected_dual_audit
from run_initial_condition_audit import schedule_residuals


def lp_residuals(cp, z):
    eq,b,_,_,ineq,h=cp.matrices
    x,c,pi,mu,zl,zu=[z[k] for k in ('primal','objective','eq_dual','ineq_dual','lower_dual','upper_dual')]
    assert all(np.isfinite(v).all() for v in (x,c,pi,mu,zl,zu))
    il,iu=np.flatnonzero(cp.lb>-1e20),np.flatnonzero(cp.ub<1e20)
    dual=b@pi+h@mu+cp.lb[il]@zl[il]+cp.ub[iu]@zu[iu]
    result=dict(primal=float(max(np.max(abs(eq@x-b)),np.max(ineq@x-h),np.max(cp.lb-x),np.max(x-cp.ub),0.)),
        sign=float(max(np.max(mu,initial=0.),-np.min(zl,initial=0.),np.max(zu,initial=0.))),
        stationarity=float(np.max(abs(c-eq.T@pi-ineq.T@mu-zl-zu))),duality_gap=abs(float(c@x-dual)),
        complementarity=float(max(np.max(abs(mu*(h-ineq@x)),initial=0.),
            np.max(abs(zl[il]*(x[il]-cp.lb[il])),initial=0.),np.max(abs(zu[iu]*(cp.ub[iu]-x[iu])),initial=0.))))
    assert max(result.values())<1e-6, result
    return result


def main():
    stage=Stage('recovery_verification_final',budgets=dict(chp=2,uc=0,self_schedule=0,auxiliary=0),seconds=120.,
        plan=dict(scope='Checkpoint hashes, raw accounting/feasibility, original full-dual interpolation, MRG KKT; no new MIP'))
    gens,net=load_case('30','ptdf',24,3,'tight')
    expected=read(ROOT/'results/mechanism_20261018/manifest.json')['model_identity']
    assert model_identity(gens,net)==expected
    hashes=[]
    for name in ('E2_local','E3_pivotal',CAUSAL_STAGE):
        manifest=read(OUTPUT/name/'manifest.json')
        for job,entry in manifest['jobs'].items():
            for suffix,key in (('.json','json_sha256'),('.npz','npz_sha256')):
                if key in entry:
                    path=OUTPUT/name/(job+suffix)
                    assert digest(path)==entry[key],path
                    hashes.append(dict(path=str(path.relative_to(ROOT)),sha256=entry[key]))
    with stage.solvers():
        cp=PersistentCHP(gens,net,0)
        stage.call('chp','original_matrices',lambda:cp.solve(0.))
        with np.load(ORACLE/'oracle.npz') as z:raw={k:z[k] for k in z.files}
        from price_vulnerability.oracle_compression import load_matched_compact
        _,_,compact=load_matched_compact(ORACLE)
        local=read(OUTPUT/'E2_local/summary.json');local_checks=[]
        for row in local['queries']:
            with np.load(OUTPUT/'E2_local'/(row['label']+'.npz')) as z:
                assert max(schedule_residuals(gens,net,z['physical_p'],z['physical_u']).values())<1e-7
                for j,sample in enumerate(row['samples']):
                    d=sample['delta'];price=z[f'price_{j}'];p=z['physical_p'][0];u=z['physical_u'][0]
                    account=ledger(gens[0],p,u,price[net.gen_bus_idx(0)],d,sample['self_best'])
                    assert abs(account['true_profit_usd']-sample['true_profit_usd'])<1e-6
                    ss_p,ss_u=z[f'self_p_{j}'],z[f'self_u_{j}']
                    assert max(schedule_residuals([gens[0]],SingleNodeNetwork(ss_p),ss_p[None],ss_u[None]).values())<1e-7
                    surplus=price[net.gen_bus_idx(0)]@ss_p-dispatch_cost(gens[0],ss_p,ss_u)-d*sample['self_exposure']
                    assert abs(surplus-sample['self_bound'])<1e-6
                    from price_vulnerability.oracle_compression import query_compact
                    value,_=query_compact(d,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])
                    cert,_=selected_dual_audit(cp,raw,compact,d,SimpleNamespace(objective=cp.c0+d*cp.direction,value=value,price=price))
                    local_checks.append(cert['residuals'])
        structural=read(OUTPUT/'E3_pivotal/summary.json');mrg_checks=[]
        for r in structural['mrg']:
            with np.load(OUTPUT/'E3_pivotal'/f"mrg_{r['unit']}_h{r['hour']}.npz") as z:
                g=int(r['unit'][1:])-1;t=r['hour']-1
                assert max(schedule_residuals(gens,net,z['uc_p'],z['uc_u']).values())<1e-7
                assert abs(z['uc_p'][g,t]-r['physical_lower_bound_mw'])<1e-6
                assert -1e-7<=r['mrg_chp_mw']<=r['mrg_uc_mw']+1e-6
                assert abs(z['objective']@z['primal']-r['mrg_chp_mw'])<1e-6
                mrg_checks.append(lp_residuals(cp,z))
        causal=read(OUTPUT/CAUSAL_STAGE/'summary.json')
        gg,nn=treatment(gens,net,causal['protocol']['intervention'])
        treated=PersistentCHP(gg,nn,0)
        stage.call('chp','treated_matrices',lambda:treated.solve(0.))
        causal_checks=[];face_checks=[]
        for r in causal['settlements']:
            network=net if r['scenario']=='original' else nn
            model=cp if r['scenario']=='original' else treated
            with np.load(OUTPUT/CAUSAL_STAGE/f"{r['scenario']}_bid{r['bid_index']}.npz") as z:
                assert max(schedule_residuals(gens,network,z['p'],z['u']).values())<1e-7
                assert np.max(abs(z['objective']-model.c0-r['delta']*model.direction))<1e-8
                causal_checks.append(lp_residuals(model,z))
                d=r['delta'];p,u=z['p'][0],z['u'][0];price=z['price'][network.gen_bus_idx(0)]
                ss_p,ss_u=z['self_p'],z['self_u']
                exposure=np.sum(ss_p-gens[0].P_min*ss_u)
                ss_best=float(price@ss_p-dispatch_cost(gens[0],ss_p,ss_u)-d*exposure)
                account=ledger(gens[0],p,u,price,d,ss_best)
                assert abs(account['true_profit_usd']-r['true_profit_usd'])<1e-6
                for endpoint in ('min','max') if r['bid_index'] in (0,2) else ():
                    prefix='face_'+endpoint+'_'
                    il,iu=np.flatnonzero(model.lb>-1e20),np.flatnonzero(model.ub<1e20)
                    zl=np.zeros_like(z['objective']);zu=zl.copy()
                    zl[il]=z[prefix+'lower_dual'];zu[iu]=z[prefix+'upper_dual']
                    bundle=dict(primal=z['primal'],objective=z['objective'],eq_dual=z[prefix+'eq_dual'],
                        ineq_dual=z[prefix+'ineq_dual'],lower_dual=zl,upper_dual=zu)
                    face_checks.append(lp_residuals(model,bundle))
                    from mechanism_study.linear_audit import project_price
                    fp=z[prefix+'price']
                    assert np.max(abs(project_price(model,bundle['eq_dual'],bundle['ineq_dual'])-fp))<1e-6
                    ss_p,ss_u=z[prefix+'self_p'],z[prefix+'self_u']
                    face=next(f for f in causal['dual_face_checks'] if f['scenario']==r['scenario'] and f['bid_index']==r['bid_index'] and f['extreme']==endpoint)
                    ss_value=float(fp[network.gen_bus_idx(0)]@ss_p-dispatch_cost(gens[0],ss_p,ss_u)-d*np.sum(ss_p-gens[0].P_min*ss_u))
                    assert abs(ss_value-face['self_schedule_upper_bound_usd'])<1e-6
                    assert abs(ledger(gens[0],p,u,fp[network.gen_bus_idx(0)],d,ss_value)['true_profit_usd']-face['true_profit_usd'])<1e-6
    result=dict(status='passed',model_identity=expected,verified_checkpoint_files=hashes,
        E2_selected_dual_checks=local_checks,E3_raw_mrg_checks=mrg_checks,E4_raw_lp_checks=causal_checks,E4_raw_face_checks=face_checks,
        limitations='Saved E2/E3 MIP bounds are checked against original outcomes, not independently re-solved; historical dual-face failures retained')
    write(stage.out/'summary.json',result);stage.finish()
    print(f"Recovery verified: {len(hashes)} checkpoint files, 18 E2 selected-dual samples, nine MRG and six E4 raw LPs")


if __name__=='__main__':main()
