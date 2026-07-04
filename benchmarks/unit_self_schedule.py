"""
Single-unit self-scheduling MILP used by literature baselines.

This module intentionally does not use the proposed GP-DAG vertex oracle.
It solves the generator's price-response problem as a standard single-unit
UC MILP, which is the conventional profit-maximization subproblem used in
Lagrangian relaxation, Dantzig-Wolfe column generation, and LOC/uplift
settlement calculations in the CHP literature.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional, Tuple

import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_proj_dir = os.path.normpath(os.path.join(_this_dir, ".."))
if _proj_dir not in sys.path:
    sys.path.insert(0, _proj_dir)

from models.generator import GeneratorParams


def dispatch_cost(params: GeneratorParams, p_dispatch: np.ndarray, u_dispatch: np.ndarray) -> float:
    """Cost of a feasible dispatch under the same accounting as ScheduleRunMILP."""
    p_dispatch = np.asarray(p_dispatch, dtype=float)
    u_dispatch = np.asarray(u_dispatch, dtype=float)

    segs = params.get_pwl_segments()
    var_cost = 0.0
    excess = np.maximum(p_dispatch - params.P_min * u_dispatch, 0.0)
    if params.is_single_segment:
        var_cost = params.cost_var * float(np.sum(excess))
    else:
        for t, q_total in enumerate(excess):
            remaining = float(q_total)
            for slope, width in segs:
                fill = min(max(remaining, 0.0), width)
                var_cost += slope * fill
                remaining -= fill
                if remaining <= 1e-9:
                    break

    u_prev = np.concatenate([[float(params.initial_status)], u_dispatch[:-1]])
    startups = float(np.sum(np.maximum(u_dispatch - u_prev, 0.0)))
    shutdowns = float(np.sum(np.maximum(u_prev - u_dispatch, 0.0)))
    fixed_cost = (
        params.cost_nl * float(np.sum(u_dispatch))
        + params.cost_su * startups
        + params.cost_sd * shutdowns
    )
    return var_cost + fixed_cost


def dispatch_profit(
    params: GeneratorParams,
    lambda_star: np.ndarray,
    p_dispatch: np.ndarray,
    u_dispatch: np.ndarray,
) -> float:
    """Profit of a dispatch at a given price."""
    return float(np.dot(lambda_star, p_dispatch)) - dispatch_cost(params, p_dispatch, u_dispatch)


class UnitSelfScheduleMILP:
    """
    Standard single-unit profit-maximization problem.

    Given prices lambda_t, solve
        max lambda^T p - C(p,u)
    over the generator's non-convex UC feasible set.
    """

    @staticmethod
    def solve(
        params: GeneratorParams,
        lambda_star: np.ndarray,
        threads: Optional[int] = None,
        return_timing: bool = False,
    ) -> Tuple[np.ndarray, np.ndarray, float]:
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as e:
            raise ImportError("需要 gurobipy 才能运行 UnitSelfScheduleMILP。") from e

        t_start = time.perf_counter()
        T = params.T
        lambda_star = np.asarray(lambda_star, dtype=float)
        segs = params.get_pwl_segments()
        K = len(segs)

        model = gp.Model("UnitSelfScheduleMILP")
        model.Params.OutputFlag = 0
        model.Params.MIPGap = 1e-7
        if threads is not None:
            model.Params.Threads = int(threads)

        u = model.addVars(T, vtype=GRB.BINARY, name="u")
        p = model.addVars(T, lb=0.0, name="p")
        su = model.addVars(T, vtype=GRB.BINARY, name="su")
        sd = model.addVars(T, vtype=GRB.BINARY, name="sd")
        x = {
            (k, t): model.addVar(lb=0.0, ub=width, name=f"x_{k}_{t}")
            for k, (_, width) in enumerate(segs)
            for t in range(T)
        }

        profit = gp.LinExpr()
        for t in range(T):
            profit += float(lambda_star[t]) * p[t]
            profit -= params.cost_nl * u[t]
            profit -= params.cost_su * su[t]
            profit -= params.cost_sd * sd[t]
            for k, (slope, _) in enumerate(segs):
                profit -= slope * x[k, t]
        model.setObjective(profit, GRB.MAXIMIZE)

        for t in range(T):
            model.addConstr(
                p[t] == params.P_min * u[t] + gp.quicksum(x[k, t] for k in range(K)),
                name=f"pwl_link_{t}",
            )
            for k, (_, width) in enumerate(segs):
                model.addConstr(x[k, t] <= width * u[t], name=f"xub_{k}_{t}")
            model.addConstr(p[t] >= params.P_min * u[t], name=f"cap_lb_{t}")
            model.addConstr(p[t] <= params.P_max * u[t], name=f"cap_ub_{t}")

        for t in range(T):
            u_prev = u[t - 1] if t > 0 else float(params.initial_status)
            p_prev = p[t - 1] if t > 0 else float(params.initial_power)
            model.addConstr(su[t] >= u[t] - u_prev, name=f"su_logic_{t}")
            model.addConstr(sd[t] >= u_prev - u[t], name=f"sd_logic_{t}")
            model.addConstr(
                p[t] - p_prev <= params.R_up * u_prev + params.SU_ramp * su[t],
                name=f"ramp_up_{t}",
            )
            model.addConstr(
                p_prev - p[t] <= params.R_down * u[t] + params.SD_ramp * sd[t],
                name=f"ramp_dn_{t}",
            )

        if params.initial_status == 1:
            residual_on = max(0, params.T_on_min - int(params.initial_up_time))
            for t in range(min(residual_on, T)):
                model.addConstr(u[t] == 1, name=f"init_on_residual_{t}")
        else:
            residual_off = max(0, params.T_off_min - int(params.initial_down_time))
            for t in range(min(residual_off, T)):
                model.addConstr(u[t] == 0, name=f"init_off_residual_{t}")

        for t in range(T):
            if params.T_on_min > 1:
                model.addConstr(
                    gp.quicksum(u[tt] for tt in range(t, min(t + params.T_on_min, T)))
                    >= params.T_on_min * su[t],
                    name=f"mut_{t}",
                )
            if params.T_off_min > 1:
                model.addConstr(
                    gp.quicksum((1 - u[tt]) for tt in range(t, min(t + params.T_off_min, T)))
                    >= params.T_off_min * sd[t],
                    name=f"mdt_{t}",
                )

        build_done = time.perf_counter()
        model.optimize()
        total_done = time.perf_counter()
        if model.Status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL):
            raise RuntimeError(f"UnitSelfScheduleMILP 求解失败，Status={model.Status}")

        p_star = np.array([p[t].X for t in range(T)], dtype=float)
        u_star = np.array([round(u[t].X) for t in range(T)], dtype=float)
        if return_timing:
            solver_time = float(getattr(model, "Runtime", total_done - build_done))
            timing = {
                "build_time": max(0.0, build_done - t_start),
                "solver_time": solver_time,
                "total_time": max(0.0, total_done - t_start),
            }
            return u_star, p_star, float(model.ObjVal), timing
        return u_star, p_star, float(model.ObjVal)

    @staticmethod
    def uplift(
        params: GeneratorParams,
        lambda_star: np.ndarray,
        p_dispatch: np.ndarray,
        u_dispatch: np.ndarray,
        max_profit: float,
    ) -> float:
        scheduled_profit = dispatch_profit(params, lambda_star, p_dispatch, u_dispatch)
        return max(0.0, float(max_profit) - scheduled_profit)
