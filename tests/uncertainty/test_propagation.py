"""Tests for the GUM clause-5 LPU with covariance (REQ-41, DD-14).

Known analytic cases plus the Hypothesis properties required by
REQ-77: variance additivity under independence, correctness under
known correlated inputs, and dimensional consistency.
"""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

import itaca as itc
from itaca.core.errors import UncertaintyError
from itaca.core.uncframe import standard_uncertainty
from itaca.core.varframe import VarFrame

_u = st.floats(min_value=0.01, max_value=10.0)


def _frame(a: float = 3.0, b: float = 4.0) -> VarFrame:
    arr = np.column_stack([[a], [b]])
    return itc.load(arr, names=["a", "b"])


class TestKnownCases:
    def test_sum_independent(self) -> None:
        db = _frame().set_uncertainty({"a": 3.0, "b": 4.0})
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["f"][0] == pytest.approx(5.0)

    def test_sum_fully_correlated(self) -> None:
        db = (
            _frame()
            .set_uncertainty({"a": 3.0, "b": 4.0})
            .set_correlation({("a", "b"): 1.0})
        )
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["f"][0] == pytest.approx(7.0)

    def test_difference_anticorrelated(self) -> None:
        db = (
            _frame()
            .set_uncertainty({"a": 3.0, "b": 4.0})
            .set_correlation({("a", "b"): -1.0})
        )
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["f"][0] == pytest.approx(1.0)

    def test_product_relative(self) -> None:
        db = _frame(a=2.0, b=5.0).set_uncertainty({"a": 0.2, "b": 0.25})
        result = db.compute("f = a * b")
        assert result.uncertainty is not None
        expected = 10.0 * np.sqrt((0.2 / 2.0) ** 2 + (0.25 / 5.0) ** 2)
        assert result.uncertainty.systematic["f"][0] == pytest.approx(expected)

    def test_components_propagate_separately(self) -> None:
        # DD-19: systematic and random never mix during propagation.
        db = (
            _frame()
            .set_uncertainty({"a": 3.0})
            .set_uncertainty({"b": 4.0}, component="random")
        )
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["f"][0] == pytest.approx(3.0)
        assert result.uncertainty.random["f"][0] == pytest.approx(4.0)
        assert result.uncertainty.combined("f")[0] == pytest.approx(5.0)

    def test_the_declared_coefficient_applies_to_the_random_component_too(
        self,
    ) -> None:
        """OQ-23: one declared r(a, b) governs BOTH components.

        Every other correlated case here asserts on `systematic` alone,
        so restricting the covariance term to that component would have
        left the suite green while contradicting the rule stated in
        `propagation.py` and in SRS Section 4.2. This is the half that
        was unverified.
        """
        db = (
            _frame()
            .set_uncertainty({"a": 3.0, "b": 4.0}, component="random")
            .set_correlation({("a", "b"): 0.5})
        )
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        expected = np.sqrt(3.0**2 + 4.0**2 + 2 * 0.5 * 3.0 * 4.0)
        assert result.uncertainty.random["f"][0] == pytest.approx(expected)
        assert not result.uncertainty.systematic


class TestProperties:
    @given(_u, _u)
    def test_variance_additivity_under_independence(self, ua: float, ub: float) -> None:
        db = _frame().set_uncertainty({"a": ua, "b": ub})
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        combined = float(result.uncertainty.systematic["f"][0])
        assert combined**2 == pytest.approx(ua**2 + ub**2, rel=1e-9)

    @given(_u, st.floats(min_value=-1.0, max_value=1.0))
    def test_known_correlated_inputs(self, ua: float, r: float) -> None:
        db = (
            _frame()
            .set_uncertainty({"a": ua, "b": ua})
            .set_correlation({("a", "b"): r})
        )
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        expected = ua * np.sqrt(max(0.0, 2.0 + 2.0 * r))
        # abs tolerance: near r = -1 the variance suffers catastrophic
        # cancellation (ua^2 * (2 + 2r) -> 0), so machine-epsilon noise
        # of order eps * ua^2 enters before the square root.
        assert float(result.uncertainty.systematic["f"][0]) == pytest.approx(
            expected, rel=1e-7, abs=1e-6
        )

    @given(_u, st.floats(min_value=0.1, max_value=50.0))
    def test_dimensional_consistency_under_scaling(
        self, ua: float, scale: float
    ) -> None:
        db = _frame().set_uncertainty({"a": ua})
        result = db.compute(f"f = {scale} * a")
        assert result.uncertainty is not None
        assert float(result.uncertainty.systematic["f"][0]) == pytest.approx(
            scale * ua, rel=1e-9
        )


class TestNegativeVarianceMateriality:
    """REV-001 ITACA-001b: a rounding residual and an impossible
    covariance are different things, and clamping both reported an
    invalid covariance structure as certainty."""

    def test_itaca_001_material_negative_variance_raises_and_rounding_residual_clamps(
        self,
    ) -> None:
        """Unit-test the helper directly.

        After the ITACA-001a fix the -0.9 triple can no longer reach
        propagate at all, because CorrelationMatrix refuses it at
        declaration time. The variance it used to produce is therefore
        exercised here against the helper rather than through the
        public path that can no longer construct it.
        """
        with pytest.raises(UncertaintyError) as excinfo:
            standard_uncertainty(
                np.array([-2.4]),
                np.array([3.0]),
                terms=6,
                obj="systematic uncertainty of 's'",
                operation="GUM clause-5 propagation with covariance",
                fix="review the declared correlations (REQ-40)",
            )
        message = str(excinfo.value)
        assert "-2.4" in message
        assert "systematic uncertainty of 's'" in message
        assert "review the declared correlations" in message

        # A rounding-scale residual is still clamped, which is what the
        # clamp was legitimately for.
        residual = standard_uncertainty(
            np.array([-1e-17]),
            np.array([2.0]),
            terms=3,
            obj="u",
            operation="op",
            fix="review the declared correlations",
        )
        assert residual[0] == 0.0

        # NaN passes through, reproducing the previous np.maximum
        # behavior for cells that select masked out.
        blank = standard_uncertainty(
            np.array([np.nan]),
            np.array([np.nan]),
            terms=3,
            obj="u",
            operation="op",
            fix="review the declared correlations",
        )
        assert np.isnan(blank[0])

    def test_itaca_001_perfect_anticorrelation_still_clamps_not_raises(self) -> None:
        """r = -1 with equal u is exact cancellation, not a defect.

        Note that test_difference_anticorrelated above is NOT this
        case: with u_a = 3 and u_b = 4 the sum is 9 + 16 - 24 = 1. The
        cancellation needs u_a == u_b, which only this test and the
        Hypothesis property below draw. This pins the materiality
        threshold against a regression that would make it too tight.
        """
        db = _frame().set_uncertainty({"a": 3.0, "b": 3.0})
        db = db.set_correlation({("a", "b"): -1.0})
        result = db.compute("f = a + b")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["f"][0] == pytest.approx(0.0, abs=1e-9)
