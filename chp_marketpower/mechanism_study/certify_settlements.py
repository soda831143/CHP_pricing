"""Save missing SS global bounds for the recovered E3/E4 settlements.

Twelve prespecified SS maximizations; no new UC, CHP, bids or treatments.
"""
import numpy as np
from engine import load_case
from mechanism_study.constraint_attribution import treatment
from mechanism_study.profit_identity import ledger
from mechanism_study.runtime import ROOT, OUTPUT, Stage, read, write
from price_vulnerability.scalar_markup import apply_generator_adder
from strategic_market_simulation.profit_sweep import _settle_target


def main():
    stage=Stage('settlement_certification',budgets=dict(self_schedule=12,uc=0,chp=0,auxiliary=0),seconds=120.,
        plan=dict(reason='Recovered E3/E4 checkpoints omitted explicit SS upper bounds after checking them in memory',
            scope='Exactly the six G2/G5 E3 ledgers and six E4 ledgers; preserve every original file'))
    gens,net=load_case('30','ptdf',24,3,'tight')
    structural=read(OUTPUT/'E3_pivotal/summary.json')
    causal=read(OUTPUT/'E4_causal_recovery_01/summary.json')
    treated_g,treated_n=treatment(gens,net,causal['protocol']['intervention'])
    jobs=[]
    for row in structural['economics']:
        if row['unit']=='G1':continue
        name=f"profit_{row['unit']}_rho{row['rho']:.12g}"
        jobs.append(('E3_'+name,row,OUTPUT/'E3_pivotal'/(name+'.npz'),int(row['unit'][1:])-1,gens,net))
    for row in causal['settlements']:
        name=f"{row['scenario']}_bid{row['bid_index']}"
        gg,nn=(gens,net) if row['scenario']=='original' else (treated_g,treated_n)
        jobs.append(('E4_'+name,row,OUTPUT/'E4_causal_recovery_01'/(name+'.npz'),0,gg,nn))
    records=[]
    with stage.solvers():
        for name,row,path,g,gg,nn in jobs:
            with np.load(path) as z:p,u,price=z['p'],z['u'],z['price']
            reported=apply_generator_adder(gg,g,row['delta'])
            ss=stage.call('self_schedule',name,lambda:_settle_target(gg[g],reported[g],price[nn.gen_bus_idx(g)],p[g],u[g],mip_gap=0.))
            account=ledger(gg[g],p[g],u[g],price[nn.gen_bus_idx(g)],row['delta'],ss['best_reported_profit'])
            assert ss['self_schedule_gap_usd']<1e-6
            assert abs(account['true_profit_usd']-row['true_profit_usd'])<1e-6
            record=dict(source=str(path.relative_to(ROOT)),unit=f'G{g+1}',delta=row['delta'],
                self_schedule_upper_bound_usd=ss['self_schedule_upper_bound'],self_schedule_gap_usd=ss['self_schedule_gap_usd'],**account)
            stage.save(name,record,dict(self_p=ss['self_output_mw'],self_u=ss['self_commitment']))
            records.append(record)
    write(stage.out/'summary.json',dict(status='passed',records=records));stage.finish()
    print('Twelve recovered settlements agree with newly certified SS global bounds')


if __name__=='__main__':main()
