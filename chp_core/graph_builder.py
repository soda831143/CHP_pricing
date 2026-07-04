"""
DAG 构建器：为每台机组枚举合法的 ON 区间与 OFF 弧，
并计算每条 ON 边的固定成本 C_fix。

DAG 节点语义
------------
节点 t ∈ {0, 1, ..., T} 表示"机组在时段 t 之前处于 OFF 状态"。
  - 节点 0：源节点（机组在调度开始前关机，初始状态为 OFF）
  - 节点 T：汇节点（调度结束）

DAG 边类型
----------
ON 弧  (t_start, t_end+1)：机组在区间 [t_start, t_end] 内持续运行。
  - 合法条件：t_end - t_start + 1 ≥ MUT
  - 前端距离：初始关机状态默认已满足 MDT；后续停机间隔由 OFF 弧约束。
  - 后端距离：T - 1 - t_end = 0 或 T - 1 - t_end ≥ MDT
  - 流量变量：z_{i,e} ∈ [0,1]
  - 固定成本：C_fix = C_SU [+ C_SD] + duration * C_NL
    （仅当 b < T-1 即区间后有停机时才含 C_SD）

OFF 弧 (t1, t2)：机组在时段 [t1, t2-1] 内保持关机。
  - 合法条件：t2 - t1 == 0（零长度，哑弧）或 t2 - t1 ≥ MDT
  - 流量变量：w_{t1→t2} ≥ 0（无出力，无固定成本）

流量守恒
--------
对每个内部节点 t ∈ {1,...,T-1}：
  Σ_{e 进入 t} z_e = Σ_{e 离开 t} z_e
源节点约束：
  Σ_{e 离开 0} z_e = 1
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

from models.generator import GeneratorParams


@dataclass(frozen=True)
class OnInterval:
    """代表一条 ON 弧的元数据。"""
    a: int          # 开机起始（全局 0-indexed，含）
    b: int          # 开机结束（全局 0-indexed，含）
    c_fix: float    # 固定成本 C_SU [+ C_SD] + duration * C_NL
    initial_online: bool = False

    @property
    def duration(self) -> int:
        return self.b - self.a + 1

    @property
    def node_from(self) -> int:
        """DAG 中 ON 弧的起始节点（= a）"""
        return self.a

    @property
    def node_to(self) -> int:
        """DAG 中 ON 弧的终止节点（= b + 1）"""
        return self.b + 1


@dataclass(frozen=True)
class OffArc:
    """代表一条 OFF 弧（单纯关机停留）的元数据。"""
    t_from: int     # 离开节点
    t_to: int       # 到达节点（t_to > t_from）
    c_fix: float = 0.0

    @property
    def duration(self) -> int:
        return self.t_to - self.t_from


@dataclass
class GeneratorDAG:
    """单台机组的完整 DAG 结构。"""
    params: GeneratorParams
    on_intervals: List[OnInterval]
    off_arcs: List[OffArc]

    @property
    def T(self) -> int:
        return self.params.T

    @property
    def n_on(self) -> int:
        return len(self.on_intervals)

    @property
    def n_off(self) -> int:
        return len(self.off_arcs)

    @property
    def n_edges(self) -> int:
        return self.n_on + self.n_off

    @property
    def n_v_vars(self) -> int:
        """所有 ON 弧上差分变量 v 的总数。"""
        return sum(iv.duration for iv in self.on_intervals)


class DAGBuilder:
    """
    为单台机组构建时间展开 DAG。

    用法
    ----
    dag = DAGBuilder.build(params)
    """

    @staticmethod
    def build(params: GeneratorParams) -> GeneratorDAG:
        """构建机组的完整 DAG（ON 区间 + OFF 弧）。"""
        on_intervals = DAGBuilder._enumerate_on_intervals(params)
        off_arcs = DAGBuilder._enumerate_off_arcs(params, on_intervals)
        return GeneratorDAG(
            params=params,
            on_intervals=on_intervals,
            off_arcs=off_arcs,
        )

    @staticmethod
    def _enumerate_on_intervals(params: GeneratorParams) -> List[OnInterval]:
        """
        枚举所有合法的 ON 区间 [a, b]。

        合法条件（与 ThermalUnit.enumerate_on_intervals 对齐）：
          (1) 区间长度 ≥ T_on_min
          (2) 前端：初始关机状态默认已满足 T_off_min；任意首次启动时刻均合法
          (3) 后端：b = T-1 或 (T-1-b) ≥ T_off_min
        """
        T = params.T
        T_on = params.T_on_min
        T_off = params.T_off_min
        result: List[OnInterval] = []

        initial_on = params.initial_status == 1
        residual_off = max(0, T_off - int(params.initial_down_time))

        if initial_on:
            for b in range(T):
                duration = b + 1
                has_shutdown = (b < T - 1)
                if has_shutdown and int(params.initial_up_time) + duration < T_on:
                    continue
                space_after = T - 1 - b
                if has_shutdown and space_after < T_off:
                    continue
                c_fix = duration * params.cost_nl
                if has_shutdown:
                    c_fix += params.cost_sd
                result.append(OnInterval(a=0, b=b, c_fix=c_fix, initial_online=True))

        for a in range(T):
            if initial_on and a == 0:
                continue
            if (not initial_on) and a < residual_off:
                continue
            for b in range(a + T_on - 1, T):
                # 后端停机空间检查
                space_after = T - 1 - b
                if space_after != 0 and space_after < T_off:
                    continue
                duration = b - a + 1
                has_shutdown = (b < T - 1)
                c_fix = params.interval_fix_cost(duration, include_shutdown=has_shutdown)
                result.append(OnInterval(a=a, b=b, c_fix=c_fix))

        return result

    @staticmethod
    def _enumerate_off_arcs(
        params: GeneratorParams,
        on_intervals: List[OnInterval],
    ) -> List[OffArc]:
        """
        枚举所有合法的 OFF 弧 (t1 → t2)。

        节点集合 {0, 1, ..., T}。
        一条 OFF 弧从节点 t1 到节点 t2（t2 > t1）合法当且仅当：
          t2 - t1 ≥ T_off_min  或  t1 = 0  或  t2 = T

        实现：对 ON 区间的终节点集合与起始节点集合，
        枚举两两之间满足条件的 OFF 弧；同时加上从源(0)到各起始节点
        以及从各终节点到汇(T)的 OFF 弧。
        """
        T = params.T
        T_off = params.T_off_min

        # 所有合法的 OFF 弧起始节点（ON 弧的终节点 b+1，加上源节点 0）
        # 所有合法的 OFF 弧终止节点（ON 弧的起始节点 a，加上汇节点 T）
        from_nodes = sorted({0} | {iv.node_to for iv in on_intervals})
        to_nodes   = sorted({T} | {iv.node_from for iv in on_intervals})

        seen = set()
        result: List[OffArc] = []

        for t1 in from_nodes:
            for t2 in to_nodes:
                if t2 <= t1:
                    continue
                gap = t2 - t1
                # 零长度哑弧（t1 = t2 不会出现，gap ≥ 1）
                c_fix = 0.0
                if t1 == 0 and params.initial_status == 1:
                    if params.initial_power > params.SD_ramp + 1e-8:
                        continue
                    if gap < T_off and t2 != T:
                        continue
                    c_fix = params.cost_sd
                # 合法：gap ≥ MDT 或 t1 = 0（初始已离线）或 t2 = T（结尾）
                if gap >= T_off or (t1 == 0 and params.initial_status == 0) or t2 == T:
                    key = (t1, t2)
                    if key not in seen:
                        seen.add(key)
                        result.append(OffArc(t_from=t1, t_to=t2, c_fix=c_fix))

        return result
