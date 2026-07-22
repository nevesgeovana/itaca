"""Property-based tests for the expression operators (REQ-44, REQ-77).

Every operator exposes ``evaluate`` plus analytical partials ``d_da``
(and ``d_db`` for binary operators). Hypothesis verifies the partials
against central finite differences on randomized inputs inside each
operator's domain (DD-20).
"""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from itaca.uncertainty.operators import BINARY, UNARY

_H = 1e-6
_TOL = 1e-4

_safe = st.floats(min_value=-30.0, max_value=30.0, allow_nan=False)
_positive = st.floats(min_value=0.1, max_value=30.0)
_unit_open = st.floats(min_value=-0.9, max_value=0.9)
_nonzero = _safe.filter(lambda v: abs(v) > 0.1)

_UNARY_DOMAINS = {
    "neg": _safe,
    "sin": _safe,
    "cos": _safe,
    "tan": _safe.filter(lambda v: abs(np.cos(v)) > 0.1),
    "asin": _unit_open,
    "acos": _unit_open,
    "atan": _safe,
    "sqrt": _positive,
    "abs": _nonzero,
    "log": _positive,
    "log10": _positive,
    "exp": st.floats(min_value=-10.0, max_value=10.0),
}

_BINARY_DOMAINS = {
    "add": (_safe, _safe),
    "sub": (_safe, _safe),
    "mul": (_safe, _safe),
    "div": (_safe, _nonzero),
    "pow": (_positive, st.floats(min_value=-3.0, max_value=3.0)),
    "atan2": (_nonzero, _nonzero),
}


def test_required_operator_coverage() -> None:
    # REQ-44: the complete operator list.
    assert set(_UNARY_DOMAINS) == set(UNARY)
    assert set(_BINARY_DOMAINS) == set(BINARY)


@pytest.mark.parametrize("name", sorted(_UNARY_DOMAINS))
def test_unary_partial_matches_finite_difference(name: str) -> None:
    operator = UNARY[name]
    domain = _UNARY_DOMAINS[name]

    @given(domain)
    def check(a: float) -> None:
        value = np.asarray(a)
        analytic = float(operator.d_da(value))
        numeric = float(
            (operator.evaluate(value + _H) - operator.evaluate(value - _H)) / (2 * _H)
        )
        assert analytic == pytest.approx(numeric, rel=_TOL, abs=1e-5)

    check()


@pytest.mark.parametrize("name", sorted(_BINARY_DOMAINS))
def test_binary_partials_match_finite_differences(name: str) -> None:
    operator = BINARY[name]
    domain_a, domain_b = _BINARY_DOMAINS[name]

    @given(domain_a, domain_b)
    def check(a: float, b: float) -> None:
        va, vb = np.asarray(a), np.asarray(b)
        analytic_a = float(operator.d_da(va, vb))
        analytic_b = float(operator.d_db(va, vb))
        numeric_a = float(
            (operator.evaluate(va + _H, vb) - operator.evaluate(va - _H, vb)) / (2 * _H)
        )
        numeric_b = float(
            (operator.evaluate(va, vb + _H) - operator.evaluate(va, vb - _H)) / (2 * _H)
        )
        assert analytic_a == pytest.approx(numeric_a, rel=_TOL, abs=1e-5)
        assert analytic_b == pytest.approx(numeric_b, rel=_TOL, abs=1e-5)

    check()


def test_operators_evaluate_vectorized() -> None:
    # REQ-88: operators act elementwise on arrays.
    values = np.array([0.5, 1.0, 2.0])
    assert np.allclose(UNARY["sqrt"].evaluate(values), np.sqrt(values))
    assert np.allclose(BINARY["mul"].evaluate(values, values), np.square(values))
