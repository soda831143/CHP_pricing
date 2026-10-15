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
@pytest.mark.parametrize('formulation', ['full_dual', 'active_cone'])
def test_full_dual_region_finds_exact_toy_interval_including_degenerate_point(primal, expected, formulation):
    p = SimpleNamespace(
        solver=True, matrices=(sparse.csr_matrix([[1., 1.]]), np.array([1.]), 0, 0,
                               sparse.csr_matrix((0, 2)), np.empty(0)),
        c0=np.array([0., 1.]), direction=np.array([1., -1.]), lb=np.zeros(2), ub=np.ones(2),
        network=SimpleNamespace(is_single_node=True))
    expander = OptimalityRegion(p, 0., 1., formulation)
    a, b = expander.expand(point(.5, primal))
    assert [a.delta, b.delta] == pytest.approx(expected, abs=1e-8)
    assert dual_audit_passed(a) and dual_audit_passed(b)
    assert expander.calls == 2


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
