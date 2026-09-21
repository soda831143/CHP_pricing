"""Small solver-free checks for the market-power MVP."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine import PrimalCHPLP, controlled_case, load_case  # noqa: E402
from price_vulnerability import (  # noqa: E402
    apply_generator_markup, central_difference, epsilon_stability, regime_differences,
    reconstruct_value_regimes, scalar_sensitivity, ValuePoint, vulnerability_metrics,
)


def test_scalar_markup_is_immutable() -> None:
    generators, _ = load_case("6", "single", T=6, segments=3)
    base_cost = generators[0].cost_var
    base_slopes = list(generators[0].pwl_slopes)
    changed = apply_generator_markup(generators, generator_index=0, beta=0.1)

    assert generators[0].cost_var == base_cost
    assert generators[0].pwl_slopes == base_slopes
    assert changed[0] is not generators[0]
    assert np.isclose(changed[0].cost_var, 1.1 * base_cost)
    assert np.allclose(changed[0].pwl_slopes, 1.1 * np.asarray(base_slopes))
    assert changed[1].cost_var == generators[1].cost_var


def test_central_difference() -> None:
    plus = np.array([[3.0, 7.0]])
    minus = np.array([[1.0, 3.0]])
    assert np.allclose(central_difference(plus, minus, 0.5), [[2.0, 4.0]])


def test_regime_differences_detects_piecewise_affine_kink() -> None:
    grid = np.array([0.0, 0.1, 0.2, 0.3])
    prices = np.array([0.0, 0.1, 0.3, 0.5])[:, None, None]
    objectives = np.array([0.0, 1.0, 3.0, 5.0])
    _, _, price_jumps, objective_jumps, candidates = regime_differences(
        grid, prices, objectives, absolute_tolerance=1e-10, relative_tolerance=1e-10
    )

    assert price_jumps == pytest.approx([1.0, 0.0])
    assert objective_jumps == pytest.approx([10.0, 0.0])
    assert candidates.tolist() == [True, False]


def test_metrics_distinguish_common_energy_from_congestion() -> None:
    energy = np.eye(3)
    uniform = np.broadcast_to(energy, (6, 3, 3))
    metrics = vulnerability_metrics(uniform, energy)
    assert metrics["temporal_spillover"] == 0
    assert metrics["congestion_share"] == 0
    assert metrics["spatial_dispersion_share"] == 0
    assert np.isclose(metrics["vulnerability"], np.sqrt(6))
    assert np.isclose(metrics["vulnerability_bus_normalized"], 1)

    local = uniform.copy()
    local[1, 2, 0] = 5
    metrics = vulnerability_metrics(local, energy)
    assert metrics["temporal_spillover"] > 0
    assert metrics["congestion_share"] > 0
    assert metrics["spatial_dispersion_share"] > 0


def test_controlled_case_removes_coupling_in_c0() -> None:
    generators, _ = controlled_case("6", "C0", T=6, segments=3)
    assert all(g.T_on_min == g.T_off_min == 1 for g in generators)
    assert all(g.cost_su == g.cost_sd == 0 for g in generators)
    assert all(g.R_up == g.P_max for g in generators)


def test_network_pair_only_changes_line_limits() -> None:
    free_g, free = controlled_case("6", "C2N", T=6, segments=3)
    tight_g, tight = controlled_case("6", "C3", T=6, segments=3)
    assert np.array_equal(free.demand, tight.demand)
    assert np.array_equal(free.PTDF, tight.PTDF)
    assert np.array_equal(free.PTDF_Gen, tight.PTDF_Gen)
    assert np.all(free.F_max >= tight.F_max)
    assert [(g.R_up, g.R_down, g.cost_su) for g in free_g] == [
        (g.R_up, g.R_down, g.cost_su) for g in tight_g
    ]


def test_load_scale_preserves_network_pair() -> None:
    _, base = controlled_case("6", "C3", T=6, segments=3)
    _, free = controlled_case("6", "C2N", T=6, segments=3, load_scale=1.02)
    _, tight = controlled_case("6", "C3", T=6, segments=3, load_scale=1.02)
    assert np.allclose(free.demand, base.demand * 1.02)
    assert np.array_equal(free.demand, tight.demand)
    assert np.array_equal(free.PTDF, tight.PTDF)
    assert np.array_equal(free.PTDF_Gen, tight.PTDF_Gen)
    assert np.all(free.F_max >= tight.F_max)
    with pytest.raises(ValueError, match="load_scale"):
        controlled_case("6", "C3", T=6, segments=3, load_scale=0)


def test_load_shift_preserves_hourly_total_and_network() -> None:
    _, base = controlled_case("30", "C3", T=6, segments=3)
    _, shifted = controlled_case("30", "C3", T=6, segments=3, load_shift=(23, 21, 0.05))
    moved = 0.05 * base.demand[22]
    assert np.allclose(shifted.sys_demand, base.sys_demand)
    assert np.allclose(shifted.demand[22], base.demand[22] - moved)
    assert np.allclose(shifted.demand[20], base.demand[20] + moved)
    assert np.array_equal(shifted.PTDF, base.PTDF)
    assert np.array_equal(shifted.F_max, base.F_max)
    with pytest.raises(ValueError, match="PTDF"):
        load_case("30", "single", T=6, segments=3, load_shift=(23, 21, 0.05))


def test_epsilon_stability_flags_regime_switch() -> None:
    stable, _ = epsilon_stability([np.array([2.0]), np.array([2.01])], 0.0, [0.01, 0.005])
    unstable, _ = epsilon_stability([np.array([2.0]), np.array([0.1])], 0.0, [0.01, 0.005])
    assert stable == "stable"
    assert unstable == "critical_or_degenerate"
    unchecked, _ = epsilon_stability([np.array([2.0])], 0.0, [0.01])
    assert unchecked == "not_checked"
    changing, _ = epsilon_stability(
        [np.array([100.0, 1.0]), np.array([100.0, 0.0])], 0.0, [0.01, 0.005]
    )
    assert changing == "critical_or_degenerate"


def test_hourly_bid_multiplier_validation() -> None:
    generators, network = load_case("6", "single", T=3, segments=3)
    with pytest.raises(ValueError, match="shape"):
        PrimalCHPLP(generators, network, bid_multipliers=np.ones((len(generators), 2)))
    invalid = np.ones((len(generators), network.T))
    invalid[0, 0] = 0.0
    with pytest.raises(ValueError, match="positive"):
        PrimalCHPLP(generators, network, bid_multipliers=invalid)
    with pytest.raises(IndexError, match="generator_index"):
        scalar_sensitivity(generators, network, -1, 0.1, "absolute")
    with pytest.raises(ValueError, match="COPT method"):
        PrimalCHPLP(generators, network, method=0)


def test_value_oracle_finds_hidden_support_lines() -> None:
    lines = [(0.0, 3.0), (0.5, 2.0), (1.3, 1.0)]

    def solve(delta: float) -> ValuePoint:
        values = np.array([intercept + slope * delta for intercept, slope in lines])
        value = float(np.min(values))
        active = [slope for (intercept, slope), result in zip(lines, values) if abs(result - value) < 1e-9]
        return ValuePoint(delta, value, active[0], min(active), max(active))

    regimes, points = reconstruct_value_regimes(solve, 0.0, 1.0)
    assert len(points) >= 3
    assert np.allclose([(item.left, item.right, item.slope) for item in regimes], [
        (0.0, 0.5, 3.0),
        (0.5, 0.8, 2.0),
        (0.8, 1.0, 1.0),
    ])


def test_value_oracle_does_not_scale_tolerance_by_total_cost() -> None:
    lines = [(50_000.0, 3.0), (50_000.499, 2.0), (50_001.0, 1.0)]

    def solve(delta: float) -> ValuePoint:
        values = np.array([intercept + slope * delta for intercept, slope in lines])
        value = float(np.min(values))
        active = [slope for (_, slope), result in zip(lines, values) if abs(result - value) < 1e-9]
        return ValuePoint(delta, value, active[0], min(active), max(active))

    regimes, _ = reconstruct_value_regimes(solve, 0.0, 1.0)
    assert np.allclose([(item.left, item.right, item.slope) for item in regimes], [
        (0.0, 0.499, 3.0),
        (0.499, 0.501, 2.0),
        (0.501, 1.0, 1.0),
    ])


if __name__ == "__main__":
    test_scalar_markup_is_immutable()
    test_central_difference()
    test_regime_differences_detects_piecewise_affine_kink()
    test_metrics_distinguish_common_energy_from_congestion()
    test_controlled_case_removes_coupling_in_c0()
    test_network_pair_only_changes_line_limits()
    test_load_shift_preserves_hourly_total_and_network()
    test_epsilon_stability_flags_regime_switch()
    test_hourly_bid_multiplier_validation()
    print("scalar-markup checks passed")
