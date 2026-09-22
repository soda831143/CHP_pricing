import numpy as np
import pytest

pytest.importorskip("gurobi_compat")

from chp_solver.chp_master_lp import PrimalCHPLP
from chp_solver.schedule_run import ScheduleRunMILP
from models.generator import GeneratorParams
from models.network import SingleNodeNetwork


@pytest.mark.parametrize("use_output_vars", [False, True])
def test_interval_output_with_or_without_aggregate_output_variables(use_output_vars):
    generator = GeneratorParams(
        P_max=100.0,
        P_min=20.0,
        R_up=25.0,
        R_down=25.0,
        SU_ramp=60.0,
        SD_ramp=40.0,
        T_on_min=2,
        T_off_min=1,
        cost_var=10.0,
        cost_su=80.0,
        cost_sd=20.0,
        cost_nl=100.0,
        T=4,
        initial_status=1,
        initial_power=50.0,
        initial_up_time=1,
        pwl_slopes=[10.0, 18.0],
        pwl_widths=[40.0, 40.0],
    )
    network = SingleNodeNetwork(np.array([55.0, 70.0, 50.0, 30.0]))

    solver = PrimalCHPLP([generator], network, use_output_vars=use_output_vars)
    lmp, objective, success = solver.solve()

    assert success
    assert np.isfinite(objective)
    assert solver.lp_dispatch()[0] == pytest.approx(network.sys_demand, abs=1e-6)
    assert np.all(solver.raw_energy_dual > 0)
    assert solver.raw_nodal_price == pytest.approx(lmp, abs=1e-7)


def test_uniform_pwl_bid_adder_keeps_constraint_matrix_fixed():
    """The absolute bid adder is a cost parameter, not a matrix parameter."""
    generator = GeneratorParams(
        P_max=100.0,
        P_min=20.0,
        R_up=100.0,
        R_down=100.0,
        SU_ramp=100.0,
        SD_ramp=100.0,
        T_on_min=1,
        T_off_min=1,
        cost_var=10.0,
        cost_su=0.0,
        cost_sd=0.0,
        cost_nl=0.0,
        T=2,
        pwl_slopes=[10.0, 18.0],
        pwl_widths=[40.0, 40.0],
    )
    network = SingleNodeNetwork(np.array([50.0, 60.0]))
    base = PrimalCHPLP([generator], network)
    shifted = PrimalCHPLP([generator], network, bid_adders=np.array([[0.5, 1.0]]))

    base_A, base_b = base._build_ineq_constraints(base._idx)
    shifted_A, shifted_b = shifted._build_ineq_constraints(shifted._idx)

    assert (base_A != shifted_A).nnz == 0
    assert shifted_b == pytest.approx(base_b)


@pytest.mark.parametrize("initial_online", [False, True])
def test_bid_adder_direction_is_above_minimum_energy(initial_online):
    generator = GeneratorParams(
        P_max=100.0,
        P_min=20.0,
        R_up=100.0,
        R_down=100.0,
        SU_ramp=100.0,
        SD_ramp=100.0,
        T_on_min=1,
        T_off_min=1,
        cost_var=10.0,
        cost_su=0.0,
        cost_sd=0.0,
        cost_nl=5.0,
        T=2,
        initial_status=int(initial_online),
        initial_power=50.0 if initial_online else 0.0,
        initial_up_time=1 if initial_online else 0,
        pwl_slopes=[10.0, 18.0],
        pwl_widths=[40.0, 40.0],
    )
    network = SingleNodeNetwork(np.array([50.0, 60.0]))
    base = PrimalCHPLP([generator], network)
    shifted = PrimalCHPLP(
        [generator],
        network,
        bid_adders=np.array([[0.5, 0.5]]),
    )
    assert base.solve()[2] and shifted.solve()[2]

    direction = base.bid_adder_direction(0)
    base_objective = np.array([variable.obj for variable in base._model.getVars()])
    shifted_objective = np.array([variable.obj for variable in shifted._model.getVars()])
    assert direction @ base._solution_x == pytest.approx(
        base.incremental_energy_exposure(0), abs=1e-7
    )
    assert shifted_objective - base_objective == pytest.approx(0.5 * direction, abs=1e-12)
    assert base.bid_adder_direction(0, hour=1) @ base._solution_x == pytest.approx(
        base.incremental_energy_exposure(0, hour=1), abs=1e-7
    )


def test_physical_uc_segment_fill_is_above_minimum_energy():
    generator = GeneratorParams(
        P_max=100.0,
        P_min=20.0,
        R_up=100.0,
        R_down=100.0,
        SU_ramp=100.0,
        SD_ramp=100.0,
        T_on_min=1,
        T_off_min=1,
        cost_var=10.0,
        cost_su=0.0,
        cost_sd=0.0,
        cost_nl=5.0,
        T=2,
        pwl_slopes=[10.0, 18.0],
        pwl_widths=[40.0, 40.0],
    )
    run = ScheduleRunMILP([generator], SingleNodeNetwork(np.array([50.0, 60.0])))
    dispatch, commitment, _ = run.solve(require_optimal=True)
    assert run.incremental_dispatch() == pytest.approx(
        dispatch - generator.P_min * commitment, abs=1e-7
    )
