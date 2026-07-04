"""
火电机组建模模块。

核心创新（修复硬伤1）：ConditionalGPolymatroid 在差分变量 v_t = p_t - p_{t-1} 空间
构造广义多面体，而非原始功率 p_t 空间。这是使 Edmonds 贪心算法在物理上正确的根本前提。

算法三层结构：
  外层 DP（区间节点图） → 找最优启停区间组合（见 solvers/dp_shortest_path.py）
  中层 区间调用          → 每个合法 ON-interval 触发一次贪心
  内层 Greedy（v 空间）  → 解固定区间内的连续出力优化

【禁止调用任何 MIP 求解器（Gurobi / CPLEX / SCIP 等）】
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Set, Tuple, Union
import numpy as np

from lib.flexitroid import GPolymatroid


AnySet = Union[Set[int], FrozenSet[int]]


# ─────────────────────────────────────────────────────────────────────────────
# 参数数据类
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ThermalParameters:
    """
    火电机组参数。
    与 data/cases/case_6ww.get_gen_params_for_thermal() 的输出字段一一对应。
    所有功率单位为 MW，成本单位为 $（启停）或 $/MWh（可变）。
    """
    P_max: float           # 最大出力 (MW)
    P_min: float           # 最小技术出力 (MW)
    R_up: float            # 向上爬坡速率 (MW/h)
    R_down: float          # 向下爬坡/滑坡速率 (MW/h)
    T_on_min: int          # 最小连续开机时段数
    T_off_min: int         # 最小连续停机时段数
    cost_var: float        # 可变成本系数 ($/MWh)
    cost_su: float         # 热启动成本 ($)
    T: int                 # 调度总时段数
    node_bus: int = 1      # 所在节点（1-indexed，与 case_6ww 对应）
    cost_sd: float = 0.0   # 停机成本 ($)
    cost_su_cold: Optional[float] = None   # 冷启动成本（可选）
    T_cold: Optional[int] = None           # 冷启动判定时长阈值（时段数）


# ─────────────────────────────────────────────────────────────────────────────
# 条件广义多面体（差分变量 v 空间）——修复硬伤 1 的核心
# ─────────────────────────────────────────────────────────────────────────────

class ConditionalGPolymatroid(GPolymatroid):
    """
    固定开机区间 [a, b] 内的条件广义多面体，在差分变量空间 v 上定义。

    变量定义
    --------
    令 v_τ = p_τ - p_{τ-1}（局部 0-indexed，τ ∈ {0,...,n-1}，n = b-a+1）
    其中 p_{-1} = 0（启动前出力为 0）。

    约束推导
    --------
    (1) 爬坡/滑坡（单步）: -R_down ≤ v_τ ≤ R_up   →  u_min[τ], u_max[τ]
    (2) 容量约束（前缀和）: P_min ≤ Σ_{τ=0}^{t} v_τ ≤ P_max
                            → 前缀累积上下界 x_min[t], x_max[t]
    (3) 启动约束（τ=0）  : v_0 = p_0 ≥ 0，且受爬坡上限 v_0 ≤ R_up
    (4) 停机约束（τ=n-1）: 区间结束后出力降至 0
                            → Σ_{τ=0}^{n-1} v_τ ≤ R_down（最后一步滑坡可达 0）
                            → x_max[n-1] ≤ R_down（在构建时收紧）

    这是标准的广义多面体形式（u_min/u_max + x_min/x_max），
    与 flexitroid-benchmark/devices/general_der.py 的 DERParameters 结构
    完全对齐，b(S)/p(S) 使用相同的 b_slow/p_slow 时序扫描算法。

    关键点
    ------
    变量 v_τ 之间无耦合（箱式约束 + 前缀和约束），Edmonds 贪心对 ṽ 正确有效。
    """

    def __init__(self, params: ThermalParameters, a: int, b: int):
        """
        Args
        ----
        params : 机组参数
        a      : 开机区间起始（全局 0-indexed，含）
        b      : 开机区间结束（全局 0-indexed，含）
        """
        assert 0 <= a <= b < params.T, f"非法区间 [{a},{b}]，T={params.T}"
        self.params = params
        self.a = a
        self._b_end = b
        self._n = b - a + 1    # 区间长度（局部时段数）

        # 在 v 空间构建广义多面体参数（对齐 DERParameters 格式）
        self._u_min, self._u_max = self._build_v_bounds()
        self._x_min, self._x_max = self._build_prefix_bounds()

    # ── v 空间参数构建 ─────────────────────────────────────────────────────────

    def _build_v_bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        构建差分变量 v_τ 的单步上下界（对应 DERParameters.u_min / u_max）。

        规则（对照 main(4).tex Def. X_e, Eq.(v-startup)-(v-ramp)）：
          τ=0（启动）: P_min ≤ v_0 ≤ SU_ramp
                       注意：SU_ramp = max(SU_ramp, P_min)（GeneratorParams 保证），
                       故 P_min ≤ SU_ramp 必成立，不会导致 u_min > u_max。
          τ>0（正常）: -R_down ≤ v_τ ≤ R_up
        """
        n = self._n
        R_up   = self.params.R_up
        R_down = self.params.R_down
        P_min  = self.params.P_min

        u_max = np.full(n,  R_up,   dtype=float)
        u_min = np.full(n, -R_down, dtype=float)

        # 启动约束（Eq. v-startup）：P_min ≤ v_0 ≤ SU_ramp
        # 对应 Phase 1 透视约束: v_0 ≥ z_e * P_min, v_0 ≤ z_e * SU_ramp
        # u_min[0] = P_min（而非0），确保 Phase 1-Phase 2 边界等价（Lemma boundary）
        u_min[0] = P_min

        return u_min, u_max

    def _build_prefix_bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        构建前缀累积量 x_t = Σ_{τ=0}^{t} v_τ = p_t 的上下界。
        （对应 DERParameters.x_min / x_max，x_t 即为 t 时刻的实际出力 p_t。）

        规则（时序传播，对照 main(4).tex Eq.(v-cap)）：
          x_max[t] = min(x_max[t-1] + u_max[t],  P_max)
          x_min[t] = max(x_min[t-1] + u_min[t],  P_min)

        启动约束（τ=0，对照 Eq.(v-startup)+(v-cap)）：
          v_0 ∈ [P_min, SU_ramp]，故 x_0 = v_0 ∈ [P_min, min(P_max, SU_ramp)]。
          注意：SU_ramp = max(SU_ramp, P_min)（GeneratorParams 保证），
          所以 P_min ≤ SU_ramp 成立，x_min[0]=P_min ≤ x_max[0]。

        停机约束（对照 Eq.(v-sd)）：
          区间最后时段 t=n-1 结束后出力需降至 0，
          故 x_max[n-1] = min(x_max[n-1], SD_ramp)
          （SD_ramp = max(SD_ramp, P_min) 保证不与容量约束矛盾）
        """
        n      = self._n
        P_min  = self.params.P_min
        P_max  = self.params.P_max
        R_up   = self.params.R_up
        R_down = self.params.R_down

        x_max = np.zeros(n, dtype=float)
        x_min = np.zeros(n, dtype=float)

        # 初始时段（τ=0）：v_0 ∈ [P_min, SU_ramp]
        # x_0 = v_0 ∈ [P_min, min(P_max, SU_ramp)]
        # 注意 SU_ramp 已在 GeneratorParams.__post_init__ 中修正为 max(SU_ramp, P_min)
        x_max[0] = min(P_max, R_up)    # R_up 是 SU_ramp 的默认值，实际由子类覆盖
        x_min[0] = P_min               # 对应 Eq.(v-startup) 下界 P_min ≤ v_0

        for t in range(1, n):
            x_max[t] = min(x_max[t - 1] + R_up,   P_max)
            x_min[t] = max(x_min[t - 1] - R_down, P_min)
            # 保证 x_min ≤ x_max（短区间传播可能 x_min > x_max）
            x_min[t] = min(x_min[t], x_max[t])

        # 停机约束（Eq. v-sd）：最后时段出力不超过 SD_ramp
        # SD_ramp 已修正为 max(SD_ramp, P_min)
        x_max[n - 1] = min(x_max[n - 1], R_down)
        x_min[n - 1] = min(x_min[n - 1], x_max[n - 1])

        return x_min, x_max

    # ── b(S) / p(S) —— 对齐 general_der.py 的 b_slow / p_slow ────────────────

    @property
    def T(self) -> int:
        return self._n

    def b(self, S: AnySet) -> float:
        """
        次模上界秩函数（时序扫描算法，完全对照 general_der.py b_slow()）。

        在 v 变量空间上运行，利用 x_max（前缀累积能量上界）逐步收紧 b(S)。
        参数 S ⊆ {0,...,n-1} 为局部索引。
        """
        if not S:
            return 0.0

        A   = set(S)
        A_c = set(range(self._n)) - A   # 补集

        b_val = float(np.sum(self._u_max[list(A)]))
        p_c   = float(np.sum(self._u_min[list(A_c)])) if A_c else 0.0

        t_set = set()
        for t in range(self._n):
            t_set.add(t)
            A_t_set_complement   = A_c - t_set
            A_minus_t_set        = A - t_set

            b_val = min(
                b_val,
                self._x_max[t]
                - p_c
                + (float(np.sum(self._u_min[list(A_t_set_complement)])) if A_t_set_complement else 0.0)
                + (float(np.sum(self._u_max[list(A_minus_t_set)]))        if A_minus_t_set        else 0.0),
            )
            p_c = max(
                p_c,
                self._x_min[t]
                - b_val
                + (float(np.sum(self._u_max[list(A_minus_t_set)]))        if A_minus_t_set        else 0.0)
                + (float(np.sum(self._u_min[list(A_t_set_complement)])) if A_t_set_complement else 0.0),
            )

        return float(b_val)

    def p(self, S: AnySet) -> float:
        """
        超模下界秩函数（时序扫描算法，完全对照 general_der.py p_slow()）。
        """
        if not S:
            return 0.0

        A   = set(S)
        A_c = set(range(self._n)) - A

        p_val = float(np.sum(self._u_min[list(A)]))
        b_c   = float(np.sum(self._u_max[list(A_c)])) if A_c else 0.0

        t_set = set()
        for t in range(self._n):
            t_set.add(t)
            A_t_set_complement   = A_c - t_set
            A_minus_t_set        = A - t_set

            p_val = max(
                p_val,
                self._x_min[t]
                - b_c
                + (float(np.sum(self._u_max[list(A_t_set_complement)])) if A_t_set_complement else 0.0)
                + (float(np.sum(self._u_min[list(A_minus_t_set)]))       if A_minus_t_set       else 0.0),
            )
            b_c = min(
                b_c,
                self._x_max[t]
                - p_val
                + (float(np.sum(self._u_min[list(A_minus_t_set)]))       if A_minus_t_set       else 0.0)
                + (float(np.sum(self._u_max[list(A_t_set_complement)])) if A_t_set_complement else 0.0),
            )

        return float(p_val)


# ─────────────────────────────────────────────────────────────────────────────
# 火电机组类
# ─────────────────────────────────────────────────────────────────────────────

class ThermalUnit:
    """
    火电机组完整建模类。

    求解流程
    --------
    1. enumerate_on_intervals()  → 枚举所有合法 ON-interval [a,b]   O(T²)
    2. solve_interval_greedy()   → 每个区间调用 v 空间贪心          O(T log T) / 区间
    3. DPShortestPath.solve()    → 区间节点 DAG 最长路径             O(I²)  I=区间数
    4. 重建 u*, p* 轨迹

    注意：步骤 1-4 整体对应 solve_subproblem() 的外部调用接口。
    """

    def __init__(self, params: ThermalParameters, unit_id: str = ""):
        self.params  = params
        self.unit_id = unit_id
        self.T       = params.T

    # ── 启动成本查询 ──────────────────────────────────────────────────────────

    def get_startup_cost(self, off_duration: int) -> float:
        """
        根据停机时长计算启动成本（支持冷/热启动）。

        Args
        ----
        off_duration : 本次开机前连续停机的时段数（≥0）
        """
        if (
            self.params.cost_su_cold is not None
            and self.params.T_cold is not None
            and off_duration > self.params.T_cold
        ):
            return self.params.cost_su_cold
        return self.params.cost_su

    # ── 合法区间枚举 ──────────────────────────────────────────────────────────

    def enumerate_on_intervals(self) -> List[Tuple[int, int]]:
        """
        枚举所有满足最小开机/停机时间约束的合法连续开机区间 [a, b]（全局 0-indexed）。

        合法条件：
          (1) 区间长度 ≥ T_on_min
          (2) 区间前方有足够停机空间：a = 0，或 a ≥ T_off_min
          (3) 区间后方有足够停机空间：b = T-1，或 (T-1-b) ≥ T_off_min

        时间复杂度：O(T²)
        """
        T     = self.T
        T_on  = self.params.T_on_min
        T_off = self.params.T_off_min
        valid = []

        for a in range(T):
            if a != 0 and a < T_off:
                continue                       # 前方停机空间不足
            for b in range(a + T_on - 1, T):
                space_after = T - 1 - b
                if space_after != 0 and space_after < T_off:
                    continue                   # 后方停机空间不足
                valid.append((a, b))

        return valid

    # ── 区间内贪心求解（修复硬伤 1 的关键方法）────────────────────────────────

    @staticmethod
    def _transform_objective(c_raw: np.ndarray) -> np.ndarray:
        """
        目标函数系数转换：从 p 空间转到 v 空间。

        原目标（p 空间）：max Σ_{t=0}^{n-1} c_t * p_t
        代入 p_t = Σ_{τ=0}^{t} v_τ 后：

          Σ_t c_t Σ_{τ=0}^t v_τ
          = Σ_τ (Σ_{t=τ}^{n-1} c_t) * v_τ
          = Σ_τ c̃_τ * v_τ

        因此 c̃_τ = Σ_{t=τ}^{n-1} c_t = 后缀累加（suffix sum）。

        实现：c̃ = np.cumsum(c[::-1])[::-1]

        Args
        ----
        c_raw : (n,)，区间内的原始收益系数（净电价 = λ_t - cost_var）

        Returns
        -------
        c_tilde : (n,)，v 空间的等价目标系数
        """
        return np.cumsum(c_raw[::-1])[::-1]

    def solve_interval_greedy(
        self,
        a: int,
        b: int,
        lambda_prices: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        """
        在固定开机区间 [a, b] 内，通过 v 空间广义多面体贪心求最优出力。

        步骤：
          1. 构建 ConditionalGPolymatroid（v 空间，局部 0-indexed）
          2. 净价格系数 c_t = λ_{a+t} - cost_var（t 为局部索引）
          3. 后缀累加得 c̃_τ（v 空间目标系数）
          4. 调用 greedy_maximize(c̃) 得最优 v*
          5. 前缀和还原：p* = cumsum(v*)
          6. 计算净利润 = revenue - var_cost

        Args
        ----
        a, b           : 全局 0-indexed 开机区间
        lambda_prices  : 全时段节点电价 (T,) $/MWh（与 cost_var 单位相同）

        Returns
        -------
        p_interval : (b-a+1,)  区间内最优出力 (MW)
        net_profit : float     净利润（含电价收益扣可变成本，不含启动成本）
        """
        n = b - a + 1
        cond_gpoly = ConditionalGPolymatroid(self.params, a, b)

        # 局部净价格系数（p 空间）
        c_raw = lambda_prices[a:b + 1] - self.params.cost_var    # (n,)

        # 转换到 v 空间（后缀累加）——硬伤 1 的核心修复
        c_tilde = self._transform_objective(c_raw)               # (n,)

        # 在 v 空间的广义多面体上贪心最大化
        v_star = cond_gpoly.greedy_maximize(c_tilde)             # (n,)

        # 还原实际出力（前缀和）
        p_interval = np.cumsum(v_star)                           # (n,) p_t = Σ_{τ=0}^t v_τ

        # 裁剪数值误差（出力不应低于 P_min）
        p_interval = np.maximum(p_interval, self.params.P_min)

        # 净利润
        revenue    = float(np.dot(lambda_prices[a:b + 1], p_interval))
        # 可变成本 = C^M · Σ_τ (p_τ - P_min)，仅对超出 P_min 的部分
        var_cost   = self.params.cost_var * float(
            np.sum(np.maximum(p_interval - self.params.P_min, 0.0))
        )
        net_profit = revenue - var_cost

        return p_interval, net_profit

    # ── 子问题完整求解（对外接口）────────────────────────────────────────────

    def solve_subproblem(
        self,
        lambda_k_t: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        火电子问题 DP-Greedy 双层求解（严禁 MIP）。

        返回：
          u_star  : (T,)  最优启停计划（0/1）
          p_star  : (T,)  最优出力轨迹 (MW)
          obj_val : float 子问题目标值 = C_su + C_var - λ^T p（用于检验数计算）

        注意 obj_val 已含负收入项（最小化形式），检验数 RC = obj_val - μ_i。
        """
        from solvers.dp_shortest_path import DPShortestPath

        on_intervals = self.enumerate_on_intervals()

        # Step 1：为所有合法区间计算贪心最优净利润
        interval_profits: Dict[Tuple[int, int], float]    = {}
        interval_outputs: Dict[Tuple[int, int], np.ndarray] = {}

        for (a, b) in on_intervals:
            p_iv, profit = self.solve_interval_greedy(a, b, lambda_k_t)
            interval_profits[(a, b)] = profit
            interval_outputs[(a, b)] = p_iv

        # Step 2：DAG 最长路径（区间节点图，修复硬伤 2）
        dp_solver = DPShortestPath(
            T            = self.T,
            on_intervals = on_intervals,
            interval_profits   = interval_profits,
            startup_cost_fn    = self.get_startup_cost,
            T_off_min    = self.params.T_off_min,
        )
        best_intervals, _ = dp_solver.solve()

        # Step 3：重建完整轨迹
        u_star = np.zeros(self.T)
        p_star = np.zeros(self.T)
        total_su_cost = 0.0
        prev_end = -1   # 上一个区间的结束时段（-1 表示从未开机）

        for (a, b) in sorted(best_intervals, key=lambda x: x[0]):
            u_star[a:b + 1] = 1.0
            p_star[a:b + 1] = interval_outputs[(a, b)]

            off_dur = (a - prev_end - 1) if prev_end >= 0 else a
            total_su_cost += self.get_startup_cost(off_dur)
            prev_end = b

        # Step 4：子问题目标值（最小化形式，用于检验数）
        total_var_cost = self.params.cost_var * float(np.sum(p_star))
        revenue        = float(np.dot(lambda_k_t, p_star))
        obj_val        = total_su_cost + total_var_cost - revenue

        return u_star, p_star, obj_val
