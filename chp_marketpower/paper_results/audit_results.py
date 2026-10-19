"""Zero-optimization audit of prices, certified curves, timings and settlements."""
import numpy as np
from engine import SingleNodeNetwork
from benchmarks.unit_self_schedule import dispatch_cost
from run_initial_condition_audit import schedule_residuals
from mechanism_study.runtime import ROOT,read,write,digest
from mechanism_study.run_study import load_inputs,PHYSICAL
from paper_results.build_results import PAPER,DATA,rows,PREVIOUS
from paper_results.components import interpolate


def main():
    inputs=read(PAPER/'input_manifest.json')
    assert all(digest(p)==sha for p,sha in inputs.items())
    summary=read(PAPER/'analysis_summary.json')
    gens,net,compact,report,critical,adjacent,plans=load_inputs()
    with np.load(DATA/'price_components.npz') as z:
        nodal=z['lambda_CHP'];energy=z['lambda_E'];congestion=z['lambda_C'];boundaries=z['delta']
        error=float(np.max(abs(nodal-energy[:,None,:]-congestion)))
        assert error<1e-7 and np.max(abs(congestion[:,0,:]))<1e-12
        assert np.max(abs((energy+congestion[:,22,:])[:,None,:]+congestion-congestion[:,22,None,:]-nodal))<1e-7
    assert abs(summary['price_effect']['total']-summary['reference_sensitivity']['total'])<1e-6
    byhour=rows(DATA/'price_effect_by_hour.csv')
    total=sum(float(r['energy_effect'])+float(r['congestion_effect']) for r in byhour)
    path=summary['path'];whole=total+path['exposure_channel_usd']+path['physical_jump_usd']
    assert abs(whole-summary['path_total_extra_profit'])<1e-5
    # Every old and newly computed response is reconstructed from a feasible trajectory.
    cache={};checked=0
    for folder in [PREVIOUS/'P1_profit_path_io_recovery',PAPER/'supplement/missing_self_schedules']:
        m=read(folder/'manifest.json');assert m['status']=='passed'
        for name,record in m['jobs'].items():
            assert digest(folder/(name+'.json'))==record['json_sha256']
            assert digest(folder/(name+'.npz'))==record['npz_sha256']
            item=read(folder/(name+'.json'));cache[item['delta']]=item;checked+=1
            p,u=np.array(item['p']),np.array(item['u'])
            residual=schedule_residuals([gens[0]],SingleNodeNetwork(p),p[None,:],u[None,:])
            assert max(residual.values())<1e-7 and abs(item['upper']-item['best'])<1e-6
            assert abs(dispatch_cost(gens[0],p,u)-item['true_cost'])<1e-6
    pieces=rows(DATA/'certified_full_range_pieces.csv');curve=rows(DATA/'fig3_profit_uplift_curves.csv')
    with np.load(PHYSICAL/'physical_plans.npz') as z:
        physical={float(d):(z['outputs'][j],z['commitments'][j]) for j,d in enumerate(z['deltas'])}
    max_ledger=0.
    for piece in pieces:
        left,right=float(piece['left']),float(piece['right'])
        region=report['physical_regions'][int(piece['physical_region'])]
        p,u=physical[region['witness_delta']]
        ss=cache[float(piece['self_witness_delta'])]
        for endpoint in [r for r in curve if r['piece']==piece['piece']]:
            d=float(endpoint['delta']);price=interpolate(boundaries,nodal,d)[net.gen_bus_idx(0)]
            best=float(price@ss['p']-ss['true_cost']-d*ss['exposure'])
            assert abs(best-cache[d]['upper'])<1e-6
            R=float(price@p[0]);C=dispatch_cost(gens[0],p[0],u[0]);Q=float(np.sum(p[0]-gens[0].P_min*u[0]))
            U=best-R+C+d*Q;Pi=R+U-C
            discrepancy=max(abs(R-float(endpoint['R'])),abs(C-float(endpoint['C'])),abs(U-float(endpoint['U'])),abs(Pi-float(endpoint['Pi'])))
            assert discrepancy<1e-5;max_ledger=max(max_ledger,discrepancy)
    assert len(pieces)==99 and float(pieces[0]['left'])==0. and float(pieces[-1]['right'])==compact['price_boundaries'][-1]
    assert all(abs(float(a['right'])-float(b['left']))<1e-9 for a,b in zip(pieces[:-1],pieces[1:]))
    candidate_error=0.
    for c in report['candidate_bids']:
        found=[r for r in curve if int(r['physical_region'])==c['physical_region'] and abs(float(r['delta'])-c['delta'])<1e-9]
        assert found
        discrepancy=min(abs(float(r['Pi'])-c['true_profit']) for r in found)
        assert discrepancy<1e-5;candidate_error=max(candidate_error,discrepancy)
    assert abs(max(float(r['delta_Pi']) for r in curve)-summary['path_total_extra_profit'])<1e-5
    for r in rows(DATA/'table_II_settlement_changes.csv'):
        assert abs(float(r['delta_R'])+float(r['delta_U'])-float(r['delta_C'])-float(r['delta_Pi']))<1e-5
    network=rows(DATA/'network_counterfactual_settlements.csv')
    for r in network:
        assert abs(float(r['R_E'])+float(r['R_C'])-float(r['R']))<1e-6
        assert abs(float(r['R'])+float(r['U'])-float(r['C'])-float(r['Pi']))<1e-6
        base=next(b for b in network if b['scenario']==r['scenario'] and b['bid']=='0')
        assert abs(float(r['Pi'])-float(base['Pi'])-float(r['delta_Pi']))<1e-6
    for r in rows(DATA/'network_settlement_identity.csv'):assert abs(float(r['network_identity_residual']))<1e-5
    for r in summary['timing']:
        assert abs(r['direct_seconds']/r['parametric_total_seconds']-r['direct_over_parametric'])<1e-12
    curves_match=0.
    legacy=rows(ROOT/'results/figure_study_20261016/generator_settlements.csv')
    for old in [r for r in legacy if r['generator_index']=='0']:
        d=float(old['delta']);g=int(old['physical_region'])
        intervals=[r for r in pieces if int(r['physical_region'])==g and float(r['left'])-1e-10<=d<=float(r['right'])+1e-10]
        assert intervals
        segment=intervals[0];end=[r for r in curve if r['piece']==segment['piece']]
        theta=(d-float(segment['left']))/(float(segment['right'])-float(segment['left']))
        for k,oldk in [('Pi','true_profit'),('U','reported_uplift')]:
            v=(1-theta)*float(end[0][k])+theta*float(end[1][k]);discrepancy=abs(v-float(old[oldk]))
            assert discrepancy<1e-4;curves_match=max(curves_match,discrepancy)
    result=dict(status='passed',source_hashes=len(inputs),nodal_price_values=int(nodal.size),max_price_decomposition_error=error,
        reconstructed_SS_witnesses=checked,common_SS_intervals=len(pieces),candidate_records=len(report['candidate_bids']),
        max_curve_ledger_error=max_ledger,max_candidate_profit_error=candidate_error,max_legacy_curve_error=curves_match,
        profit_path_residual=whole-summary['path_total_extra_profit'],new_optimization_solves=0)
    write(PAPER/'verification.json',result);print(result)


if __name__=='__main__':main()
