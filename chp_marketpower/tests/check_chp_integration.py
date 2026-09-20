"""Run explicitly with a valid COPT license: python tests/check_chp_integration.py."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import controlled_case, solve_chp  # noqa: E402
from price_vulnerability import apply_generator_markup, hourly_sensitivity, scalar_sensitivity  # noqa: E402
from price_vulnerability.diagnostics import pricing_mechanism_diagnostics  # noqa: E402
from strategic_market_simulation.profit_sweep import profit_at_markup  # noqa: E402


def main() -> None:
    generators, network = controlled_case("6", "C0", T=3, segments=3)
    base = solve_chp(generators, network)
    ones = solve_chp(generators, network, np.ones((len(generators), network.T)))
    assert base.solver_status == ones.solver_status == "optimal"
    assert np.allclose(base.lmp, ones.lmp, atol=1e-6)
    assert np.isclose(base.objective, ones.objective, atol=1e-6)

    multipliers = np.ones((len(generators), network.T))
    multipliers[1] = 1.01
    by_array = solve_chp(generators, network, multipliers)
    by_copy = solve_chp(apply_generator_markup(generators, 1, 0.01), network)
    assert np.allclose(by_array.lmp, by_copy.lmp, atol=1e-5)
    assert np.isclose(by_array.objective, by_copy.objective, atol=1e-5)

    adders = np.zeros((len(generators), network.T))
    adders[1] = 0.2
    by_adder = solve_chp(generators, network, bid_adders=adders)
    copied = deepcopy(generators)
    copied[1].cost_var += 0.2
    copied[1].pwl_slopes = [s + 0.2 for s in copied[1].pwl_slopes]
    by_copy_adder = solve_chp(copied, network)
    assert np.allclose(by_adder.lmp, by_copy_adder.lmp, atol=1e-5)
    assert np.isclose(by_adder.objective, by_copy_adder.objective, atol=1e-5)
    absolute_scalar = scalar_sensitivity(generators, network, 1, 0.1, "absolute")
    assert np.all(np.isfinite(absolute_scalar.derivative))

    J, _, _, _ = hourly_sensitivity(generators, network, 1, 1, 0.01)
    assert np.max(np.abs(J[:, [0, 2]])) < 1e-4
    J_abs, _, _, _ = hourly_sensitivity(generators, network, 1, 1, 0.1, "absolute")
    assert np.max(np.abs(J_abs[:, [0, 2]])) < 1e-4
    profit = profit_at_markup(generators, network, 1, 0.02)
    assert np.isclose(
        profit["true_profit"],
        profit["energy_revenue"] + profit["reported_uplift"] - profit["true_cost"],
    )
    assert profit["reported_cost"] >= profit["true_cost"]

    loose_g, loose_n = controlled_case("6", "C2N", T=24, segments=3)
    tight_g, tight_n = controlled_case("6", "C3", T=24, segments=3)
    assert np.allclose(loose_n.PTDF, tight_n.PTDF)
    assert np.allclose(loose_n.demand, tight_n.demand)
    assert np.all(loose_n.F_max >= tight_n.F_max)
    loose = pricing_mechanism_diagnostics(loose_g, loose_n)
    tight = pricing_mechanism_diagnostics(tight_g, tight_n)
    assert not any(row["price_setting"] for row in loose["lines"])
    assert any(row["price_setting"] and row["binding"] for row in tight["lines"])
    print("CHP integration checks passed")


if __name__ == "__main__":
    main()
