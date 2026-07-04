"""
对比基准方法二：拉格朗日松弛 + 次梯度法（Lagrangian Relaxation + Subgradient Method）

原理
----
将耦合约束（功率平衡、线路容量）松弛到目标函数中，形成拉格朗日对偶问题：

  L(λ, μ) = Σ_i [ min_{UC_i} C_i(p_i) - λ_eff_{i} · p_i ] + λ · D
             - μ_ub · rhs_pos + μ_lb · rhs_neg     （多节点附加项）

其中：
  λ_eff_{i,t} = λ_t + Σ_l PTDF_Gen[l,i] · (μ_lb[l,t] - μ_ub[l,t])   （多节点）
  λ_eff_{i,t} = λ_t                                                     （单节点）

每次迭代分解为 N 个单机 UC MILP 子问题，再用次梯度法更新乘子。

次梯度更新公式
--------------
  λ^{k+1}       = λ^k + α_k · (D_t - Σ_i p_i*_t)         [无约束更新]
  μ_ub^{k+1}[l] = max(0, μ_ub^k[l] + α_k · g_ub[l])       [投影到非负域]
  μ_lb^{k+1}[l] = max(0, μ_lb^k[l] + α_k · g_lb[l])       [投影到非负域]

其中次梯度方向（以线路 l 为例）：
  g_ub[l,t] = (PTDF_Gen @ p*)_l,t - rhs_pos[l,t]  （线路上越限 > 0）
  g_lb[l,t] = rhs_neg[l,t] - (PTDF_Gen @ p*)_l,t  （线路下越限 > 0）

步长规则
--------
- Polyak 步长（若提供 milp_ub）：α_k = β · (f_UB - L(λ^k)) / ||g^k||²
  需要可行上界 f_UB（即 MILP 目标值），β ∈ (0, 2) 一般取 0.5~1.0。
  收敛速度最快，是电力系统 LR 文献中最常用的规则。
- 衰减步长（降级 fallback）：α_k = α_0 / sqrt(k)
  不需要 UB，适用于 MILP 未提前求解的场景。

LMP 重建（多节点）
-----------------
  LMP[n,t] = λ_t + Σ_l PTDF[l,n] · (μ_lb[l,t] - μ_ub[l,t])
  与 CHP LP 后处理公式对应关系：α = -μ_ub, β = -μ_lb（Gurobi 符号约定）。

局限性
------
- LR 对偶界 ≤ CHP LP 目标（因为 CHP LP 对凸包刻画更精确）。
- 次梯度法不保证原问题可行（功率不平衡是正常现象），需记录最优对偶界。
- 多节点需更多迭代收敛，因为乘子维度增加（T + 2·N_line·T）。
"""

from __future__ import annotations

import sys
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from models.network import NetworkModel, SingleNodeNetwork


class LagrangianRelaxation:
    """
    拉格朗日松弛 + 次梯度法。

    松弛耦合约束（功率平衡 + 线路容量），每轮迭代求解 N 个单机 MILP 子问题，
    再用 Polyak 步长或衰减步长更新对偶乘子。
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

    # ── 对外接口 ──────────────────────────────────────────────────────────────

    def solve(
        self,
        max_iter: int = 300,
        milp_ub: Optional[float] = None,
        beta_polyak: float = 0.5,
        alpha_init: float = 1.0,
        tol: float = 1e-3,
        verbose: bool = False,
    ) -> dict:
        """
        运行次梯度法求解拉格朗日对偶，返回最优价格和收敛历史。

        Parameters
        ----------
        max_iter    : 最大迭代次数
        milp_ub     : MILP 目标值（用于 Polyak 步长；None 时用衰减步长）
        beta_polyak : Polyak 步长缩放因子 β ∈ (0, 2)，推荐 0.5~1.0
        alpha_init  : 衰减步长初始值（仅在无 milp_ub 时使用）
        tol         : 收敛判据：次梯度 L2 范数 < tol 时提前停止
        verbose     : 是否打印每轮迭代信息

        Returns
        -------
        dict：{
          'lmp_matrix': (N_bus, T),       最优对偶乘子对应的 LMP
          'dual_bound': float,            最优对偶下界（最大 L(λ)）
          'n_iter': int,                  实际迭代次数
          'history': {                    收敛历史（用于绘图）
             'iter':       list[int],
             'dual_bound': list[float],
             'gap':        list[float],   仅在提供 milp_ub 时有效
             'step':       list[float],
             'grad_norm':  list[float],
          }
        }
        """
        T  = self.T
        N  = self.N
        is_single = self.network.is_single_node

        # 初始化乘子
        lam   = np.zeros(T)          # 功率平衡对偶（无约束）
        if not is_single:
            N_line = self.network.N_line
            mu_ub  = np.zeros((N_line, T))   # 线路上界乘子 ≥ 0
            mu_lb  = np.zeros((N_line, T))   # 线路下界乘子 ≥ 0
            PTDF_Gen = self.network.PTDF_Gen   # (N_line, N)
            rhs_pos, rhs_neg = self.network.line_rhs()  # (N_line, T)
        else:
            N_line = 0
            mu_ub  = np.empty((0, T))
            mu_lb  = np.empty((0, T))
            PTDF_Gen = np.empty((0, N))
            rhs_pos  = np.empty((0, T))
            rhs_neg  = np.empty((0, T))

        demand = self.network.sys_demand   # (T,)

        best_dual   = -np.inf
        best_lam    = lam.copy()
        best_mu_ub  = mu_ub.copy()
        best_mu_lb  = mu_lb.copy()

        history: Dict[str, list] = {
            "iter": [], "dual_bound": [], "best_dual": [], "gap": [],
            "step": [], "grad_norm": [], "elapsed_s": []
        }
        t_start = time.time()
        converged = False
        stop_reason = "max_iter"

        for k in range(1, max_iter + 1):

            # ── 计算各机组的有效价格 λ_eff ──────────────────────────────
            # 单节点：λ_eff_i = λ  (所有机组相同)
            # 多节点：λ_eff_{i,t} = λ_t + Σ_l PTDF_Gen[l,i]·(μ_lb[l,t] - μ_ub[l,t])
            if is_single:
                lambda_eff = np.tile(lam, (N, 1))   # (N, T)
            else:
                # congestion_correction[i,t] = Σ_l PTDF_Gen[l,i]·(μ_lb[l,t]-μ_ub[l,t])
                congestion = PTDF_Gen.T @ (mu_lb - mu_ub)   # (N, T)
                lambda_eff = lam[np.newaxis, :] + congestion   # (N, T)

            # ── 求解 N 个单机 MILP 子问题 ────────────────────────────────
            p_stars = np.zeros((N, T))
            sub_obj_total = 0.0
            for i, g in enumerate(self.generators):
                p_star_i, sub_obj_i = self._solve_unit_subproblem(g, lambda_eff[i])
                p_stars[i] = p_star_i
                sub_obj_total += sub_obj_i

            # ── 计算对偶函数值 L(λ, μ) ───────────────────────────────────
            # L = Σ q_i + λ·D - μ_ub·rhs_pos + μ_lb·rhs_neg
            dual_val = (
                sub_obj_total
                + float(np.dot(lam, demand))
                - float(np.sum(mu_ub * rhs_pos))
                + float(np.sum(mu_lb * rhs_neg))
            )

            if dual_val > best_dual:
                best_dual  = dual_val
                best_lam   = lam.copy()
                best_mu_ub = mu_ub.copy()
                best_mu_lb = mu_lb.copy()

            # ── 计算次梯度 ───────────────────────────────────────────────
            # g_λ[t] = D_t - Σ_i p_i*_t
            g_lam = demand - p_stars.sum(axis=0)   # (T,)

            if not is_single:
                # g_ub[l,t] = (PTDF_Gen @ p*)_l,t - rhs_pos[l,t]
                # g_lb[l,t] = rhs_neg[l,t] - (PTDF_Gen @ p*)_l,t
                flows  = PTDF_Gen @ p_stars        # (N_line, T)
                g_ub   = flows - rhs_pos           # (N_line, T); >0 → line overloaded
                g_lb   = rhs_neg - flows           # (N_line, T); >0 → flow below lower
            else:
                g_ub = np.empty((0, T))
                g_lb = np.empty((0, T))

            # ── 计算步长 ─────────────────────────────────────────────────
            grad_sq = float(np.sum(g_lam ** 2))
            if not is_single:
                grad_sq += float(np.sum(g_ub ** 2) + np.sum(g_lb ** 2))
            grad_norm = np.sqrt(grad_sq)

            if grad_norm < tol:
                converged = True
                stop_reason = "grad_norm"
                if verbose:
                    print(f"  [LR] 收敛：k={k}, ||g||={grad_norm:.2e}")
                break

            if milp_ub is not None and grad_sq > 1e-12:
                gap_val  = milp_ub - dual_val
                alpha_k  = beta_polyak * max(gap_val, 0.0) / grad_sq
            else:
                alpha_k  = alpha_init / np.sqrt(k)

            # ── 更新乘子 ─────────────────────────────────────────────────
            lam    = lam    + alpha_k * g_lam        # λ：无约束更新
            if not is_single:
                # μ_ub, μ_lb：投影到非负域 max(0, μ + α·g)
                mu_ub = np.maximum(0.0, mu_ub + alpha_k * g_ub)
                mu_lb = np.maximum(0.0, mu_lb + alpha_k * g_lb)

            # ── 记录历史 ─────────────────────────────────────────────────
            gap = (milp_ub - dual_val) if milp_ub is not None else float("nan")
            history["iter"].append(k)
            history["dual_bound"].append(dual_val)
            history["best_dual"].append(best_dual)
            history["gap"].append(gap)
            history["step"].append(alpha_k)
            history["grad_norm"].append(grad_norm)
            history["elapsed_s"].append(time.time() - t_start)

            if verbose and k % 50 == 0:
                print(
                    f"  [LR] k={k:4d}  dual={dual_val:10.2f}  "
                    f"gap={gap:8.2f}  step={alpha_k:.4f}  ||g||={grad_norm:.4f}"
                )

        # ── 重建最优 LMP ─────────────────────────────────────────────────────
        lam_best = best_lam.copy()
        lam_best = np.clip(lam_best, 0.0, None)   # LMP ≥ 0（单节点）

        if is_single:
            lmp_matrix = np.tile(lam_best, (1, 1))   # (1, T)
        else:
            # LMP[n,t] = λ_t + Σ_l PTDF[l,n]·(μ_lb[l,t] - μ_ub[l,t])
            PTDF = self.network.PTDF   # (N_line, N_bus)
            lmp_matrix = (
                lam_best[np.newaxis, :]                        # (1, T)
                + PTDF.T @ (best_mu_lb - best_mu_ub)          # (N_bus, T)
            )

        # 保存最优 PTDF 对偶乘子，供 FTR 成本计算（多节点 Eq.34 第二行）
        # LR 符号约定：mu_ub ≥ 0 → γ_paper（上界），mu_lb ≥ 0 → β_paper（下界）
        # 对应 Gurobi min LP：mu_ub = -alpha，mu_lb = -beta_code
        return {
            "lmp_matrix":  lmp_matrix,
            "dual_bound":  best_dual,
            "n_iter":      k,
            "history":     history,
            "converged":   converged,
            "stop_reason": stop_reason,
            "ptdf_mu_ub":  best_mu_ub if not is_single else None,   # (N_line, T), ≥ 0
            "ptdf_mu_lb":  best_mu_lb if not is_single else None,   # (N_line, T), ≥ 0
        }

    # ── 单机子问题求解 ────────────────────────────────────────────────────────

    def _solve_unit_subproblem(
        self,
        g: GeneratorParams,
        lambda_eff: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        """
        给定有效价格 λ_eff (T,)，为单台机组求解 UC MILP：

          min_{(u,p)∈UC_i} [ C_i(p, u) - λ_eff · p ]

        目标：最小化成本减去收入，等价于最大化利润。

        Returns
        -------
        p_star : (T,)  最优出力
        obj_val: float  子问题最优值 q_i(λ_eff)
        """
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as e:
            raise ImportError("需要 gurobipy。") from e

        T = self.T

        model = gp.Model("UnitSubproblem")
        model.Params.OutputFlag = 0
        model.Params.MIPGap     = 1e-5

        u  = model.addVars(T, vtype=GRB.BINARY, name="u")
        p  = model.addVars(T, lb=0.0,           name="p")
        su = model.addVars(T, vtype=GRB.BINARY, name="su")
        sd = model.addVars(T, vtype=GRB.BINARY, name="sd")

        segs = g.get_pwl_segments()
        K    = len(segs)
        x    = {}
        for k, (_, wk) in enumerate(segs):
            for t in range(T):
                x[k, t] = model.addVar(lb=0.0, ub=wk, name=f"x_{k}_{t}")

        # 目标：C_i(p,u) - λ_eff · p
        obj = gp.LinExpr()
        for t in range(T):
            for k, (slope_k, _) in enumerate(segs):
                obj += slope_k * x[k, t]
            obj += g.cost_nl * u[t]
            obj += g.cost_su * su[t]
            obj += g.cost_sd * sd[t]
            obj -= float(lambda_eff[t]) * p[t]   # 减去收入
        model.setObjective(obj, GRB.MINIMIZE)

        for t in range(T):
            # 分段等式
            model.addConstr(
                p[t] == g.P_min * u[t] + gp.quicksum(x[k, t] for k in range(K))
            )
            # 段宽
            for k, (_, wk) in enumerate(segs):
                model.addConstr(x[k, t] <= wk * u[t])
            # 容量
            model.addConstr(p[t] >= g.P_min * u[t])
            model.addConstr(p[t] <= g.P_max * u[t])

        for t in range(T):
            u_prev = u[t - 1] if t > 0 else int(g.initial_status)
            p_prev = p[t - 1] if t > 0 else float(g.initial_power)

            model.addConstr(su[t] >= u[t] - u_prev)
            model.addConstr(sd[t] >= u_prev - u[t])
            model.addConstr(p[t] - p_prev <= g.R_up * u_prev + g.SU_ramp * su[t])
            model.addConstr(p_prev - p[t] <= g.R_down * u[t] + g.SD_ramp * sd[t])

        if g.initial_status == 1:
            residual_on = max(0, g.T_on_min - int(g.initial_up_time))
            for t in range(min(residual_on, T)):
                model.addConstr(u[t] == 1)
        else:
            residual_off = max(0, g.T_off_min - int(g.initial_down_time))
            for t in range(min(residual_off, T)):
                model.addConstr(u[t] == 0)

        for t in range(T):
            if g.T_on_min > 1:
                model.addConstr(
                    gp.quicksum(u[tt] for tt in range(t, min(t + g.T_on_min, T)))
                    >= g.T_on_min * su[t]
                )
        for t in range(T):
            if g.T_off_min > 1:
                model.addConstr(
                    gp.quicksum(
                        (1 - u[tt]) for tt in range(t, min(t + g.T_off_min, T))
                    ) >= g.T_off_min * sd[t]
                )

        model.optimize()

        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            # 次梯度过程中偶发不可行时返回零（保守策略）
            return np.zeros(T), 0.0

        p_star = np.array([p[t].X for t in range(T)])
        return p_star, model.ObjVal
