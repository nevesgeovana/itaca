"""Property-based tests for the B1 math kernels (REQ-77).

Covers the propagation engine (the reduction and interpolation weight
rules of REQ-98/REQ-99) and the interpolation operators' partition of
unity, which the example-based op tests exercise only at single points.
"""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from itaca.ops._interp_kernels import (
    cubic_matrix,
    linear_matrix,
    nearest_matrix,
    polyfit_matrix,
)
from itaca.ops._reduction import (
    reduce_random,
    reduce_systematic,
    trapezoid_weights,
)

_finite = st.floats(
    min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False
)


class TestReductionRules:
    # REQ-98/REQ-99: the systematic component is the absolute weighted
    # sum (fully correlated), the random component the root sum of the
    # squared weighted terms (independent points).
    @given(
        weights=st.lists(_finite, min_size=1, max_size=8),
        unc=st.lists(
            st.floats(min_value=0.0, max_value=1e3, allow_nan=False),
            min_size=1,
            max_size=8,
        ),
    )
    def test_systematic_is_absolute_weighted_sum(
        self, weights: list[float], unc: list[float]
    ) -> None:
        n = min(len(weights), len(unc))
        w = np.array(weights[:n])
        u = np.array(unc[:n])
        got = reduce_systematic(w, u, -1)
        assert got == np.abs(np.sum(w * u)) or np.isclose(got, abs(np.sum(w * u)))
        assert got >= -1e-12

    @given(
        weights=st.lists(_finite, min_size=1, max_size=8),
        unc=st.lists(
            st.floats(min_value=0.0, max_value=1e3, allow_nan=False),
            min_size=1,
            max_size=8,
        ),
    )
    def test_random_is_root_sum_of_squares(
        self, weights: list[float], unc: list[float]
    ) -> None:
        n = min(len(weights), len(unc))
        w = np.array(weights[:n])
        u = np.array(unc[:n])
        got = reduce_random(w, u, -1)
        assert np.isclose(got**2, np.sum(np.square(w * u)))

    @given(
        n=st.integers(min_value=1, max_value=20),
        sigma=st.floats(min_value=1e-3, max_value=1e3, allow_nan=False),
    )
    def test_uniform_mean_gains_one_over_sqrt_n(self, n: int, sigma: float) -> None:
        # A mean over N independent equal-uncertainty points reduces the
        # random component by exactly 1/sqrt(N).
        w = np.full(n, 1.0 / n)
        u = np.full(n, sigma)
        assert np.isclose(reduce_random(w, u, -1), sigma / np.sqrt(n))
        # Fully correlated: the mean of a common bias keeps its size.
        assert np.isclose(reduce_systematic(w, u, -1), sigma)


class TestInterpolationPartitionOfUnity:
    # An interpolating operator reproduces a constant field exactly:
    # each weight row sums to 1 for targets inside the hull.
    @given(
        knots=st.integers(min_value=2, max_value=8),
        offset=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_linear_rows_sum_to_one(self, knots: int, offset: float) -> None:
        x = np.arange(float(knots))
        targets = np.array([offset, knots - 1 - offset])
        rows = linear_matrix(x, targets).sum(axis=1)
        assert np.allclose(rows, 1.0)

    @given(
        knots=st.integers(min_value=3, max_value=8),
        offset=st.floats(min_value=0.05, max_value=0.95),
    )
    def test_cubic_rows_sum_to_one(self, knots: int, offset: float) -> None:
        x = np.arange(float(knots))
        targets = np.array([offset, knots - 1 - offset])
        rows = cubic_matrix(x, targets).sum(axis=1)
        assert np.allclose(rows, 1.0, atol=1e-8)

    @given(knots=st.integers(min_value=2, max_value=8))
    def test_nearest_rows_sum_to_one(self, knots: int) -> None:
        x = np.arange(float(knots))
        targets = x + 0.1
        rows = nearest_matrix(x, targets).sum(axis=1)
        assert np.allclose(rows, 1.0)

    @given(
        knots=st.integers(min_value=3, max_value=8),
        deg=st.integers(min_value=1, max_value=2),
    )
    def test_polyfit_reproduces_constant(self, knots: int, deg: int) -> None:
        x = np.arange(float(knots))
        targets = np.array([0.3, knots - 1.3])
        rows = polyfit_matrix(x, targets, deg).sum(axis=1)
        assert np.allclose(rows, 1.0, atol=1e-8)


class TestInterpolationReproducesNodes:
    # W @ y at the nodes returns y for every method (exact interpolation
    # at the sample points).
    @given(
        values=st.lists(_finite, min_size=3, max_size=8),
    )
    def test_cubic_reproduces_node_values(self, values: list[float]) -> None:
        y = np.array(values)
        x = np.arange(float(y.size))
        weights = cubic_matrix(x, x)
        assert np.allclose(weights @ y, y, atol=1e-6)

    @given(values=st.lists(_finite, min_size=2, max_size=8))
    def test_linear_reproduces_node_values(self, values: list[float]) -> None:
        y = np.array(values)
        x = np.arange(float(y.size))
        assert np.allclose(linear_matrix(x, x) @ y, y)


class TestTrapezoidWeights:
    @given(
        coords=st.lists(
            st.floats(min_value=-100.0, max_value=100.0, allow_nan=False),
            min_size=2,
            max_size=12,
            unique=True,
        )
    )
    def test_weights_sum_to_interval_length(self, coords: list[float]) -> None:
        x = np.sort(np.array(coords))
        # The trapezoid weights of a unit integrand give the interval
        # length (exact quadrature of a constant).
        assert np.isclose(trapezoid_weights(x).sum(), x[-1] - x[0])
