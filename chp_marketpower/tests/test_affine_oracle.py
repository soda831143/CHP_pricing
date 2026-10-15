"""Solver-free checks of the online selector's boundaries and interpolation."""

import sys
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from price_vulnerability.affine_oracle import Endpoint, query  # noqa: E402
from price_vulnerability.budgeted_oracle import (  # noqa: E402
    build_budgeted_oracle, interval_status,
)


def test_query_interpolates_and_uses_shared_endpoint_once() -> None:
    boundaries = np.array([0.0, 0.1, 0.3])
    values = np.array([10.0, 12.0, 13.0])
    prices = np.array([[[2.0, 4.0]], [[3.0, 6.0]], [[7.0, 8.0]]])
    value, price = query(0.05, boundaries, values, prices)
    assert value == pytest.approx(11.0)
    np.testing.assert_allclose(price, [[2.5, 5.0]])
    value, price = query(0.1, boundaries, values, prices)
    assert value == pytest.approx(12.0)
    np.testing.assert_allclose(price, prices[1])
    value, price = query(0.3, boundaries, values, prices)
    assert value == pytest.approx(13.0)
    np.testing.assert_allclose(price, prices[-1])


@pytest.mark.parametrize("delta", [-0.1, 0.31, float("nan")])
def test_query_rejects_outside_domain(delta: float) -> None:
    with pytest.raises(ValueError, match="outside"):
        query(delta, np.array([0.0, 0.3]), np.array([1.0, 2.0]),
              np.array([[[3.0]], [[4.0]]]))


def _toy_point(delta: float) -> Endpoint:
    # min(delta, 1-delta): one genuine value kink at 0.5.
    objective = np.array([delta, 1 - delta])
    primal = np.array([1.0, 0.0]) if delta <= 0.5 else np.array([0.0, 1.0])
    value = float(objective @ primal)
    audit = {name: 0.0 for name in (
        "primal_feasibility", "dual_sign", "stationarity", "duality_gap",
        "row_complementarity", "bound_complementarity",
        "objective_reconstruction", "price_projection",
    )}
    return Endpoint(
        delta, value, value, float(np.array([1.0, -1.0]) @ primal),
        np.array([[delta]]), objective, primal,
        np.zeros(1), np.zeros(1), np.zeros(2), np.zeros(2), audit, 0.0,
    )


def test_budgeted_refinement_finds_hidden_kink_and_prices_only_audited_intervals() -> None:
    snapshots = []
    full, intervals = build_budgeted_oracle(
        _toy_point, 0.0, 1.0, max_points=3,
        on_update=lambda points, current: snapshots.append((len(points), current)),
    )
    assert [point.delta for point in full] == pytest.approx([0.0, 0.5, 1.0])
    assert all(item.price_ready for item in intervals)
    assert [count for count, _ in snapshots] == [2, 3]
    json.dumps([asdict(item) for item in intervals])
    assert max(item.max_value_gap for item in intervals) == pytest.approx(0.0)

    partial, unresolved = build_budgeted_oracle(_toy_point, 0.0, 1.0, max_points=2)
    assert len(partial) == 2
    assert unresolved[0].max_value_gap == pytest.approx(0.5)
    assert not unresolved[0].price_ready
    assert interval_status(partial[0], partial[1]).probe_delta == pytest.approx(0.5)


def test_small_value_gap_never_implies_an_audited_price() -> None:
    _, intervals = build_budgeted_oracle(
        _toy_point, 0.0, 1.0, max_points=20, value_tolerance=1.0,
    )
    assert len(intervals) == 1
    assert not intervals[0].price_ready


def test_query_refuses_uncovered_price_but_accepts_solved_endpoints() -> None:
    boundaries = np.array([0.0, 1.0])
    values = np.array([0.0, 0.0])
    prices = np.array([[[1.0]], [[2.0]]])
    with pytest.raises(ValueError, match="direct CHP fallback"):
        query(0.5, boundaries, values, prices, np.array([False]))
    assert query(0.0, boundaries, values, prices, np.array([False]))[1][0, 0] == 1.0


def test_focus_reserves_solves_for_a_query_window() -> None:
    points, intervals = build_budgeted_oracle(
        _toy_point, 0.0, 1.0, max_points=4,
        focus=(0.0, 0.5), focus_budget=4,
    )
    assert points[1].delta == pytest.approx(0.5)
    assert intervals[0].price_ready


def test_budgeted_discovery_resumes_without_resolving_saved_points() -> None:
    saved, _ = build_budgeted_oracle(_toy_point, 0.0, 1.0, max_points=2)
    calls = []
    def solve(delta):
        calls.append(delta)
        return _toy_point(delta)
    points, intervals = build_budgeted_oracle(
        solve, 0.0, 1.0, max_points=3, initial_points=saved,
    )
    assert calls == pytest.approx([0.5])
    assert len(points) == 3 and all(item.price_ready for item in intervals)


def test_complete_dual_interpolation_is_optimal_when_one_primal_works_at_both_ends() -> None:
    # min δ x1 + (1-δ) x2, x1+x2=1, x>=0; both endpoints use x=(1,0).
    a, b, delta = 0.0, 0.4, 0.2
    theta = (delta - a) / (b - a)
    primal = np.array([1.0, 0.0])
    pi_a, pi_b = a, b
    z_a, z_b = np.array([0.0, 1.0]), np.array([0.0, 0.2])
    pi = (1 - theta) * pi_a + theta * pi_b
    z = (1 - theta) * z_a + theta * z_b
    c = np.array([delta, 1 - delta])
    np.testing.assert_allclose(c, np.ones(2) * pi + z)
    assert np.all(z >= 0)
    assert c @ primal == pytest.approx(pi)
    assert np.dot(z, primal) == pytest.approx(0.0)
