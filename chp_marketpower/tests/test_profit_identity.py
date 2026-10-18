"""Money checks with independently calculated small physical examples."""
from types import SimpleNamespace

import numpy as np
import pytest

from mechanism_study.profit_identity import hourly_cost, ledger, paired_identity


def generator():
    return SimpleNamespace(T=2, P_min=10., P_max=30., cost_nl=20., cost_su=5.,
        cost_sd=2., initial_status=0, get_pwl_segments=lambda: [(2., 10.), (4., 10.)])


def test_pwl_start_stop_and_minimum_output_are_counted_once():
    gen = generator()
    # 15 MWh above minimum: 10*2+5*4; plus no-load and actual startup.
    assert hourly_cost(gen, [25., 0.], [1., 0.]).tolist() == [65., 2.]
    # At these prices every positive output loses money; the true SS maximum is zero.
    row = ledger(gen, [25., 0.], [1., 0.], [1., 1.], 3., 0.)
    assert row['true_cost_usd'] == 67.
    assert row['exposure_mwh'] == 15.
    assert row['reported_cost_usd'] == 112.
    assert row['loc_usd'] == 87.
    assert row['true_profit_usd'] == 45.
    assert row['identity_residual_usd'] == 0.


def test_p2_uses_incremental_exposure_not_total_generation():
    gen = generator()
    # Equal total generation, different online hours: D differs by 10 MWh.
    a = ledger(gen, [30., 0.], [1., 0.], [1., 1.], 3., 0.)
    b = ledger(gen, [15., 15.], [1., 1.], [1., 1.], 3., 0.)
    pair = paired_identity(3., a, b)
    assert pair['generation_difference_mwh'] == 0.
    assert pair['exposure_difference_mwh'] == 10.
    assert pair['observed_profit_difference_usd'] == 30.
    assert pair['residual_usd'] == 0.


def test_truthful_profit_is_invariant_for_different_feasible_dispatches():
    gen = generator()
    a = ledger(gen, [30., 0.], [1., 0.], [1., 1.], 0., 0.)
    b = ledger(gen, [15., 15.], [1., 1.], [1., 1.], 0., 0.)
    assert a['energy_revenue_usd']+a['loc_usd']-a['true_cost_usd'] == 0.
    assert paired_identity(0., a, b)['observed_profit_difference_usd'] == 0.


def test_missing_full_loc_does_not_satisfy_the_identity():
    row = ledger(generator(), [25., 0.], [1., 0.], [1., 1.], 3., 0.)
    capped_loc = min(row['loc_usd'], 5.)
    incomplete_profit = row['energy_revenue_usd']+capped_loc-row['true_cost_usd']
    assert incomplete_profit != row['best_reported_profit_usd']+row['bid_wedge_usd']


def test_inconsistent_self_schedule_or_physical_input_is_rejected():
    gen = generator()
    with pytest.raises(ValueError, match='below feasible'):
        ledger(gen, [30., 0.], [1., 0.], [100., 100.], 0., 0.)
    with pytest.raises(ValueError, match='committed capacity'):
        hourly_cost(gen, [5., 0.], [1., 0.])
    with pytest.raises(ValueError, match='binary'):
        hourly_cost(gen, [15., 0.], [.5, 0.])
    with pytest.raises(ValueError, match='finite'):
        ledger(gen, [25., 0.], [1., 0.], [np.nan, 1.], 0., 20.)


def test_local_channels_and_their_one_sided_kink_on_a_finite_schedule_set():
    # C(p)=p/2, p in [0,2]; endpoints attain the same support as the full interval.
    p = np.array([0., 1., 2.])
    cost, exposure = p/2, p
    def profit(delta):
        return np.max((3.+.5*delta)*p-cost-delta*exposure)+delta
    eps = 1e-5
    # At delta=1, SS p=2 and D_UC=1: price 1, exposure -1.
    assert (profit(1.+eps)-profit(1.-eps))/(2*eps) == pytest.approx(0., abs=1e-9)
    assert .5*2.+1.-2. == 0.
    # At delta=5 all SS choices tie: an arbitrary optimizer is NOT a two-sided derivative.
    assert (profit(5.)-profit(5.-eps))/eps == pytest.approx(0., abs=1e-9)
    assert (profit(5.+eps)-profit(5.))/eps == pytest.approx(1., abs=1e-9)


def test_max_affine_plus_fixed_exposure_is_convex_and_endpoint_bounded():
    def profit(delta):
        return max(2.-delta, 2.*delta-1.)+.3*delta
    maximum = max(profit(0.), profit(2.))
    assert all(profit(d) <= maximum+1e-12 for d in np.linspace(0., 2., 51))
    a,b = .2, 1.5
    assert profit(.4*a+.6*b) <= .4*profit(a)+.6*profit(b)+1e-12
