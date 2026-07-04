"""
Dantzig-Wolfe / Column Generation benchmark for convex hull pricing.

This module implements the M-DWP baseline used in recent CHP papers:
the restricted master problem (RMP) contains one convex-combination
constraint per generator and system balance/network constraints.  Each
column is a feasible single-generator trajectory.  Given the RMP dual
prices, the pricing subproblem for each generator is solved by a standard
single-unit self-scheduling MILP, which is the same LOC response model used
in CHP benchmark papers.  It is deliberately independent from the proposed
GP-DAG oracle.

The RMP is kept alive across column-generation iterations and new generator
trajectory columns are injected with Gurobi's ``Column`` interface.  Unit
pricing subproblems can be solved in parallel.  This keeps the implementation
faithful to the Dantzig-Wolfe benchmark while avoiding repeated RMP rebuilds.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
import sys
import time
from typing import List, Optional, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from models.network import NetworkModel, SingleNodeNetwork
from benchmarks.unit_self_schedule import UnitSelfScheduleMILP, dispatch_cost


@dataclass
class DWColumn:
    """One feasible trajectory column for one generator."""

    p: np.ndarray
    u: np.ndarray
    cost: float
    name: str


def _trajectory_cost(params: GeneratorParams, p: np.ndarray, u: np.ndarray) -> float:
    """Cost accounting aligned with ScheduleRunMILP."""
    return dispatch_cost(params, p, u)


def _column_key(p: np.ndarray, u: np.ndarray, ndigits: int = 6) -> Tuple[Tuple[float, ...], Tuple[int, ...]]:
    """Numerical duplicate key for columns."""
    return (
        tuple(np.round(np.asarray(p, dtype=float), ndigits)),
        tuple(int(round(x)) for x in np.asarray(u, dtype=float)),
    )


class DantzigWolfePricing:
    """
    M-DWP benchmark: exact convex-hull pricing by column generation.

    Literature mapping
    ------------------
    This is the M-DWP family used in Andrianesis et al., "Computation of
    Convex Hull Prices in Electricity Markets With Non-Convexities Using
    Dantzig-Wolfe Decomposition", IEEE TPWRS, and used as a benchmark in
    Xiao et al.  The multi-node adaptation keeps the same RMP/column
    generation structure and adds PTDF line-capacity rows to the RMP.

    Parameters
    ----------
    generators
        Generator parameter list.
    network
        Single-node or PTDF network model.
    p_dispatch, u_dispatch
        Feasible schedule-run columns used to initialize the RMP.
    max_iter
        Maximum column-generation iterations.
    tol
        Reduced-cost tolerance.  The RMP is considered converged when no
        generator has a column with reduced cost below ``-tol``.
    """

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
        p_dispatch: np.ndarray,
        u_dispatch: np.ndarray,
        max_iter: int = 200,
        tol: float = 1e-6,
        verbose: bool = False,
        incremental_rmp: bool = True,
        parallel_pricing: bool = True,
        max_workers: Optional[int] = None,
        pricing_threads: int = 1,
    ) -> None:
        self.generators = generators
        if isinstance(network, np.ndarray):
            network = SingleNodeNetwork(network)
        self.network = network
        self.p_dispatch = np.asarray(p_dispatch, dtype=float)
        self.u_dispatch = np.asarray(u_dispatch, dtype=float)
        self.max_iter = max_iter
        self.tol = tol
        self.verbose = verbose
        self.incremental_rmp = incremental_rmp
        self.parallel_pricing = parallel_pricing
        self.max_workers = max_workers
        self.pricing_threads = pricing_threads
        self.T = network.T
        self.N = len(generators)

        self._ptdf_alpha: Optional[np.ndarray] = None
        self._ptdf_beta_: Optional[np.ndarray] = None
        self.history: List[dict] = []
        self.n_columns = 0
        self.n_iter = 0
        self.converged = False
        self.stalled = False
        self.stop_reason = "not_started"
        self.final_columns: Optional[List[List[DWColumn]]] = None
        self.final_theta: Optional[dict] = None
        self.build_time = float("nan")
        self.solver_time = float("nan")
        self.total_time = float("nan")
        self.pricing_oracle_time = float("nan")

    def solve(self) -> Tuple[np.ndarray, float, bool]:
        try:
            import gurobipy as gp  # noqa: F401
        except ImportError as e:
            raise ImportError("需要 gurobipy 才能运行 DantzigWolfePricing。") from e
        self._timing = {
            "pricing_build": 0.0,
            "pricing_solver": 0.0,
            "pricing_total": 0.0,
            "rmp_solver": 0.0,
        }
        if not self.incremental_rmp:
            return self._solve_with_rebuilt_rmp()

        total_start = time.time()
        columns = self._initial_columns()
        column_keys = [{_column_key(c.p, c.u) for c in cols} for cols in columns]
        rmp_state = self._build_incremental_rmp(columns)

        t_start = time.time()
        cumulative_rmp_s = 0.0
        cumulative_pricing_s = 0.0
        best_certified_dual = -float("inf")
        for it in range(1, self.max_iter + 1):
            t_rmp = time.time()
            rmp = self._optimize_incremental_rmp(rmp_state)
            cumulative_rmp_s += time.time() - t_rmp

            added = 0
            min_reduced_cost = 0.0
            negative_reduced_cost_sum = 0.0
            t_pricing = time.time()
            for i, u_new, p_new, max_profit in self._solve_pricing_subproblems(rmp["lmp_matrix"]):
                # RMP column reduced cost is
                #   c_i(y) - lambda^T p_i(y) - sigma_i
                # where sigma_i is the dual of sum_y theta_{i,y}=1.  The
                # oracle returns max_y {lambda^T p_i(y)-c_i(y)}, so the most
                # negative reduced cost equals -max_profit - sigma_i.
                reduced_cost = -float(max_profit) - float(rmp["sigma"][i])
                min_reduced_cost = min(min_reduced_cost, reduced_cost)
                negative_reduced_cost_sum += min(0.0, reduced_cost)

                if reduced_cost < -self.tol:
                    key = _column_key(p_new, u_new)
                    if key not in column_keys[i]:
                        new_col = DWColumn(
                            p=np.asarray(p_new, dtype=float),
                            u=np.asarray(u_new, dtype=float),
                            cost=_trajectory_cost(self.generators[i], p_new, u_new),
                            name=f"cg_{it}_{i}",
                        )
                        columns[i].append(new_col)
                        column_keys[i].add(key)
                        self._add_incremental_column(rmp_state, i, len(columns[i]) - 1, new_col)
                        added += 1
            cumulative_pricing_s += time.time() - t_pricing

            certified_lower_bound = rmp["obj"] + negative_reduced_cost_sum
            best_certified_dual = max(best_certified_dual, certified_lower_bound)

            self.history.append(
                {
                    "iter": it,
                    "rmp_obj": rmp["obj"],
                    "dual_bound": certified_lower_bound,
                    "certified_lower_bound": certified_lower_bound,
                    "best_certified_dual": best_certified_dual,
                    "rmp_gap_bound": -negative_reduced_cost_sum,
                    "columns": sum(len(cols) for cols in columns),
                    "min_reduced_cost": min_reduced_cost,
                    "added": added,
                    "rmp_runtime_s": rmp.get("runtime_s", float("nan")),
                    "cumulative_rmp_s": cumulative_rmp_s,
                    "cumulative_pricing_s": cumulative_pricing_s,
                    "cumulative_solve_s": cumulative_rmp_s + cumulative_pricing_s,
                    "elapsed_s": time.time() - t_start,
                }
            )
            if self.verbose:
                print(
                    f"  [DWP] iter={it:03d} obj={rmp['obj']:.4f} "
                    f"min_rc={min_reduced_cost:.3e} added={added}"
                )

            if min_reduced_cost >= -self.tol:
                self.n_iter = it
                self.converged = True
                self.stop_reason = "reduced_cost"
                break
            if added == 0:
                self.n_iter = it
                self.stalled = True
                self.stop_reason = "duplicate_or_stalled"
                break
        else:
            self.n_iter = self.max_iter
            self.stop_reason = "max_iter"

        final = self._optimize_incremental_rmp(rmp_state)
        self.n_columns = sum(len(cols) for cols in columns)
        self.final_columns = columns
        self.final_theta = final.get("theta_values")
        self._ptdf_alpha = final["alpha"]
        self._ptdf_beta_ = final["beta"]
        self.total_time = max(0.0, time.time() - total_start)
        self.pricing_oracle_time = float(self._timing["pricing_total"])
        self.solver_time = float(
            self._timing["rmp_solver"] + self._timing["pricing_solver"]
        )
        self.build_time = max(0.0, self.total_time - self.solver_time)
        return final["lmp_matrix"], float(final["obj"]), True

    def _solve_with_rebuilt_rmp(self) -> Tuple[np.ndarray, float, bool]:
        total_start = time.time()
        columns = self._initial_columns()
        t_start = time.time()
        cumulative_rmp_s = 0.0
        cumulative_pricing_s = 0.0
        best_certified_dual = -float("inf")
        for it in range(1, self.max_iter + 1):
            t_rmp = time.time()
            rmp = self._solve_rmp(columns)
            cumulative_rmp_s += time.time() - t_rmp

            added = 0
            min_reduced_cost = 0.0
            negative_reduced_cost_sum = 0.0
            t_pricing = time.time()
            for i, u_new, p_new, max_profit in self._solve_pricing_subproblems(rmp["lmp_matrix"]):
                reduced_cost = -float(max_profit) - float(rmp["sigma"][i])
                min_reduced_cost = min(min_reduced_cost, reduced_cost)
                negative_reduced_cost_sum += min(0.0, reduced_cost)

                if reduced_cost < -self.tol:
                    key = _column_key(p_new, u_new)
                    existing = {_column_key(c.p, c.u) for c in columns[i]}
                    if key not in existing:
                        columns[i].append(
                            DWColumn(
                                p=np.asarray(p_new, dtype=float),
                                u=np.asarray(u_new, dtype=float),
                                cost=_trajectory_cost(self.generators[i], p_new, u_new),
                                name=f"cg_{it}_{i}",
                            )
                        )
                        added += 1
            cumulative_pricing_s += time.time() - t_pricing

            certified_lower_bound = rmp["obj"] + negative_reduced_cost_sum
            best_certified_dual = max(best_certified_dual, certified_lower_bound)
            self.history.append(
                {
                    "iter": it,
                    "rmp_obj": rmp["obj"],
                    "dual_bound": certified_lower_bound,
                    "certified_lower_bound": certified_lower_bound,
                    "best_certified_dual": best_certified_dual,
                    "rmp_gap_bound": -negative_reduced_cost_sum,
                    "columns": sum(len(cols) for cols in columns),
                    "min_reduced_cost": min_reduced_cost,
                    "added": added,
                    "rmp_runtime_s": rmp.get("runtime_s", float("nan")),
                    "cumulative_rmp_s": cumulative_rmp_s,
                    "cumulative_pricing_s": cumulative_pricing_s,
                    "cumulative_solve_s": cumulative_rmp_s + cumulative_pricing_s,
                    "elapsed_s": time.time() - t_start,
                }
            )
            if min_reduced_cost >= -self.tol:
                self.n_iter = it
                self.converged = True
                self.stop_reason = "reduced_cost"
                break
            if added == 0:
                self.n_iter = it
                self.stalled = True
                self.stop_reason = "duplicate_or_stalled"
                break
        else:
            self.n_iter = self.max_iter
            self.stop_reason = "max_iter"

        final = self._solve_rmp(columns)
        self.n_columns = sum(len(cols) for cols in columns)
        self.final_columns = columns
        self.final_theta = final.get("theta_values")
        self._ptdf_alpha = final["alpha"]
        self._ptdf_beta_ = final["beta"]
        self.total_time = max(0.0, time.time() - total_start)
        self.pricing_oracle_time = float(self._timing["pricing_total"])
        self.solver_time = float(
            self._timing["rmp_solver"] + self._timing["pricing_solver"]
        )
        self.build_time = max(0.0, self.total_time - self.solver_time)
        return final["lmp_matrix"], float(final["obj"]), True

    def _solve_pricing_subproblems(self, lmp_matrix: np.ndarray) -> List[Tuple[int, np.ndarray, np.ndarray, float]]:
        tasks = []
        for i, g in enumerate(self.generators):
            lambda_i = np.asarray(lmp_matrix[self.network.gen_bus_idx(i)], dtype=float)
            tasks.append((i, g, lambda_i))

        def solve_one(task: Tuple[int, GeneratorParams, np.ndarray]) -> Tuple[int, np.ndarray, np.ndarray, float, dict]:
            i, g, lambda_i = task
            u_new, p_new, max_profit, timing = UnitSelfScheduleMILP.solve(
                g, lambda_i, threads=self.pricing_threads, return_timing=True
            )
            return i, u_new, p_new, float(max_profit), timing

        if not self.parallel_pricing or self.N <= 1:
            results = [solve_one(task) for task in tasks]
        else:
            workers = self.max_workers or min(self.N, os.cpu_count() or self.N)
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                results = list(pool.map(solve_one, tasks))

        if hasattr(self, "_timing"):
            self._timing["pricing_build"] += sum(float(r[4]["build_time"]) for r in results)
            self._timing["pricing_solver"] += sum(float(r[4]["solver_time"]) for r in results)
            self._timing["pricing_total"] += sum(float(r[4]["total_time"]) for r in results)
        return [(i, u_new, p_new, max_profit) for i, u_new, p_new, max_profit, _ in results]

    def _initial_columns(self) -> List[List[DWColumn]]:
        columns: List[List[DWColumn]] = []
        for i, g in enumerate(self.generators):
            p_sch = self.p_dispatch[i].copy()
            u_sch = self.u_dispatch[i].copy()
            cols = [
                DWColumn(
                    p=p_sch,
                    u=u_sch,
                    cost=_trajectory_cost(g, p_sch, u_sch),
                    name="schedule",
                )
            ]
            zero_p = np.zeros(self.T)
            zero_u = np.zeros(self.T)
            zero_feasible = (
                g.initial_status == 0
                or (
                    int(g.initial_up_time) >= g.T_on_min
                    and float(g.initial_power) <= g.SD_ramp + 1e-8
                )
            )
            if zero_feasible and _column_key(zero_p, zero_u) != _column_key(p_sch, u_sch):
                cols.append(
                    DWColumn(
                        p=zero_p,
                        u=zero_u,
                        cost=_trajectory_cost(g, zero_p, zero_u),
                        name="off",
                    )
                )
            columns.append(cols)
        return columns

    def _build_incremental_rmp(self, columns: List[List[DWColumn]]) -> dict:
        import gurobipy as gp
        from gurobipy import GRB

        model = gp.Model("DantzigWolfeRMP")
        model.Params.OutputFlag = 0
        # Column generation needs economically meaningful simplex duals for
        # reduced-cost pricing.  The model is persistent, so simplex warm starts
        # are reused across column additions.
        model.Params.Method = 1
        model.ModelSense = GRB.MINIMIZE

        theta = {}
        for i, cols in enumerate(columns):
            for j, col in enumerate(cols):
                theta[i, j] = model.addVar(
                    lb=0.0, obj=float(col.cost), name=f"theta_{i}_{j}"
                )

        convexity = {}
        for i in range(self.N):
            convexity[i] = model.addConstr(
                gp.quicksum(theta[i, j] for j in range(len(columns[i]))) == 1.0,
                name=f"convexity_{i}",
            )

        balance = {}
        for t in range(self.T):
            balance[t] = model.addConstr(
                gp.quicksum(
                    columns[i][j].p[t] * theta[i, j]
                    for i in range(self.N)
                    for j in range(len(columns[i]))
                )
                == float(self.network.sys_demand[t]),
                name=f"balance_{t}",
            )

        ptdf_ub = {}
        ptdf_lb = {}
        if not self.network.is_single_node:
            PTDF_Gen = self.network.PTDF_Gen
            rhs_pos, rhs_neg = self.network.line_rhs()
            for l in range(self.network.N_line):
                for t in range(self.T):
                    lhs = gp.quicksum(
                        float(PTDF_Gen[l, i]) * columns[i][j].p[t] * theta[i, j]
                        for i in range(self.N)
                        for j in range(len(columns[i]))
                    )
                    ptdf_ub[l, t] = model.addConstr(
                        lhs <= float(rhs_pos[l, t]), name=f"ptdf_ub_{l}_{t}"
                    )
                    ptdf_lb[l, t] = model.addConstr(
                        -lhs <= -float(rhs_neg[l, t]), name=f"ptdf_lb_{l}_{t}"
                    )

        model.update()
        return {
            "model": model,
            "theta": theta,
            "convexity": convexity,
            "balance": balance,
            "ptdf_ub": ptdf_ub,
            "ptdf_lb": ptdf_lb,
        }

    def _add_incremental_column(self, state: dict, i: int, j: int, column: DWColumn) -> None:
        import gurobipy as gp

        model = state["model"]
        col = gp.Column()
        col.addTerms(1.0, state["convexity"][i])
        for t in range(self.T):
            coeff = float(column.p[t])
            if abs(coeff) > 1e-12:
                col.addTerms(coeff, state["balance"][t])

        if not self.network.is_single_node:
            PTDF_Gen = self.network.PTDF_Gen
            for l in range(self.network.N_line):
                base_coeff = float(PTDF_Gen[l, i])
                if abs(base_coeff) <= 1e-12:
                    continue
                for t in range(self.T):
                    coeff = base_coeff * float(column.p[t])
                    if abs(coeff) > 1e-12:
                        col.addTerms(coeff, state["ptdf_ub"][l, t])
                        col.addTerms(-coeff, state["ptdf_lb"][l, t])

        state["theta"][i, j] = model.addVar(
            lb=0.0,
            obj=float(column.cost),
            column=col,
            name=f"theta_{i}_{j}",
        )
        model.update()

    def _optimize_incremental_rmp(self, state: dict) -> dict:
        from gurobipy import GRB

        model = state["model"]
        model.optimize()
        if hasattr(self, "_timing"):
            self._timing["rmp_solver"] += float(getattr(model, "Runtime", 0.0))
        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(f"Dantzig-Wolfe RMP 求解失败，Gurobi Status={model.Status}")

        balance = state["balance"]
        convexity = state["convexity"]
        ptdf_ub = state["ptdf_ub"]
        ptdf_lb = state["ptdf_lb"]

        lambda_t = np.array([balance[t].Pi for t in range(self.T)], dtype=float)
        lambda_t = np.where(np.abs(lambda_t) < 1e-9, 0.0, lambda_t)
        sigma = np.array([convexity[i].Pi for i in range(self.N)], dtype=float)

        alpha = None
        beta = None
        if self.network.is_single_node:
            lmp_matrix = np.tile(lambda_t, (1, 1))
        else:
            alpha = np.array(
                [[ptdf_ub[l, t].Pi for t in range(self.T)] for l in range(self.network.N_line)],
                dtype=float,
            )
            beta = np.array(
                [[ptdf_lb[l, t].Pi for t in range(self.T)] for l in range(self.network.N_line)],
                dtype=float,
            )
            lmp_matrix = lambda_t[np.newaxis, :] + self.network.PTDF.T @ (alpha - beta)

        return {
            "obj": float(model.ObjVal),
            "runtime_s": float(getattr(model, "Runtime", float("nan"))),
            "lambda": lambda_t,
            "sigma": sigma,
            "alpha": alpha,
            "beta": beta,
            "lmp_matrix": lmp_matrix,
            "theta_values": {
                key: float(var.X)
                for key, var in state["theta"].items()
            },
        }

    def _solve_rmp(self, columns: List[List[DWColumn]]) -> dict:
        import gurobipy as gp
        from gurobipy import GRB

        model = gp.Model("DantzigWolfeRMP")
        model.Params.OutputFlag = 0
        # Column generation needs economically meaningful simplex duals for
        # reduced-cost pricing.  Barrier analytic-center duals can be highly
        # degenerate in the RMP and may stall the multi-node CG loop.
        model.Params.Method = 1

        theta = {}
        for i, cols in enumerate(columns):
            for j, _ in enumerate(cols):
                theta[i, j] = model.addVar(lb=0.0, name=f"theta_{i}_{j}")

        model.setObjective(
            gp.quicksum(
                columns[i][j].cost * theta[i, j]
                for i in range(self.N)
                for j in range(len(columns[i]))
            ),
            GRB.MINIMIZE,
        )

        convexity = {}
        for i in range(self.N):
            convexity[i] = model.addConstr(
                gp.quicksum(theta[i, j] for j in range(len(columns[i]))) == 1.0,
                name=f"convexity_{i}",
            )

        balance = {}
        for t in range(self.T):
            balance[t] = model.addConstr(
                gp.quicksum(
                    columns[i][j].p[t] * theta[i, j]
                    for i in range(self.N)
                    for j in range(len(columns[i]))
                )
                == float(self.network.sys_demand[t]),
                name=f"balance_{t}",
            )

        ptdf_ub = {}
        ptdf_lb = {}
        if not self.network.is_single_node:
            PTDF_Gen = self.network.PTDF_Gen
            rhs_pos, rhs_neg = self.network.line_rhs()
            for l in range(self.network.N_line):
                for t in range(self.T):
                    lhs = gp.quicksum(
                        float(PTDF_Gen[l, i]) * columns[i][j].p[t] * theta[i, j]
                        for i in range(self.N)
                        for j in range(len(columns[i]))
                    )
                    ptdf_ub[l, t] = model.addConstr(
                        lhs <= float(rhs_pos[l, t]), name=f"ptdf_ub_{l}_{t}"
                    )
                    ptdf_lb[l, t] = model.addConstr(
                        -lhs <= -float(rhs_neg[l, t]), name=f"ptdf_lb_{l}_{t}"
                    )

        model.optimize()
        if hasattr(self, "_timing"):
            self._timing["rmp_solver"] += float(getattr(model, "Runtime", 0.0))
        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(f"Dantzig-Wolfe RMP 求解失败，Gurobi Status={model.Status}")

        # Use raw RMP duals for column generation.  The Dantzig-Wolfe reduced
        # cost in Andrianesis et al. is c_i - lambda^T p_i - pi_i, and the
        # intermediate lambda values can legitimately be negative.
        lambda_t = np.array([balance[t].Pi for t in range(self.T)], dtype=float)
        lambda_t = np.where(np.abs(lambda_t) < 1e-9, 0.0, lambda_t)

        sigma = np.array([convexity[i].Pi for i in range(self.N)], dtype=float)

        alpha = None
        beta = None
        if self.network.is_single_node:
            lmp_matrix = np.tile(lambda_t, (1, 1))
        else:
            alpha = np.array(
                [[ptdf_ub[l, t].Pi for t in range(self.T)] for l in range(self.network.N_line)],
                dtype=float,
            )
            beta = np.array(
                [[ptdf_lb[l, t].Pi for t in range(self.T)] for l in range(self.network.N_line)],
                dtype=float,
            )
            lmp_matrix = lambda_t[np.newaxis, :] + self.network.PTDF.T @ (alpha - beta)

        return {
            "obj": float(model.ObjVal),
            "runtime_s": float(getattr(model, "Runtime", float("nan"))),
            "lambda": lambda_t,
            "sigma": sigma,
            "alpha": alpha,
            "beta": beta,
            "lmp_matrix": lmp_matrix,
            "theta_values": {
                (i, j): float(theta[i, j].X)
                for i in range(self.N)
                for j in range(len(columns[i]))
            },
        }
