"""
调度运行（Schedule Run）——双轨制第一轨。

使用 Gurobi 求解标准机组组合（UC）混合整数规划，
输出物理强制调度的出力轨迹 p_dispatch 和启停状态 u_dispatch。
这两个结果随后被传入 VertexOracle.compute_uplift() 用于结算 Uplift。

同时支持单节点（无网络约束）和多节点（PTDF 直流潮流）两种模式，
由 NetworkModel.is_single_node 自动切换。

假设：所有机组在 t=0 之前均处于关机状态（初始状态为 OFF）。

变量说明
--------
u[i,t] ∈ {0,1}    : 机组 i 在时段 t 的开机状态
p[i,t] ≥ 0        : 机组 i 在时段 t 的出力 (MW)
su[i,t] ∈ {0,1}   : 机组 i 在时段 t 的启动指示（0→1 跳变）
sd[i,t] ∈ {0,1}   : 机组 i 在时段 t 的停机指示（1→0 跳变）
x[k][i,t] ≥ 0     : 第 k 成本段在 (i,t) 的填充量 (MW)

约束说明
--------
单节点：
  (1) 全局功率平衡：Σ_i p[i,t] = Demand[t]
多节点（PTDF）：
  (1) 全系统功率平衡：Σ_i p[i,t] = Σ_n D[n,t]
  (1f) 线路容量：Σ_i PTDF_Gen[l,i]·p[i,t] ∈ [rhs_neg, rhs_pos]  ∀l
  PTDF reduced form 已消去相角变量；节点注入位置通过 PTDF_Gen 和 PTDF·D 进入线路约束。

公共约束：
  (2) 容量：P_min·u ≤ p ≤ P_max·u
  (3) 启动爬坡：p[i,t] - p[i,t-1] ≤ R_up·u[i,t-1] + SU_ramp·su[i,t]
  (4) 停机爬坡：p[i,t-1] - p[i,t] ≤ R_down·u[i,t] + SD_ramp·sd[i,t]
  (5) 启停逻辑：su[i,t] ≥ u[i,t] - u[i,t-1];  sd[i,t] ≥ u[i,t-1] - u[i,t]
  (6) 最小开机时间（MUT）：标准滚动窗口公式
  (7) 最小停机时间（MDT）：标准滚动窗口公式
  (8) 分段等式：p[i,t] = P_min·u[i,t] + Σ_k x[k][i,t]
  (9) 段宽约束：0 ≤ x[k][i,t] ≤ width_k·u[i,t]

目标函数
--------
min Σ_{i,t} [Σ_k slope_k·x[k][i,t] + C_SU·su[i,t] + C_SD·sd[i,t] + C_NL·u[i,t]]

成本会计：与 PrimalCHPLP 和 VertexOracle 严格一致，确保 Total_Uplift = MILP_obj - LP_obj。
"""

from __future__ import annotations
import sys
import os
from typing import List, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)
from models.generator import GeneratorParams
from models.network import NetworkModel, SingleNodeNetwork


class ScheduleRunMILP:
    """
    UC MILP 调度运行求解器（Gurobi）。

    使用分段线性成本（PWL）或单段线性成本，与 PrimalCHPLP 的成本口径严格一致，
    保证 Uplift 恒等式 Total_Uplift = MILP_obj - LP_obj 成立。
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
        self.demand = network.sys_demand
        self.T = network.T
        self.N = len(generators)

    def solve(self) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        求解 UC MILP，返回物理调度结果。

        Returns
        -------
        p_dispatch : (N, T) 各机组各时段出力 (MW)
        u_dispatch : (N, T) 各机组各时段开机状态（0/1 整数）
        obj_val    : float  MILP 目标值
        """
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as e:
            raise ImportError("需要安装 gurobipy 才能运行 ScheduleRunMILP。") from e

        N, T = self.N, self.T
        gens = self.generators
        demand = self.demand

        model = gp.Model("ScheduleRun")
        model.Params.OutputFlag = 0
        model.Params.MIPGap     = 1e-6

        # ── 变量 ─────────────────────────────────────────────────────────────
        u  = model.addVars(N, T, vtype=GRB.BINARY, name="u")
        p  = model.addVars(N, T, lb=0.0,           name="p")
        su = model.addVars(N, T, vtype=GRB.BINARY, name="su")
        sd = model.addVars(N, T, vtype=GRB.BINARY, name="sd")

        # 分段线性成本的块填充变量 x[i][k][t]
        # x[i][k][t] : 机组 i 第 k 段在时段 t 的填充量 ∈ [0, width_k * u]
        x = {}
        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            for k, (slope_k, width_k) in enumerate(segs):
                for t in range(T):
                    x[i, k, t] = model.addVar(
                        lb=0.0, ub=width_k, name=f"x_{i}_{k}_{t}"
                    )

        # ── 目标函数 ──────────────────────────────────────────────────────────
        # Σ slope_k * x[i,k,t] + C_NL * u + C_SU * su + C_SD * sd
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

        # ── 约束 ─────────────────────────────────────────────────────────────

        # (1) 全局功率平衡：单节点 & 多节点均使用 Σ_i p_i = total_demand_t
        # DC PTDF 模型不使用节点平衡约束——节点 LMP 由 LP 定价运行的对偶后处理给出，
        # MILP（整数规划）不产生有意义的对偶价格。
        for t in range(T):
            model.addConstr(
                gp.quicksum(p[i, t] for i in range(N)) == float(demand[t]),
                name=f"balance_{t}"
            )

        # (1f) PTDF 线路容量约束（仅多节点模式）
        # 线路潮流：f_{l,t} = PTDF_Gen @ p_{,t} - (PTDF @ D_{,t})
        # 约束：-F_max ≤ f ≤ F_max → rhs_neg ≤ PTDF_Gen @ p ≤ rhs_pos
        if not self.network.is_single_node:
            PTDF_Gen         = self.network.PTDF_Gen    # (N_line, N_gen)
            rhs_pos, rhs_neg = self.network.line_rhs()  # (N_line, T)
            for l in range(self.network.N_line):
                for t in range(T):
                    lhs = gp.quicksum(
                        float(PTDF_Gen[l, i]) * p[i, t] for i in range(N)
                    )
                    model.addConstr(lhs <= float(rhs_pos[l, t]),
                                    name=f"flow_ub_{l}_{t}")
                    model.addConstr(lhs >= float(rhs_neg[l, t]),
                                    name=f"flow_lb_{l}_{t}")

        for i, g in enumerate(gens):
            segs = g.get_pwl_segments()
            K = len(segs)

            for t in range(T):
                # (8) 分段等式：p = P_min·u + Σ_k x[k]
                model.addConstr(
                    p[i, t] == g.P_min * u[i, t]
                    + gp.quicksum(x[i, k, t] for k in range(K)),
                    name=f"pwl_link_{i}_{t}"
                )
                # (9) 段宽约束：x[k] ≤ width_k · u
                for k, (_, width_k) in enumerate(segs):
                    model.addConstr(
                        x[i, k, t] <= width_k * u[i, t],
                        name=f"xub_{i}_{k}_{t}"
                    )

            # (2) 容量约束（隐含在 (8)+(9) 中，但保留以加速求解）
            for t in range(T):
                model.addConstr(p[i, t] >= g.P_min * u[i, t], name=f"cap_lb_{i}_{t}")
                model.addConstr(p[i, t] <= g.P_max * u[i, t], name=f"cap_ub_{i}_{t}")

            # (3)(4) 爬坡约束；(5) 启停逻辑
            for t in range(T):
                p_prev = p[i, t - 1] if t > 0 else float(g.initial_power)
                u_prev = u[i, t - 1] if t > 0 else int(g.initial_status)

                model.addConstr(su[i, t] >= u[i, t] - u_prev, name=f"su_logic_{i}_{t}")
                model.addConstr(sd[i, t] >= u_prev - u[i, t], name=f"sd_logic_{i}_{t}")

                model.addConstr(
                    p[i, t] - p_prev <= g.R_up * u_prev + g.SU_ramp * su[i, t],
                    name=f"ramp_up_{i}_{t}"
                )
                model.addConstr(
                    p_prev - p[i, t] <= g.R_down * u[i, t] + g.SD_ramp * sd[i, t],
                    name=f"ramp_dn_{i}_{t}"
                )

            if g.initial_status == 1:
                residual_on = max(0, g.T_on_min - int(g.initial_up_time))
                for t in range(min(residual_on, T)):
                    model.addConstr(u[i, t] == 1, name=f"init_on_residual_{i}_{t}")
            else:
                residual_off = max(0, g.T_off_min - int(g.initial_down_time))
                for t in range(min(residual_off, T)):
                    model.addConstr(u[i, t] == 0, name=f"init_off_residual_{i}_{t}")

            # (6) 最小开机时间（MUT）滚动窗口
            for t in range(T):
                u_prev = u[i, t - 1] if t > 0 else int(g.initial_status)
                if g.T_on_min > 1:
                    model.addConstr(
                        gp.quicksum(
                            u[i, tt]
                            for tt in range(t, min(t + g.T_on_min, T))
                        ) >= g.T_on_min * su[i, t],
                        name=f"mut_{i}_{t}"
                    )

            # (7) 最小停机时间（MDT）滚动窗口
            for t in range(T):
                u_prev = u[i, t - 1] if t > 0 else int(g.initial_status)
                if g.T_off_min > 1:
                    model.addConstr(
                        gp.quicksum(
                            (1 - u[i, tt])
                            for tt in range(t, min(t + g.T_off_min, T))
                        ) >= g.T_off_min * sd[i, t],
                        name=f"mdt_{i}_{t}"
                    )

        model.optimize()

        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(
                f"ScheduleRunMILP 求解失败，Status={model.Status}。"
                "请检查需求是否可行（总装机容量是否满足峰值需求）。"
            )

        # ── 提取结果 ──────────────────────────────────────────────────────────
        p_dispatch = np.array([[p[i, t].X for t in range(T)] for i in range(N)])
        u_dispatch = np.array([[round(u[i, t].X) for t in range(T)] for i in range(N)],
                               dtype=float)
        obj_val = model.ObjVal

        return p_dispatch, u_dispatch, obj_val
