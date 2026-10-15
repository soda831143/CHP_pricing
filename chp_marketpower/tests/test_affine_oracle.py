"""Solver-free checks of the online selector's boundaries and interpolation."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from price_vulnerability.affine_oracle import query  # noqa: E402


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
