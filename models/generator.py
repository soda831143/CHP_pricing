"""
发电机参数数据类。

支持两种成本模式：
  单段线性  (is_single_segment == True)  : 使用 cost_var ($/MWh) — 弦斜率近似
  分段线性  (is_single_segment == False) : 使用 pwl_slopes / pwl_widths

__post_init__ 中执行两个物理鲁棒性修正：
  SD_ramp = max(SD_ramp, P_min)  ← 防止停机约束与容量下限矛盾
  SU_ramp = max(SU_ramp, P_min)  ← 防止启动约束与容量下限矛盾
"""

from __future__ import annotations
import sys
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class GeneratorParams:
    """
    火电机组参数（原空间 CHP 框架）。

    功率单位：MW
    成本单位：$（启停）或 $/MWh（可变/空载）
    """
    P_max: float          # 最大出力 (MW)
    P_min: float          # 最小技术出力 (MW)
    R_up: float           # 向上爬坡速率 (MW/h)
    R_down: float         # 向下滑坡速率 (MW/h)
    T_on_min: int         # 最小连续开机时段数
    T_off_min: int        # 最小连续停机时段数
    cost_var: float       # 单段线性可变成本 ($/MWh)，弦斜率近似
    cost_su: float        # 热启动成本 ($)
    cost_sd: float        # 停机成本 ($)
    cost_nl: float        # 空载成本 = C(P_min)（每开机时段）($/h)
    T: int                # 调度总时段数
    node_bus: int = 1     # 所在节点（1-indexed）

    # 启动/停机爬坡限制（若未单独指定，默认等于 R_up / R_down）
    SU_ramp: float = field(default=0.0)
    SD_ramp: float = field(default=0.0)

    unit_id: str = ""     # 机组标识符（可选）

    # Initial condition before the first modeled period.  The default matches
    # the original benchmark convention: initially offline with minimum
    # down-time already satisfied.
    initial_status: int = 0
    initial_power: float = 0.0
    initial_up_time: int = 0
    initial_down_time: int = 10**6

    # 分段线性成本（K 段；若为空则退化为单段线性 cost_var）
    # pwl_slopes[k] : 第 k 段的边际成本斜率 ($/MWh)，单调不减（凸成本）
    # pwl_widths[k] : 第 k 段的容量宽度 (MW)
    # 区间：[P_min + Σ_{j<k} widths[j], P_min + Σ_{j≤k} widths[j]]
    pwl_slopes: List[float] = field(default_factory=list)
    pwl_widths: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        # SU/SD_ramp 默认值：根据 MATLAB 原文，(Pmax+Pmin)/2
        if self.SU_ramp <= 0.0:
            self.SU_ramp = (self.P_max + self.P_min) / 2.0
        if self.SD_ramp <= 0.0:
            self.SD_ramp = (self.P_max + self.P_min) / 2.0

        # 鲁棒性修正：防止 LP 因物理参数矛盾而不可行
        self.SD_ramp = max(self.SD_ramp, self.P_min)
        self.SU_ramp = max(self.SU_ramp, self.P_min)

        # 若提供了 pwl 数据，确保两个列表等长
        if self.pwl_slopes or self.pwl_widths:
            assert len(self.pwl_slopes) == len(self.pwl_widths), (
                f"pwl_slopes ({len(self.pwl_slopes)}) 与 "
                f"pwl_widths ({len(self.pwl_widths)}) 长度不一致"
            )

        self.initial_status = int(round(self.initial_status))
        if self.initial_status not in (0, 1):
            raise ValueError("initial_status must be 0 or 1")
        if self.initial_status == 0:
            self.initial_power = 0.0
            self.initial_up_time = 0
            self.initial_down_time = max(0, int(self.initial_down_time))
        else:
            self.initial_power = float(self.initial_power)
            if self.initial_power < self.P_min - 1e-8 or self.initial_power > self.P_max + 1e-8:
                raise ValueError(
                    f"initial_power={self.initial_power} outside "
                    f"[P_min,P_max]=[{self.P_min},{self.P_max}] for online unit"
                )
            self.initial_up_time = max(1, int(self.initial_up_time))
            self.initial_down_time = 0

    # ── 成本模式属性 ──────────────────────────────────────────────────────────

    @property
    def n_segments(self) -> int:
        """分段线性成本的段数；0 或 1 表示单段线性（退化为 cost_var）。"""
        return len(self.pwl_slopes)

    @property
    def is_single_segment(self) -> bool:
        """True → 使用 cost_var 单段近似；False → 使用 pwl_slopes / pwl_widths。"""
        return self.n_segments <= 1

    def get_pwl_segments(self) -> List[Tuple[float, float]]:
        """
        返回 [(slope_k, width_k), ...] 列表。

        单段退化时返回 [(cost_var, P_max - P_min)]，
        确保代码可以统一用此接口迭代所有段。
        """
        if self.is_single_segment:
            return [(self.cost_var, self.P_max - self.P_min)]
        return list(zip(self.pwl_slopes, self.pwl_widths))

    def pwl_intercepts(self) -> List[float]:
        """
        计算每段的截距 b_k，保证在段边界处成本函数连续。

        对段 k，在出力 P_min + Σ_{j<k} widths[j] 处两段值相等：
          b_k = b_{k-1} + (s_{k-1} - s_k) · P_break_{k-1}
        这与 MATLAB cal_piecewise_linear_function.m 的逻辑一致。

        截距意义：单位输出（含 P_min 基准）的成本 = s_k · p + b_k，
        但在透视 LP 中需乘以 z_e。
        """
        segs = self.get_pwl_segments()
        K = len(segs)
        intercepts = [0.0] * K
        # 第 0 段截距：成本 = s_0 · (p - P_min) + 0，即截距参考 P_min 处为 0
        # （固定成本 cost_nl 已单独用 z_e 计入目标）
        # 各段截距通过连续性递推
        cumulative_w = 0.0
        for k in range(1, K):
            s_prev = segs[k - 1][0]
            s_curr = segs[k][0]
            w_prev = segs[k - 1][1]
            cumulative_w += w_prev
            intercepts[k] = intercepts[k - 1] + (s_prev - s_curr) * cumulative_w
        return intercepts

    # ── 固定成本辅助 ──────────────────────────────────────────────────────────

    @property
    def c_fix(self) -> float:
        """单次开-关周期的固定成本（不含持续时长相关的空载成本，仅启+停）。"""
        return self.cost_su + self.cost_sd

    def interval_fix_cost(self, duration: int, include_shutdown: bool = True) -> float:
        """
        开机区间 [a, b] 的完整固定成本。

        Parameters
        ----------
        duration         : b - a + 1
        include_shutdown : 区间结束后是否发生停机（b < T-1 时为 True）。
                           若区间延伸到调度末尾 (b = T-1)，无停机事件，不收 C_SD。

        Returns
        -------
        C_SU [+ C_SD] + duration * C_NL
        """
        cost = self.cost_su + duration * self.cost_nl
        if include_shutdown:
            cost += self.cost_sd
        return cost


def from_case6ww(gen_idx: int, T: int = 24,
                 cost_nl: Optional[float] = None,
                 n_segments: int = 3) -> GeneratorParams:
    """
    从 case6ww 数据构建 GeneratorParams。

    Args
    ----
    gen_idx    : 0-indexed 发电机编号（0=G1, 1=G2, 2=G3）
    T          : 调度时段数（默认 24）
    cost_nl    : 空载成本覆盖值 $/h（None 表示使用 case6ww 内置派生值 C(P_min)）
    n_segments : 分段线性成本的段数（默认 3）
    """
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)

    from data.cases.case_6ww import build_case_6ww, get_gen_params_for_thermal

    mpc = build_case_6ww(n_segments=n_segments)
    raw = get_gen_params_for_thermal(mpc, gen_idx)

    return GeneratorParams(
        P_max      = raw["P_max"],
        P_min      = raw["P_min"],
        R_up       = raw["R_up"],
        R_down     = raw["R_down"],
        T_on_min   = raw["T_on_min"],
        T_off_min  = raw["T_off_min"],
        cost_var   = raw["cost_var"],
        cost_su    = raw["cost_su"],
        cost_sd    = raw["cost_sd"],
        cost_nl    = cost_nl if cost_nl is not None else raw["cost_nl"],
        pwl_slopes = raw["pwl_slopes"],
        pwl_widths = raw["pwl_widths"],
        T          = T,
        node_bus   = raw["node_bus"],
        unit_id    = f"G{gen_idx + 1}",
    )


def load_all_case6ww_generators(T: int = 24,
                                cost_nl: Optional[float] = None,
                                n_segments: int = 3) -> List[GeneratorParams]:
    """
    返回 case6ww 全部 3 台机组的 GeneratorParams 列表。

    cost_nl=None    → 使用 case6ww 内置空载成本 C(P_min)
    cost_nl=0.0     → 强制覆盖为 0（无空载成本场景）
    n_segments=1    → 使用单段线性（cost_var 弦斜率，pwl_slopes 为空）
    n_segments=3    → 使用 3 段分段线性（默认）
    """
    return [from_case6ww(i, T=T, cost_nl=cost_nl, n_segments=n_segments)
            for i in range(3)]


def from_case30ww(
    gen_idx: int,
    T: int = 24,
    cost_nl: Optional[float] = None,
    n_segments: int = 3,
) -> GeneratorParams:
    """
    从 `data.cases.case_30ww` 构建第 `gen_idx` 台（0 起）机组的 `GeneratorParams`。
    共 6 台机（对应 IEEE 30-bus 的 6 个 gen）。
    """
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)

    from data.cases.case_30ww import build_case_30ww, get_gen_params_for_thermal

    mpc = build_case_30ww(n_segments=n_segments)
    raw = get_gen_params_for_thermal(mpc, gen_idx)
    return GeneratorParams(
        P_max=raw["P_max"],
        P_min=raw["P_min"],
        R_up=raw["R_up"],
        R_down=raw["R_down"],
        T_on_min=raw["T_on_min"],
        T_off_min=raw["T_off_min"],
        cost_var=raw["cost_var"],
        cost_su=raw["cost_su"],
        cost_sd=raw["cost_sd"],
        cost_nl=cost_nl if cost_nl is not None else raw["cost_nl"],
        pwl_slopes=raw["pwl_slopes"],
        pwl_widths=raw["pwl_widths"],
        T=T,
        node_bus=raw["node_bus"],
        unit_id=f"G{gen_idx + 1}",
    )


def load_all_case30ww_generators(
    T: int = 24,
    cost_nl: Optional[float] = None,
    n_segments: int = 3,
) -> List[GeneratorParams]:
    """case_30ww 全部 6 台机组（单次 `build_case_30ww`）。"""
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)
    from data.cases.case_30ww import build_case_30ww, get_gen_params_for_thermal

    mpc = build_case_30ww(n_segments=n_segments)
    out: List[GeneratorParams] = []
    for i in range(mpc.NG):
        raw = get_gen_params_for_thermal(mpc, i)
        out.append(
            GeneratorParams(
                P_max=raw["P_max"],
                P_min=raw["P_min"],
                R_up=raw["R_up"],
                R_down=raw["R_down"],
                T_on_min=raw["T_on_min"],
                T_off_min=raw["T_off_min"],
                cost_var=raw["cost_var"],
                cost_su=raw["cost_su"],
                cost_sd=raw["cost_sd"],
                cost_nl=cost_nl if cost_nl is not None else raw["cost_nl"],
                pwl_slopes=raw["pwl_slopes"],
                pwl_widths=raw["pwl_widths"],
                T=T,
                node_bus=raw["node_bus"],
                unit_id=f"G{i + 1}",
            )
        )
    return out


def from_case118ww(
    gen_idx: int,
    T: int = 24,
    cost_nl: Optional[float] = None,
    n_segments: int = 3,
) -> GeneratorParams:
    """从 `case_118ww` 构建第 `gen_idx` 台机组（0 起，共 54 台）。"""
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)

    from data.cases.case_118ww import build_case_118ww, get_gen_params_for_thermal

    mpc = build_case_118ww(n_segments=n_segments)
    raw = get_gen_params_for_thermal(mpc, gen_idx)
    return GeneratorParams(
        P_max=raw["P_max"],
        P_min=raw["P_min"],
        R_up=raw["R_up"],
        R_down=raw["R_down"],
        T_on_min=raw["T_on_min"],
        T_off_min=raw["T_off_min"],
        cost_var=raw["cost_var"],
        cost_su=raw["cost_su"],
        cost_sd=raw["cost_sd"],
        cost_nl=cost_nl if cost_nl is not None else raw["cost_nl"],
        pwl_slopes=raw["pwl_slopes"],
        pwl_widths=raw["pwl_widths"],
        T=T,
        node_bus=raw["node_bus"],
        unit_id=f"G{gen_idx + 1}",
    )


def load_all_case118ww_generators(
    T: int = 24,
    cost_nl: Optional[float] = None,
    n_segments: int = 3,
) -> List[GeneratorParams]:
    """case_118ww 全部 54 台机组（单次 `build_case_118ww`）。"""
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
    if _proj_dir not in sys.path:
        sys.path.insert(0, _proj_dir)
    from data.cases.case_118ww import build_case_118ww, get_gen_params_for_thermal

    mpc = build_case_118ww(n_segments=n_segments)
    out: List[GeneratorParams] = []
    for i in range(mpc.NG):
        raw = get_gen_params_for_thermal(mpc, i)
        out.append(
            GeneratorParams(
                P_max=raw["P_max"],
                P_min=raw["P_min"],
                R_up=raw["R_up"],
                R_down=raw["R_down"],
                T_on_min=raw["T_on_min"],
                T_off_min=raw["T_off_min"],
                cost_var=raw["cost_var"],
                cost_su=raw["cost_su"],
                cost_sd=raw["cost_sd"],
                cost_nl=cost_nl if cost_nl is not None else raw["cost_nl"],
                pwl_slopes=raw["pwl_slopes"],
                pwl_widths=raw["pwl_widths"],
                T=T,
                node_bus=raw["node_bus"],
                unit_id=f"G{i + 1}",
            )
        )
    return out
