"""Assemble traceable tables and a local delivery inventory without optimization."""
import csv
import json
from pathlib import Path
import subprocess
import numpy as np

from engine import load_case
from price_vulnerability.oracle_compression import load_matched_compact,query_compact
from mechanism_study.structural_pivotality import map_for
from mechanism_study.runtime import ROOT,OUTPUT,read,write,digest,CAUSAL_STAGE


def table(name, rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with (OUTPUT/name).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    assert read(OUTPUT/'recovery_verification_final/summary.json')['status']=='passed'
    assert read(OUTPUT/'settlement_certification/summary.json')['status']=='passed'
    assert read(OUTPUT/'E5_finite_screen/summary.json')['status']=='passed'
    local=read(OUTPUT/'E2_local/summary.json')
    structural=read(OUTPUT/'E3_pivotal/summary.json')
    causal=read(OUTPUT/CAUSAL_STAGE/'summary.json')
    assert causal['status']=='passed' and all(f['status']=='optimal' for f in causal['dual_face_checks'])
    gens,net=load_case('30','ptdf',24,3,'tight')
    channels=[]
    for query in local['queries']:
        center=0 if query['delta']==0 else 1;w=query['common_ss_witness']
        sample=query['samples'][center]
        with np.load(OUTPUT/'E2_local'/(query['label']+'.npz')) as z:
            common=dict(query=query['label'],unit='G1',delta=query['delta'],rho=query['delta']/41.982,
                derivative_kind=query['derivative_kind'],price_selector='Archived full-dual affine interpolation',
                D_UC_mwh=sample['exposure_mwh'],D_SS_mwh=query['samples'][w]['self_exposure'],
                price=json.dumps(z[f'price_{center}'][net.gen_bus_idx(0)].tolist()),
                price_slope=json.dumps(z['price_slope'][net.gen_bus_idx(0)].tolist()),
                self_p=json.dumps(z[f'self_p_{w}'].tolist()),LOC_usd=sample['loc_usd'],true_profit_usd=sample['true_profit_usd'],
                source=f"E2_local/{query['label']}.npz")
            channels.extend(dict(**common,**derivative) for derivative in query['derivatives'])
    table('profit_mechanism.csv',channels)
    table('constraint_attribution.csv',read(OUTPUT/CAUSAL_STAGE/'original_bid0.json')['activity']+
        [row for scenario in ('original','relaxed') for j in range(3) if (scenario,j)!=('original',0)
         for row in read(OUTPUT/CAUSAL_STAGE/f'{scenario}_bid{j}.json')['activity']])
    table('counterfactual_profit_effects.csv',causal['effects'])
    table('counterfactual_settlements.csv',[{k:v for k,v in row.items() if not isinstance(v,dict)} for row in causal['settlements']])
    table('structural_indispensability.csv',[dict(**r,removal_status=next(x['status'] for x in structural['removals'] if x['unit']==r['unit']),
        kappa_usd=None,kappa_note='Whole-unit removal infeasible; no finite removal premium assigned') for r in structural['mrg']])
    comparison=[]
    for g in (0,4,1):
        rows=[r for r in structural['economics'] if r['unit']==f'G{g+1}']
        base=next(r['true_profit_usd'] for r in rows if r['rho']==0.)
        directory=map_for(g);_,_,compact=load_matched_compact(directory)
        price0=query_compact(0.,*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1]
        path=ROOT/'results/mechanism_20261018/baseline.npz' if g==0 else OUTPUT/'E3_pivotal'/f'profit_G{g+1}_rho0.npz'
        with np.load(path) as z:weight=z['self_p'].copy()
        for r in rows:
            price=query_compact(r['delta'],*[compact[k] for k in ('value_boundaries','values','price_boundaries','prices')])[1]
            if g==0:
                name='baseline' if r['rho']==0. else 'boundary'
                path=ROOT/'results/mechanism_20261018'/(name+'.npz')
                if r['rho']==.5:path=OUTPUT/'E5_finite_screen/G1_rho50.npz'
                with np.load(path) as z:
                    pp,uu=(z['p'][g],z['u'][g]) if r['rho']==.5 else (z['p_solver'][g],z['u_solver'][g]) if r['rho']==0. else (z['p_A_left'][g],z['u_A_left'][g])
                    ss_p,ss_u=z['self_p'],z['self_u']
            else:
                with np.load(OUTPUT/'E3_pivotal'/f"profit_G{g+1}_rho{r['rho']:.12g}.npz") as z:
                    pp,uu,ss_p,ss_u=z['p'][g],z['u'][g],z['self_p'],z['self_u']
            duc=float(np.sum(pp-gens[g].P_min*uu));dss=float(np.sum(ss_p-gens[g].P_min*ss_u))
            comparison.append(dict(unit=r['unit'],rho=r['rho'],delta=r['delta'],reference_slope=r['reference_slope'],
                true_profit_usd=r['true_profit_usd'],extra_profit_usd=r['true_profit_usd']-base,
                positive_extra_profit=r['true_profit_usd']-base>1e-6,
                full_nodal_price_response_l2=float(np.linalg.norm(price-price0)),
                own_baseline_SS_signed_price_exposure_usd=float(weight@(price[net.gen_bus_idx(g)]-price0[net.gen_bus_idx(g)])),
                D_UC_mwh=duc,D_SS_mwh=dss,exposure_gap_mwh=duc-dss,
                removal_status='infeasible_pivotal',kappa_usd=None,
                tie_rule='Inherited G1 optimistic boundary candidate' if g==0 and r['rho']>0 and r['rho']<.5 else 'Original optimizer execution',
                scope='Three prespecified bids; existence evidence, not a continuous-domain ranking'))
    table('structural_profit_comparison.csv',comparison)
    table('finite_set_screening.csv',read(OUTPUT/'E5_finite_screen/summary.json')['records'])
    face=[]
    for r in causal['dual_face_checks']:
        face.append(dict(source=CAUSAL_STAGE,**r))
    face.extend(dict(source='E4_causal_recovery_01',**r) for r in read(OUTPUT/'E4_causal_recovery_01/summary.json')['dual_face_checks'])
    for name in ('E4_dual_face_recovery_01','E4_dual_face_scaled_01','E4_dual_face_nopresolve_01'):
        face.extend(dict(source=name,scenario='original',bid_index=2,**r) for r in read(OUTPUT/name/'summary.json')['records'])
    table('dual_face_sensitivity.csv',face)
    paths=[p for p in OUTPUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts
        and not any(part.startswith('test_tmp') for part in p.parts) and p.name!='delivery_manifest.json']
    paths+=list((ROOT/'mechanism_study').glob('*.py'))+[ROOT/'tests/test_mechanism_followup.py']
    inventory={str(p.relative_to(ROOT)):digest(p) for p in paths}
    git=lambda *a:subprocess.check_output(['git',*a],cwd=ROOT,encoding='utf-8').strip()
    stages={p.parent.name:read(p) for p in OUTPUT.glob('*/manifest.json') if 'test_tmp' not in str(p)}
    write(OUTPUT/'delivery_manifest.json',dict(base_commit=git('rev-parse','HEAD'),remote_audit_commit=git('rev-parse','origin/research/market-power-parametric-regimes'),
        branch=git('branch','--show-current'),git_history='Diverged local/raw and remote/publication histories retained; no merge/reset/clean/force-push',
        E0_E1='Historical passed, all originals preserved',E2='Recovered and raw-verified',E3='Recovered and raw-verified',
        E4='Six certified settlements and eight coherent optimal-dual-face endpoints; historical numerical failures retained',
        E5='Finite-set preliminary screen only; no generalization claim',new_market_scenarios=1,
        stages={name:dict(status=m['status'],budgets=m['identity']['budgets'],calls=m['calls']) for name,m in stages.items()},files_sha256=inventory))
    print('Mechanism tables and local delivery manifest assembled')


if __name__=='__main__':main()
