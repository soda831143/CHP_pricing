"""
6节点IEEE标准系统 (case6ww) Python 版本。
从 MATLAB case_6ww.m + MATPOWER case6ww.m 完整移植。

系统说明：
  - 6 节点，3 台发电机，11 条支路（Wood & Wollenberg 完整拓扑）
  - 节点 1 (G1 基荷 Pmax=200), 节点 2 (G2 中等 Pmax=150), 节点 3 (G3 峰荷 Pmax=180)
  - 节点 4, 5, 6 为负荷节点（Pd=70/80/90 MW）
  - MUT/MDT: G1=4/4, G2=3/3, G3=2/2

v2.0 变更（2026-06-09）：
  - 发电机 Pmax/Pmin/cost/ramp 恢复为 MATLAB 用户版数据
  - 支路从 7 条恢复为 11 条（MATPOWER case6ww 原始拓扑）
  - 与之前研究成果（banben6.0）完全对齐

单位约定与负荷/PTDF/成本推导逻辑见 case_common.py。
"""
from __future__ import annotations

from .case_common import (
    BranchData, BusData, CaseMPC, GenCostData, GenData,
    build_load_profile, build_ptdf, derive_piecewise_costs,
    get_gen_params_for_thermal, get_line_limits,
)

Case6WW = CaseMPC


def build_case_6ww(n_segments: int = 3) -> Case6WW:
    """构建 6 节点标准测试系统。

    Parameters
    ----------
    n_segments : 分段线性近似的段数（默认 3，与 MATLAB derive_piecewise_from_quadratic 一致）
    """
    mpc = CaseMPC()

    # ── 节点（与 MATLAB case_6ww.m 完全一致）──────────────────────────
    mpc.buses = [
        BusData(bus_i=1, bus_type=3, Pd=0,  Qd=0,  Vm=1.05, Vmax=1.05, Vmin=1.05),
        BusData(bus_i=2, bus_type=2, Pd=0,  Qd=0,  Vm=1.05, Vmax=1.05, Vmin=1.05),
        BusData(bus_i=3, bus_type=2, Pd=0,  Qd=0,  Vm=1.07, Vmax=1.07, Vmin=1.07),
        BusData(bus_i=4, bus_type=1, Pd=70, Qd=70, Vm=1.0,  Vmax=1.05, Vmin=0.95),
        BusData(bus_i=5, bus_type=1, Pd=80, Qd=70, Vm=1.0,  Vmax=1.05, Vmin=0.95),
        BusData(bus_i=6, bus_type=1, Pd=90, Qd=70, Vm=1.0,  Vmax=1.05, Vmin=0.95),
    ]

    # ── 发电机（与 MATLAB case_6ww.m 完全一致）───────────────────────
    # G1=基荷(200MW), G2=中等(150MW), G3=峰荷(180MW)
    # ramp 取自 MATLAB gen(:,22) 列
    mpc.generators = [
        GenData(bus=1, Pg=0,  Pmax=200, Pmin=50,  Qmax=100, Qmin=-100,
                T_on_min=4, T_off_min=4),
        GenData(bus=2, Pg=50, Pmax=150, Pmin=37.5, Qmax=100, Qmin=-100,
                T_on_min=3, T_off_min=3),
        GenData(bus=3, Pg=60, Pmax=180, Pmin=45,  Qmax=100, Qmin=-100,
                T_on_min=2, T_off_min=2),
    ]

    # ── 成本（二次函数，与 MATLAB case_6ww.m 完全一致）─────────────
    # C(P) = a·P² + b·P + c
    mpc.gen_costs = [
        GenCostData(model=2, cost_a=0.00533, cost_b=11.669,  cost_c=213.1,
                    ramp_up=60.0, ramp_down=60.0),
        GenCostData(model=2, cost_a=0.00889, cost_b=10.333,  cost_c=200.0,
                    ramp_up=50.0, ramp_down=50.0),
        GenCostData(model=2, cost_a=0.00741, cost_b=10.833,  cost_c=240.0,
                    ramp_up=70.0, ramp_down=70.0),
    ]

    # ── 支路（与 MATPOWER case6ww.m 完整 11 条支路一致）─────────────
    mpc.branches = [
        BranchData(fbus=1, tbus=2, r=0.10, x=0.20, b=0.04, rateA=40),
        BranchData(fbus=1, tbus=4, r=0.05, x=0.20, b=0.04, rateA=60),
        BranchData(fbus=1, tbus=5, r=0.08, x=0.30, b=0.06, rateA=40),
        BranchData(fbus=2, tbus=3, r=0.05, x=0.25, b=0.06, rateA=40),
        BranchData(fbus=2, tbus=4, r=0.05, x=0.10, b=0.02, rateA=60),
        BranchData(fbus=2, tbus=5, r=0.10, x=0.30, b=0.04, rateA=30),
        BranchData(fbus=2, tbus=6, r=0.07, x=0.20, b=0.05, rateA=90),
        BranchData(fbus=3, tbus=5, r=0.12, x=0.26, b=0.05, rateA=70),
        BranchData(fbus=3, tbus=6, r=0.02, x=0.10, b=0.02, rateA=80),
        BranchData(fbus=4, tbus=5, r=0.20, x=0.40, b=0.08, rateA=20),
        BranchData(fbus=5, tbus=6, r=0.10, x=0.30, b=0.06, rateA=40),
    ]

    mpc.NB = len(mpc.buses)
    mpc.NG = len(mpc.generators)
    mpc.NL = len(mpc.branches)

    build_load_profile(mpc)
    build_ptdf(mpc)
    derive_piecewise_costs(mpc, n_segments=n_segments)

    return mpc


__all__ = [
    "BusData", "GenData", "GenCostData", "BranchData", "Case6WW", "CaseMPC",
    "build_case_6ww", "get_line_limits", "get_gen_params_for_thermal",
]
