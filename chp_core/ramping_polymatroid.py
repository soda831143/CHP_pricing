"""
爬坡广义多面体（RampingPolymatroid）。

本模块在本地 lib/thermal_unit.py 的 ConditionalGPolymatroid 基础上，
通过子类 CHPConditionalGPolymatroid 修正三处边界，确保 Phase 2
的广义多面体与 Phase 1 的透视缩放约束在数学上完全等价
（对照 main(4).tex Lemma boundary, \\ref{lem:boundary}）：

修正点 1：SU_ramp 作用于启动时段（局部索引 0）
────────────────────────────────────────────────
u_max[0] = SU_ramp；u_max[τ>0] = R_up
对应 Phase 1 透视约束 1：z·P_min ≤ v_0 ≤ z·SU_ramp
（基类已设 u_min[0] = P_min，此处只需覆盖上界）

修正点 2：SD_ramp 约束最后时段总出力 x_max[n-1]
────────────────────────────────────────────────
x_max[n-1] = min(x_max[n-1], SD_ramp)
对应 Phase 1 透视约束 4：Σ_{k=0}^{n-1} v_k ≤ z·SD_ramp
（基类用 R_down，CHP 需要用 SD_ramp 替换）

修正点 3：x_max[0] = min(P_max, SU_ramp)
────────────────────────────────────────────────
基类设 x_max[0] = min(P_max, R_up)，但 CHP 中启动上界是 SU_ramp。
v_0 ≤ SU_ramp ⟹ x_0 = v_0 ≤ SU_ramp，同时 x_0 ≤ P_max。
"""

from __future__ import annotations
import sys
import os
from typing import Set, Union, FrozenSet

import numpy as np

# chp_core/ → chp_project/（项目根）
_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from lib.thermal_unit import ConditionalGPolymatroid, ThermalParameters
from models.generator import GeneratorParams

AnySet = Union[Set[int], FrozenSet[int]]


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：GeneratorParams → ThermalParameters
# ─────────────────────────────────────────────────────────────────────────────

def _to_thermal_params(params: GeneratorParams) -> ThermalParameters:
    return ThermalParameters(
        P_max     = params.P_max,
        P_min     = params.P_min,
        R_up      = params.R_up,
        R_down    = params.R_down,
        T_on_min  = params.T_on_min,
        T_off_min = params.T_off_min,
        cost_var  = params.cost_var,
        cost_su   = params.cost_su,
        T         = params.T,
        node_bus  = params.node_bus,
        cost_sd   = params.cost_sd,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CHPConditionalGPolymatroid：修正 SU_ramp 与 SD_ramp 边界
# ─────────────────────────────────────────────────────────────────────────────

class CHPConditionalGPolymatroid(ConditionalGPolymatroid):
    """
    ConditionalGPolymatroid 子类，修正启停爬坡边界。

    确保 Phase 2 的 GP 与 Phase 1 透视约束（z_e=1 时）精确等价。

    Parameters
    ----------
    params   : ThermalParameters
    a, b     : 全局 0-indexed 开机区间
    SU_ramp  : 启动爬坡限制（仅约束局部 τ=0）
    SD_ramp  : 停机爬坡限制（约束区间末尾总出力 x_max[n-1]）
    include_shutdown : 该 ON 区间结束后是否发生停机事件
    """

    def __init__(self, params: ThermalParameters, a: int, b: int,
                 SU_ramp: float, SD_ramp: float,
                 include_shutdown: bool = True) -> None:
        self._SU_ramp = SU_ramp
        self._SD_ramp = SD_ramp
        self._include_shutdown = include_shutdown
        super().__init__(params, a, b)

    def _build_v_bounds(self):
        u_min, u_max = super()._build_v_bounds()
        # 修正点 1：τ=0 上界用 SU_ramp（而非 R_up）
        # 基类已设 u_min[0] = P_min，此处只覆盖上界
        u_max[0] = self._SU_ramp
        return u_min, u_max

    def _build_prefix_bounds(self):
        x_min, x_max = super()._build_prefix_bounds()
        n = self._n
        # 修正点 3：x_max[0] = min(P_max, SU_ramp)
        # 基类设 x_max[0] = min(P_max, R_up)，但 CHP 中启动上界是 SU_ramp
        x_max[0] = min(x_max[0], self._SU_ramp)
        # 确保可行性：x_min[0] ≤ x_max[0]
        # x_min[0] = P_min（基类已设），x_max[0] ≥ P_min 由 SU_ramp = max(SU_ramp, P_min) 保证
        x_min[0] = min(x_min[0], x_max[0])

        # 修正点 2：停机约束，最后时段总出力 ≤ SD_ramp。
        # 仅当区间后确有停机事件时施加；若 b = T-1，则没有期末停机。
        if self._include_shutdown:
            x_max[n - 1] = min(x_max[n - 1], self._SD_ramp)
            x_min[n - 1] = min(x_min[n - 1], x_max[n - 1])
        return x_min, x_max


# ─────────────────────────────────────────────────────────────────────────────
# RampingPolymatroid：公开接口
# ─────────────────────────────────────────────────────────────────────────────

class RampingPolymatroid:
    """
    固定开机区间 [a, b] 的爬坡广义多面体（差分变量 v 空间）。

    Parameters
    ----------
    params : GeneratorParams
    a      : 区间起始（全局 0-indexed，含）
    b      : 区间结束（全局 0-indexed，含）
    """

    def __init__(
        self,
        params: GeneratorParams,
        a: int,
        b: int,
        include_shutdown: bool = True,
    ) -> None:
        tp = _to_thermal_params(params)
        self._gpoly = CHPConditionalGPolymatroid(
            params  = tp,
            a       = a,
            b       = b,
            SU_ramp = params.SU_ramp,
            SD_ramp = params.SD_ramp,
            include_shutdown = include_shutdown,
        )
        self.a = a
        self.b = b

    @property
    def T(self) -> int:
        return self._gpoly.T

    def f_eval(self, S: AnySet) -> float:
        return self._gpoly.b(S)

    def g_eval(self, S: AnySet) -> float:
        return self._gpoly.p(S)

    def greedy_maximize(self, w: np.ndarray) -> np.ndarray:
        """
        在广义多面体上求解 max w^T v（b* 算法，正确处理正负混合权重）。
        """
        return self._gpoly.greedy_maximize(w)
