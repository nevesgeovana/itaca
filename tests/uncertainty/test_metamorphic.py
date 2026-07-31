"""Metamorphic invariants for the UQ engine (BRF-059, gap C).

A metamorphic test states a relation between the outputs of two runs
instead of naming an expected number, so it needs no oracle and no
hand-computed reference. That is what makes it able to find what line
coverage cannot: the engine executed every line of ``propagation.py`` on
the way to a 3.6x overstatement, because coverage asks whether a line
RAN and a metamorphic relation asks whether the answer is CONSISTENT
with another answer the same engine gave.

Two families here, and the second is the one that would have caught
FND-058, FND-074 and FND-088 on the day they were written:

* **Self-cancellation.** ``f(x) - f(x)`` is identically zero for every
  ``f`` and every ``x``, so its uncertainty is exactly zero. No
  reference value is needed to know that.
* **Route equivalence.** Two ways of computing the same quantity must
  agree. After SEAT-UNC the relation is weaker by design and still
  binding: the composed route either AGREES with the direct route or
  REFUSES. What it may never do is return a different number quietly,
  and that disjunction is exactly the contract the interim refusal
  claims to provide.
"""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import itaca as itc
from itaca.core.errors import UncertaintyLineageError
from itaca.core.varframe import VarFrame

_value = st.floats(min_value=0.5, max_value=50.0, allow_nan=False, allow_infinity=False)
_sigma = st.floats(min_value=1e-4, max_value=2.0, allow_nan=False, allow_infinity=False)
_gain = st.floats(
    min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False
)


def _frame(x: float, u: float, component: str = "systematic") -> VarFrame:
    arr = np.column_stack([np.array([x])])
    frame = itc.load(arr, names=["x"])
    return frame.set_uncertainty({"x": u}, component=component)


def _u(db: VarFrame, name: str, component: str = "systematic") -> float:
    table = getattr(db.uncertainty, component)
    return float(table[name][0])


class TestSelfCancellation:
    """f(x) - f(x) is exactly zero, so u of it is exactly zero."""

    @pytest.mark.parametrize(
        "expression", ["x", "3*x", "x**2", "sqrt(x)", "log(x)", "exp(x)", "sin(x)"]
    )
    @given(x=_value, u=_sigma)
    @settings(max_examples=25, deadline=None)
    def test_difference_with_itself_has_zero_uncertainty(
        self, expression: str, x: float, u: float
    ) -> None:
        db = _frame(x, u)
        got = _u(db.compute(f"y = ({expression}) - ({expression})"), "y")
        assert got == pytest.approx(0.0, abs=1e-12)

    @given(x=_value, u=_sigma)
    @settings(max_examples=25, deadline=None)
    def test_ratio_with_itself_has_zero_uncertainty(self, x: float, u: float) -> None:
        db = _frame(x, u)
        assert _u(db.compute("y = (3*x) / (3*x)"), "y") == pytest.approx(0.0, abs=1e-12)


class TestLinearScaling:
    """u(k*x) = |k| * u(x), for every k and every x."""

    @given(x=_value, u=_sigma, k=_gain)
    @settings(max_examples=40, deadline=None)
    def test_gain_scales_the_uncertainty(self, x: float, u: float, k: float) -> None:
        db = _frame(x, u)
        got = _u(db.compute(f"y = {k!r} * x"), "y")
        assert got == pytest.approx(abs(k) * u, rel=1e-9, abs=1e-15)

    @given(x=_value, u=_sigma, c=_gain)
    @settings(max_examples=40, deadline=None)
    def test_an_added_constant_does_not_change_the_uncertainty(
        self, x: float, u: float, c: float
    ) -> None:
        db = _frame(x, u)
        assert _u(db.compute(f"y = x + {c!r}"), "y") == pytest.approx(u, rel=1e-9)

    @given(x=_value, u=_sigma, k=_gain)
    @settings(max_examples=40, deadline=None)
    def test_both_components_scale_alike(self, x: float, u: float, k: float) -> None:
        # REQ-99 keeps the two components separate; neither may leak into
        # the other, and each obeys the same linear rule on its own.
        db = _frame(x, u, component="random")
        derived = db.compute(f"y = {k!r} * x")
        assert _u(derived, "y", "random") == pytest.approx(
            abs(k) * u, rel=1e-9, abs=1e-15
        )
        assert not derived.uncertainty.systematic


class TestRouteEquivalence:
    """The composed route agrees with the direct route, or it refuses.

    This is the relation that FND-058, FND-074 and FND-088 all violated,
    each in a different operation, and it is stated once here over the
    operation that carries the others.
    """

    @given(x=_value, u=_sigma, a=_gain, b=_gain)
    @settings(max_examples=60, deadline=None)
    def test_stepwise_agrees_with_direct_or_refuses(
        self, x: float, u: float, a: float, b: float
    ) -> None:
        db = _frame(x, u)
        direct = _u(db.compute(f"r = {a!r}*x - {b!r}*x"), "r")
        composed = db.compute(f"p = {a!r}*x").compute(f"q = {b!r}*x")
        refused = False
        stepwise = float("nan")
        try:
            stepwise = _u(composed.compute("r = p - q"), "r")
        except UncertaintyLineageError:
            refused = True
        if not refused:
            assert stepwise == pytest.approx(direct, rel=1e-9, abs=1e-15)
        # Which branch was taken is asserted too, so this relation cannot
        # pass vacuously. p and q share the root x on EVERY example, so
        # the refusal is the branch that must fire; a run that silently
        # took neither would otherwise look like a pass. Remove the
        # refusal and the agreement assertion above runs and fails, which
        # is how this relation catches FND-058 rather than merely
        # tolerating it.
        assert refused

    @given(x=_value, u=_sigma, a=_gain)
    @settings(max_examples=40, deadline=None)
    def test_a_single_carrier_composition_is_exact_either_way(
        self, x: float, u: float, a: float
    ) -> None:
        # Only ONE derived variable enters the second expression, so no
        # covariance term is missing and the composed route must agree
        # rather than refuse. This is the half of the space the refusal
        # must leave alone, and it is asserted rather than assumed.
        db = _frame(x, u)
        direct = _u(db.compute(f"r = ({a!r}*x) * 2"), "r")
        stepwise = _u(db.compute(f"p = {a!r}*x").compute("r = p * 2"), "r")
        assert stepwise == pytest.approx(direct, rel=1e-9, abs=1e-15)

    @given(x=_value, u=_sigma)
    @settings(max_examples=25, deadline=None)
    def test_independent_roots_never_refuse(self, x: float, u: float) -> None:
        # Two roots, no shared ancestry: the refusal must not fire, or it
        # would break every ordinary multi-channel workflow.
        arr = np.column_stack([np.array([x]), np.array([x + 1.0])])
        db = itc.load(arr, names=["a", "b"]).set_uncertainty({"a": u, "b": u})
        composed = db.compute("p = 2*a").compute("q = 3*b")
        result = composed.compute("r = p - q")
        assert _u(result, "r") == pytest.approx(np.hypot(2 * u, 3 * u), rel=1e-9)


class TestReductionInvariants:
    """Relations the REQ-99 reduction rules must satisfy on any data."""

    @given(u=_sigma)
    @settings(max_examples=25, deadline=None)
    def test_averaging_n_identical_random_points_gains_one_over_sqrt_n(
        self, u: float
    ) -> None:
        n = 4
        arr = np.column_stack(
            [np.arange(float(n)), np.full(n, 2.0)],
        )
        db = itc.load(arr, names=["x", "Y"]).pivot(dims=["x"])
        db = db.set_uncertainty({"Y": u}, component="random")
        reduced = db.average(along="x")
        assert _u(reduced, "Y", "random") == pytest.approx(u / np.sqrt(n), rel=1e-9)

    @given(u=_sigma)
    @settings(max_examples=25, deadline=None)
    def test_averaging_systematic_points_keeps_the_magnitude(self, u: float) -> None:
        # Fully correlated across points, so the mean of N of them has the
        # same uncertainty as one. No 1/sqrt(N) gain, ever.
        n = 4
        arr = np.column_stack([np.arange(float(n)), np.full(n, 2.0)])
        db = itc.load(arr, names=["x", "Y"]).pivot(dims=["x"])
        db = db.set_uncertainty({"Y": u})
        assert _u(db.average(along="x"), "Y") == pytest.approx(u, rel=1e-9)
