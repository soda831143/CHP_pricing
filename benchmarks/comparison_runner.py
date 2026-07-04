"""
对比实验驱动器（Comparison Runner）

统一调用多种定价方法，并在同一把文献通用的物理标尺下比较：
  - 所有方法产生的价格 λ_matrix 都丢进同一个单机自调度 MILP
  - MILP 响应器输出每台机组在该价格下的最大理论利润
  - Uplift = max_profit - dispatch_profit，与方法无关，只与价格有关
  - 这保证了对比基准不依赖本文提出的 GP-DAG oracle

多节点 FTR 成本（金融传输权，Financial Transmission Right）
-----------------------------------------------------------
根据论文公式 (34)（Yang Xiao, 2025），多节点系统中：

  Total Uplift = Generator Uplift + FTR Cost

其中：
  Generator Uplift = Σ_g (max_profit_g - dispatch_profit_g)
  FTR Cost = Σ_l Σ_t [β_l,t × (F_l + f_l,t) + γ_l,t × (F_l - f_l,t)]

β_l,t ≥ 0：线路下界约束的对偶（binding when flow = -F_max）
γ_l,t ≥ 0：线路上界约束的对偶（binding when flow = F_max）
f_l,t：MILP 调度方案对应的实际线路潮流

与 Gurobi min LP 对偶的对应关系（Eq.34 对偶符号→代码变量）：
  γ_paper = -alpha  ≥ 0  （alpha = Pi of PTDF_Gen@p ≤ rhs_pos, Gurobi convention ≤ 0）
  β_paper = -beta_  ≥ 0  （beta_  = Pi of -PTDF_Gen@p ≤ -rhs_neg, Gurobi convention ≤ 0）
对于 LR 方法（最大化对偶）：
  γ_paper = mu_ub ≥ 0，β_paper = mu_lb ≥ 0（直接使用 LR 乘子）

单节点情形：β = γ = 0 → FTR Cost = 0 → Total Uplift = Generator Uplift = Duality Gap ✓
"""

from __future__ import annotations

import sys
import os
import time
import math
from typing import List, Optional, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from models.network import NetworkModel
from benchmarks.unit_self_schedule import UnitSelfScheduleMILP, dispatch_profit


# ─────────────────────────────────────────────────────────────────────────────
# FTR 成本计算
# ─────────────────────────────────────────────────────────────────────────────

def compute_milp_line_flows(network: NetworkModel, p_dispatch: np.ndarray) -> np.ndarray:
    """
    计算 MILP 调度方案对应的实际线路潮流。

    f_l,t = (PTDF_Gen @ p_dispatch[:,t])[l] - (PTDF @ demand[:,t])[l]

    Returns
    -------
    f_actual : (N_line, T)，单节点返回空矩阵 (0, T)
    """
    if network.is_single_node:
        return np.empty((0, network.T))
    return (
        network.PTDF_Gen @ p_dispatch              # (N_line, T): generator contribution
        - network.PTDF @ network.demand            # (N_line, T): load contribution
    )


def compute_ftr_from_gurobi_duals(
    alpha: Optional[np.ndarray],
    beta_code: Optional[np.ndarray],
    f_actual: np.ndarray,
    F_max: np.ndarray,
) -> Tuple[np.ndarray, float]:
    """
    从 Gurobi min LP 对偶变量计算 FTR 成本（适用于 CHP LP、M-IRP、LMP 方法）。

    论文公式 (34) 第二行：
      FTR = Σ_l Σ_t [β_paper × (F_l + f_l,t) + γ_paper × (F_l - f_l,t)]

    Gurobi 符号转换：
      γ_paper = -alpha  ≥ 0  （alpha ≤ 0）
      β_paper = -beta_  ≥ 0  （beta_ ≤ 0）

    Parameters
    ----------
    alpha     : (N_line, T) or None，Gurobi Pi of PTDF_Gen@p ≤ rhs_pos（≤ 0）
    beta_code : (N_line, T) or None，Gurobi Pi of -PTDF_Gen@p ≤ -rhs_neg（≤ 0）
    f_actual  : (N_line, T)，MILP 实际线路潮流
    F_max     : (N_line,)，线路容量

    Returns
    -------
    ftr_per_lt : (N_line, T)，各线路各时段的 FTR 成本
    ftr_total  : float，系统总 FTR 成本
    """
    if alpha is None or f_actual.shape[0] == 0:
        return np.zeros_like(f_actual), 0.0

    gamma_paper = -alpha      # ≥ 0，上界对偶
    beta_paper  = -beta_code  # ≥ 0，下界对偶
    ftr_per_lt  = (
        beta_paper  * (F_max[:, None] + f_actual)   # β × (F + f)
        + gamma_paper * (F_max[:, None] - f_actual)   # γ × (F - f)
    )
    return ftr_per_lt, float(ftr_per_lt.sum())


def compute_ftr_from_lr_duals(
    mu_ub: Optional[np.ndarray],
    mu_lb: Optional[np.ndarray],
    f_actual: np.ndarray,
    F_max: np.ndarray,
) -> Tuple[np.ndarray, float]:
    """
    从 LR 最优对偶乘子计算 FTR 成本（适用于拉格朗日松弛方法）。

    LR 符号与论文一致：γ_paper = mu_ub，β_paper = mu_lb（均 ≥ 0）
    FTR = Σ [mu_lb × (F + f) + mu_ub × (F - f)]
    """
    if mu_ub is None or f_actual.shape[0] == 0:
        return np.zeros_like(f_actual), 0.0
    ftr_per_lt = (
        mu_lb * (F_max[:, None] + f_actual)
        + mu_ub * (F_max[:, None] - f_actual)
    )
    return ftr_per_lt, float(ftr_per_lt.sum())


# ─────────────────────────────────────────────────────────────────────────────
# 核心辅助：在给定价格下用单机 UC MILP 统一结算 Uplift
# ─────────────────────────────────────────────────────────────────────────────

def compute_uplift_under_prices(
    generators: List[GeneratorParams],
    network: NetworkModel,
    p_dispatch: np.ndarray,
    u_dispatch: np.ndarray,
    lmp_matrix: np.ndarray,
) -> dict:
    """
    给定任意定价方法输出的 lmp_matrix，用单机自调度 MILP 统一结算各机组 Uplift。

    这是对比实验公平性的核心保证：响应问题是文献通用的 LOC 自调度问题，
    不使用本文提出的 GP-DAG greedy oracle。
    """
    max_profits  = []
    disp_profits = []
    uplifts      = []
    mw_uplift    = 0.0
    loc_uplift   = 0.0

    for i, g in enumerate(generators):
        node_idx = network.gen_bus_idx(i)
        lambda_i = lmp_matrix[node_idx]   # (T,)

        _, _, max_profit = UnitSelfScheduleMILP.solve(g, lambda_i)
        uplift = UnitSelfScheduleMILP.uplift(
            g, lambda_i, p_dispatch[i], u_dispatch[i], max_profit
        )
        disp_profit = dispatch_profit(g, lambda_i, p_dispatch[i], u_dispatch[i])

        dispatched = bool(np.any(u_dispatch[i] > 0.5))
        if dispatched:
            mw_uplift  += uplift
        else:
            loc_uplift += uplift

        max_profits.append(max_profit)
        disp_profits.append(disp_profit)
        uplifts.append(uplift)

    return {
        "max_profits":   max_profits,
        "disp_profits":  disp_profits,
        "uplifts":       uplifts,
        "gen_uplift":    mw_uplift + loc_uplift,   # 发电商侧机会成本之和
        "mw_uplift":     mw_uplift,
        "loc_uplift":    loc_uplift,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 主对比函数
# ─────────────────────────────────────────────────────────────────────────────

def timed_uplift_under_prices(
    generators: List[GeneratorParams],
    network: NetworkModel,
    p_dispatch: np.ndarray,
    u_dispatch: np.ndarray,
    lmp_matrix: np.ndarray,
) -> dict:
    t0 = time.perf_counter()
    out = compute_uplift_under_prices(
        generators, network, p_dispatch, u_dispatch, lmp_matrix
    )
    out["oracle_time"] = time.perf_counter() - t0
    return out


def timing_fields(solver, fallback_total: float) -> dict:
    return {
        "build_time": getattr(solver, "build_time", ""),
        "solver_time": getattr(solver, "solver_time", ""),
        "total_time": getattr(solver, "total_time", fallback_total),
    }


def run_comparison(
    generators: List[GeneratorParams],
    network: NetworkModel,
    p_dispatch: np.ndarray,
    u_dispatch: np.ndarray,
    milp_obj: float,
    chp_lp_obj: float,
    chp_lmp_matrix: np.ndarray,
    chp_uplifts: list,
    chp_ptdf_alpha: Optional[np.ndarray] = None,
    chp_ptdf_beta_: Optional[np.ndarray] = None,
    methods: Optional[List[str]] = None,
    lr_max_iter: int = 300,
    lr_verbose: bool = False,
    xiao_max_states: int = 200000,
    xiao_state_step: float = 0.0,
    chp_solve_time: float = 0.0,
) -> dict:
    """
    运行对比实验，调用选定的基准方法并输出对比表。

    Parameters
    ----------
    chp_ptdf_alpha  : (N_line, T) CHP LP 上界约束对偶（Gurobi ≤ 0），用于 FTR 计算
    chp_ptdf_beta_  : (N_line, T) CHP LP 下界约束对偶（Gurobi ≤ 0），用于 FTR 计算
    """
    if methods is None:
        methods = ["lmp", "mirp", "level", "dwp"]

    # 预计算 MILP 实际线路潮流（用于所有方法的 FTR 计算）
    f_actual = compute_milp_line_flows(network, p_dispatch)   # (N_line, T)
    F_max    = network.F_max if not network.is_single_node else np.empty(0)

    results = {}

    # ── CHP（基准）────────────────────────────────────────────────────────
    if not (isinstance(chp_lp_obj, float) and math.isnan(chp_lp_obj)):
        chp_oracle = timed_uplift_under_prices(
            generators, network, p_dispatch, u_dispatch, chp_lmp_matrix
        )
        _, chp_ftr = compute_ftr_from_gurobi_duals(
            chp_ptdf_alpha, chp_ptdf_beta_, f_actual, F_max
        )
        results["chp"] = {
            "name":        "CHP 原空间精确 LP（本文）",
            "pricing_obj": chp_lp_obj,
            "duality_gap": milp_obj - chp_lp_obj,
            "lmp_min":     float(chp_lmp_matrix.min()),
            "lmp_max":     float(chp_lmp_matrix.max()),
            "gen_uplift":  chp_oracle["gen_uplift"],
            "ftr_cost":    chp_ftr,
            "total_uplift":chp_oracle["gen_uplift"] + chp_ftr,
            "mw_uplift":   chp_oracle["mw_uplift"],
            "loc_uplift":  chp_oracle["loc_uplift"],
            "solve_time":  chp_solve_time,
            "lmp_matrix":  chp_lmp_matrix,
            "per_unit":    chp_oracle,
        }
        results["chp"].update({
            "build_time": "",
            "solver_time": "",
            "total_time": chp_solve_time,
            "oracle_time": chp_oracle.get("oracle_time", ""),
        })

    # ── M-IRP ─────────────────────────────────────────────────────────────
    if "mirp" in methods:
        from benchmarks.mirp_pricing import MIRPPricing
        t0 = time.time()
        mirp = MIRPPricing(generators, network)
        mirp_lmp, mirp_obj, _ = mirp.solve()
        mirp_time = time.time() - t0
        mirp_oracle = timed_uplift_under_prices(
            generators, network, p_dispatch, u_dispatch, mirp_lmp
        )
        _, mirp_ftr = compute_ftr_from_gurobi_duals(
            mirp._ptdf_alpha, mirp._ptdf_beta_, f_actual, F_max
        )
        results["mirp"] = {
            "name":        "M-IRP（LP 松弛 / LR 对偶界）",
            "pricing_obj": mirp_obj,
            "duality_gap": milp_obj - mirp_obj,
            "lmp_min":     float(mirp_lmp.min()),
            "lmp_max":     float(mirp_lmp.max()),
            "gen_uplift":  mirp_oracle["gen_uplift"],
            "ftr_cost":    mirp_ftr,
            "total_uplift":mirp_oracle["gen_uplift"] + mirp_ftr,
            "mw_uplift":   mirp_oracle["mw_uplift"],
            "loc_uplift":  mirp_oracle["loc_uplift"],
            "solve_time":  mirp_time,
            "lmp_matrix":  mirp_lmp,
            "per_unit":    mirp_oracle,
        }
        results["mirp"].update(timing_fields(mirp, mirp_time))
        results["mirp"]["oracle_time"] = mirp_oracle.get("oracle_time", "")

    # ── Plain Lagrangian-relaxation subgradient benchmark ────────────────
    if "lrp" in methods:
        from benchmarks.lagrangian_relaxation import LagrangianRelaxation
        t0 = time.time()
        lr_solver = LagrangianRelaxation(generators, network)
        lr_out = lr_solver.solve(
            max_iter=lr_max_iter,
            milp_ub=milp_obj,
            beta_polyak=0.5,
            tol=1e-3,
            verbose=lr_verbose,
        )
        lr_time = time.time() - t0
        lr_lmp = lr_out["lmp_matrix"]
        lr_oracle = timed_uplift_under_prices(
            generators, network, p_dispatch, u_dispatch, lr_lmp
        )
        _, lr_ftr = compute_ftr_from_lr_duals(
            lr_out.get("ptdf_mu_ub"), lr_out.get("ptdf_mu_lb"), f_actual, F_max
        )
        results["lrp"] = {
            "name":        f"Lagrangian relaxation（{lr_out['n_iter']} 次迭代）",
            "pricing_obj": lr_out["dual_bound"],
            "duality_gap": milp_obj - lr_out["dual_bound"],
            "lmp_min":     float(lr_lmp.min()),
            "lmp_max":     float(lr_lmp.max()),
            "gen_uplift":  lr_oracle["gen_uplift"],
            "ftr_cost":    lr_ftr,
            "total_uplift":lr_oracle["gen_uplift"] + lr_ftr,
            "mw_uplift":   lr_oracle["mw_uplift"],
            "loc_uplift":  lr_oracle["loc_uplift"],
            "solve_time":  lr_time,
            "lmp_matrix":  lr_lmp,
            "per_unit":    lr_oracle,
            "history":     lr_out["history"],
            "n_iter":      lr_out["n_iter"],
            "converged":   lr_out.get("converged", False),
            "stop_reason": lr_out.get("stop_reason", "max_iter"),
        }
        results["lrp"].update({
            "build_time": "",
            "solver_time": "",
            "total_time": lr_time,
            "oracle_time": lr_oracle.get("oracle_time", ""),
        })

    # ── Level method / bundle-stabilized LR ──────────────────────────────
    if "level" in methods:
        from benchmarks.level_method_pricing import LevelMethodPricing
        t0 = time.time()
        level_solver = LevelMethodPricing(generators, network)
        level_out = level_solver.solve(
            max_iter=lr_max_iter,
            tol=1e-4,
            verbose=lr_verbose,
        )
        level_time = time.time() - t0
        level_lmp = level_out["lmp_matrix"]
        level_oracle = timed_uplift_under_prices(
            generators, network, p_dispatch, u_dispatch, level_lmp
        )
        _, level_ftr = compute_ftr_from_lr_duals(
            level_out.get("ptdf_mu_ub"), level_out.get("ptdf_mu_lb"), f_actual, F_max
        )
        results["level"] = {
            "name":        f"Level method（{level_out['n_iter']} 次迭代）",
            "pricing_obj": level_out["dual_bound"],
            "duality_gap": milp_obj - level_out["dual_bound"],
            "lmp_min":     float(level_lmp.min()),
            "lmp_max":     float(level_lmp.max()),
            "gen_uplift":  level_oracle["gen_uplift"],
            "ftr_cost":    level_ftr,
            "total_uplift":level_oracle["gen_uplift"] + level_ftr,
            "mw_uplift":   level_oracle["mw_uplift"],
            "loc_uplift":  level_oracle["loc_uplift"],
            "solve_time":  level_time,
            "lmp_matrix":  level_lmp,
            "per_unit":    level_oracle,
            "history":     level_out["history"],
            "n_iter":      level_out["n_iter"],
            "converged":   level_out.get("converged", False),
            "stop_reason": level_out.get("stop_reason", "max_iter"),
            "upper_bound": level_out.get("upper_bound", float("nan")),
        }
        results["level"].update(timing_fields(level_solver, level_time))
        results["level"]["oracle_time"] = level_oracle.get("oracle_time", "")

    def _store_dwp_result(key: str, solver, display_name: str) -> None:
        t0 = time.time()
        dwp_lmp, dwp_obj, _ = solver.solve()
        dwp_time = time.time() - t0
        dwp_oracle = timed_uplift_under_prices(
            generators, network, p_dispatch, u_dispatch, dwp_lmp
        )
        _, dwp_ftr = compute_ftr_from_gurobi_duals(
            solver._ptdf_alpha, solver._ptdf_beta_, f_actual, F_max
        )
        dwp_status = "收敛" if solver.converged else (
            "停滞" if solver.stalled else "未收敛"
        )
        results[key] = {
            "name":        f"{display_name}（{solver.n_iter} 轮，{dwp_status}）",
            "pricing_obj": dwp_obj,
            "duality_gap": milp_obj - dwp_obj,
            "lmp_min":     float(dwp_lmp.min()),
            "lmp_max":     float(dwp_lmp.max()),
            "gen_uplift":  dwp_oracle["gen_uplift"],
            "ftr_cost":    dwp_ftr,
            "total_uplift":dwp_oracle["gen_uplift"] + dwp_ftr,
            "mw_uplift":   dwp_oracle["mw_uplift"],
            "loc_uplift":  dwp_oracle["loc_uplift"],
            "solve_time":  dwp_time,
            "lmp_matrix":  dwp_lmp,
            "per_unit":    dwp_oracle,
            "history":     solver.history,
            "n_iter":      solver.n_iter,
            "n_columns":   solver.n_columns,
            "converged":    solver.converged,
            "stop_reason":  solver.stop_reason,
        }
        results[key].update(timing_fields(solver, dwp_time))
        results[key]["oracle_time"] = dwp_oracle.get("oracle_time", "")

    # ── Dantzig-Wolfe / Column Generation ───────────────────────────────
    # Main DWP benchmark: rebuilt RMP with parallel unit pricing.  The
    # incremental-RMP implementation is kept as a supplementary timing variant.
    if "dwp" in methods:
        from benchmarks.dantzig_wolfe_pricing_rebuild import ParallelRebuiltDantzigWolfePricing
        _store_dwp_result(
            "dwp",
            ParallelRebuiltDantzigWolfePricing(
                generators=generators,
                network=network,
                p_dispatch=p_dispatch,
                u_dispatch=u_dispatch,
            ),
            "Dantzig-Wolfe",
        )

    if "dwp_incremental" in methods:
        from benchmarks.dantzig_wolfe_pricing import DantzigWolfePricing
        _store_dwp_result(
            "dwp_incremental",
            DantzigWolfePricing(
                generators=generators,
                network=network,
                p_dispatch=p_dispatch,
                u_dispatch=u_dispatch,
            ),
            "Dantzig-Wolfe (incremental)",
        )

    # ── Xiao explicit formulation / M-CHP ───────────────────────────────
    if "xiao" in methods:
        from benchmarks.xiao_explicit_pricing import XiaoExplicitPricing
        t0 = time.time()
        xiao_solver = XiaoExplicitPricing(
            generators=generators,
            network=network,
            max_states_per_unit=xiao_max_states,
            state_output_step=xiao_state_step,
        )
        xiao_lmp, xiao_obj, _ = xiao_solver.solve()
        xiao_time = time.time() - t0
        xiao_oracle = timed_uplift_under_prices(
            generators, network, p_dispatch, u_dispatch, xiao_lmp
        )
        _, xiao_ftr = compute_ftr_from_gurobi_duals(
            xiao_solver._ptdf_alpha, xiao_solver._ptdf_beta_, f_actual, F_max
        )
        results["xiao"] = {
            "name":        f"Xiao explicit M-CHP（{xiao_solver.n_arcs} arcs）",
            "pricing_obj": xiao_obj,
            "duality_gap": milp_obj - xiao_obj,
            "lmp_min":     float(xiao_lmp.min()),
            "lmp_max":     float(xiao_lmp.max()),
            "gen_uplift":  xiao_oracle["gen_uplift"],
            "ftr_cost":    xiao_ftr,
            "total_uplift":xiao_oracle["gen_uplift"] + xiao_ftr,
            "mw_uplift":   xiao_oracle["mw_uplift"],
            "loc_uplift":  xiao_oracle["loc_uplift"],
            "solve_time":  xiao_time,
            "lmp_matrix":  xiao_lmp,
            "per_unit":    xiao_oracle,
            "n_states":    xiao_solver.n_states,
            "n_arcs":      xiao_solver.n_arcs,
        }
        results["xiao"].update(timing_fields(xiao_solver, xiao_time))
        results["xiao"]["oracle_time"] = xiao_oracle.get("oracle_time", "")

    # ── LMP（传统边际电价）────────────────────────────────────────────────
    if "lmp" in methods:
        from benchmarks.lmp_pricing import FixedULP
        t0 = time.time()
        lmp_solver = FixedULP(generators, network, u_dispatch)
        lmp_lmp, lmp_obj, _ = lmp_solver.solve()
        lmp_time   = time.time() - t0
        lmp_oracle = timed_uplift_under_prices(
            generators, network, p_dispatch, u_dispatch, lmp_lmp
        )
        _, lmp_ftr = compute_ftr_from_gurobi_duals(
            lmp_solver._ptdf_alpha, lmp_solver._ptdf_beta_, f_actual, F_max
        )
        results["lmp"] = {
            "name":        "传统 LMP（固定启停 LP）",
            "pricing_obj": lmp_obj,
            "duality_gap": float("nan"),
            "lmp_min":     float(lmp_lmp.min()),
            "lmp_max":     float(lmp_lmp.max()),
            "gen_uplift":  lmp_oracle["gen_uplift"],
            "ftr_cost":    lmp_ftr,
            "total_uplift":lmp_oracle["gen_uplift"] + lmp_ftr,
            "mw_uplift":   lmp_oracle["mw_uplift"],
            "loc_uplift":  lmp_oracle["loc_uplift"],
            "solve_time":  lmp_time,
            "lmp_matrix":  lmp_lmp,
            "per_unit":    lmp_oracle,
        }
        results["lmp"].update(timing_fields(lmp_solver, lmp_time))
        results["lmp"]["oracle_time"] = lmp_oracle.get("oracle_time", "")

    _print_comparison_table(results, milp_obj, generators, network)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 打印格式化对比表
# ─────────────────────────────────────────────────────────────────────────────

def _print_comparison_table(
    results: dict,
    milp_obj: float,
    generators: List[GeneratorParams],
    network: NetworkModel,
) -> None:
    W    = 88
    sep  = "─" * W
    eq   = "═" * W
    order = ["chp", "xiao", "dwp", "dwp_incremental", "mirp", "level", "lmp"]
    keys  = [k for k in order if k in results]

    is_multi = not network.is_single_node
    mode_str = "多节点 PTDF" if is_multi else "单节点"

    print()
    print(eq)
    print(f"  {'定价方法对比实验':^{W-4}}")
    print(f"  MILP 调度成本: {milp_obj:,.2f} $   |   网络模式: {mode_str}   |   T={network.T}")
    print(eq)

    name_w = 30

    if is_multi:
        # 多节点：显示发电商机会成本 + FTR + 总 Uplift 三列
        hdr = (f"  {'方法':<{name_w}}"
               f"  {'发电机Uplift($)':>16}"
               f"  {'FTR成本($)':>12}"
               f"  {'总Uplift($)':>12}"
               f"  {'Gap($)':>12}"
               f"  {'时间(s)':>8}")
        print(hdr)
        print(sep)
        for k in keys:
            r   = results[k]
            gap = r["duality_gap"]
            gap_s = f"{gap:,.2f}" if not (isinstance(gap, float) and np.isnan(gap)) else "   N/A   "
            chk   = " [=]" if abs(r["total_uplift"] - gap) < 1.0 else "    "
            print(
                f"  {r['name']:<{name_w}}"
                f"  {r['gen_uplift']:>16,.2f}"
                f"  {r['ftr_cost']:>12,.2f}"
                f"  {r['total_uplift']:>12,.2f}"
                f"  {gap_s:>12}"
                f"  {r['solve_time']:>8.3f}"
                f"{chk}"
            )
        print(sep)
        print(f"  [*] 理论恒等式（无阻塞）：发电机Uplift + FTR成本 = 总Uplift = Duality Gap")
        print(f"  [*] FTR成本 = Σ_l Σ_t [β_l,t×(F_l+f_l,t) + γ_l,t×(F_l-f_l,t)]（论文公式34）")
    else:
        # 单节点：FTR = 0，简化显示
        hdr = (f"  {'方法':<{name_w}}"
               f"  {'定价目标($)':>14}"
               f"  {'Gap($)':>12}"
               f"  {'λ范围($/MWh)':>18}"
               f"  {'总Uplift($)':>12}"
               f"  {'时间(s)':>8}")
        print(hdr)
        print(sep)
        for k in keys:
            r   = results[k]
            gap = r["duality_gap"]
            gap_s = f"{gap:,.2f}" if not (isinstance(gap, float) and np.isnan(gap)) else "   N/A   "
            lmp_rng = f"[{r['lmp_min']:.2f},{r['lmp_max']:.2f}]"
            chk = " [OK]" if abs(r["total_uplift"] - gap) < 1.0 else "      "
            print(
                f"  {r['name']:<{name_w}}"
                f"  {r['pricing_obj']:>14,.2f}"
                f"  {gap_s:>12}"
                f"  {lmp_rng:>18}"
                f"  {r['total_uplift']:>12,.2f}"
                f"  {r['solve_time']:>8.3f}"
                f"{chk}"
            )
        print(sep)

    print()

    # ── 经济学结论摘要 ────────────────────────────────────────────────────
    if "chp" in results and "lmp" in results:
        chp_u = results["chp"]["total_uplift"]
        lmp_u = results["lmp"]["total_uplift"]
        print(f"  [经济效益] CHP vs LMP 总Uplift节省: {lmp_u - chp_u:,.2f} $  "
              f"（减少 {100*(lmp_u-chp_u)/max(lmp_u,1):.1f}%）")
    if "chp" in results and "dwp" in results:
        print(f"  [一致性]   CHP Gap={results['chp']['duality_gap']:,.2f}$  vs  "
              f"DWP Gap={results['dwp']['duality_gap']:,.2f}$（两者都应逼近精确凸包定价）")
    if "chp" in results and "xiao" in results:
        print(f"  [一致性]   CHP Gap={results['chp']['duality_gap']:,.2f}$  vs  "
              f"Xiao Gap={results['xiao']['duality_gap']:,.2f}$（同模型下 exact CHP 目标应一致）")
    if "chp" in results and "mirp" in results:
        print(f"  [精确性]   CHP Gap={results['chp']['duality_gap']:,.2f}$  vs  "
              f"M-IRP Gap={results['mirp']['duality_gap']:,.2f}$（CHP 凸包约束更紧）")
    print(eq)

    # ── 各机组 Uplift 明细表 ─────────────────────────────────────────────
    N = len(generators)
    print(f"\n  各机组 Uplift 明细 ($/日）")
    print(sep)
    header = f"  {'机组':<8s}"
    for k in keys:
        header += f"  {results[k]['name'][:16]:>18s}"
    print(header)
    print(sep)
    for i, g in enumerate(generators):
        row = f"  {g.unit_id:<8s}"
        for k in keys:
            row += f"  {results[k]['per_unit']['uplifts'][i]:>18.2f}"
        print(row)
    print(sep)
    row = f"  {'发电机合计':<8s}"
    for k in keys:
        row += f"  {results[k]['gen_uplift']:>18.2f}"
    print(row)
    if is_multi:
        row = f"  {'FTR 成本':<8s}"
        for k in keys:
            row += f"  {results[k]['ftr_cost']:>18.2f}"
        print(row)
        print(sep)
        row = f"  {'总 Uplift':<8s}"
        for k in keys:
            row += f"  {results[k]['total_uplift']:>18.2f}"
        print(row)
    print("═" * W)
