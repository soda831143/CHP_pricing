"""
火电子问题外层 DP 求解器（修复硬伤 2）。

核心修复：DAG 的节点是"合法开机区间"本身，而非"时段 t"。

原错误设计（违反马尔可夫性）：
  - 节点 = 时段 t，状态 dp[t] = 最大利润
  - 用 last_on_end[t] 记录"上一次停机时刻"
  → 问题：同一个 t 可由停机时长完全不同的路径到达，
           last_on_end[t] 只能记录一种情况，破坏无后效性。

正确 DAG 设计（本文件实现）：
  节点集合 = {SOURCE} ∪ {每个合法区间 I_k = (a_k, b_k)} ∪ {SINK}

  边：
    SOURCE → I_k        权重 = profit(I_k) - startup_cost(a_k)
                        条件 = I_k 前方有合法停机空间（a_k=0 或 a_k≥T_off_min）
                               注意：a_k 本身就是从调度起始时刻到开机的停机时长

    I_j → I_k           权重 = profit(I_k) - startup_cost(a_k - b_j - 1)
                        条件 = a_k - b_j - 1 ≥ T_off_min（两区间间隔合法）
                               此时停机时长 = a_k - b_j - 1（图结构确定，无歧义）

    I_k → SINK          权重 = 0
                        条件 = I_k 后方有合法停机空间（b_k=T-1 或 T-1-b_k≥T_off_min）

  在此 DAG 上求最长路径（最大总净利润）：
    - 图已是 DAG（区间按起点排序可得拓扑序）
    - 用拓扑排序 + DP 求解，O(I²) 时间，I 为合法区间数

  每条边上的停机时长由图的边本身唯一确定，彻底消除马尔可夫性问题。
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# 节点结构
# ─────────────────────────────────────────────────────────────────────────────

_SOURCE = -1   # 虚拟起点的节点 ID
_SINK   = -2   # 虚拟终点的节点 ID


@dataclass
class IntervalNode:
    """
    DAG 中对应一个合法开机区间的节点。

    node_id : 节点在节点列表中的索引（0-based）
    a, b    : 全局 0-indexed，开机区间 [a, b]（含）
    profit  : 该区间内贪心最优净利润（不含启动成本）
    """
    node_id: int
    a: int
    b: int
    profit: float


@dataclass
class DPState:
    """DP 状态：到达某节点时的最大累计净利润 + 路径回溯信息。"""
    best_profit: float = -1e15
    prev_node_id: Optional[int] = None   # 前驱节点 ID（_SOURCE / _SINK / 区间ID）
    # 到达此节点所使用的区间信息（仅对区间节点有意义）
    via_interval: Optional[Tuple[int, int]] = None


# ─────────────────────────────────────────────────────────────────────────────
# 主类
# ─────────────────────────────────────────────────────────────────────────────

class DPShortestPath:
    """
    在区间节点 DAG 上求最优启停区间组合（最大总净利润）。

    使用方式
    --------
    solver = DPShortestPath(T, on_intervals, interval_profits, startup_cost_fn, T_off_min)
    best_intervals, max_profit = solver.solve()
    """

    def __init__(
        self,
        T: int,
        on_intervals:      List[Tuple[int, int]],
        interval_profits:  Dict[Tuple[int, int], float],
        startup_cost_fn:   Callable[[int], float],
        T_off_min: int,
    ):
        """
        Args
        ----
        T                : 总调度时段数
        on_intervals     : 合法开机区间列表 [(a, b), ...]（0-indexed，含）
        interval_profits : 各区间的贪心最优净利润（不含启动成本）
        startup_cost_fn  : f(off_duration: int) → float  启动成本
        T_off_min        : 最小连续停机时段数（用于验证两区间间隔合法性）
        """
        self.T               = T
        self.T_off_min       = T_off_min
        self.startup_cost_fn = startup_cost_fn

        # 按区间起点 a 升序排列，保证拓扑有序（a 小的节点在前）
        sorted_ivls = sorted(on_intervals, key=lambda x: (x[0], x[1]))

        # 构建区间节点列表
        self.nodes: List[IntervalNode] = [
            IntervalNode(
                node_id = idx,
                a       = a,
                b       = b,
                profit  = interval_profits.get((a, b), 0.0),
            )
            for idx, (a, b) in enumerate(sorted_ivls)
        ]
        self.n_nodes = len(self.nodes)

    # ── DAG 构建 ──────────────────────────────────────────────────────────────

    def _source_to_node_weight(self, node: IntervalNode) -> Optional[float]:
        """
        SOURCE → node 的边权重。

        停机时长 = node.a（从调度起点 t=0 到开机起点之前的时段数）。
        边合法条件：node.a == 0 或 node.a ≥ T_off_min（枚举时已保证，但再次校验）。
        边权重 = profit(node) - startup_cost(off_duration=node.a)
        """
        off_dur = node.a   # 0 ~ node.a-1 共 node.a 个停机时段
        return node.profit - self.startup_cost_fn(off_dur)

    def _node_to_node_weight(
        self, src: IntervalNode, dst: IntervalNode
    ) -> Optional[float]:
        """
        src → dst 的边权重（若允许则返回权重，否则返回 None）。

        合法条件：dst.a - src.b - 1 ≥ T_off_min
        停机时长 = dst.a - src.b - 1（唯一确定，无歧义，这是修复硬伤 2 的关键）
        边权重 = profit(dst) - startup_cost(dst.a - src.b - 1)
        """
        off_dur = dst.a - src.b - 1
        if off_dur < self.T_off_min:
            return None
        return dst.profit - self.startup_cost_fn(off_dur)

    def _node_to_sink_valid(self, node: IntervalNode) -> bool:
        """
        node → SINK 是否合法。
        条件：node.b == T-1，或区间后方停机空间满足 T_off_min。
        """
        space_after = self.T - 1 - node.b
        return space_after == 0 or space_after >= self.T_off_min

    # ── DP 最长路径 ──────────────────────────────────────────────────────────

    def solve(self) -> Tuple[List[Tuple[int, int]], float]:
        """
        在区间节点 DAG 上用拓扑排序 DP 求最长路径。

        节点已按起点 a 升序排列，天然满足拓扑序（a 小的区间先处理）。
        时间复杂度：O(I²)，I = 合法区间数（通常远小于 T²）。

        Returns
        -------
        best_intervals : 最优开机区间列表（按时间顺序）
        max_profit     : 最大总净利润（已扣除所有启动成本）
        """
        n = self.n_nodes

        # 若无合法区间，直接返回全停（净利润=0）
        if n == 0:
            return [], 0.0

        # DP 状态初始化
        # dp[i] 表示"到达区间节点 i 且已激活该区间"的最大累计净利润
        # dp_sink 表示到达 SINK 的最大累计净利润
        dp: List[DPState] = [DPState() for _ in range(n)]
        dp_sink = DPState(best_profit=0.0)   # SINK 的初始利润=0（全程停机方案）

        # ── 从 SOURCE 出发，转入各区间节点 ──
        for i, node in enumerate(self.nodes):
            w = self._source_to_node_weight(node)
            if w is not None and w > dp[i].best_profit:
                dp[i] = DPState(
                    best_profit  = w,
                    prev_node_id = _SOURCE,
                    via_interval = (node.a, node.b),
                )

        # ── 按拓扑序（起点 a 升序）转移 ──
        for i, src in enumerate(self.nodes):
            if dp[i].best_profit <= -1e14:
                continue   # 该节点不可达，跳过

            # i → 后续区间节点 j（j > i 且 dst.a > src.b）
            for j in range(i + 1, n):
                dst = self.nodes[j]
                if dst.a <= src.b:
                    continue   # 区间重叠或紧接，跳过（已在 _node_to_node_weight 校验）
                w = self._node_to_node_weight(src, dst)
                if w is None:
                    continue
                candidate = dp[i].best_profit + w
                if candidate > dp[j].best_profit:
                    dp[j] = DPState(
                        best_profit  = candidate,
                        prev_node_id = i,
                        via_interval = (dst.a, dst.b),
                    )

            # i → SINK（若区间后方停机合法）
            if self._node_to_sink_valid(src):
                if dp[i].best_profit > dp_sink.best_profit:
                    dp_sink = DPState(
                        best_profit  = dp[i].best_profit,
                        prev_node_id = i,
                        via_interval = None,
                    )

        # ── 路径回溯 ──────────────────────────────────────────────────────────
        best_intervals: List[Tuple[int, int]] = []
        max_profit = dp_sink.best_profit

        node_id = dp_sink.prev_node_id   # 从 SINK 的前驱开始回溯
        while node_id is not None and node_id != _SOURCE:
            state = dp[node_id]
            if state.via_interval is not None:
                best_intervals.append(state.via_interval)
            node_id = state.prev_node_id

        best_intervals.reverse()   # 回溯路径逆序 → 按时间正序排列
        return best_intervals, float(max_profit)

    # ── 调试辅助 ──────────────────────────────────────────────────────────────

    def get_dag_summary(self) -> dict:
        """返回 DAG 的基本统计信息（节点数、边数），用于调试。"""
        n_edges = 0
        for i, src in enumerate(self.nodes):
            # SOURCE → src
            if self._source_to_node_weight(src) is not None:
                n_edges += 1
            # src → SINK
            if self._node_to_sink_valid(src):
                n_edges += 1
            # src → dst（后续区间）
            for j in range(i + 1, self.n_nodes):
                dst = self.nodes[j]
                if dst.a > src.b and self._node_to_node_weight(src, dst) is not None:
                    n_edges += 1

        return {
            'n_interval_nodes' : self.n_nodes,
            'n_edges'          : n_edges + 1,   # +1 for SOURCE→SINK (全停路径)
            'T'                : self.T,
            'T_off_min'        : self.T_off_min,
        }
