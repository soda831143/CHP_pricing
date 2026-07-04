"""
对比基准方法一：传统边际电价定价（LMP / Fixed-u LP Pricing）

做法
----
1. 从 Schedule Run 获取物理调度结果 u_dispatch（启停状态），将其固定为常数。
2. 构建纯连续 LP（p, x 为变量；u 为参数），最小化可变成本。
3. 从功率平衡约束的对偶变量提取 LMP。

经济学含义
----------
- LMP 反映"在给定启停方案下的边际发电成本"，忽略非凸的启停固定成本。
- 由于未考虑 C_SU、C_SD、C_NL 的影响，LMP 定价通常产生更大的 Uplift 缺口，
  这正是 CHP 存在意义的核心对比点。

技术细节
--------
- Gurobi Method=2 (Barrier), Crossover=0：
  内点法在原问题简并时仍能给出对偶空间的解析中心（Analytic Center），
  避免多重对偶最优导致的 LMP 不唯一问题。固定 u 后，多个机组可能恰好压在
  P_min 或 P_max，此时若用单纯形法，对偶解不唯一、LMP 随跳变不稳定。
- 支持单节点和多节点 PTDF 两种网络模式（与 CHP 框架一致）。

对偶提取规则（多节点）
-------------------
  LMP[n,t] = λ_t + Σ_l PTDF[l,n] * (α[l,t] − β[l,t])
  其中 α、β 分别为 PTDF 上下界约束的对偶（Gurobi Convention: Pi ≤ 0 for min LP）。
"""

from __future__ import annotations

import sys
import os
import time
from typing import List, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from models.network import NetworkModel, SingleNodeNetwork


class FixedULP:
    """
    固定启停 LP：传统 LMP 定价的精确实现。

    将 MILP Schedule Run 的整数启停方案 u_dispatch 固定为常数参数，
    构建最小化可变成本的 LP，从功率平衡约束的对偶提取 LMP。
    """

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
        u_dispatch: np.ndarray,
    ) -> None:
        self.generators = generators
        if isinstance(network, np.ndarray):
            network = SingleNodeNetwork(network)
        self.network  = network
        self.u_fixed  = np.asarray(u_dispatch, dtype=float)   # (N, T)
        self.T        = network.T
        self.N        = len(generators)
        self.build_time = float("nan")
        self.solver_time = float("nan")
        self.total_time = float("nan")

    def solve(self) -> Tuple[np.ndarray, float, bool]:
        """
        求解固定启停 LP，提取 LMP。

        Returns
        -------
        lmp_matrix : np.ndarray, shape (N_bus, T)
        obj_val    : float  LP 总成本（含固定成本常数项，与 CHP 会计口径一致）
        success    : bool
        """
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as e:
            raise ImportError("需要 gurobipy 才能运行 FixedULP。") from e

        t_start = time.perf_counter()
        N, T = self.N, self.T
        gens = self.generators
        u_fixed = self.u_fixed

        # su_fixed[i,t] = max(0, u[i,t] - u[i,t-1])
        initial_u = np.array([float(g.initial_status) for g in gens], dtype=float).reshape(N, 1)
        u_prev_mat = np.concatenate([initial_u, u_fixed[:, :-1]], axis=1)
        su_fixed   = np.maximum(u_fixed - u_prev_mat, 0.0)   # (N, T)
        sd_fixed   = np.maximum(u_prev_mat - u_fixed, 0.0)   # (N, T)

        model = gp.Model("FixedULP")
        model.Params.OutputFlag = 0
        model.Params.Method     = 2   # 内点法：避免简并时的多重对偶最优
        model.Params.Crossover  = 0   # 不交叉，保留解析中心 LMP

        # ── 变量 ─────────────────────────────────────────────────────────────
        p = model.addVars(N, T, lb=0.0, name="p")

        x = {}
        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            for k, (_, width_k) in enumerate(segs):
                for t in range(T):
                    # 段宽上界随 u_fixed 缩放（u=0 时上界为 0，强制 x=0）
                    ub_kt = width_k * float(u_fixed[i, t])
                    x[i, k, t] = model.addVar(lb=0.0, ub=ub_kt, name=f"x_{i}_{k}_{t}")

        # ── 目标函数 ─────────────────────────────────────────────────────────
        # 可变成本进入 LP 优化；固定成本作为常数加入报告值（不影响对偶）
        fixed_cost_total = 0.0
        obj = gp.LinExpr()
        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            for t in range(T):
                for k, (slope_k, _) in enumerate(segs):
                    obj += slope_k * x[i, k, t]
                fixed_cost_total += (
                    g.cost_nl * float(u_fixed[i, t])
                    + g.cost_su * float(su_fixed[i, t])
                    + g.cost_sd * float(sd_fixed[i, t])
                )
        model.setObjective(obj, GRB.MINIMIZE)

        # ── 约束 ─────────────────────────────────────────────────────────────

        # (1) 全局功率平衡 → 对偶 λ_t = LMP（基准）
        balance_constrs = {}
        for t in range(T):
            c = model.addConstr(
                gp.quicksum(p[i, t] for i in range(N)) == float(self.network.sys_demand[t]),
                name=f"balance_{t}",
            )
            balance_constrs[t] = c

        # (1f) PTDF 线路约束（多节点）
        ptdf_ub_constrs = {}
        ptdf_lb_constrs = {}
        if not self.network.is_single_node:
            PTDF_Gen = self.network.PTDF_Gen
            rhs_pos, rhs_neg = self.network.line_rhs()
            for l in range(self.network.N_line):
                for t in range(T):
                    lhs = gp.quicksum(float(PTDF_Gen[l, i]) * p[i, t] for i in range(N))
                    ptdf_ub_constrs[l, t] = model.addConstr(
                        lhs <= float(rhs_pos[l, t]), name=f"ptdf_ub_{l}_{t}"
                    )
                    # 下界统一改写为 -lhs <= -rhs_neg，
                    # 使上下界对偶都遵循 min LP 的 "Pi <= 0" 口径，
                    # 与 PrimalCHPLP / comparison_runner / 论文公式完全一致。
                    ptdf_lb_constrs[l, t] = model.addConstr(
                        -lhs <= -float(rhs_neg[l, t]), name=f"ptdf_lb_{l}_{t}"
                    )

        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            K = len(segs)
            for t in range(T):
                u_it = float(u_fixed[i, t])

                # (8) 分段等式：p = P_min·u + Σ x[k]
                model.addConstr(
                    p[i, t] == g.P_min * u_it
                    + gp.quicksum(x[i, k, t] for k in range(K)),
                    name=f"pwl_{i}_{t}",
                )

                # (2) 容量约束（由段宽隐含，显式加入加速求解）
                model.addConstr(p[i, t] >= g.P_min * u_it, name=f"cap_lb_{i}_{t}")
                model.addConstr(p[i, t] <= g.P_max * u_it, name=f"cap_ub_{i}_{t}")

            # (3)(4) 爬坡约束（固定 u 后仍需约束可变出力的物理爬坡速率）
            for t in range(T):
                p_prev     = p[i, t - 1] if t > 0 else float(g.initial_power)
                u_it       = float(u_fixed[i, t])
                u_prev_val = float(u_fixed[i, t - 1]) if t > 0 else float(g.initial_status)
                su_it      = float(su_fixed[i, t])
                sd_it      = float(sd_fixed[i, t])

                model.addConstr(
                    p[i, t] - p_prev <= g.R_up * u_prev_val + g.SU_ramp * su_it,
                    name=f"ramp_up_{i}_{t}",
                )
                model.addConstr(
                    p_prev - p[i, t] <= g.R_down * u_it + g.SD_ramp * sd_it,
                    name=f"ramp_dn_{i}_{t}",
                )

        build_done = time.perf_counter()
        model.optimize()
        total_done = time.perf_counter()
        self.build_time = max(0.0, build_done - t_start)
        self.solver_time = float(getattr(model, "Runtime", total_done - build_done))
        self.total_time = max(0.0, total_done - t_start)

        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(f"FixedULP 求解失败，Gurobi Status={model.Status}")

        # ── 对偶提取 ─────────────────────────────────────────────────────────
        # Gurobi 等式约束 Pi 的符号：对 min LP，功率平衡的 Pi ≥ 0
        lambda_t = np.array([balance_constrs[t].Pi for t in range(T)])
        lambda_t = np.clip(lambda_t, 0.0, None)   # 纯火电单节点 LMP ≥ 0

        var_obj   = model.ObjVal
        total_obj = var_obj + fixed_cost_total   # 与 MILP/CHP 口径一致的总成本

        self._ptdf_alpha = None
        self._ptdf_beta_ = None

        if self.network.is_single_node:
            lmp_matrix = np.tile(lambda_t, (1, 1))   # (1, T)
        else:
            # PTDF 拥塞修正（与 PrimalCHPLP 后处理逻辑完全一致）
            N_line = self.network.N_line
            PTDF   = self.network.PTDF   # (N_line, N_bus)
            alpha  = np.array([
                [ptdf_ub_constrs[l, t].Pi for t in range(T)]
                for l in range(N_line)
            ])   # (N_line, T), ≤ 0 for min LP
            beta_ = np.array([
                [ptdf_lb_constrs[l, t].Pi for t in range(T)]
                for l in range(N_line)
            ])   # (N_line, T), ≤ 0 for min LP
            lmp_matrix = (
                lambda_t[np.newaxis, :]        # (1, T)
                + PTDF.T @ (alpha - beta_)     # (N_bus, T)
            )
            # 保存供外部 FTR 计算
            self._ptdf_alpha = alpha
            self._ptdf_beta_ = beta_

        return lmp_matrix, total_obj, True
