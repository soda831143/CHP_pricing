"""
对比基准方法三：M-IRP（混合整数松弛定价 / Mixed-Integer Relaxation Pricing）

理论依据
--------
M-IRP 将标准 UC MILP 中所有二进制变量（u, su, sd）松弛为连续变量（∈ [0,1]），
然后求解该连续线性规划（LP 松弛），从功率平衡约束的对偶提取近似凸包电价。

关键数学性质（使 M-IRP 成为有意义的基准）：
  1. M-IRP 是标准 UC MILP 的连续松弛价格，是 Xiao 等文献中常用的
     近似 CHP 基准。
  2. M-IRP 一般不是 exact CHP；它可能比单机凸包/列生成/显式凸包
     formulation 更松。
  3. M-IRP 定价目标 ≤ CHP（原空间 LP）定价目标 ≤ MILP 目标
     因为 CHP LP 比标准 LP 松弛更紧（更多的物理约束被精确刻画）。
  4. 在一致的 LOC 结算口径下，M-IRP 总 Uplift 通常不低于 exact CHP。

与其他方法的关系
---------------
  - LR 次梯度法（方法二）是对 NCUC Lagrangian dual 的迭代近似；
    它不应被简单等同于 M-IRP。
  - CHP 原空间 LP（方法零）> M-IRP（因为凸包约束比整数松弛更强）
  - LMP 固定-u LP（方法一）：约束不同，不可直接与 M-IRP 比较定价目标

技术实现
--------
本类与 ScheduleRunMILP 代码结构完全一致，唯一区别：
  BINARY → continuous [0,1]，并使用 Method=2, Crossover=0。
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


class MIRPPricing:
    """
    M-IRP：将 UC MILP 整数变量松弛为 [0,1] 连续变量的 LP 松弛定价。

    这是 CHP 文献中常用的连续松弛近似基准；它不应被等同于
    NCUC Lagrangian dual 或 exact convex-hull pricing 的最优值。
    """

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
    ) -> None:
        self.generators = generators
        if isinstance(network, np.ndarray):
            network = SingleNodeNetwork(network)
        self.network = network
        self.T       = network.T
        self.N       = len(generators)
        self.build_time = float("nan")
        self.solver_time = float("nan")
        self.total_time = float("nan")

    def solve(self) -> Tuple[np.ndarray, float, bool]:
        """
        求解 M-IRP LP 松弛，提取近似凸包 LMP。

        Returns
        -------
        lmp_matrix : np.ndarray, shape (N_bus, T)  节点边际电价
        obj_val    : float  UC LP 松弛目标值
        success    : bool
        """
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as e:
            raise ImportError("需要 gurobipy 才能运行 MIRPPricing。") from e

        t_start = time.perf_counter()
        N, T = self.N, self.T
        gens = self.generators

        model = gp.Model("MIRP")
        model.Params.OutputFlag = 0
        model.Params.Method     = 2   # 内点法：clean 对偶变量
        model.Params.Crossover  = 0   # 不交叉，保留 LP 松弛对偶（内点 LMP）

        # ── 变量（与 ScheduleRunMILP 一致，BINARY → 连续 [0,1]）───────────
        u  = model.addVars(N, T, lb=0.0, ub=1.0, name="u")
        p  = model.addVars(N, T, lb=0.0,          name="p")
        su = model.addVars(N, T, lb=0.0, ub=1.0, name="su")
        sd = model.addVars(N, T, lb=0.0, ub=1.0, name="sd")

        x = {}
        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            for k, (_, width_k) in enumerate(segs):
                for t in range(T):
                    x[i, k, t] = model.addVar(lb=0.0, ub=width_k, name=f"x_{i}_{k}_{t}")

        # ── 目标函数（与 ScheduleRunMILP 完全一致）───────────────────────
        obj = gp.LinExpr()
        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            for t in range(T):
                for k, (slope_k, _) in enumerate(segs):
                    obj += slope_k * x[i, k, t]
                obj += g.cost_nl * u[i, t]
                obj += g.cost_su * su[i, t]
                obj += g.cost_sd * sd[i, t]
        model.setObjective(obj, GRB.MINIMIZE)

        # ── 约束（与 ScheduleRunMILP 完全一致）──────────────────────────

        # (1) 全局功率平衡 → 对偶 λ_t = M-IRP LMP
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
                    # 与 CHP LP 和结算公式保持一致。
                    ptdf_lb_constrs[l, t] = model.addConstr(
                        -lhs <= -float(rhs_neg[l, t]), name=f"ptdf_lb_{l}_{t}"
                    )

        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            K    = len(segs)

            for t in range(T):
                # (8) 分段等式
                model.addConstr(
                    p[i, t] == g.P_min * u[i, t]
                    + gp.quicksum(x[i, k, t] for k in range(K)),
                    name=f"pwl_link_{i}_{t}",
                )
                # (9) 段宽约束
                for k, (_, width_k) in enumerate(segs):
                    model.addConstr(
                        x[i, k, t] <= width_k * u[i, t], name=f"xub_{i}_{k}_{t}"
                    )

            # (2) 容量约束
            for t in range(T):
                model.addConstr(p[i, t] >= g.P_min * u[i, t], name=f"cap_lb_{i}_{t}")
                model.addConstr(p[i, t] <= g.P_max * u[i, t], name=f"cap_ub_{i}_{t}")

            # (3)(4)(5) 爬坡 + 启停逻辑
            for t in range(T):
                p_prev = p[i, t - 1] if t > 0 else float(g.initial_power)
                u_prev = u[i, t - 1] if t > 0 else float(g.initial_status)
                model.addConstr(su[i, t] >= u[i, t] - u_prev, name=f"su_logic_{i}_{t}")
                model.addConstr(sd[i, t] >= u_prev - u[i, t], name=f"sd_logic_{i}_{t}")
                model.addConstr(
                    p[i, t] - p_prev <= g.R_up * u_prev + g.SU_ramp * su[i, t],
                    name=f"ramp_up_{i}_{t}",
                )
                model.addConstr(
                    p_prev - p[i, t] <= g.R_down * u[i, t] + g.SD_ramp * sd[i, t],
                    name=f"ramp_dn_{i}_{t}",
                )

            if g.initial_status == 1:
                residual_on = max(0, g.T_on_min - int(g.initial_up_time))
                for t in range(min(residual_on, T)):
                    model.addConstr(u[i, t] == 1, name=f"init_on_residual_{i}_{t}")
            else:
                residual_off = max(0, g.T_off_min - int(g.initial_down_time))
                for t in range(min(residual_off, T)):
                    model.addConstr(u[i, t] == 0, name=f"init_off_residual_{i}_{t}")

            # (6) 最小开机时间（MUT）
            for t in range(T):
                if g.T_on_min > 1:
                    model.addConstr(
                        gp.quicksum(u[i, tt] for tt in range(t, min(t + g.T_on_min, T)))
                        >= g.T_on_min * su[i, t],
                        name=f"mut_{i}_{t}",
                    )
            # (7) 最小停机时间（MDT）
            for t in range(T):
                if g.T_off_min > 1:
                    model.addConstr(
                        gp.quicksum(
                            (1 - u[i, tt]) for tt in range(t, min(t + g.T_off_min, T))
                        ) >= g.T_off_min * sd[i, t],
                        name=f"mdt_{i}_{t}",
                    )

        build_done = time.perf_counter()
        model.optimize()
        total_done = time.perf_counter()
        self.build_time = max(0.0, build_done - t_start)
        self.solver_time = float(getattr(model, "Runtime", total_done - build_done))
        self.total_time = max(0.0, total_done - t_start)

        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(f"MIRPPricing 求解失败，Gurobi Status={model.Status}")

        # ── 对偶提取（与 FixedULP / PrimalCHPLP 一致的后处理）────────────
        lambda_t = np.array([balance_constrs[t].Pi for t in range(T)])
        lambda_t = np.clip(lambda_t, 0.0, None)

        self._ptdf_alpha = None
        self._ptdf_beta_ = None

        if self.network.is_single_node:
            lmp_matrix = np.tile(lambda_t, (1, 1))   # (1, T)
        else:
            N_line = self.network.N_line
            PTDF   = self.network.PTDF
            alpha  = np.array([
                [ptdf_ub_constrs[l, t].Pi for t in range(T)]
                for l in range(N_line)
            ])   # (N_line, T)
            beta_ = np.array([
                [ptdf_lb_constrs[l, t].Pi for t in range(T)]
                for l in range(N_line)
            ])   # (N_line, T)
            lmp_matrix = (
                lambda_t[np.newaxis, :]
                + PTDF.T @ (alpha - beta_)
            )
            self._ptdf_alpha = alpha
            self._ptdf_beta_ = beta_

        return lmp_matrix, model.ObjVal, True
