"""
网络拓扑模型（NetworkModel）。

两种实现：
  SingleNodeNetwork  ——单节点（集中式），所有机组接入同一母线，
                        系统约束退化为纯功率平衡等式。
                        对偶变量 λ*(T,)，对所有机组相同。

  PTDFNetwork        ——多节点 DC 潮流网络，支路潮流用 PTDF 矩阵线性表达。
                        代码采用 PTDF reduced form：每个时段保留一个
                        系统功率平衡等式，并追加线路容量不等式。
                        节点 LMP 由系统平衡对偶与线路对偶后处理恢复，
                        等价于显式 DC-OPF 节点平衡对偶。

设计原则
────────
PrimalCHPLP 与 ScheduleRunMILP 均只与 NetworkModel 接口交互。
切换到多节点时只需替换 NetworkModel 实例。

关键接口
────────
  network.T                : int          调度时段数
  network.N_bus            : int          节点数
  network.demand           : (N_bus, T)   各节点负荷（MW）
  network.sys_demand       : (T,)         系统总负荷（MW）
  network.is_single_node   : bool         是否为单节点
  network.gen_bus_idx(i)   : int          机组 i 的节点索引（0-indexed）

  仅 PTDFNetwork：
  network.PTDF             : (N_line, N_bus)  功率转移分配因子矩阵（pu/pu）
  network.PTDF_Gen         : (N_line, N_gen)  机组注入的 PTDF 矩阵
  network.F_max            : (N_line,)        支路容量上限（MW）
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


def _extend_time_axis(arr: np.ndarray, T: int) -> np.ndarray:
    """
    Return a physically reasonable ``T``-period load trajectory from the base
    daily profile.

    All case_*ww data currently provide a 24-hour load profile.  The scaling
    experiments use T=48/72/96 to study algorithmic growth.  For horizons
    longer than 24 hours, keep the same intra-day valley/peak trend and apply
    mild day-to-day multipliers.  This avoids a mechanically identical repeat
    while keeping peak load within the tested UC feasibility envelope.
    """
    data = np.asarray(arr, dtype=float)
    if data.shape[-1] >= T:
        return data[..., :T].copy()

    base_len = data.shape[-1]
    out_shape = data.shape[:-1] + (T,)
    out = np.empty(out_shape, dtype=float)
    # Four-day cycle: normal day, slightly higher weekday, slightly lower day,
    # and another high-ramp day.  The amplitudes are deliberately modest so
    # congestion/ramping effects change without turning the case into a
    # different adequacy study.
    day_factors = (1.00, 1.02, 0.98, 1.03)
    for t in range(T):
        day = t // base_len
        hour = t % base_len
        out[..., t] = data[..., hour] * day_factors[day % len(day_factors)]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 抽象基类
# ─────────────────────────────────────────────────────────────────────────────

class NetworkModel(ABC):
    """
    网络拓扑抽象接口。所有求解器通过此接口访问网络数据，
    不直接感知底层拓扑细节。
    """

    @property
    @abstractmethod
    def T(self) -> int: ...

    @property
    @abstractmethod
    def N_bus(self) -> int: ...

    @property
    @abstractmethod
    def demand(self) -> np.ndarray:
        """各节点负荷矩阵 (N_bus, T)，单位 MW。"""
        ...

    @property
    def sys_demand(self) -> np.ndarray:
        """系统总负荷 (T,) = demand.sum(axis=0)，单位 MW。"""
        return self.demand.sum(axis=0)

    @property
    def is_single_node(self) -> bool:
        return self.N_bus == 1

    def gen_bus_idx(self, gen_idx: int) -> int:
        """
        机组 gen_idx（0-indexed）所在节点的 0-indexed 索引。

        单节点模式下所有机组返回 0；
        多节点模式由子类存储 gen_bus_map 并覆盖此方法。
        """
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# 单节点网络
# ─────────────────────────────────────────────────────────────────────────────

class SingleNodeNetwork(NetworkModel):
    """
    单节点（集中式）网络：所有发电机接入同一母线，无线路约束。

    系统约束退化为：
        Σ_i p_{i,τ} = demand_τ,  ∀τ

    Parameters
    ----------
    demand_vec : (T,) 系统总需求（MW）
    """

    def __init__(self, demand_vec: np.ndarray) -> None:
        self._demand_vec = np.asarray(demand_vec, dtype=float)

    @property
    def T(self) -> int:
        return len(self._demand_vec)

    @property
    def N_bus(self) -> int:
        return 1

    @property
    def demand(self) -> np.ndarray:
        return self._demand_vec.reshape(1, -1)   # (1, T)

    @property
    def sys_demand(self) -> np.ndarray:
        return self._demand_vec                  # (T,)

    def __repr__(self) -> str:
        return (
            f"SingleNodeNetwork(T={self.T}, "
            f"demand_range=[{self._demand_vec.min():.1f}, "
            f"{self._demand_vec.max():.1f}] MW)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 多节点 PTDF 网络（完整实现）
# ─────────────────────────────────────────────────────────────────────────────

class PTDFNetwork(NetworkModel):
    """
    多节点 DC 潮流网络（PTDF 矩阵形式）。

    数学模型（PTDF reduced form）
    ----------------------------
    每时段保留一个系统功率平衡：
        Σ_i p_{i,τ} = Σ_n D_{n,τ}

    直流线路潮流（PTDF 形式，线路 l，时段 τ）：
        f_{l,τ} = Σ_i PTDF_Gen[l,i] · p_{i,τ}
                  - Σ_n PTDF[l,n] · D_{n,τ}

    线路容量约束：
        -F_max[l] ≤ f_{l,τ} ≤ F_max[l}

    展开后，线路约束用纯机组出力表达（消去 f 变量）：
        Σ_i PTDF_Gen[l,i]·p_{i,τ} ≤  F_max[l] + Σ_n PTDF[l,n]·D_{n,τ}
        Σ_i PTDF_Gen[l,i]·p_{i,τ} ≥ -F_max[l] + Σ_n PTDF[l,n]·D_{n,τ}

    对偶变量（LMP）
    --------------
    代码中不显式建立 N_bus × T 个节点平衡等式。定价 LP 求解后，
    用系统平衡对偶 λ_τ 与线路上下限对偶恢复节点边际电价：
        LMP[n,τ] = λ_τ + Σ_l PTDF[l,n]·(α[l,τ] - β[l,τ])
    这与显式 DC-OPF 节点平衡模型的节点对偶价格等价；DC 模型无损耗项。

    Parameters
    ----------
    demand_matrix : (N_bus, T) 各节点负荷（MW）
    PTDF          : (N_line, N_bus) 功率转移分配因子矩阵（pu/pu）
    F_max         : (N_line,) 线路容量上限（MW）
    gen_bus_map   : (N_gen,) 各机组所在节点的 0-indexed 索引（可选）
    PTDF_Gen      : (N_line, N_gen) 机组注入的 PTDF（可选，若无则从 PTDF + gen_bus_map 推导）
    """

    def __init__(
        self,
        demand_matrix: np.ndarray,
        PTDF:          np.ndarray,
        F_max:         np.ndarray,
        gen_bus_map:   Optional[List[int]] = None,
        PTDF_Gen:      Optional[np.ndarray] = None,
    ) -> None:
        self._demand   = np.asarray(demand_matrix, dtype=float)
        self._PTDF     = np.asarray(PTDF,          dtype=float)
        self._F_max    = np.asarray(F_max,         dtype=float)
        self._gen_bus  = list(gen_bus_map) if gen_bus_map is not None else []

        if PTDF_Gen is not None:
            self._PTDF_Gen = np.asarray(PTDF_Gen, dtype=float)
        elif gen_bus_map is not None:
            self._PTDF_Gen = self._PTDF[:, gen_bus_map]
        else:
            self._PTDF_Gen = None

        assert self._demand.ndim == 2, "demand_matrix 必须是 (N_bus, T) 二维矩阵"
        assert self._PTDF.shape[1] == self._demand.shape[0], \
            f"PTDF 列数 ({self._PTDF.shape[1]}) 必须等于节点数 N_bus ({self._demand.shape[0]})"

    @property
    def T(self) -> int:
        return self._demand.shape[1]

    @property
    def N_bus(self) -> int:
        return self._demand.shape[0]

    @property
    def N_line(self) -> int:
        return self._F_max.shape[0]

    @property
    def demand(self) -> np.ndarray:
        return self._demand

    @property
    def PTDF(self) -> np.ndarray:
        return self._PTDF

    @property
    def PTDF_Gen(self) -> Optional[np.ndarray]:
        return self._PTDF_Gen

    @property
    def F_max(self) -> np.ndarray:
        return self._F_max

    def gen_bus_idx(self, gen_idx: int) -> int:
        if self._gen_bus:
            return self._gen_bus[gen_idx]
        return 0

    def line_rhs(self) -> np.ndarray:
        """
        计算线路约束右端项 rhs[l, t]（MW）。

        线路 l 的实际容量上限（考虑负荷注入后的净可用容量）：
            rhs[l, t] = F_max[l] + Σ_n PTDF[l,n] · D_{n,t}

        约束形式：
            Σ_i PTDF_Gen[l,i] · p_{i,t}  ≤  rhs[l, t]   （上限）
            Σ_i PTDF_Gen[l,i] · p_{i,t}  ≥ -rhs[l, t] + 2·Σ_n PTDF[l,n]·D_{n,t}

        通常更简洁的写法（直接展开等价于）：
            PTDF_Gen · p_t ∈ [-F_max + PTDF·D_t,  F_max + PTDF·D_t]

        Returns
        -------
        rhs_pos : (N_line, T)  上界（pu → MW 已转换）
        rhs_neg : (N_line, T)  下界（负值）
        """
        load_term = self._PTDF @ self._demand   # (N_line, T) MW
        rhs_pos = (self._F_max[:, None] + load_term)    # (N_line, T)
        rhs_neg = (-self._F_max[:, None] + load_term)   # (N_line, T)
        return rhs_pos, rhs_neg

    def __repr__(self) -> str:
        return (
            f"PTDFNetwork(N_bus={self.N_bus}, T={self.T}, "
            f"N_line={self.N_line}, N_gen={len(self._gen_bus) if self._gen_bus else '?'})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────────────────────────────────────

def build_ptdf_network_from_case6ww(T: int = 24,
                                     congestion: str = "tight",
                                     fmax_scale: float | None = None) -> PTDFNetwork:
    """
    从 case6ww 数据构建多节点 PTDF 网络（11 支路 Wood & Wollenberg 拓扑）。

    参数
    ----
    T          : 时段数
    congestion : 拥塞程度
                 "tight"    — 线路容量接近 UC 最小可行值，容易阻塞
                 "moderate" — 适度裕度，部分线路可能阻塞
                 "relaxed"  — 所有线路容量极大（2000 MW），等效单节点
    fmax_scale : 直接缩放原始 rateA（覆盖 congestion 参数）

    使用方式
    --------
    >> net = build_ptdf_network_from_case6ww(T=24, congestion="tight")
    >> net = build_ptdf_network_from_case6ww(T=24, congestion="relaxed")
    """
    import sys, os
    _proj_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)

    from data.cases.case_6ww import build_case_6ww
    mpc = build_case_6ww()

    demand_matrix = _extend_time_axis(mpc.PD * mpc.baseMVA, T)
    rateA = np.array([br.rateA for br in mpc.branches], dtype=float)
    NL = mpc.NL

    if fmax_scale is not None:
        F_max = rateA * fmax_scale
    elif congestion == "tight":
        # 0.8× original rateA is the tightest tested setting that keeps the
        # 24-hour UC feasible while producing nonzero nodal price separation.
        F_max = rateA * 0.8
    elif congestion == "moderate":
        F_max = rateA
    elif congestion == "relaxed":
        F_max = np.full(NL, 2000.0)
    else:
        raise ValueError(f"Unknown congestion='{congestion}'")

    gen_bus_map = [gen.bus - 1 for gen in mpc.generators]

    return PTDFNetwork(
        demand_matrix = demand_matrix,
        PTDF          = mpc.PTDF,
        F_max         = F_max,
        gen_bus_map   = gen_bus_map,
        PTDF_Gen      = mpc.PTDF_Gen,
    )


def build_single_node_from_case6ww(T: int = 24) -> SingleNodeNetwork:
    """从 case6ww 数据构建单节点网络（所有母线负荷加总）。"""
    import sys
    import os
    _proj_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)

    from data.cases.case_6ww import build_case_6ww
    mpc = build_case_6ww()
    demand_vec = _extend_time_axis((mpc.PD * mpc.baseMVA).sum(axis=0), T)   # (T,) MW
    return SingleNodeNetwork(demand_vec)


def build_ptdf_network_from_case30ww(
    T: int = 24,
    congestion: str = "tight",
    fmax_scale: float | None = None,
) -> PTDFNetwork:
    """
    从 `case_30ww`（MATPOWER case30 拓扑 + `case_30ww.m` 负荷/机组）构建 PTDF 网络。

    congestion : "tight" 使用 1.3 倍算例内建限值，"moderate" 使用 2.0 倍，
                 "relaxed" 使用极大限值，近似退化为无阻塞网络。
    fmax_scale : 对线路 `rateA`（MVA）的统一乘子；非 None 时覆盖 congestion。
    """
    import os
    import sys

    _proj_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)

    from data.cases.case_30ww import build_case_30ww

    mpc = build_case_30ww()
    demand_matrix = _extend_time_axis(mpc.PD * mpc.baseMVA, T)
    rateA = np.array([br.rateA for br in mpc.branches], dtype=float)
    if fmax_scale is not None:
        F_max = rateA * fmax_scale
    elif congestion == "tight":
        # Standard case30 rateA is too tight for the 24-hour UC data.  The
        # 1.3x setting is the closest tested feasible congested case.
        F_max = rateA * 1.3
    elif congestion == "moderate":
        F_max = rateA * 2.0
    elif congestion == "relaxed":
        F_max = np.full(mpc.NL, 2000.0)
    else:
        raise ValueError(f"Unknown congestion='{congestion}'")
    gen_bus_map = [gen.bus - 1 for gen in mpc.generators]
    return PTDFNetwork(
        demand_matrix=demand_matrix,
        PTDF=mpc.PTDF,
        F_max=F_max,
        gen_bus_map=gen_bus_map,
        PTDF_Gen=mpc.PTDF_Gen,
    )


def build_ptdf_network_from_case118ww(
    T: int = 24,
    congestion: str = "tight",
    fmax_scale: float | None = None,
) -> PTDFNetwork:
    """
    从 `case_118ww` 构建 PTDF 网络。支路限值已含 `branch_capacity_map` 与默认大限值支路。

    congestion : "tight" 使用算例内建限值，"moderate" 放宽为 1.5 倍，
                 "relaxed" 使用极大限值，近似退化为无阻塞网络。
    """
    import os
    import sys

    _proj_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)

    from data.cases.case_118ww import build_case_118ww

    mpc = build_case_118ww()
    demand_matrix = _extend_time_axis(mpc.PD * mpc.baseMVA, T)
    rateA = np.array([br.rateA for br in mpc.branches], dtype=float)
    if fmax_scale is not None:
        F_max = rateA * fmax_scale
    elif congestion == "tight":
        F_max = rateA
    elif congestion == "moderate":
        F_max = rateA * 1.25
    elif congestion == "relaxed":
        F_max = np.full(mpc.NL, 5000.0)
    else:
        raise ValueError(f"Unknown congestion='{congestion}'")
    gen_bus_map = [gen.bus - 1 for gen in mpc.generators]
    return PTDFNetwork(
        demand_matrix=demand_matrix,
        PTDF=mpc.PTDF,
        F_max=F_max,
        gen_bus_map=gen_bus_map,
        PTDF_Gen=mpc.PTDF_Gen,
    )


def build_single_node_from_case30ww(T: int = 24) -> SingleNodeNetwork:
    import os
    import sys

    _proj_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)
    from data.cases.case_30ww import build_case_30ww

    mpc = build_case_30ww()
    demand_vec = _extend_time_axis((mpc.PD * mpc.baseMVA).sum(axis=0), T)
    return SingleNodeNetwork(demand_vec)


def build_single_node_from_case118ww(T: int = 24) -> SingleNodeNetwork:
    import os
    import sys

    _proj_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)
    from data.cases.case_118ww import build_case_118ww

    mpc = build_case_118ww()
    demand_vec = _extend_time_axis((mpc.PD * mpc.baseMVA).sum(axis=0), T)
    return SingleNodeNetwork(demand_vec)
