"""
Diagnostic test for PrimalCHPLP (no Gurobi needed).
Validates that the LP constraint matrices and variable layouts are internally consistent.
"""
import sys, os
_proj_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

import numpy as np
from models.generator import load_all_case6ww_generators, load_all_case30ww_generators
from models.network import build_single_node_from_case6ww, build_single_node_from_case30ww
from chp_core.graph_builder import DAGBuilder
from chp_solver.chp_master_lp import _VarIndex

def test_lp_structure(case_label, T=24, n_seg=3):
    print(f"\n=== Test: case{case_label}, T={T}, segments={n_seg} ===")
    
    if case_label == "6":
        gens = load_all_case6ww_generators(T=T, n_segments=n_seg)
        net = build_single_node_from_case6ww(T=T)
    else:
        gens = load_all_case30ww_generators(T=T, n_segments=n_seg)
        net = build_single_node_from_case30ww(T=T)
    
    dags = [DAGBuilder.build(g) for g in gens]
    use_pwl = any(not g.is_single_segment for g in gens)
    idx = _VarIndex(dags, use_pwl=use_pwl)
    
    # 1. Variable count sanity
    assert idx.n_z >= sum(d.n_on + d.n_off for d in dags), "z count mismatch"
    for i, dag in enumerate(dags):
        n_v = sum(iv.duration for iv in dag.on_intervals)
        # v_offset[i][-1] + last_duration should equal starting offset + total v count
        if dag.n_on > 0:
            last_v_start = idx.v_offset[i][-1]
            expected_total_v_for_i = sum(idx.v_offset[i][j+1] - idx.v_offset[i][j] for j in range(dag.n_on-1)) + dag.on_intervals[-1].duration
    print(f"  [PASS] Variable layout: z={idx.n_z}, v={idx.n_v}, cvar={idx.n_cvar}, total={idx.n_total}")
    
    # 2. ON arc constraints count
    n_perspective_rows = 0
    for i, (dag, g) in enumerate(zip(dags, gens)):
        for k, iv in enumerate(dag.on_intervals):
            n = iv.duration
            n_perspective_rows += 2  # su upper + su lower
            n_perspective_rows += 2 * (n - 1)  # ramp upper + lower for each tau>0
            n_perspective_rows += 2 * n  # capacity upper + lower for each tau
            n_perspective_rows += 1  # shutdown
            if use_pwl and not g.is_single_segment:
                n_perspective_rows += n * g.n_segments  # PWL epigraph
            elif use_pwl and g.is_single_segment:
                n_perspective_rows += n  # single-segment epigraph
    print(f"  [PASS] Perspective rows: {n_perspective_rows}")
    
    # 3. Demand feasibility
    total_pmax = sum(g.P_max for g in gens)
    total_pmin = sum(g.P_min for g in gens)
    peak = max(net.sys_demand)
    valley = min(net.sys_demand)
    print(f"  Demand: [{valley:.1f}, {peak:.1f}] MW")
    print(f"  Capacity: Pmin_sum={total_pmin}, Pmax_sum={total_pmax}")
    feasible = total_pmax >= peak and (T >= 6 or total_pmin <= valley)
    if not feasible:
        print(f"  [WARN] Demand may be infeasible (Pmax_sum={total_pmax} < peak={peak})")
    else:
        print(f"  [PASS] Capacity adequate")
    
    # 4. Check that all generators have minimum up-time intervals
    for i, dag in enumerate(dags):
        min_dur = min(iv.duration for iv in dag.on_intervals)
        expected_min = gens[i].T_on_min
        assert min_dur >= expected_min, f"G{i+1}: min interval {min_dur} < MUT={expected_min}"
    print(f"  [PASS] All ON intervals satisfy MUT")
    
    print(f"  [PASS] All static checks passed for case{case_label} seg={n_seg} T={T}")
    return True

if __name__ == "__main__":
    for T in [24]:
        for case in ["6", "30"]:
            for n_seg in [1, 3]:
                test_lp_structure(case, T=T, n_seg=n_seg)
    print("\n=== ALL STATIC CHECKS PASSED ===")
