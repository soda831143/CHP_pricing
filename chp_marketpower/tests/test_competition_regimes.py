import pytest

from paper_results.competition_analysis_20261102 import dominance_margin


def line(cost, exposure=0., hours=0.):
    return dict(cost=cost, exposure=exposure, g5_online_hours=hours)


def test_strict_dominance_requires_every_offer_and_cost_corner():
    pair = [line(10., 1., 2.), line(20., -1., 0.)]
    assert dominance_margin(pair, line(0.), [0., 5.], [0., 2.]) == pytest.approx(10.)
    # A cheaper competitor at delta=0 can still lose at the other end.
    assert dominance_margin([line(1., -1.)], line(0.), [0., 2.], [0., 5.]) == pytest.approx(-1.)
    assert dominance_margin([line(1.)], line(0., hours=1.), [0., 2.], [0., 5.]) == pytest.approx(-4.)


def test_equal_cost_is_not_strict_exclusion():
    assert dominance_margin([line(0.)], line(0.), [0., 20.991], [0., 5.]) == 0.
