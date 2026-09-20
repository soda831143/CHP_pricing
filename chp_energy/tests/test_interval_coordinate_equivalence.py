import numpy as np
import pytest

pytest.importorskip("gurobi_compat")

from chp_solver.chp_master_lp import PrimalCHPLP
from models.generator import GeneratorParams
from models.network import SingleNodeNetwork


@pytest.mark.parametrize("use_output_vars", [False, True])
def test_differential_and_absolute_interval_coordinates_are_equivalent(use_output_vars):
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

    differential = PrimalCHPLP([generator], network, use_output_vars=use_output_vars)
    absolute = PrimalCHPLP(
        [generator],
        network,
        use_output_vars=use_output_vars,
        power_coordinates="absolute",
    )
    _, differential_obj, differential_ok = differential.solve()
    _, absolute_obj, absolute_ok = absolute.solve()

    assert differential_ok and absolute_ok
    assert absolute_obj == pytest.approx(differential_obj, abs=1e-6)
    assert absolute.lp_dispatch() == pytest.approx(differential.lp_dispatch(), abs=1e-6)


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
