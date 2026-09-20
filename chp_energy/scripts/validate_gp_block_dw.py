"""Minimal exact GP block-column-generation check against an absolute-q LP.

The PWL perspective epigraph stays in the restricted master.  A generated
column is therefore only a feasible fixed-ON output profile; pricing that
column is linear over the interval g-polymatroid and uses the existing greedy
oracle.  The reference keeps this project's DAG and changes only the interval
power coordinates; it is Yu/Pan-style, not an independent reproduction of
every feature in those papers.  This is an audit prototype, not a production
solver.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chp_core.graph_builder import DAGBuilder
from chp_core.ramping_polymatroid import RampingPolymatroid
from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.schedule_run import ScheduleRunMILP
from run_experiments import load_case


def _runs(u: np.ndarray) -> list[tuple[int, int]]:
    padded = np.r_[0, np.rint(u).astype(int), 0]
    starts = np.flatnonzero(np.diff(padded) == 1)
    ends = np.flatnonzero(np.diff(padded) == -1) - 1
    return list(zip(starts.tolist(), ends.tolist()))


def solve_gp_block_dw(generators, network, p_dispatch, u_dispatch, *, tol=1e-7, max_iter=200):
    import gurobi_compat as gp
    from gurobi_compat import GRB

    started = time.perf_counter()
    dags = [DAGBuilder.build(g) for g in generators]
    if any(g.initial_status for g in generators):
        raise NotImplementedError("audit prototype currently covers initial-off units")

    model = gp.Model("GPBlockDW")
    model.Params.OutputFlag = 0
    model.Params.Method = 1
    model.setObjSense(GRB.MINIMIZE)

    off = {
        (i, k): model.addVar(lb=0.0, ub=1.0, obj=arc.c_fix, name=f"off_{i}_{k}")
        for i, dag in enumerate(dags) for k, arc in enumerate(dag.off_arcs)
    }
    cvar = {
        (i, k, tau): model.addVar(lb=0.0, obj=1.0, name=f"c_{i}_{k}_{tau}")
        for i, dag in enumerate(dags) for k, iv in enumerate(dag.on_intervals)
        for tau in range(iv.duration)
    }

    profiles: dict[tuple[int, int], list[np.ndarray]] = {
        (i, k): [] for i, dag in enumerate(dags) for k in range(dag.n_on)
    }
    theta = {}
    for i, dag in enumerate(dags):
        interval_index = {(iv.a, iv.b): k for k, iv in enumerate(dag.on_intervals)}
        for a, b in _runs(u_dispatch[i]):
            k = interval_index[a, b]
            q = np.asarray(p_dispatch[i, a:b + 1], dtype=float)
            profiles[i, k].append(q)
            theta[i, k, 0] = model.addVar(lb=0.0, obj=dag.on_intervals[k].c_fix,
                                           name=f"theta_{i}_{k}_0")

    def theta_terms(i, k, coefficient):
        return gp.quicksum(
            coefficient(r, q) * theta[i, k, r]
            for r, q in enumerate(profiles[i, k])
        )

    flow_d, flow_u = {}, {}
    for i, dag in enumerate(dags):
        for t in range(1, dag.T):
            flow_d[i, t] = model.addConstr(
                gp.quicksum(theta_terms(i, k, lambda _r, _q: 1.0)
                            for k, iv in enumerate(dag.on_intervals) if iv.node_to == t)
                - gp.quicksum(off[i, k] for k, arc in enumerate(dag.off_arcs)
                              if arc.t_from == t) == 0.0,
                name=f"flow_d_{i}_{t}",
            )
            flow_u[i, t] = model.addConstr(
                gp.quicksum(off[i, k] for k, arc in enumerate(dag.off_arcs)
                            if arc.t_to == t)
                - gp.quicksum(theta_terms(i, k, lambda _r, _q: 1.0)
                              for k, iv in enumerate(dag.on_intervals) if iv.node_from == t) == 0.0,
                name=f"flow_u_{i}_{t}",
            )
    source = {}
    for i, dag in enumerate(dags):
        source[i] = model.addConstr(
            gp.quicksum(theta_terms(i, k, lambda _r, _q: 1.0)
                        for k, iv in enumerate(dag.on_intervals) if iv.node_from == 0)
            + gp.quicksum(off[i, k] for k, arc in enumerate(dag.off_arcs)
                          if arc.t_from == 0) == 1.0,
            name=f"source_{i}",
        )

    balance = {}
    for t in range(network.T):
        balance[t] = model.addConstr(
            gp.quicksum(
                theta_terms(i, k, lambda _r, q, tau=t - iv.a: float(q[tau]))
                for i, dag in enumerate(dags) for k, iv in enumerate(dag.on_intervals)
                if iv.a <= t <= iv.b
            ) == float(network.sys_demand[t]), name=f"balance_{t}"
        )

    pwl = {}
    for i, (dag, params) in enumerate(zip(dags, generators)):
        slopes = [x[0] for x in params.get_pwl_segments()]
        intercepts = params.pwl_intercepts() if not params.is_single_segment else [0.0]
        for k, iv in enumerate(dag.on_intervals):
            for tau in range(iv.duration):
                for seg, (slope, intercept) in enumerate(zip(slopes, intercepts)):
                    pwl[i, k, tau, seg] = model.addConstr(
                        -cvar[i, k, tau]
                        + theta_terms(
                            i, k,
                            lambda _r, q, tau=tau, slope=slope, intercept=intercept,
                            pmin=params.P_min:
                            float(slope * (q[tau] - pmin) + intercept),
                        ) <= 0.0,
                        name=f"pwl_{i}_{k}_{tau}_{seg}",
                    )

    ptdf_ub, ptdf_lb = {}, {}
    if not network.is_single_node:
        rhs_pos, rhs_neg = network.line_rhs()
        for line in range(network.N_line):
            for t in range(network.T):
                lhs = gp.quicksum(
                    float(network.PTDF_Gen[line, i])
                    * theta_terms(i, k, lambda _r, q, tau=t - iv.a: float(q[tau]))
                    for i, dag in enumerate(dags) for k, iv in enumerate(dag.on_intervals)
                    if iv.a <= t <= iv.b
                )
                ptdf_ub[line, t] = model.addConstr(
                    lhs <= float(rhs_pos[line, t]), name=f"ptdf_ub_{line}_{t}"
                )
                ptdf_lb[line, t] = model.addConstr(
                    -lhs <= -float(rhs_neg[line, t]), name=f"ptdf_lb_{line}_{t}"
                )

    model.update()
    history = []
    for iteration in range(1, max_iter + 1):
        model.optimize()
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError(f"RMP status {model.Status}")

        candidates = []
        for i, (dag, params) in enumerate(zip(dags, generators)):
            nodal_price = np.array([balance[t].Pi for t in range(network.T)])
            if not network.is_single_node:
                congestion = network.PTDF_Gen[:, i] @ np.array([
                    [ptdf_ub[line, t].Pi - ptdf_lb[line, t].Pi
                     for t in range(network.T)] for line in range(network.N_line)
                ])
                nodal_price += congestion

            slopes = np.array([x[0] for x in params.get_pwl_segments()], dtype=float)
            intercepts = np.asarray(
                params.pwl_intercepts() if not params.is_single_segment else [0.0],
                dtype=float,
            )
            for k, iv in enumerate(dag.on_intervals):
                xi = -nodal_price[iv.a:iv.b + 1].copy()
                for tau in range(iv.duration):
                    xi[tau] -= sum(
                        pwl[i, k, tau, seg].Pi * slopes[seg]
                        for seg in range(len(slopes))
                    )
                weights = np.cumsum(xi[::-1])[::-1]
                poly = RampingPolymatroid(
                    params, iv.a, iv.b, include_shutdown=iv.b < params.T - 1
                )
                q = np.cumsum(poly.greedy_maximize(-weights))

                rc = float(iv.c_fix)
                if iv.node_to < dag.T:
                    rc -= flow_d[i, iv.node_to].Pi
                if iv.node_from > 0:
                    rc += flow_u[i, iv.node_from].Pi
                else:
                    rc -= source[i].Pi
                for tau, t in enumerate(range(iv.a, iv.b + 1)):
                    rc -= balance[t].Pi * q[tau]
                    if not network.is_single_node:
                        for line in range(network.N_line):
                            coeff = float(network.PTDF_Gen[line, i] * q[tau])
                            rc -= ptdf_ub[line, t].Pi * coeff
                            rc += ptdf_lb[line, t].Pi * coeff
                    for seg, (slope, intercept) in enumerate(zip(slopes, intercepts)):
                        rc -= pwl[i, k, tau, seg].Pi * (
                            slope * (q[tau] - params.P_min) + intercept
                        )
                if rc < -tol:
                    key = tuple(np.round(q, 7))
                    if not any(tuple(np.round(old, 7)) == key for old in profiles[i, k]):
                        candidates.append((rc, i, k, q))

        history.append((iteration, float(model.objval), len(candidates),
                        min((x[0] for x in candidates), default=0.0),
                        sum(len(v) for v in profiles.values())))
        if not candidates:
            break

        for _rc, i, k, q in candidates:
            dag, params, iv = dags[i], generators[i], dags[i].on_intervals[k]
            column = gp.cp.Column()
            if iv.node_to < dag.T:
                column.addTerms(flow_d[i, iv.node_to], 1.0)
            if iv.node_from > 0:
                column.addTerms(flow_u[i, iv.node_from], -1.0)
            else:
                column.addTerms(source[i], 1.0)
            for tau, t in enumerate(range(iv.a, iv.b + 1)):
                column.addTerms(balance[t], float(q[tau]))
                if not network.is_single_node:
                    for line in range(network.N_line):
                        coeff = float(network.PTDF_Gen[line, i] * q[tau])
                        column.addTerms(ptdf_ub[line, t], coeff)
                        column.addTerms(ptdf_lb[line, t], -coeff)
                slopes = [x[0] for x in params.get_pwl_segments()]
                intercepts = params.pwl_intercepts() if not params.is_single_segment else [0.0]
                for seg, (slope, intercept) in enumerate(zip(slopes, intercepts)):
                    column.addTerms(
                        pwl[i, k, tau, seg],
                        float(slope * (q[tau] - params.P_min) + intercept),
                    )
            r = len(profiles[i, k])
            profiles[i, k].append(q)
            theta[i, k, r] = model.addVar(
                lb=0.0, obj=float(iv.c_fix), column=column, name=f"theta_{i}_{k}_{r}"
            )
        model.update()
    else:
        raise RuntimeError("GP block DW did not converge")

    alpha = beta = None
    prices = np.array([balance[t].Pi for t in range(network.T)])[None, :]
    if not network.is_single_node:
        alpha = np.array([[ptdf_ub[l, t].Pi for t in range(network.T)]
                          for l in range(network.N_line)])
        beta = np.array([[ptdf_lb[l, t].Pi for t in range(network.T)]
                         for l in range(network.N_line)])
        prices = prices + network.PTDF.T @ (alpha - beta)
    return prices, float(model.objval), history, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T", type=int, default=8)
    parser.add_argument("--network", choices=("single", "ptdf"), default="single")
    args = parser.parse_args()
    generators, network = load_case("30", args.network, args.T, 3, congestion="tight")
    p, u, _ = ScheduleRunMILP(generators, network).solve()
    direct = PrimalCHPLP(generators, network, power_coordinates="absolute")
    direct_started = time.perf_counter()
    direct_prices, direct_obj, direct_ok = direct.solve()
    if not direct_ok:
        raise RuntimeError("Yu-q reference LP failed")
    direct_elapsed = time.perf_counter() - direct_started
    prices, obj, history, elapsed = solve_gp_block_dw(generators, network, p, u)
    result = {
        "T": args.T,
        "network": args.network,
        "direct_obj": direct_obj,
        "gp_block_obj": obj,
        "objective_gap": obj - direct_obj,
        "max_price_gap": float(np.max(np.abs(prices - direct_prices))),
        "iterations": history[-1][0],
        "columns": history[-1][4],
        "direct_time_s": direct_elapsed,
        "gp_block_time_s": elapsed,
    }
    print(result)
    assert abs(result["objective_gap"]) <= 1e-5
    assert result["max_price_gap"] <= 1e-5


if __name__ == "__main__":
    main()
