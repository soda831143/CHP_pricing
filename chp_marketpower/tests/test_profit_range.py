import numpy as np
import pytest

from run_profit_range import physical_regions
from run_scope_experiments import select_contrasting_generator
from price_vulnerability.range_vulnerability import range_price_impact


def test_nonconvex_physical_choices_have_complete_common_plan_regions():
    # A finite NONCONVEX schedule set: three feasible full-plan cost lines.
    intercepts, slopes = np.array([0., .25, .75]), np.array([2., 1., 0.])
    def solve(delta):
        costs = intercepts+delta*slopes
        k = int(np.argmin(costs))
        return dict(intercept=intercepts[k], exposure=slopes[k], lower_bound=float(costs[k]))
    points, regions = physical_regions(solve, 0., 1.)
    assert len(points) < 15
    assert all(r['ready'] for r in regions)
    assert [r['right'] for r in regions] == pytest.approx([.25, .5, 1.])
    for region in regions:
        plan = points[region['witness_delta']]
        for d in np.linspace(region['left'], region['right'], 9):
            assert plan['intercept']+d*plan['exposure'] == pytest.approx(np.min(intercepts+d*slopes))


def test_partial_physical_map_never_claims_complete_coverage():
    def solve(delta):
        return dict(intercept=0. if delta < .5 else .5,
                    exposure=1. if delta < .5 else 0., lower_bound=min(delta, .5))
    _, regions = physical_regions(solve, 0., 1., max_solves=2)
    assert not all(r['ready'] for r in regions)
    with pytest.raises(ValueError):
        physical_regions(solve, 1., 0.)


def test_bad_global_mip_bound_cannot_support_a_physical_region():
    with pytest.raises(RuntimeError):
        physical_regions(lambda d: dict(intercept=0., exposure=1., lower_bound=d+1.), 0., 1.)


def test_uncertainty_in_global_uc_bound_is_not_ignored():
    _, regions = physical_regions(lambda d: dict(intercept=0., exposure=1., lower_bound=d-1e-3),
                                  0., 1., max_solves=3)
    assert all(not r['ready'] for r in regions)


def test_saved_compact_is_actually_matched_to_raw_prices(tmp_path):
    import hashlib
    import json
    from price_vulnerability.oracle_compression import load_matched_compact
    boundaries, values, prices = np.array([0., 1.]), np.array([0., 2.]), np.array([[[0.]], [[1.]]])
    np.savez(tmp_path/'oracle.npz', boundaries=boundaries, values=values, prices=prices)
    audit = dict(status='numerically_validated')
    compression = dict(status='numerically_validated_compression',
        source_sha256=hashlib.sha256((tmp_path/'oracle.npz').read_bytes()).hexdigest(),
        value_raw_indices=[0, 1], price_raw_indices=[0, 1])
    (tmp_path/'audit.json').write_text(json.dumps(audit))
    (tmp_path/'compression.json').write_text(json.dumps(compression))
    for shift in (0., 1.):
        np.savez(tmp_path/'compact.npz', value_boundaries=boundaries, values=values,
            price_boundaries=boundaries, prices=prices+shift, value_raw_indices=[0, 1], price_raw_indices=[0, 1])
        if shift == 0:
            load_matched_compact(tmp_path)
        else:
            with pytest.raises(ValueError, match='Compact prices'):
                load_matched_compact(tmp_path)


def test_successful_physical_witness_survives_a_later_mip_failure(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import run_profit_range as study
    source, output = tmp_path/'source', tmp_path/'output'
    source.mkdir()
    (source/'compact.npz').write_bytes(b'test source')
    arrays = dict(value_boundaries=np.array([0., .5]), values=np.array([1., 1.5]),
                  price_boundaries=np.array([0., .5]), prices=np.ones((2, 1, 1)))
    scope = dict(case='30', network='ptdf', T=1, segments=1, congestion='tight', generator_index=0)
    monkeypatch.setattr(study, 'load_matched_compact', lambda p: (dict(scope=scope), dict(source_sha256='test'), arrays))
    gen = SimpleNamespace(pwl_slopes=[1.], P_min=0.)
    monkeypatch.setattr(study, 'load_case', lambda *a: ([gen], object()))
    monkeypatch.setattr(study, 'apply_generator_adder', lambda gens, g, d: gens)
    monkeypatch.setattr(study, 'dispatch_cost', lambda gen, p, u: float(p.sum()))
    class UC:
        calls = 0
        def __init__(self, *args):
            pass
        def solve(self, **kwargs):
            UC.calls += 1
            if UC.calls == 2:
                raise RuntimeError('injected MIP failure')
            self.solve_info = dict(lower_bound=1.)
            return np.ones((1, 1)), np.ones((1, 1)), 1.
    monkeypatch.setattr(study, 'ScheduleRunMILP', UC)
    with pytest.warns(RuntimeWarning, match='Legacy'), pytest.raises(RuntimeError, match='injected MIP failure'):
        study.assess(source, output)
    with np.load(output/'physical_plans.npz') as saved:
        assert saved['deltas'].tolist() == [0.]
        assert saved['lower_bounds'].tolist() == [1.]
        assert saved['outputs'].shape == (1, 1, 1)
    assert json.loads((output/'failure.json').read_text())['successful_uc_solves'] == 1


def test_generator_selection_excludes_zero_exposure_and_does_not_use_profit():
    rows = [dict(generator_index=i, online_hours=h, incremental_energy_mwh=e)
            for i, h, e in [(0, 24, 100), (1, 4, 22), (2, 4, 0), (3, 18, 150)]]
    assert select_contrasting_generator(rows) == 1


def test_signed_directional_price_impact_distinguishes_bid_and_price_direction():
    result = range_price_impact([-1., 0., 1.], np.array([[[3., -4.]], [[0., 0.]], [[2., -1.]]]))
    down = result['directional_signed_extremes']['downward_bid']
    assert down['largest_increase']['signed_change_usd_per_mwh'] == 3.
    assert down['largest_decrease']['signed_change_usd_per_mwh'] == -4.
    assert down['largest_decrease']['hour_1based'] == 2


def test_physical_tie_break_changes_attainment_not_the_left_profit_limit():
    # Demand one; target bid delta and true cost zero, competitor bid one.
    # Both physical allocations are optimal at delta=1, but only target dispatch attains sup Pi=1.
    def profit(delta, dispatch):
        price = min(delta, 1.)
        reported_self_surplus = max(price-delta, 0.)
        return reported_self_surplus+delta*dispatch
    assert profit(1., 1.) == 1.
    assert profit(1., 0.) == 0.
    left = np.array([profit(1.-10.**(-k), 1.) for k in range(1, 8)])
    assert np.all(left < 1.) and np.all(np.diff(left) > 0.)
    assert left[-1] == pytest.approx(1., abs=1e-6)
    assert profit(1.1, 0.) == 0.
