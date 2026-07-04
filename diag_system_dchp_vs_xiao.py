"""Diagnostic: system-level D-CHP vs Xiao single-node comparison."""
import numpy as np
from run_experiments import load_case, derive_warm_start_initial_conditions, apply_initial_conditions
from chp_solver.chp_master_lp import PrimalCHPLP
from benchmarks.xiao_explicit_pricing import XiaoExplicitPricing
from models.network import SingleNodeNetwork

gens, net = load_case('118', 'single', 24, 3, congestion='tight', fmax_scale=1.0)
u0, p0, on, off = derive_warm_start_initial_conditions('118', 'single', 3, 'tight', 1.0)
gens = apply_initial_conditions(gens, u0, p0, on, off)

# Test with system demand, single-node (no PTDF)
sn = SingleNodeNetwork(net.sys_demand)

# D-CHP
dchp = PrimalCHPLP(gens, sn)
lmp_dchp, dchp_obj, dchp_ok = dchp.solve()
print(f'D-CHP obj: {dchp_obj:.6f}')
print(f'D-CHP build/solver time: {dchp.build_time:.2f}s / {dchp.solver_time:.2f}s')

# Get the D-CHP dispatch
p_dchp = dchp.lp_dispatch()
print(f'D-CHP total dispatch per hour (first 6): {p_dchp.sum(axis=0)[:6]}')
print(f'System demand (first 6): {net.sys_demand[:6]}')
print(f'Max dispatch-demand gap: {np.max(np.abs(p_dchp.sum(axis=0) - net.sys_demand)):.6f}')
print(f'D-CHP LMP (first 6): {lmp_dchp[0,:6]}')

# Check per-unit dispatch
for i, g in enumerate(gens):
    p_i = p_dchp[i]
    if g.initial_status == 1 and np.any(p_i > 0):
        print(f'  Unit {i+1}: p0={g.initial_power:.1f}, LP dispatch first 6: {p_i[:6].round(2)}')

print()

# Xiao
xiao = XiaoExplicitPricing(gens, sn, max_states_per_unit=500000)
lmp_xiao, xiao_obj, xiao_ok = xiao.solve()
print(f'Xiao obj: {xiao_obj:.6f}')
print(f'Xiao LMP (first 6): {lmp_xiao[0,:6]}')

gap = dchp_obj - xiao_obj
print(f'\nGap: D-CHP - Xiao = {gap:.6f}')
tag = "tighter" if dchp_obj >= xiao_obj else "LOOSER"
print(f'D-CHP is {tag} than Xiao')

# Now let's check: try D-CHP with crossover=1 (simplex crossover)
print('\n--- D-CHP with crossover=1 ---')
dchp2 = PrimalCHPLP(gens, sn, crossover=1)
lmp_dchp2, dchp2_obj, dchp2_ok = dchp2.solve()
print(f'D-CHP+crossover obj: {dchp2_obj:.6f}')
print(f'D-CHP+crossover LMP (first 6): {lmp_dchp2[0,:6]}')
print(f'Gap vs Xiao: {dchp2_obj - xiao_obj:.6f}')

# Try method=1 (dual simplex)
print('\n--- D-CHP with method=1 (dual simplex) ---')
dchp3 = PrimalCHPLP(gens, sn, method=1, crossover=-1)
lmp_dchp3, dchp3_obj, dchp3_ok = dchp3.solve()
print(f'D-CHP dual-simplex obj: {dchp3_obj:.6f}')
print(f'D-CHP dual-simplex LMP (first 6): {lmp_dchp3[0,:6]}')
print(f'Gap vs Xiao: {dchp3_obj - xiao_obj:.6f}')
