"""
共享 MATPOWER 式测试算例数据结构与工具函数。

- `CaseMPC`：多算例复用的数据容器（原仅用于 case6ww 的 Case6WW）。
- `build_load_profile` / `build_ptdf` / `derive_piecewise_costs`：与 MATLAB case_*ww
  中 24h 归一化负荷、makePTDF、二次成本推 PWL 等逻辑一致。

单位约定同 `case_6ww.py`：功率 MW，baseMVA=100，内部 PTDF 为 pu/pu。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BusData:
    """节点数据（对应 MATLAB mpc.bus）"""
    bus_i: int
    bus_type: int
    Pd: float
    Qd: float
    Vm: float = 1.0
    Va: float = 0.0
    baseKV: float = 230.0
    Vmax: float = 1.05
    Vmin: float = 0.95


@dataclass
class GenData:
    """发电机数据（对应 MATLAB mpc.gen）"""
    bus: int
    Pg: float
    Pmax: float
    Pmin: float
    Qmax: float
    Qmin: float
    T_on_min: int = 3
    T_off_min: int = 3


@dataclass
class GenCostData:
    """Quadratic heat-rate data and derived PWL operating-cost fields."""
    model: int
    cost_a: float
    cost_b: float
    cost_c: float
    ramp_up: float
    ramp_down: float
    fuel_price: float = 1.0
    startup_fuel: Optional[float] = None
    shutdown_fuel: Optional[float] = None

    startup: float = 0.0
    shutdown: float = 0.0
    cost_nl: float = 0.0
    cost_var: float = 0.0
    pwl_slopes: List[float] = field(default_factory=list)
    pwl_widths: List[float] = field(default_factory=list)


@dataclass
class BranchData:
    """支路数据"""
    fbus: int
    tbus: int
    r: float
    x: float
    b: float
    rateA: float


@dataclass
class CaseMPC:
    """
    多算例复用的 `mpc` 式数据对象。由 `build_case_*()` 填充。
    """
    baseMVA: float = 100.0
    NT: int = 24

    buses:      List[BusData]     = field(default_factory=list)
    generators: List[GenData]     = field(default_factory=list)
    gen_costs:  List[GenCostData] = field(default_factory=list)
    branches:   List[BranchData]  = field(default_factory=list)

    NB: int = 0
    NG: int = 0
    NL: int = 0

    PD: Optional[np.ndarray] = None
    PTDF: Optional[np.ndarray] = None
    PTDF_Gen: Optional[np.ndarray] = None
    piecewise_costs: Optional[Dict] = None


# 与 MATLAB 各 case_*ww 相同的 24h 归一化曲线（峰值为 1）
# STANDARD_DEMAND_24: np.ndarray = np.array(
#     [
#         0.79, 0.73, 0.76, 0.81, 0.90, 0.96,
#         0.95, 0.89, 0.88, 0.83, 0.87, 1.12,
#         1.34, 1.52, 1.56, 1.53, 1.39, 1.02,
#         0.79, 0.71, 0.66, 0.63, 0.60, 0.57,
#     ],
#     dtype=float,
# )

STANDARD_DEMAND_24: np.ndarray = np.array(
[
    0.62, 0.58, 0.56, 0.58, 0.65, 0.78,    # dawn ramp
    0.90, 0.84, 0.72, 0.60, 0.52, 0.46,    # solar valley ↓
    0.44, 0.48, 0.58, 0.74, 0.94, 1.20,    # evening ramp ↑
    1.38, 1.22, 0.98, 0.82, 0.70, 0.62,    # late decline
],
    dtype=float,
)


def build_load_profile(mpc: CaseMPC) -> None:
    """
    24h 负荷：PD[k,t] = demand_t[t] * Pd_rated[k] / baseMVA （pu）
    """
    demand_t = STANDARD_DEMAND_24 / STANDARD_DEMAND_24.max()
    Pd_rated = np.array([b.Pd for b in mpc.buses], dtype=float)
    mpc.PD = np.outer(Pd_rated / mpc.baseMVA, demand_t)


def build_ptdf(mpc: CaseMPC) -> None:
    """
    DC 潮流 PTDF（B 矩阵法），与 MATPOWER makePTDF 思想一致。slack 列为 0。
    """
    NB = mpc.NB
    NL = mpc.NL

    x_vec = np.array(
        [max(float(br.x), 1e-8) for br in mpc.branches], dtype=float
    )
    b_vec = 1.0 / x_vec

    A_mat = np.zeros((NL, NB))
    for l, br in enumerate(mpc.branches):
        A_mat[l, br.fbus - 1] = 1.0
        A_mat[l, br.tbus - 1] = -1.0

    B_f = np.diag(b_vec) @ A_mat
    B_bus = A_mat.T @ np.diag(b_vec) @ A_mat

    ref_idx = next(i for i, bus in enumerate(mpc.buses) if bus.bus_type == 3)
    non_ref = [i for i in range(NB) if i != ref_idx]

    B_red = B_bus[np.ix_(non_ref, non_ref)]
    Bf_red = B_f[:, non_ref]

    try:
        B_inv = np.linalg.inv(B_red)
    except np.linalg.LinAlgError:
        B_inv = np.linalg.pinv(B_red)

    PTDF_red = Bf_red @ B_inv
    PTDF = np.zeros((NL, NB))
    for new_col, orig_col in enumerate(non_ref):
        PTDF[:, orig_col] = PTDF_red[:, new_col]

    PTDF = np.round(PTDF, 6)
    PTDF[np.abs(PTDF) < 1e-8] = 0.0
    mpc.PTDF = PTDF

    mpc.PTDF_Gen = np.zeros((NL, mpc.NG))
    for i, gen in enumerate(mpc.generators):
        mpc.PTDF_Gen[:, i] = PTDF[:, gen.bus - 1]


def derive_piecewise_costs(mpc: CaseMPC, n_segments: int = 3) -> None:
    """
    由二次成本推导 PWL 与 `cost_var`、启停等，写回 `GenCostData`。
    """
    mpc.piecewise_costs = {}
    for i, (gen, cost) in enumerate(zip(mpc.generators, mpc.gen_costs)):
        P_lo, P_hi = gen.Pmin, gen.Pmax
        a, b, c_ = cost.cost_a, cost.cost_b, cost.cost_c
        dP = max(P_hi - P_lo, 1e-6)

        c_at_pmin = a * P_lo**2 + b * P_lo + c_
        c_at_pmax = a * P_hi**2 + b * P_hi + c_

        fuel_price = float(cost.fuel_price)
        cost.cost_nl = fuel_price * c_at_pmin
        cost.startup = fuel_price * (
            float(cost.startup_fuel)
            if cost.startup_fuel is not None
            else 2.0 * c_
        )
        cost.shutdown = fuel_price * (
            float(cost.shutdown_fuel)
            if cost.shutdown_fuel is not None
            else (
                float(cost.startup_fuel)
                if cost.startup_fuel is not None
                else 2.0 * c_
            )
        )
        cost.cost_var = fuel_price * (c_at_pmax - c_at_pmin) / dP

        bp = np.linspace(P_lo, P_hi, n_segments + 1)
        midpoints = 0.5 * (bp[:-1] + bp[1:])
        slopes = 2.0 * a * midpoints + b
        widths = np.diff(bp)

        slopes = fuel_price * slopes

        cost.pwl_slopes = slopes.tolist()
        cost.pwl_widths = widths.tolist()

        mpc.piecewise_costs[i] = {
            "breakpoints": bp,
            "slopes": slopes,
            "widths": widths,
            "fixed_cost": cost.cost_nl,
            "startup_cost": cost.startup,
            "shutdown_cost": cost.shutdown,
            "cost_var": cost.cost_var,
        }


def get_line_limits(mpc: CaseMPC) -> np.ndarray:
    """线路热极限 (NL,) 单位 pu（= rateA / baseMVA）。"""
    return np.array([br.rateA for br in mpc.branches], dtype=float) / mpc.baseMVA


def get_gen_params_for_thermal(mpc: CaseMPC, gen_idx: int) -> Dict[str, Any]:
    """转 `GeneratorParams` 的字段字典。"""
    gen = mpc.generators[gen_idx]
    cost = mpc.gen_costs[gen_idx]
    return {
        "P_max": gen.Pmax,
        "P_min": gen.Pmin,
        "R_up": cost.ramp_up,
        "R_down": cost.ramp_down,
        "T_on_min": gen.T_on_min,
        "T_off_min": gen.T_off_min,
        "cost_var": cost.cost_var,
        "cost_su": cost.startup,
        "cost_sd": cost.shutdown,
        "cost_nl": cost.cost_nl,
        "pwl_slopes": cost.pwl_slopes,
        "pwl_widths": cost.pwl_widths,
        "T": mpc.NT,
        "node_bus": gen.bus,
    }
