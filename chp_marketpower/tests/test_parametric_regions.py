from types import SimpleNamespace

import numpy as np
import pytest
from scipy import sparse

from price_vulnerability.affine_oracle import Endpoint, dual_audit_passed
from price_vulnerability.budgeted_oracle import interval_status
from price_vulnerability.optimality_region import OptimalityRegion
from price_vulnerability.range_vulnerability import range_price_impact


def point(delta, primal):
    c = np.array([delta, 1-delta])
    value = float(c@primal)
    return Endpoint(delta, value, value, float(np.array([1., -1.])@primal),
                    np.array([[value]]), c, np.asarray(primal), np.array([value]), np.empty(0),
                    c-value, np.zeros(2), {name:0. for name in (
                        'primal_feasibility', 'dual_sign', 'stationarity', 'duality_gap',
                        'row_complementarity', 'bound_complementarity', 'objective_reconstruction',
                        'price_projection')}, 0.)


@pytest.mark.parametrize('primal,expected', [([1., 0.], [0., .5]), ([0., 1.], [.5, 1.]),
                                           ([.5, .5], [.5, .5])])
@pytest.mark.parametrize('formulation', ['full_dual', 'active_cone', 'persistent_cone'])
def test_full_dual_region_finds_exact_toy_interval_including_degenerate_point(primal, expected, formulation):
    p = SimpleNamespace(
        solver=True, matrices=(sparse.csr_matrix([[1., 1.]]), np.array([1.]), 0, 0,
                               sparse.csr_matrix((0, 2)), np.empty(0)),
        c0=np.array([0., 1.]), direction=np.array([1., -1.]), lb=np.zeros(2), ub=np.ones(2),
        network=SimpleNamespace(is_single_node=True, T=1))
    expander = OptimalityRegion(p, 0., 1., formulation)
    a, b = expander.expand(point(.5, primal))
    assert [a.delta, b.delta] == pytest.approx(expected, abs=1e-8)
    assert dual_audit_passed(a) and dual_audit_passed(b)
    assert expander.calls == 2
    if formulation == 'persistent_cone':
        saved_model = expander.model
        other = [0., 1.] if primal == [1., 0.] else [1., 0.]
        left, right = expander.expand(point(.5, other))
        assert expander.model is saved_model
        assert [left.delta, right.delta] == pytest.approx([.5, 1.] if other == [0., 1.] else [0., .5], abs=1e-8)


def test_interior_common_primal_avoids_rejection_due_to_degenerate_endpoint_choices():
    a, b = point(0., [1., 0.]), point(1., [0., 1.])
    # min{delta, 1-delta, 0}: each endpoint may return a non-common optimum.
    from dataclasses import replace
    a = replace(a, objective=np.array([0., 1., 0.]), primal=np.array([1., 0., 0.]))
    b = replace(b, objective=np.array([1., 0., 0.]), primal=np.array([0., 1., 0.]))
    common = replace(a, delta=.5, primal=np.array([0., 0., 1.]))
    assert not interval_status(a, b).price_ready
    assert interval_status(a, b, witnesses=[a, b, common]).price_ready


def test_continuous_price_extreme_uses_endpoints_and_detects_local_extrapolation_error():
    result = range_price_impact([0., 1., 2.], np.array([[[0.]], [[1.]], [[1.5]]]))
    assert result['range_price_impact_usd_per_mwh'] == 1.5
    assert result['maximizing_delta'] == 2.
    assert result['max_local_linear_extrapolation_error'] == .5
    assert result['local_linear_predicted_range_impact'] == 2.
    with pytest.raises(ValueError):
        range_price_impact([1., 2.], np.array([[[0.]], [[1.]]]))


def test_common_witness_bound_retains_the_endpoint_primal_dual_gap():
    from dataclasses import replace
    a, b = point(0., [1., 0.]), point(.4, [1., 0.])
    a, b = replace(a, dual_value=a.value-1e-7), replace(b, dual_value=b.value-1e-7)
    result = interval_status(a, b, witnesses=[a, b])
    assert result.price_ready
    assert result.max_value_gap == pytest.approx(1e-7, abs=1e-12)
    fast = interval_status(a, b, witness_lines=(np.array([0., 0.]), np.array([1., 1.])))
    assert fast.max_value_gap == pytest.approx(result.max_value_gap, abs=1e-12)


def test_common_physical_schedule_requires_endpoint_global_bounds():
    from run_profit_interval import common_schedule_gap
    assert common_schedule_gap([100., 120.], [100., 120.]) == 0.
    assert common_schedule_gap([100., 120.], [100., 119.]) == 1.
    with pytest.raises(ValueError):
        common_schedule_gap([100., 120.], [101., 120.])


def test_cached_endpoint_values_preserve_interval_gate():
    a, b = point(0., [1., 0.]), point(.4, [1., 0.])
    assert interval_status(a, b) == interval_status(a, b, primal_values=(a.value, b.value))


def test_compression_can_use_a_common_witness_saved_outside_the_interval():
    from price_vulnerability.oracle_compression import compress_full_oracle
    boundaries = np.array([-1., -1e-10, 0., 1.])
    objectives = np.array([[d, 1-d, 0.] for d in boundaries])
    primals = np.array([[1., 0., 0.], [0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
    values = np.array([-1., -1e-10, 0., 0.])
    result = compress_full_oracle(boundaries, values, values, objectives, primals,
                                  np.zeros((4, 1, 1)), np.ones(3, bool))
    assert result.value_indices.tolist() == [0, 2, 3]
    assert result.value_witness_indices[-1] == 1


@pytest.mark.parametrize('aggregate_output', [False, True])
def test_native_query_baseline_reads_balance_rows_with_or_without_output_links(aggregate_output):
    from engine import load_case
    from benchmark_oracle_queries import _reoptimize_workload
    from price_vulnerability.affine_oracle import solve_endpoint
    generators, network = load_case('6', 'ptdf', 3, 3, 'tight')
    elapsed, values, prices = _reoptimize_workload(generators, network, 1,
        np.array([.2, -.2, 0.]), aggregate_output=aggregate_output)
    assert elapsed > 0 and np.asarray(prices).shape == (3, 6, 3)
    expected = solve_endpoint(generators, network, 1, -.2, aggregate_output=aggregate_output)
    assert abs(values[1]-expected.value) < 1e-6
    assert np.allclose(prices[1], expected.price, atol=1e-6)
