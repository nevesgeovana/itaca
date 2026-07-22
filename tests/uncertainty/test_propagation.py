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
        assert float(result.uncertainty.systematic["f"][0]) == pytest.approx(
            expected, rel=1e-9, abs=1e-12
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
