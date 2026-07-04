"""
Level-method Lagrangian pricing benchmark.

This module implements the single-cut level method described by Stevens and
Papavasiliou for nonsmooth Lagrangian-dual CHP computation.  It uses the same
unit self-scheduling oracle and the same relaxed coupling constraints as
``lagrangian_relaxation.py``.  The implementation is intentionally kept out of
the paper-output pipeline until its benchmark behavior is audited.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams
from models.network import NetworkModel, SingleNodeNetwork
from benchmarks.lagrangian_relaxation import LagrangianRelaxation
from benchmarks.unit_self_schedule import UnitSelfScheduleMILP


@dataclass
class _Cut:
    point: np.ndarray
    value: float
    supergrad: np.ndarray

    @property
    def intercept(self) -> float:
        return float(self.value - np.dot(self.supergrad, self.point))


class LevelMethodPricing:
    """
    Single-cut level method for the Lagrangian dual of network-constrained UC.

    The dual variables are represented as
    ``y = [lambda, mu_ub, mu_lb]``.  ``lambda`` is free but bounded by a price
    box, while the line-capacity multipliers are nonnegative and bounded by the
    same cap.  At each iterate, a supergradient cut

        L(y) <= L(y_j) + g_j^T (y - y_j)

    is added to the cutting-plane model.  The next iterate is the Euclidean
    projection of the current iterate onto the level set of the model function.
    """

    def __init__(
        self,
        generators: List[GeneratorParams],
        network: "NetworkModel | np.ndarray",
        price_cap: float = 300.0,
        parallel_pricing: bool = True,
        max_workers: Optional[int] = None,
        pricing_threads: int = 1,
    ) -> None:
        self.generators = generators
        if isinstance(network, np.ndarray):
            network = SingleNodeNetwork(network)
        self.network = network
        self.T = network.T
        self.N = len(generators)
        self.price_cap = float(price_cap)
        self.parallel_pricing = parallel_pricing
        self.max_workers = max_workers
        self.pricing_threads = pricing_threads
        self._lr_oracle = LagrangianRelaxation(generators, network)

        self.history: list[dict] = []
        self.build_time = float("nan")
        self.solver_time = float("nan")
        self.total_time = float("nan")
        self.oracle_time = float("nan")

    def solve(
        self,
        max_iter: int = 100,
        tol: float = 1e-4,
        alpha_level: float = 0.2,
        shrink_iters: Tuple[int, ...] = (),
        shrink_radius: float = 25.0,
        verbose: bool = False,
    ) -> dict:
        try:
            import gurobipy as gp  # noqa: F401
        except ImportError as e:
            raise ImportError("需要 gurobipy 才能运行 LevelMethodPricing。") from e

        y = self._initial_point()
        lb = -float("inf")
        ub = float("inf")
        best_y = y.copy()
        best_dual = -float("inf")
        cuts: list[_Cut] = []
        t_start = time.time()
        self._timing = {
            "unit_build": 0.0,
            "unit_solver": 0.0,
            "unit_total": 0.0,
            "master_build": 0.0,
            "master_solver": 0.0,
            "master_total": 0.0,
            "projection_build": 0.0,
            "projection_solver": 0.0,
            "projection_total": 0.0,
        }
        converged = False
        stop_reason = "max_iter"

        lower, upper = self._bounds_around(None)

        for it in range(1, max_iter + 1):
            dual_val, grad, pieces = self._evaluate(y)
            cuts.append(_Cut(point=y.copy(), value=dual_val, supergrad=grad.copy()))

            if dual_val > best_dual:
                best_dual = dual_val
                best_y = y.copy()
            lb = max(lb, dual_val)

            ub_model, master_y = self._solve_master(cuts, lower, upper)
            ub = min(ub, ub_model)
            abs_gap = max(0.0, ub - lb)
            rel_gap = abs_gap / max(1.0, abs(ub))

            self.history.append(
                {
                    "iter": it,
                    "dual_bound": dual_val,
                    "best_dual": best_dual,
                    "upper_bound": ub,
                    "model_upper_bound": ub_model,
                    "abs_gap": abs_gap,
                    "rel_gap": rel_gap,
                    "grad_norm": float(np.linalg.norm(grad)),
                    "elapsed_s": time.time() - t_start,
                    "n_cuts": len(cuts),
                }
            )
            if verbose:
                print(
                    f"  [LEVEL] k={it:03d} dual={dual_val:.4f} "
                    f"LB={lb:.4f} UB={ub:.4f} gap={rel_gap:.3e}"
                )

            if rel_gap <= tol:
                converged = True
                stop_reason = "relative_gap"
                break

            if it in shrink_iters:
                lower, upper = self._bounds_around(master_y, radius=shrink_radius)

            level = alpha_level * ub + (1.0 - alpha_level) * lb
            y = self._solve_projection(y, cuts, level, lower, upper)

        lam, mu_ub, mu_lb = self._unpack(best_y)
        lmp_matrix = self._lmp_matrix(lam, mu_ub, mu_lb)
        self.total_time = max(0.0, time.time() - t_start)
        self.oracle_time = float(self._timing["unit_total"])
        self.solver_time = float(
            self._timing["unit_solver"]
            + self._timing["master_solver"]
            + self._timing["projection_solver"]
        )
        self.build_time = max(0.0, self.total_time - self.solver_time)
        return {
            "lmp_matrix": lmp_matrix,
            "dual_bound": best_dual,
            "upper_bound": ub,
            "n_iter": len(self.history),
            "history": self.history,
            "converged": converged,
            "stop_reason": stop_reason,
            "ptdf_mu_ub": mu_ub if not self.network.is_single_node else None,
            "ptdf_mu_lb": mu_lb if not self.network.is_single_node else None,
        }

    def _initial_point(self) -> np.ndarray:
        if self.network.is_single_node:
            return np.zeros(self.T)
        return np.zeros(self.T + 2 * self.network.N_line * self.T)

    def _bounds_around(
        self,
        center: Optional[np.ndarray],
        radius: Optional[float] = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        dim = len(self._initial_point())
        lower = np.full(dim, -self.price_cap)
        upper = np.full(dim, self.price_cap)
        if not self.network.is_single_node:
            mu_start = self.T
            lower[mu_start:] = 0.0
        if center is not None:
            box_radius = self.price_cap if radius is None else float(radius)
            lower = np.maximum(lower, center - box_radius)
            upper = np.minimum(upper, center + box_radius)
            if not self.network.is_single_node:
                lower[self.T :] = np.maximum(lower[self.T :], 0.0)
        return lower, upper

    def _unpack(self, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        lam = np.asarray(y[: self.T], dtype=float)
        if self.network.is_single_node:
            return lam, np.empty((0, self.T)), np.empty((0, self.T))
        n_lt = self.network.N_line * self.T
        a = self.T
        b = a + n_lt
        mu_ub = np.asarray(y[a:b], dtype=float).reshape(self.network.N_line, self.T)
        mu_lb = np.asarray(y[b : b + n_lt], dtype=float).reshape(self.network.N_line, self.T)
        return lam, mu_ub, mu_lb

    def _pack(self, lam: np.ndarray, mu_ub: np.ndarray, mu_lb: np.ndarray) -> np.ndarray:
        if self.network.is_single_node:
            return np.asarray(lam, dtype=float)
        return np.concatenate([lam.ravel(), mu_ub.ravel(), mu_lb.ravel()])

    def _evaluate(self, y: np.ndarray) -> tuple[float, np.ndarray, dict]:
        lam, mu_ub, mu_lb = self._unpack(y)
        T = self.T
        N = self.N
        demand = self.network.sys_demand

        if self.network.is_single_node:
            lambda_eff = np.tile(lam, (N, 1))
            rhs_pos = rhs_neg = np.empty((0, T))
            PTDF_Gen = np.empty((0, N))
        else:
            PTDF_Gen = self.network.PTDF_Gen
            rhs_pos, rhs_neg = self.network.line_rhs()
            lambda_eff = lam[np.newaxis, :] + PTDF_Gen.T @ (mu_lb - mu_ub)

        p_stars = np.zeros((N, T))
        sub_obj_total = 0.0

        sub_results = self._solve_unit_oracles(lambda_eff)
        for i, p_i, sub_obj_i in sub_results:
            p_stars[i] = p_i
            sub_obj_total += sub_obj_i

        dual_val = sub_obj_total + float(np.dot(lam, demand))
        g_lam = demand - p_stars.sum(axis=0)

        if self.network.is_single_node:
            grad = g_lam
        else:
            flows = PTDF_Gen @ p_stars
            dual_val += -float(np.sum(mu_ub * rhs_pos)) + float(np.sum(mu_lb * rhs_neg))
            g_ub = flows - rhs_pos
            g_lb = rhs_neg - flows
            grad = self._pack(g_lam, g_ub, g_lb)

        return float(dual_val), np.asarray(grad, dtype=float), {"p_stars": p_stars}

    def _solve_unit_oracles(self, lambda_eff: np.ndarray) -> list[tuple[int, np.ndarray, float]]:
        tasks = [
            (i, g, np.asarray(lambda_eff[i], dtype=float))
            for i, g in enumerate(self.generators)
        ]

        def solve_one(task: tuple[int, GeneratorParams, np.ndarray]) -> tuple[int, np.ndarray, float, dict]:
            i, g, lambda_i = task
            _, p_i, max_profit, timing = UnitSelfScheduleMILP.solve(
                g, lambda_i, threads=self.pricing_threads, return_timing=True
            )
            return i, p_i, -float(max_profit), timing

        if not self.parallel_pricing or self.N <= 1:
            results = [solve_one(task) for task in tasks]
        else:
            workers = self.max_workers or min(self.N, os.cpu_count() or self.N)
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                results = list(pool.map(solve_one, tasks))

        if hasattr(self, "_timing"):
            self._timing["unit_build"] += sum(float(r[3]["build_time"]) for r in results)
            self._timing["unit_solver"] += sum(float(r[3]["solver_time"]) for r in results)
            self._timing["unit_total"] += sum(float(r[3]["total_time"]) for r in results)
        return [(i, p_i, sub_obj_i) for i, p_i, sub_obj_i, _ in results]

    def _solve_master(
        self,
        cuts: list[_Cut],
        lower: np.ndarray,
        upper: np.ndarray,
    ) -> tuple[float, np.ndarray]:
        import gurobipy as gp
        from gurobipy import GRB

        t_start = time.perf_counter()
        m = gp.Model("LevelMaster")
        m.Params.OutputFlag = 0
        m.Params.DualReductions = 0
        y = m.addVars(
            len(lower),
            lb={i: float(lower[i]) for i in range(len(lower))},
            ub={i: float(upper[i]) for i in range(len(lower))},
            name="y",
        )
        theta = m.addVar(lb=-GRB.INFINITY, name="theta")
        for cut in cuts:
            expr = gp.LinExpr(float(cut.intercept))
            for i, coef in enumerate(cut.supergrad):
                if abs(float(coef)) > 1e-12:
                    expr += float(coef) * y[i]
            m.addConstr(theta <= expr)
        m.setObjective(theta, GRB.MAXIMIZE)
        build_done = time.perf_counter()
        m.optimize()
        total_done = time.perf_counter()
        if hasattr(self, "_timing"):
            solver_time = float(getattr(m, "Runtime", total_done - build_done))
            self._timing["master_build"] += max(0.0, build_done - t_start)
            self._timing["master_solver"] += solver_time
            self._timing["master_total"] += max(0.0, total_done - t_start)
        if m.Status != GRB.OPTIMAL:
            raise RuntimeError(f"Level master failed with Gurobi status {m.Status}")
        return float(theta.X), np.array([y[i].X for i in range(len(lower))], dtype=float)

    def _solve_projection(
        self,
        current: np.ndarray,
        cuts: list[_Cut],
        level: float,
        lower: np.ndarray,
        upper: np.ndarray,
    ) -> np.ndarray:
        import gurobipy as gp
        from gurobipy import GRB

        t_start = time.perf_counter()
        m = gp.Model("LevelProjection")
        m.Params.OutputFlag = 0
        m.Params.DualReductions = 0
        y = m.addVars(
            len(lower),
            lb={i: float(lower[i]) for i in range(len(lower))},
            ub={i: float(upper[i]) for i in range(len(lower))},
            name="y",
        )
        for cut in cuts:
            expr = gp.LinExpr(float(cut.intercept))
            for i, coef in enumerate(cut.supergrad):
                if abs(float(coef)) > 1e-12:
                    expr += float(coef) * y[i]
            m.addConstr(expr >= float(level))
        obj = gp.QuadExpr()
        for i in range(len(lower)):
            diff_i = y[i] - float(current[i])
            obj += diff_i * diff_i
        m.setObjective(obj, GRB.MINIMIZE)
        build_done = time.perf_counter()
        m.optimize()
        total_done = time.perf_counter()
        if hasattr(self, "_timing"):
            solver_time = float(getattr(m, "Runtime", total_done - build_done))
            self._timing["projection_build"] += max(0.0, build_done - t_start)
            self._timing["projection_solver"] += solver_time
            self._timing["projection_total"] += max(0.0, total_done - t_start)
        if m.Status == GRB.OPTIMAL:
            return np.array([y[i].X for i in range(len(lower))], dtype=float)
        if m.Status in (GRB.INFEASIBLE, GRB.INF_OR_UNBD):
            _, master_y = self._solve_master(cuts, lower, upper)
            return master_y
        raise RuntimeError(f"Level projection failed with Gurobi status {m.Status}")

    def _lmp_matrix(self, lam: np.ndarray, mu_ub: np.ndarray, mu_lb: np.ndarray) -> np.ndarray:
        lam = np.clip(np.asarray(lam, dtype=float), 0.0, None)
        if self.network.is_single_node:
            return np.tile(lam, (1, 1))
        return lam[np.newaxis, :] + self.network.PTDF.T @ (mu_lb - mu_ub)
