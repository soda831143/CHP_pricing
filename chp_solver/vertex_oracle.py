"""
Phase 2：极点抓取神谕（Vertex Oracle）。

给定凸包电价 λ*，为每台机组计算使其利润最大化的物理极点轨迹，
并计算 Uplift 缺口。

算法流程
--------
**单段线性成本** (is_single_segment == True)：
  1. Abel 变换：w_k = Σ_{τ=k}^{n-1} (λ*_{a+τ} - cost_var)（v 空间后缀和权重）
  2. RampingPolymatroid.greedy_maximize(w) → v*  (b* 算法，正确处理正负权重)
  3. p* = cumsum(v*)

**分段线性成本** (is_single_segment == False)：
  PWL profit is separable and concave, so one call to the linear
  g-polymatroid greedy routine is not, in general, exact.  The production
  route therefore uses the exact compact interval LP.  A certificate-based
  conditional-greedy diagnostic is retained below for internal verification
  of the linear g-polymatroid oracle, but it is not used to generate reported
  settlement quantities.

会计对齐保证 uplift ≥ 0
-----------------------
W_e* 中扣除的 c_fix 与 PrimalCHPLP 目标函数中的 c_fix_e 完全相同。
dispatch_profit 中扣除的成本分量与 W_e* 累计意义相同。
由凸包定理，max_profit ≥ dispatch_profit，故 uplift ≥ 0。
"""

from __future__ import annotations
import sys
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from chp_core.graph_builder import DAGBuilder, OnInterval
from chp_core.ramping_polymatroid import RampingPolymatroid
from lib.dp_shortest_path import DPShortestPath


class VertexOracle:
    """
    Phase 2 极点抓取神谕。

    给定 λ* 后，为单台机组求解利润最大化极点并计算 Uplift。
    """

    # ── 区间内求解（调度器）──────────────────────────────────────────────────

    @staticmethod
    def solve_interval(
        params: GeneratorParams,
        a: int,
        b: int,
        lambda_star: np.ndarray,
        *,
        initial_online: bool = False,
        c_fix: Optional[float] = None,
    ) -> Tuple[np.ndarray, float]:
        """
        在固定开机区间 [a, b] 内求最优出力极点。

        单段 → Abel 变换 + greedy_maximize（快速精确）
        多段 → exact compact interval LP
        """
        # Initial-online intervals use the previous physical output and normal
        # ramp bounds at the left boundary.  The generic interval LP handles
        # that boundary exactly for both single- and multi-segment costs.
        if params.is_single_segment and not initial_online:
            return VertexOracle._solve_interval_single_segment(
                params, a, b, lambda_star
            )
        return VertexOracle._solve_interval_pwl_lp(
            params, a, b, lambda_star,
            initial_online=initial_online,
            c_fix=c_fix,
        )

    # ── 单段线性：Abel 变换 + 广义多面体贪心 ─────────────────────────────────

    @staticmethod
    def _solve_interval_single_segment(
        params: GeneratorParams,
        a: int,
        b: int,
        lambda_star: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        """
        Abel 变换将 p-space 线性目标映射到 v-space，调用 greedy_maximize。

        w_k = Σ_{τ=k}^{n-1} (λ*_{a+τ} - cost_var)  (v-space 后缀和权重)
        """
        n = b - a + 1
        net_price = lambda_star[a : b + 1] - params.cost_var   # (n,)
        w = np.cumsum(net_price[::-1])[::-1]                    # Abel 后缀和

        has_shutdown = (b < params.T - 1)
        poly   = RampingPolymatroid(params, a, b, include_shutdown=has_shutdown)
        v_star = poly.greedy_maximize(w)                        # b* 算法

        p_interval = np.cumsum(v_star)
        p_interval = np.maximum(p_interval, 0.0)

        revenue  = float(np.dot(lambda_star[a : b + 1], p_interval))
        # 可变成本 = C^M · Σ_τ (p_τ - P_min)（仅对超出 P_min 的部分收费）
        # 理论上 p_τ ≥ P_min（由 GP 下界 g_e({0,...,τ})=P_min 保证），
        # 但数值误差可能导致微小负偏差，故用 np.maximum 保护
        var_cost = params.cost_var * float(
            np.sum(np.maximum(p_interval - params.P_min, 0.0))
        )
        c_fix    = params.interval_fix_cost(n, include_shutdown=has_shutdown)
        W_e      = revenue - var_cost - c_fix

        return p_interval, W_e

    # ── 多段线性：带证书的条件贪心 ──────────────────────────────────────────

    @staticmethod
    def _solve_interval_pwl_conditional_greedy(
        params: GeneratorParams,
        a: int,
        b: int,
        lambda_star: np.ndarray,
        *,
        c_fix: Optional[float] = None,
        tolerance: float = 1e-10,
        max_iterations: int = 200,
    ) -> Optional[Tuple[np.ndarray, float, int, float]]:
        """Solve a normal PWL ON interval by a certified greedy-oracle loop.

        Let ``h(p)`` denote interval revenue minus convex PWL variable cost.
        At a feasible iterate ``p``, a supergradient ``d`` of ``h`` gives the
        global upper bound

        ``h(y) - h(p) <= d @ (y - p)`` for every feasible ``y``.

        The right-hand maximizer is obtained exactly by the linear
        g-polymatroid greedy oracle after the usual cumulative-coordinate
        transformation.  Consequently, a nonpositive linearization gap is a
        sufficient certificate of global optimality for the concave PWL
        interval problem.  Exact one-dimensional line search keeps every
        iterate feasible and evaluates all PWL breakpoints on the segment.

        The method is intentionally conservative: it returns ``None`` rather
        than an uncertified point.  It is an internal diagnostic and does not
        replace the production PWL interval LP.  It is not applied to
        initially-online intervals because their inherited-output boundary
        requires the more general interval formulation.
        """
        if params.is_single_segment:
            return None

        n = b - a + 1
        prices = np.asarray(lambda_star[a : b + 1], dtype=float)
        has_shutdown = b < params.T - 1
        poly = RampingPolymatroid(
            params, a, b, include_shutdown=has_shutdown
        )

        def _linear_greedy_profile(marginal_profit: np.ndarray) -> np.ndarray:
            # p_tau = sum_{j<=tau} v_j.  Hence the coefficient of v_j is
            # the suffix sum of the output-coordinate linear coefficient.
            weights = np.cumsum(marginal_profit[::-1])[::-1]
            profile = np.cumsum(poly.greedy_maximize(weights))
            return np.asarray(profile, dtype=float)

        def _profit(profile: np.ndarray) -> float:
            return float(np.dot(prices, profile) -
                         _compute_pwl_var_cost(params, profile))

        def _supergradient(profile: np.ndarray) -> np.ndarray:
            """Return one valid supergradient of PWL interval profit."""
            q = np.asarray(profile, dtype=float) - params.P_min
            segments = params.get_pwl_segments()
            slopes = np.asarray([slope for slope, _ in segments], dtype=float)
            widths = np.asarray([width for _, width in segments], dtype=float)
            breaks = np.concatenate(([0.0], np.cumsum(widths)))
            marginal_cost = np.empty(n, dtype=float)
            kink_tol = 1e-8

            for tau, value in enumerate(q):
                # At an interior breakpoint the convex cost subdifferential is
                # [s_left, s_right].  Choosing the projection of the price
                # onto this interval supplies a valid, numerically balanced
                # supergradient of revenue minus cost.
                kink = np.flatnonzero(np.abs(breaks[1:-1] - value) <= kink_tol)
                if kink.size:
                    right = int(kink[0] + 1)
                    marginal_cost[tau] = np.clip(
                        prices[tau], slopes[right - 1], slopes[right]
                    )
                    continue

                segment = int(np.searchsorted(breaks[1:], value, side="right"))
                segment = min(max(segment, 0), len(slopes) - 1)
                marginal_cost[tau] = slopes[segment]

            return prices - marginal_cost

        def _line_search(profile: np.ndarray, direction: np.ndarray) -> Tuple[float, float]:
            """Maximize the concave PWL profit on ``profile + alpha*direction``."""
            q = profile - params.P_min
            breaks = np.concatenate(
                ([0.0], np.cumsum([width for _, width in params.get_pwl_segments()]))
            )
            candidates = [0.0, 1.0]
            for q_tau, d_tau in zip(q, direction):
                if abs(d_tau) <= 1e-12:
                    continue
                for breakpoint in breaks:
                    alpha = (breakpoint - q_tau) / d_tau
                    if 1e-10 < alpha < 1.0 - 1e-10:
                        candidates.append(float(alpha))

            best_alpha = 0.0
            best_value = _profit(profile)
            for alpha in sorted(set(round(value, 14) for value in candidates)):
                candidate = profile + alpha * direction
                value = _profit(candidate)
                if value > best_value + 1e-9:
                    best_alpha, best_value = float(alpha), value
            return best_alpha, best_value

        # A zero-objective greedy vertex is feasible and gives a deterministic
        # starting point without invoking an LP.
        profile = _linear_greedy_profile(np.zeros(n, dtype=float))
        objective_scale = max(
            1.0,
            float(np.sum(np.abs(prices)) * max(params.P_max, 1.0)),
        )

        for iteration in range(1, max_iterations + 1):
            gradient = _supergradient(profile)
            oracle_profile = _linear_greedy_profile(gradient)
            gap = float(np.dot(gradient, oracle_profile - profile))
            if gap <= tolerance * objective_scale:
                fixed_cost = c_fix
                if fixed_cost is None:
                    fixed_cost = params.interval_fix_cost(
                        n, include_shutdown=has_shutdown
                    )
                return profile, _profit(profile) - float(fixed_cost), iteration, gap

            direction = oracle_profile - profile
            alpha, candidate_value = _line_search(profile, direction)
            if alpha <= 1e-10 or candidate_value <= _profit(profile) + 1e-9:
                # A valid certificate was not reached with the chosen
                # supergradient.  Preserve exactness by delegating to the LP.
                return None
            profile = profile + alpha * direction

        return None

    # ── 多段线性：精确区间 LP ─────────────────────────────────────────────────

    @staticmethod
    def _solve_interval_pwl_lp(
        params: GeneratorParams,
        a: int,
        b: int,
        lambda_star: np.ndarray,
        *,
        initial_online: bool = False,
        c_fix: Optional[float] = None,
    ) -> Tuple[np.ndarray, float]:
        """
        Groenevelt 等价精确解：通过小型 Gurobi LP 求解区间内分段线性利润最大化。

        变量：
          p[τ]    : 时段 τ 的总出力 ∈ [P_min, P_max]
          x[k][τ] : 第 k 成本段在时段 τ 的填充量 ∈ [0, w_k]

        等式：p[τ] = P_min + Σ_k x[k][τ]

        不等式：爬坡约束（含 SU_ramp、SD_ramp）

        目标：max Σ_τ Σ_k (λ*_{a+τ} - slope_k) * x[k][τ]
              （P_min 部分的收益为常数，不影响优化；c_fix 在 W_e 计算时扣除）
        """
        n    = b - a + 1
        segs = params.get_pwl_segments()   # [(slope_k, width_k), ...]
        K    = len(segs)

        # ── Gurobi 构建 ──────────────────────────────────────────────────────
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError:
            # 无 Gurobi → 退化为单段弦斜率近似
            return VertexOracle._solve_interval_single_segment(
                params, a, b, lambda_star
            )

        model = gp.Model("IntervalPWL")
        model.Params.OutputFlag = 0
        model.Params.Method     = 2   # Barrier，适合小型稠密 LP

        # A normal interval begins with a physical start-up and therefore uses
        # SU_ramp.  An initial-online interval instead ramps from the inherited
        # initial output using the normal up/down limits.
        first_ub = params.P_max if initial_online else min(params.P_max, params.SU_ramp)
        p_ub = [first_ub] + [params.P_max] * (n - 1)
        has_shutdown = (b < params.T - 1)
        if has_shutdown:
            p_ub[-1] = min(p_ub[-1], params.SD_ramp)

        p_vars = [
            model.addVar(lb=params.P_min, ub=p_ub[tau], name=f"p_{tau}")
            for tau in range(n)
        ]

        # x[k][τ] ∈ [0, width_k]
        x_vars = [
            [model.addVar(lb=0.0, ub=segs[k][1], name=f"x_{k}_{tau}")
             for tau in range(n)]
            for k in range(K)
        ]

        # 等式：p[τ] = P_min + Σ_k x[k][τ]
        for tau in range(n):
            model.addConstr(
                p_vars[tau] == params.P_min + gp.quicksum(x_vars[k][tau]
                                                           for k in range(K))
            )

        # 爬坡约束
        for tau in range(1, n):
            model.addConstr(p_vars[tau] - p_vars[tau - 1] <= params.R_up)
            model.addConstr(p_vars[tau - 1] - p_vars[tau] <= params.R_down)
        if initial_online:
            model.addConstr(p_vars[0] - params.initial_power <= params.R_up)
            model.addConstr(params.initial_power - p_vars[0] <= params.R_down)

        # 目标：max Σ_τ Σ_k (λ*_{a+τ} - slope_k) * x[k][τ]
        obj = gp.quicksum(
            (float(lambda_star[a + tau]) - segs[k][0]) * x_vars[k][tau]
            for k in range(K) for tau in range(n)
        )
        model.setObjective(obj, GRB.MAXIMIZE)
        model.optimize()

        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            # 求解失败 → 退化为单段近似
            return VertexOracle._solve_interval_single_segment(
                params, a, b, lambda_star
            )

        p_interval = np.array([p_vars[tau].X for tau in range(n)])
        p_interval = np.clip(p_interval, params.P_min, params.P_max)

        # ── 计算区间净利润（与 PrimalCHPLP 会计口径对齐）───────────────────
        revenue  = float(np.dot(lambda_star[a : b + 1], p_interval))
        var_cost = sum(
            segs[k][0] * sum(x_vars[k][tau].X for tau in range(n))
            for k in range(K)
        )
        interval_fixed_cost = c_fix
        if interval_fixed_cost is None:
            interval_fixed_cost = params.interval_fix_cost(
                n, include_shutdown=has_shutdown
            )
        W_e = revenue - var_cost - float(interval_fixed_cost)

        return p_interval, W_e

    # ── 子问题完整求解 ───────────────────────────────────────────────────────

    @staticmethod
    def solve(
        params: GeneratorParams,
        lambda_star: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        为单台机组求解利润最大化极点轨迹（DAG DP + 区间贪心/LP 双层）。

        Parameters
        ----------
        params       : 机组参数
        lambda_star  : (T,) 凸包电价 $/MWh

        Returns
        -------
        u_star     : (T,) 最优启停计划（0/1）
        p_star     : (T,) 最优出力轨迹 (MW)
        max_profit : float 最大理论利润（含 c_fix 扣除）
        """
        dag          = DAGBuilder.build(params)
        on_intervals = dag.on_intervals

        # Step 1：对所有合法区间调用区间求解
        interval_profits: Dict[Tuple[int, int], float]      = {}
        interval_outputs: Dict[Tuple[int, int], np.ndarray] = {}

        for iv in on_intervals:
            p_iv, W_e = VertexOracle.solve_interval(
                params,
                iv.a,
                iv.b,
                lambda_star,
                initial_online=iv.initial_online,
                c_fix=iv.c_fix,
            )
            interval_profits[(iv.a, iv.b)] = W_e
            interval_outputs[(iv.a, iv.b)] = p_iv

        # Step 2：DAG DP 最长路径
        # W_e 已扣除完整 c_fix（含 C_SU），startup_cost_fn 传 0 避免重复扣除。
        initial_interval_keys = {
            (iv.a, iv.b) for iv in on_intervals if iv.initial_online
        }
        residual_on = max(0, params.T_on_min - int(params.initial_up_time))
        immediate_shutdown_ok = (
            params.initial_status == 1
            and residual_on == 0
            and params.initial_power <= params.SD_ramp + 1e-8
        )

        def source_allowed(a: int, b: int) -> bool:
            if params.initial_status == 0:
                return True
            if (a, b) in initial_interval_keys:
                return True
            return immediate_shutdown_ok and a >= params.T_off_min

        def source_extra_cost(a: int, b: int) -> float:
            if params.initial_status == 1 and (a, b) not in initial_interval_keys:
                return params.cost_sd
            return 0.0

        if params.initial_status == 0:
            empty_path_profit: Optional[float] = 0.0
        elif immediate_shutdown_ok:
            empty_path_profit = -params.cost_sd
        else:
            empty_path_profit = None

        dp = DPShortestPath(
            T                = params.T,
            on_intervals     = [(iv.a, iv.b) for iv in on_intervals],
            interval_profits = interval_profits,
            startup_cost_fn  = lambda _: 0.0,
            T_off_min        = params.T_off_min,
            source_allowed_fn= source_allowed,
            source_extra_cost_fn=source_extra_cost,
            empty_path_profit=empty_path_profit,
        )
        best_intervals, max_profit = dp.solve()

        # Step 3：重建完整轨迹
        u_star = np.zeros(params.T)
        p_star = np.zeros(params.T)

        # 若最大利润在数值噪声范围内（< 1e-4 $），视为全停（利润 = 0）。
        # 这防止浮点误差导致"名义上 0 利润"的区间被错误地选为最优轨迹。
        _PROFIT_TOL = 1e-4
        if params.initial_status == 1 or max_profit > _PROFIT_TOL:
            for (a, b) in sorted(best_intervals, key=lambda x: x[0]):
                u_star[a : b + 1] = 1.0
                p_star[a : b + 1] = interval_outputs[(a, b)]
            max_profit_out = max_profit
        else:
            max_profit_out = 0.0

        return u_star, p_star, max_profit_out

    # ── Uplift 计算 ──────────────────────────────────────────────────────────

    @staticmethod
    def compute_uplift(
        params: GeneratorParams,
        lambda_star: np.ndarray,
        p_dispatch: np.ndarray,
        u_dispatch: np.ndarray,
        max_profit: float,
    ) -> float:
        """
        计算单台机组的 Uplift 缺口（make-whole 补偿费用）。

        Parameters
        ----------
        params       : 机组参数
        lambda_star  : (T,) 凸包电价 $/MWh
        p_dispatch   : (T,) 物理调度出力（来自 Schedule Run MILP）
        u_dispatch   : (T,) 物理调度启停状态 0/1（来自 Schedule Run MILP）
        max_profit   : float 由 solve() 返回的最大理论利润

        Returns
        -------
        uplift : float ≥ 0
        """
        p_dispatch = np.asarray(p_dispatch, dtype=float)
        u_dispatch = np.asarray(u_dispatch, dtype=float)

        # 收入
        revenue = float(np.dot(lambda_star, p_dispatch))

        # 可变成本：仅计算超出 P_min 的部分
        if params.is_single_segment:
            var_cost = params.cost_var * float(
                np.sum(np.maximum(p_dispatch - params.P_min, 0.0))
            )
        else:
            var_cost = _compute_pwl_var_cost(params, p_dispatch)

        # 空载成本（按开机时段数，由 u_dispatch 精确统计）
        nl_cost = params.cost_nl * float(np.sum(u_dispatch))

        # 启动 / 停机次数（通过 u_dispatch 跳变计算）
        u_prev    = np.concatenate([[float(params.initial_status)], u_dispatch[:-1]])
        startups  = int(np.sum(np.maximum(u_dispatch - u_prev, 0.0)))
        shutdowns = int(np.sum(np.maximum(u_prev - u_dispatch, 0.0)))

        su_cost = params.cost_su * startups
        sd_cost = params.cost_sd * shutdowns

        dispatch_profit = revenue - var_cost - nl_cost - su_cost - sd_cost
        uplift          = max(0.0, max_profit - dispatch_profit)
        return uplift


# ─────────────────────────────────────────────────────────────────────────────
# 模块内辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _compute_pwl_var_cost(
    params: GeneratorParams,
    p_dispatch: np.ndarray,
) -> float:
    """
    按分段线性成本精确计算实际调度出力 p_dispatch 的可变成本。

    对每个时段 τ，将 p_τ 分配到各段，计算 Σ_k slope_k * fill_k(p_τ)。
    （空载成本 cost_nl 在调用方单独扣除，此处仅计算超出 P_min 的部分）
    """
    segs = params.get_pwl_segments()   # [(slope_k, width_k)]
    total_cost = 0.0
    cumW = 0.0
    for slope, width in segs:
        lower = params.P_min + cumW
        upper = lower + width
        fill = np.clip(p_dispatch - lower, 0.0, width)
        # 进一步修正：仅计算实际在段内的部分
        # fill_k = max(0, min(p - lower, width))
        fill = np.maximum(p_dispatch - lower, 0.0)
        fill = np.minimum(fill, width)
        total_cost += slope * float(np.sum(fill))
        cumW += width
    return total_cost
