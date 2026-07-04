"""
Phase 1：定价运行主问题（Pricing Master Problem）。

使用 Gurobi Matrix API 构建纯连续 LP，通过透视缩放约束精确刻画
火电机组可行域的凸包，提取功率平衡约束的对偶变量作为凸包电价 λ*。

支持单节点与多节点（PTDF 直流潮流）两种网络模式，
由 NetworkModel.is_single_node 自动切换，其余求解器代码完全不变。

变量布局
--------
x = [z_vars | v_vars | cvar_vars]

z_vars（共 Σ_i (n_on_i + n_off_i) 个）：
  每台机组每条 ON/OFF 弧的流量变量 z_{i,e} ∈ [0,1]

v_vars（共 Σ_i Σ_e duration_e 个，仅 ON 弧）：
  每台机组每条 ON 弧在每个时段的差分出力 v_{i,e,τ}（自由变量）
  物理意义：p_{i,e,τ} = Σ_{k=0}^{τ} v_{i,e,k}（即总出力，非超出 P_min 部分）

cvar_vars（与 v_vars 等数量）：
  每台机组每条 ON 弧每个时段的变动成本上镜图变量 c_var_{i,e,τ} ≥ 0

等式约束顺序
-----------
[0 : n_flow)                        flow_conservation  — 节点流量守恒
[n_flow : n_flow+n_src)             source_flow        — 源节点流出 = 1
[n_flow+n_src : n_flow+n_src+n_bal) system_balance     — 系统功率平衡 ← dual = λ*

  单节点：n_bal = T，dual (T,) = λ*
  多节点：n_bal = T，dual (T,) = 系统能量价格基准 λ*
          节点 LMP 由 λ* 与 PTDF 线路容量对偶变量后处理得到

不等式约束
----------
(A) 物理透视约束（每条 ON 弧 4 类）
(B) 分段线性成本上镜图约束（PWL 模式）
(C) PTDF 线路容量约束（多节点模式）：每条线路每时段 2 个（±F_max）

目标函数
--------
单段 (is_single_segment == True)：
  Abel 稀疏化：C_var * (duration - τ) * v_{e,τ}  + C_fix * z_e
  （其中 C_fix 中 z_e 系数已扣减 C_var * n * P_min）

分段 (is_single_segment == False)：
  Σ_{i,e,τ} c_var_{i,e,τ}  +  Σ_{i,e} C_fix_e · z_e
"""

from __future__ import annotations
import sys
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp

# chp_solver/ → chp_project/
_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from models.network import NetworkModel, SingleNodeNetwork
from chp_core.graph_builder import DAGBuilder, GeneratorDAG, OnInterval, OffArc


# ─────────────────────────────────────────────────────────────────────────────
# 变量索引辅助结构
# ─────────────────────────────────────────────────────────────────────────────

class _VarIndex:
    """记录所有变量的列偏移，供稀疏矩阵构建使用。"""

    def __init__(self, dags: List[GeneratorDAG],
                 use_pwl: bool = False) -> None:
        self.dags    = dags
        self.use_pwl = use_pwl

        # ── z 变量偏移 ────────────────────────────────────────────────────────
        self.z_on_offset:  List[List[int]] = []
        self.z_off_offset: List[List[int]] = []
        col = 0
        for dag in dags:
            on_cols  = list(range(col, col + dag.n_on));  col += dag.n_on
            off_cols = list(range(col, col + dag.n_off)); col += dag.n_off
            self.z_on_offset.append(on_cols)
            self.z_off_offset.append(off_cols)
        self.n_z = col

        # ── v 变量偏移 ────────────────────────────────────────────────────────
        self.v_offset: List[List[int]] = []
        for i, dag in enumerate(dags):
            v_cols = []
            for iv in dag.on_intervals:
                v_cols.append(col)
                col += iv.duration
            self.v_offset.append(v_cols)
        self.n_v = col - self.n_z

        # ── cvar 变量偏移（仅分段线性模式）──────────────────────────────────
        # 每条 ON 弧的每个时段对应一个 cvar 变量
        self.cvar_offset: List[List[int]] = []
        if use_pwl:
            for i, dag in enumerate(dags):
                cv_cols = []
                for iv in dag.on_intervals:
                    cv_cols.append(col)
                    col += iv.duration
                self.cvar_offset.append(cv_cols)
        else:
            for dag in dags:
                self.cvar_offset.append([])

        self.n_cvar  = col - self.n_z - self.n_v
        self.n_total = col

    def z_on(self, i: int, k: int) -> int:
        return self.z_on_offset[i][k]

    def z_off(self, i: int, k: int) -> int:
        return self.z_off_offset[i][k]

    def v(self, i: int, k: int, local_tau: int) -> int:
        return self.v_offset[i][k] + local_tau

    def cvar(self, i: int, k: int, local_tau: int) -> int:
        """仅 use_pwl == True 时有效。"""
        return self.cvar_offset[i][k] + local_tau


# ─────────────────────────────────────────────────────────────────────────────
# 主问题 LP 类
# ─────────────────────────────────────────────────────────────────────────────

class PrimalCHPLP:
    """
    原空间凸包定价主问题（纯连续 LP）。

    自动检测 GeneratorParams.is_single_segment：
      True  → Abel 稀疏目标（无额外变量，高效）
      False → max-of-lines 上镜图目标（支持分段线性成本，精确）
    """

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
        *,
        method: int = 2,
        crossover: int = 0,
        bar_conv_tol: Optional[float] = None,
        feasibility_tol: Optional[float] = None,
        optimality_tol: Optional[float] = None,
        numeric_focus: Optional[int] = None,
    ) -> None:
        self.generators = generators
        if isinstance(network, np.ndarray):
            network = SingleNodeNetwork(network)
        self.network = network
        self.demand  = network.sys_demand
        self.T       = network.T
        self.N       = len(generators)

        self.dags: List[GeneratorDAG] = [
            DAGBuilder.build(g) for g in generators
        ]

        # 若任意一台机组使用分段线性成本，启用 cvar 变量
        self._use_pwl = any(not g.is_single_segment for g in generators)
        self._idx     = _VarIndex(self.dags, use_pwl=self._use_pwl)
        self._balance_constrs = None
        self._model           = None
        self._solution_x      = None
        self.method = method
        self.crossover = crossover
        self.bar_conv_tol = bar_conv_tol
        self.feasibility_tol = feasibility_tol
        self.optimality_tol = optimality_tol
        self.numeric_focus = numeric_focus
        self.build_time = float("nan")
        self.solver_time = float("nan")
        self.total_time = float("nan")

    # ── 对外接口 ──────────────────────────────────────────────────────────────

    def solve(self) -> Tuple[np.ndarray, float, bool]:
        """
        构建并求解 LP，返回 LMP 矩阵、目标值和成功标志。

        Returns
        -------
        lmp_matrix : (N_bus, T) 节点边际电价矩阵 ($/MWh)
                     单节点模式下 N_bus=1，lmp_matrix[0] 即为全局电价 λ*
                     多节点模式下 lmp_matrix[n, t] 为节点 n 在时段 t 的 LMP
        obj_val    : float  LP 目标值 ($)
        success    : bool
        """
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as e:
            raise ImportError("需要安装 gurobipy 才能运行 PrimalCHPLP。") from e

        solve_start = time.perf_counter()
        idx    = self._idx
        n_cols = idx.n_total

        # ── 1. 变量界限 ─────────────────────────────────────────────────────
        lb = np.zeros(n_cols)
        ub = np.full(n_cols, np.inf)

        for i, dag in enumerate(self.dags):
            for k in range(dag.n_on):
                ub[idx.z_on(i, k)] = 1.0
            for k in range(dag.n_off):
                ub[idx.z_off(i, k)] = 1.0

        # v 变量：自由变量
        for i, dag in enumerate(self.dags):
            for k, iv in enumerate(dag.on_intervals):
                for tau in range(iv.duration):
                    lb[idx.v(i, k, tau)] = -GRB.INFINITY
                    ub[idx.v(i, k, tau)] =  GRB.INFINITY

        # cvar 变量：非负（上镜图约束自动保证从下方限制）
        if self._use_pwl:
            for i, dag in enumerate(self.dags):
                for k, iv in enumerate(dag.on_intervals):
                    for tau in range(iv.duration):
                        lb[idx.cvar(i, k, tau)] = 0.0
                        ub[idx.cvar(i, k, tau)] = GRB.INFINITY

        # ── 2. 目标函数 ─────────────────────────────────────────────────────
        # cost_var / pwl_slopes 仅作用于超出 P_min 的出力部分。
        # 因此 Abel 稀疏化后 z_e 系数需减去 cost_var * duration * P_min，
        # 对应 Σ_τ cost_var*(p_τ - z*P_min) 的展开。
        c_obj = np.zeros(n_cols)
        for i, (dag, params) in enumerate(zip(self.dags, self.generators)):
            for k, iv in enumerate(dag.on_intervals):
                if not self._use_pwl or params.is_single_segment:
                    # 单段 Abel 稀疏化：
                    # Σ_τ cost_var*(p_τ - z*P_min) = cost_var*Σp_τ - cost_var*n*P_min*z
                    # Abel of cost_var*Σp_τ = Σ_τ cost_var*(n-τ)*v_τ
                    p0 = params.initial_power if iv.initial_online else 0.0
                    c_obj[idx.z_on(i, k)] = (
                        iv.c_fix + params.cost_var * iv.duration * (p0 - params.P_min)
                    )
                    for tau in range(iv.duration):
                        c_obj[idx.v(i, k, tau)] = params.cost_var * (iv.duration - tau)
                else:
                    # 分段：cvar 变量进目标，v 系数 = 0
                    # cvar 上镜图约束中已用 (b_k - s_k*P_min)*z 正确扣减 P_min 基底
                    c_obj[idx.z_on(i, k)] = iv.c_fix
                    for tau in range(iv.duration):
                        c_obj[idx.cvar(i, k, tau)] = 1.0
            for k, arc in enumerate(dag.off_arcs):
                c_obj[idx.z_off(i, k)] = arc.c_fix

        # ── 3. 等式约束 ─────────────────────────────────────────────────────
        A_eq_csr, b_eq, n_flow, n_src, n_bal = self._build_eq_constraints(idx)

        # ── 4. 不等式约束（物理透视 + PWL 上镜图）─────────────────────────
        A_ub_csr, b_ub = self._build_ineq_constraints(idx)

        # ── 5. Gurobi 求解 ─────────────────────────────────────────────────
        build_done = time.perf_counter()
        model = gp.Model("PrimalCHP")
        model.Params.OutputFlag = 0
        model.Params.Method     = self.method
        model.Params.Crossover  = self.crossover
        if self.bar_conv_tol is not None:
            model.Params.BarConvTol = self.bar_conv_tol
        if self.feasibility_tol is not None:
            model.Params.FeasibilityTol = self.feasibility_tol
        if self.optimality_tol is not None:
            model.Params.OptimalityTol = self.optimality_tol
        if self.numeric_focus is not None:
            model.Params.NumericFocus = self.numeric_focus

        x = model.addMVar(shape=n_cols, lb=lb, ub=ub, name="x")
        eq_constrs   = model.addMConstr(A_eq_csr, x, '=', b_eq, name="eq")
        ineq_constrs = None
        if A_ub_csr.shape[0] > 0:
            ineq_constrs = model.addMConstr(A_ub_csr, x, '<', b_ub, name="ineq")

        model.setMObjective(None, c_obj, 0.0, sense=GRB.MINIMIZE)
        model.optimize()
        self._model = model
        self.build_time = build_done - solve_start
        self.solver_time = float(getattr(model, "Runtime", float("nan")))
        self.total_time = time.perf_counter() - solve_start

        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            self._ptdf_alpha = None
            self._ptdf_beta_ = None
            N_bus = self.network.N_bus
            return np.zeros((N_bus, self.T)), float("inf"), False

        obj_val = model.ObjVal
        self._solution_x = np.array(x.X, dtype=float)

        # ── 6. 提取全局能量价格 λ（等式约束对偶）─────────────────────────
        # 等式约束行排列：[n_flow | n_src | n_bal]
        # n_bal = T，全局平衡约束，对偶 = 能量价格 λ_t（所有节点共享基准）
        all_pi_eq  = np.array(eq_constrs.Pi)
        balance_pi = all_pi_eq[n_flow + n_src : n_flow + n_src + n_bal]   # (T,)

        # 符号修正：barrier 内点法有时返回符号相反的对偶
        if np.all(balance_pi <= 1e-8) and np.any(balance_pi < -1e-6):
            balance_pi = -balance_pi
        balance_pi = np.where(np.abs(balance_pi) < 1e-8, 0.0, balance_pi)
        balance_pi = np.clip(balance_pi, 0.0, None)    # 能量价格非负
        lambda_t   = balance_pi                         # (T,)

        N_bus = self.network.N_bus

        # ── 7. 计算节点边际电价（LMP）──────────────────────────────────────
        # 单节点：LMP = λ（全局统一价格）
        # 多节点 PTDF 直流潮流公式：
        #   LMP_{n,t} = λ_t + Σ_l PTDF[l,n] * (α_{l,t} − β_{l,t})
        # 其中：
        #   α_{l,t} = Pi of (PTDF_Gen @ p ≤ rhs_pos) constraint ≤ 0 (Gurobi min convention)
        #   β_{l,t} = Pi of (-PTDF_Gen @ p ≤ -rhs_neg) constraint ≤ 0
        #   拥塞正向（线路达上限）：α < 0 → 发电侧节点 LMP 降低，负荷侧 LMP 升高
        if self.network.is_single_node or ineq_constrs is None:
            lmp_matrix = np.tile(lambda_t, (1, 1))      # (1, T)
        else:
            # 多节点 PTDF 直流潮流 LMP 后处理计算：
            # PTDF 不等式约束排列：物理/PWL 约束在前，PTDF 约束在后
            # PTDF 约束排列：l=0→T-1 upper; l=0→T-1 lower; l=1→T-1 upper; ...
            all_pi_ub = np.array(ineq_constrs.Pi)       # (n_ineq,)
            N_line    = self.network.N_line
            n_ptdf_rows = 2 * N_line * self.T
            n_unit_ineq = len(all_pi_ub) - n_ptdf_rows
            ptdf_pi   = all_pi_ub[n_unit_ineq:]         # (2*N_line*T,)

            # alpha[l,t] = Pi of (PTDF_Gen@p ≤ rhs_pos) at line l, time t (≤0 for min LP)
            # beta_[l,t] = Pi of (-PTDF_Gen@p ≤ -rhs_neg) at line l, time t (≤0 for min LP)
            # 排列：连续2行 per (l,t)：[upper, lower, upper, lower, ...]
            alpha = ptdf_pi[0::2].reshape(N_line, self.T)   # rows 0,2,4,...
            beta_ = ptdf_pi[1::2].reshape(N_line, self.T)   # rows 1,3,5,...

            PTDF = self.network.PTDF                    # (N_line, N_bus)
            # LMP[n,t] = λ[t] + Σ_l PTDF[l,n] * (α[l,t] − β[l,t])
            # (alpha ≤ 0, beta ≤ 0; their difference gives the congestion component)
            lmp_matrix = (
                lambda_t[np.newaxis, :]                 # (1, T) broadcast
                + PTDF.T @ (alpha - beta_)              # (N_bus, T)
            )

        self._balance_constrs = eq_constrs
        # 保存 PTDF 对偶变量，供外部计算 FTR 成本（多节点 Eq.34 第二行）
        # alpha ≤ 0：上限约束 Pi；beta_code ≤ 0：下限约束 Pi（Gurobi min LP 惯例）
        # 对应论文符号：γ_paper = -alpha ≥ 0，β_paper = -beta_code ≥ 0
        if not self.network.is_single_node and ineq_constrs is not None:
            self._ptdf_alpha  = alpha   # (N_line, T), ≤ 0
            self._ptdf_beta_  = beta_   # (N_line, T), ≤ 0
        else:
            self._ptdf_alpha  = None
            self._ptdf_beta_  = None
        return lmp_matrix, obj_val, True

    def lp_dispatch(self) -> np.ndarray:
        """
        Return the convexified LP dispatch reconstructed from the solved
        differential variables.  This is a reporting helper for paper figures;
        it is not used by the pricing LP itself.
        """
        if self._solution_x is None:
            raise RuntimeError("Call solve() before lp_dispatch().")

        idx = self._idx
        p_lp = np.zeros((self.N, self.T), dtype=float)
        for i, dag in enumerate(self.dags):
            for k, iv in enumerate(dag.on_intervals):
                for tau in range(iv.a, iv.b + 1):
                    local_end = tau - iv.a
                    if iv.initial_online:
                        p_lp[i, tau] += self._solution_x[idx.z_on(i, k)] * dag.params.initial_power
                    p_lp[i, tau] += sum(
                        self._solution_x[idx.v(i, k, local_j)]
                        for local_j in range(local_end + 1)
                    )
        return p_lp

    # ── 内部：等式约束构建 ─────────────────────────────────────────────────

    def _build_eq_constraints(
        self, idx: _VarIndex
    ) -> Tuple[sp.csr_matrix, np.ndarray, int, int, int]:
        rows, cols, data = [], [], []
        b_eq_list: List[float] = []
        row = 0

        # (A) 节点流量守恒（内部节点 t=1,...,T-1）
        for i, dag in enumerate(self.dags):
            for t in range(1, dag.T):
                for k, iv in enumerate(dag.on_intervals):
                    if iv.node_to == t:
                        rows.append(row); cols.append(idx.z_on(i, k)); data.append(1.0)
                for k, arc in enumerate(dag.off_arcs):
                    if arc.t_to == t:
                        rows.append(row); cols.append(idx.z_off(i, k)); data.append(1.0)
                for k, iv in enumerate(dag.on_intervals):
                    if iv.node_from == t:
                        rows.append(row); cols.append(idx.z_on(i, k)); data.append(-1.0)
                for k, arc in enumerate(dag.off_arcs):
                    if arc.t_from == t:
                        rows.append(row); cols.append(idx.z_off(i, k)); data.append(-1.0)
                b_eq_list.append(0.0); row += 1

        n_flow = row

        # (B) 源节点约束：Σ z_离开0 = 1
        for i, dag in enumerate(self.dags):
            for k, iv in enumerate(dag.on_intervals):
                if iv.node_from == 0:
                    rows.append(row); cols.append(idx.z_on(i, k)); data.append(1.0)
            for k, arc in enumerate(dag.off_arcs):
                if arc.t_from == 0:
                    rows.append(row); cols.append(idx.z_off(i, k)); data.append(1.0)
            b_eq_list.append(1.0); row += 1

        n_src = row - n_flow

        # (C) 全局功率平衡（单节点 & 多节点均使用总需求，T 行等式）
        # 对偶 λ_t = 能量价格，是所有节点 LMP 的公共基准。
        # 多节点 LMP 通过 λ_t + 线路拥塞修正项（后处理）计算，而非通过节点等式对偶。
        for tau in range(self.T):
            for i, dag in enumerate(self.dags):
                for k, iv in enumerate(dag.on_intervals):
                    if iv.a <= tau <= iv.b:
                        local_end = tau - iv.a
                        if iv.initial_online:
                            rows.append(row)
                            cols.append(idx.z_on(i, k))
                            data.append(dag.params.initial_power)
                        for local_k in range(local_end + 1):
                            rows.append(row)
                            cols.append(idx.v(i, k, local_k))
                            data.append(1.0)
            b_eq_list.append(float(self.network.sys_demand[tau]))
            row += 1

        n_bal  = self.T
        n_rows = row
        n_cols = idx.n_total

        A_eq_csr = sp.coo_matrix(
            (data, (rows, cols)), shape=(n_rows, n_cols)
        ).tocsr()
        return A_eq_csr, np.array(b_eq_list, dtype=float), n_flow, n_src, n_bal

    # ── 内部：不等式约束构建 ──────────────────────────────────────────────

    def _build_ineq_constraints(
        self, idx: _VarIndex
    ) -> Tuple[sp.csr_matrix, np.ndarray]:
        """
        构建物理透视约束（4 类）+ 分段线性上镜图约束（PWL 模式）。
        所有约束统一为 Ax ≤ b。
        """
        rows, cols, data = [], [], []
        b_ub_list: List[float] = []
        row = 0

        for i, (dag, params) in enumerate(zip(self.dags, self.generators)):
            for k, iv in enumerate(dag.on_intervals):
                z_col = idx.z_on(i, k)
                n     = iv.duration

                # ── (1) 启动约束 τ=0 ─────────────────────────────────────────
                v0_col = idx.v(i, k, 0)
                if iv.initial_online:
                    rows.append(row); cols.append(v0_col); data.append(1.0)
                    rows.append(row); cols.append(z_col);  data.append(-params.R_up)
                    b_ub_list.append(0.0); row += 1

                    rows.append(row); cols.append(v0_col); data.append(-1.0)
                    rows.append(row); cols.append(z_col);  data.append(-params.R_down)
                    b_ub_list.append(0.0); row += 1
                else:
                    rows.append(row); cols.append(v0_col); data.append(1.0)
                    rows.append(row); cols.append(z_col);  data.append(-params.SU_ramp)
                    b_ub_list.append(0.0); row += 1

                    rows.append(row); cols.append(v0_col); data.append(-1.0)
                    rows.append(row); cols.append(z_col);  data.append(params.P_min)
                    b_ub_list.append(0.0); row += 1

                # ── (2) 管内爬坡约束 τ=1..n-1 ───────────────────────────────
                # 对照 main(4).tex Eq.(persp-ramp): -z_e·R_down ≤ v_τ ≤ z_e·R_up
                for tau in range(1, n):
                    vt_col = idx.v(i, k, tau)
                    # 上界：v_τ ≤ z_e·R_up → v_τ - R_up·z_e ≤ 0
                    rows.append(row); cols.append(vt_col); data.append(1.0)
                    rows.append(row); cols.append(z_col);  data.append(-params.R_up)
                    b_ub_list.append(0.0); row += 1

                    # 下界：v_τ ≥ -z_e·R_down → -v_τ - R_down·z_e ≤ 0
                    rows.append(row); cols.append(vt_col); data.append(-1.0)
                    rows.append(row); cols.append(z_col);  data.append(-params.R_down)
                    b_ub_list.append(0.0); row += 1

                # ── (3) 容量前缀和约束 τ=0..n-1 ─────────────────────────────
                for tau in range(n):
                    p0 = params.initial_power if iv.initial_online else 0.0
                    for local_k in range(tau + 1):
                        rows.append(row); cols.append(idx.v(i, k, local_k)); data.append(1.0)
                    rows.append(row); cols.append(z_col); data.append(p0 - params.P_max)
                    b_ub_list.append(0.0); row += 1

                    for local_k in range(tau + 1):
                        rows.append(row); cols.append(idx.v(i, k, local_k)); data.append(-1.0)
                    rows.append(row); cols.append(z_col); data.append(params.P_min - p0)
                    b_ub_list.append(0.0); row += 1

                # ── (4) 停机脱网约束 ─────────────────────────────────────────
                # 仅当 ON 区间后确实发生停机事件时施加。若区间延伸到调度
                # 末端 (b = T-1)，DAG/固定成本口径均表示没有期末停机事件，
                # 因而不应强迫最后一个在线时段满足 shutdown-ramp 上界。
                if iv.b < params.T - 1:
                    p0 = params.initial_power if iv.initial_online else 0.0
                    for local_k in range(n):
                        rows.append(row); cols.append(idx.v(i, k, local_k)); data.append(1.0)
                    rows.append(row); cols.append(z_col); data.append(p0 - params.SD_ramp)
                    b_ub_list.append(0.0); row += 1

                # ── (B) 分段线性上镜图约束（仅 PWL 模式且本机组分段）────────
                # cvar 代表超出 P_min 的变动成本。由于 Σv = 总出力 p（含 P_min），
                # 需扣减 P_min 基底：
                #   c_var ≥ s_k · (Σv - z·P_min) + b_k · z
                #        = s_k · Σv + (b_k - s_k·P_min) · z
                if self._use_pwl and not params.is_single_segment:
                    slopes     = params.pwl_slopes
                    intercepts = params.pwl_intercepts()
                    Pmin       = params.P_min
                    p0         = params.initial_power if iv.initial_online else 0.0
                    for tau in range(n):
                        cv_col = idx.cvar(i, k, tau)
                        for seg_k, (s_k, b_k) in enumerate(
                                zip(slopes, intercepts)):
                            rows.append(row); cols.append(cv_col); data.append(-1.0)
                            for local_j in range(tau + 1):
                                rows.append(row)
                                cols.append(idx.v(i, k, local_j))
                                data.append(s_k)
                            rows.append(row); cols.append(z_col)
                            data.append(b_k + s_k * (p0 - Pmin))
                            b_ub_list.append(0.0); row += 1

                elif self._use_pwl and params.is_single_segment:
                    # 单段退化：c_var ≥ cost_var · (Σv - z·P_min)
                    Pmin = params.P_min
                    p0 = params.initial_power if iv.initial_online else 0.0
                    for tau in range(n):
                        cv_col = idx.cvar(i, k, tau)
                        rows.append(row); cols.append(cv_col); data.append(-1.0)
                        for local_j in range(tau + 1):
                            rows.append(row)
                            cols.append(idx.v(i, k, local_j))
                            data.append(params.cost_var)
                        rows.append(row); cols.append(z_col)
                        data.append(params.cost_var * (p0 - Pmin))
                        b_ub_list.append(0.0); row += 1

        # ── (C) PTDF 线路容量约束（多节点模式）────────────────────────────
        # 直流潮流：f_{l,τ} = Σ_i PTDF_Gen[l,i] · p_{i,τ} − Σ_n PTDF[l,n] · D_{n,τ}
        # 容量约束：−F_max[l] ≤ f_{l,τ} ≤ F_max[l]
        # 展开为变量的线性约束（消去 f 变量）：
        #   上界：Σ_i PTDF_Gen[l,i] · p_{i,τ} ≤ F_max[l] + Σ_n PTDF[l,n]·D_{n,τ}  = rhs_pos[l,τ]
        #   下界：Σ_i PTDF_Gen[l,i] · p_{i,τ} ≥ −F_max[l] + Σ_n PTDF[l,n]·D_{n,τ} = rhs_neg[l,τ]
        # 其中 p_{i,τ} = Σ_{e∋τ} Σ_{k=0}^{τ-a} v_{e,k}（在 LP 变量中表达）
        if not self.network.is_single_node:
            PTDF_Gen       = self.network.PTDF_Gen   # (N_line, N_gen)
            rhs_pos, rhs_neg = self.network.line_rhs()   # each (N_line, T)
            N_line         = self.network.N_line

            for l in range(N_line):
                ptdf_row = PTDF_Gen[l]                   # (N_gen,) float
                for tau in range(self.T):
                    rhs_p = float(rhs_pos[l, tau])
                    rhs_n = float(rhs_neg[l, tau])

                    # Upper bound: Σ coeff * v ≤ rhs_pos
                    for i, dag in enumerate(self.dags):
                        coeff = float(ptdf_row[i])
                        if abs(coeff) < 1e-10:
                            continue
                        for k, iv in enumerate(dag.on_intervals):
                            if iv.a <= tau <= iv.b:
                                local_end = tau - iv.a
                                if iv.initial_online:
                                    rows.append(row)
                                    cols.append(idx.z_on(i, k))
                                    data.append(coeff * dag.params.initial_power)
                                for local_k in range(local_end + 1):
                                    rows.append(row)
                                    cols.append(idx.v(i, k, local_k))
                                    data.append(coeff)
                    b_ub_list.append(rhs_p); row += 1

                    # Lower bound (negated): -Σ coeff * v ≤ -rhs_neg
                    for i, dag in enumerate(self.dags):
                        coeff = float(ptdf_row[i])
                        if abs(coeff) < 1e-10:
                            continue
                        for k, iv in enumerate(dag.on_intervals):
                            if iv.a <= tau <= iv.b:
                                local_end = tau - iv.a
                                if iv.initial_online:
                                    rows.append(row)
                                    cols.append(idx.z_on(i, k))
                                    data.append(-coeff * dag.params.initial_power)
                                for local_k in range(local_end + 1):
                                    rows.append(row)
                                    cols.append(idx.v(i, k, local_k))
                                    data.append(-coeff)
                    b_ub_list.append(-rhs_n); row += 1

        if row == 0:
            return sp.csr_matrix((0, idx.n_total)), np.array([], dtype=float)

        A_ub_csr = sp.coo_matrix(
            (data, (rows, cols)), shape=(row, idx.n_total)
        ).tocsr()
        return A_ub_csr, np.array(b_ub_list, dtype=float)

    # ── 内部：对偶清理 ────────────────────────────────────────────────────

    @staticmethod
    def _clean_duals(pi: np.ndarray, clip_nonneg: bool = True) -> np.ndarray:
        """
        清理内点法数值噪声。

        Parameters
        ----------
        pi           : 原始对偶向量
        clip_nonneg  : True → 截断至 ≥ 0（单节点全局价格）
                       False → 保留负值（多节点 LMP 可合法为负）
        """
        if np.all(pi <= 1e-8) and np.any(pi < -1e-6):
            pi = -pi
        pi = np.where(np.abs(pi) < 1e-8, 0.0, pi)
        if clip_nonneg:
            pi = np.clip(pi, 0.0, None)
        return pi
