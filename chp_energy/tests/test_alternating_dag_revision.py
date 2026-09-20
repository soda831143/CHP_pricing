"""Regression tests for the alternating-DAG and rolling-boundary revision."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

_PROJECT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from benchmarks.unit_self_schedule import UnitSelfScheduleMILP
from chp_core.graph_builder import DAGBuilder
from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.vertex_oracle import VertexOracle
from models.generator import GeneratorParams


def _generator(**overrides) -> GeneratorParams:
    data = dict(
        P_max=100.0,
        P_min=20.0,
        R_up=20.0,
        R_down=40.0,
        T_on_min=1,
        T_off_min=1,
        cost_var=10.0,
        cost_su=10.0,
        cost_sd=100.0,
        cost_nl=5.0,
        T=3,
        SU_ramp=100.0,
        SD_ramp=60.0,
        unit_id="test-unit",
    )
    data.update(overrides)
    return GeneratorParams(**data)


def test_ramp_reset_on_to_on_counterexample_is_infeasible() -> None:
    """The former [0,1]->[2,2] ramp reset must not satisfy fixed demand."""
    pytest.importorskip("gurobi_compat")
    params = _generator(R_up=5.0)
    model = PrimalCHPLP([params], np.array([100.0, 60.0, 100.0]))
    _, objective, success = model.solve()
    assert not success
    assert np.isinf(objective)


def test_cross_flow_rows_reject_same_type_joins() -> None:
    """At each internal boundary, each arc type must continue as the other."""
    params = _generator()
    model = PrimalCHPLP([params], np.zeros(params.T))
    idx = model._idx
    matrix, rhs, n_flow, n_src, n_bal = model._build_eq_constraints(idx)

    assert n_flow == 2 * (params.T - 1)
    assert n_src == 1
    assert n_bal == params.T
    assert np.allclose(rhs[:n_flow], 0.0)

    dag = model.dags[0]
    boundary = 1
    d_row = 2 * (boundary - 1)
    u_row = d_row + 1

    incoming_on = [
        idx.z_on(0, k)
        for k, interval in enumerate(dag.on_intervals)
        if interval.node_to == boundary
    ]
    outgoing_on = [
        idx.z_on(0, k)
        for k, interval in enumerate(dag.on_intervals)
        if interval.node_from == boundary
    ]
    incoming_off = [
        idx.z_off(0, k)
        for k, arc in enumerate(dag.off_arcs)
        if arc.t_to == boundary
    ]
    outgoing_off = [
        idx.z_off(0, k)
        for k, arc in enumerate(dag.off_arcs)
        if arc.t_from == boundary
    ]

    assert incoming_on and outgoing_on and incoming_off and outgoing_off
    assert all(matrix[d_row, col] == 1.0 for col in incoming_on)
    assert all(matrix[d_row, col] == -1.0 for col in outgoing_off)
    assert all(matrix[d_row, col] == 0.0 for col in outgoing_on)
    assert all(matrix[u_row, col] == 1.0 for col in incoming_off)
    assert all(matrix[u_row, col] == -1.0 for col in outgoing_on)
    assert all(matrix[u_row, col] == 0.0 for col in outgoing_off)


def test_initially_online_residual_mut_forbids_immediate_shutdown() -> None:
    params = _generator(
        T=4,
        T_on_min=3,
        T_off_min=2,
        initial_status=1,
        initial_power=20.0,
        initial_up_time=1,
    )
    dag = DAGBuilder.build(params)

    assert not any(arc.t_from == 0 for arc in dag.off_arcs)
    shutdown_intervals = [
        interval for interval in dag.on_intervals if interval.b < params.T - 1
    ]
    assert shutdown_intervals
    assert min(interval.duration for interval in shutdown_intervals) >= 2


def test_initially_online_immediate_shutdown_requires_shutdown_ramp() -> None:
    allowed = _generator(
        initial_status=1,
        initial_power=50.0,
        initial_up_time=5,
        SD_ramp=60.0,
    )
    blocked = _generator(
        initial_status=1,
        initial_power=80.0,
        initial_up_time=5,
        SD_ramp=60.0,
    )
    assert any(arc.t_from == 0 for arc in DAGBuilder.build(allowed).off_arcs)
    assert not any(arc.t_from == 0 for arc in DAGBuilder.build(blocked).off_arcs)


def test_terminal_online_interval_has_no_artificial_shutdown_cost() -> None:
    params = _generator(cost_su=17.0, cost_sd=91.0, cost_nl=3.0)
    dag = DAGBuilder.build(params)
    terminal = next(
        interval
        for interval in dag.on_intervals
        if interval.a == 0 and interval.b == params.T - 1
    )
    assert terminal.c_fix == pytest.approx(
        params.cost_su + terminal.duration * params.cost_nl
    )


def test_model_statistics_match_solver_counters() -> None:
    pytest.importorskip("gurobi_compat")
    params = _generator()
    model = PrimalCHPLP([params], np.full(params.T, params.P_min))
    _, _, success = model.solve()
    assert success
    assert model.n_variables == model._model.NumVars
    assert model.n_constraints == model._model.NumConstrs
    assert model.n_nonzeros == model._model.Elems
    assert model.build_time >= 0.0
    assert model.solver_time >= 0.0
    assert model.total_time >= model.build_time
    assert model.primal_violation <= 1e-6


def test_interval_response_matches_exact_self_schedule_for_initial_online() -> None:
    pytest.importorskip("gurobi_compat")
    params = _generator(
        T=5,
        T_on_min=3,
        T_off_min=2,
        initial_status=1,
        initial_power=40.0,
        initial_up_time=1,
        R_up=25.0,
        R_down=25.0,
        SD_ramp=45.0,
    )
    prices = np.array([35.0, 30.0, 5.0, 45.0, 50.0])

    u_interval, p_interval, profit_interval = VertexOracle.solve(params, prices)
    u_milp, p_milp, profit_milp = UnitSelfScheduleMILP.solve(params, prices)

    assert profit_interval == pytest.approx(profit_milp, abs=1e-5)
    assert np.allclose(u_interval, u_milp, atol=1e-7)
    assert np.allclose(p_interval, p_milp, atol=1e-5)


def test_pwl_conditional_greedy_matches_interval_lp_at_cost_kink() -> None:
    """A PWL optimum at a breakpoint must agree with the exact interval LP."""
    pytest.importorskip("gurobi_compat")
    params = _generator(
        T=1,
        P_max=100.0,
        R_up=100.0,
        R_down=100.0,
        SU_ramp=100.0,
        SD_ramp=100.0,
        cost_su=0.0,
        cost_sd=0.0,
        cost_nl=0.0,
        pwl_slopes=[5.0, 15.0],
        pwl_widths=[20.0, 60.0],
    )
    prices = np.array([10.0])

    greedy = VertexOracle._solve_interval_pwl_conditional_greedy(
        params, 0, 0, prices
    )
    lp_output, lp_profit = VertexOracle._solve_interval_pwl_lp(
        params, 0, 0, prices
    )

    assert greedy is not None
    greedy_output, greedy_profit, _, gap = greedy
    assert greedy_output[0] == pytest.approx(40.0, abs=1e-7)
    assert greedy_profit == pytest.approx(lp_profit, abs=1e-7)
    assert np.allclose(greedy_output, lp_output, atol=1e-7)
    assert gap <= 1e-7


def test_ramping_polymatroid_preserves_startup_and_shutdown_limits() -> None:
    """SU/SD limits must replace, not be tightened by, ordinary ramp bounds."""
    from chp_core.ramping_polymatroid import RampingPolymatroid

    params = _generator(
        T=2,
        P_max=120.0,
        P_min=40.0,
        R_up=60.0,
        R_down=60.0,
        SU_ramp=80.0,
        SD_ramp=80.0,
    )
    poly = RampingPolymatroid(params, 0, 1, include_shutdown=True)
    # p=(80,80) corresponds to v=(80,0); it satisfies both the physical
    # startup and shutdown limits although they exceed normal ramp limits.
    feasible, violating_set = poly._gpoly.check_feasibility(
        np.array([80.0, 0.0])
    )
    assert feasible, violating_set
