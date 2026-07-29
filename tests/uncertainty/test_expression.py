"""Tests for the ast-based expression engine (REQ-44, DD-20, REQ-36)."""

import numpy as np
import pytest

from itaca.core.errors import (
    DataError,
    UncertaintyCompatibilityError,
    VariableNotFoundError,
)
from itaca.uncertainty.expression import parse_expression

ENV = {
    "a": np.array([1.0, 2.0, 3.0]),
    "b": np.array([2.0, 2.0, 2.0]),
}
KNOWN = set(ENV)


class TestEvaluation:
    def test_arithmetic_and_precedence(self) -> None:
        tree = parse_expression("a + b * a ** 2", KNOWN)
        assert np.allclose(tree.evaluate(ENV), [3.0, 10.0, 21.0])

    def test_functions_and_constants(self) -> None:
        tree = parse_expression("sqrt(a) * cos(0.0) + pi - pi", KNOWN)
        assert np.allclose(tree.evaluate(ENV), np.sqrt(ENV["a"]))

    def test_unary_minus(self) -> None:
        tree = parse_expression("-a + b", KNOWN)
        assert np.allclose(tree.evaluate(ENV), [1.0, 0.0, -1.0])

    def test_atan2_two_arguments(self) -> None:
        tree = parse_expression("atan2(a, b)", KNOWN)
        assert np.allclose(tree.evaluate(ENV), np.arctan2(ENV["a"], ENV["b"]))

    def test_numpy_differentiable_normalized(self) -> None:
        # REQ-36: np.sin and friends are normalized to native operators.
        tree = parse_expression("np.sin(a) + np.sqrt(b)", KNOWN)
        assert np.allclose(tree.evaluate(ENV), np.sin(ENV["a"]) + np.sqrt(ENV["b"]))
        assert np.isfinite(tree.derivative(ENV, "a")).all()

    def test_numpy_generic_allowed_without_uncertainty(self) -> None:
        tree = parse_expression("np.round(a / b)", KNOWN)
        assert np.allclose(tree.evaluate(ENV), np.round(ENV["a"] / ENV["b"]))

    def test_variables_reported(self) -> None:
        tree = parse_expression("a * 2 + 1", KNOWN)
        assert tree.variables() == {"a"}


class TestDerivatives:
    def test_chain_rule(self) -> None:
        tree = parse_expression("sqrt(a * b)", KNOWN)
        expected = ENV["b"] / (2 * np.sqrt(ENV["a"] * ENV["b"]))
        assert np.allclose(tree.derivative(ENV, "a"), expected)

    def test_derivative_of_absent_variable_is_zero(self) -> None:
        tree = parse_expression("a * 2", KNOWN)
        assert np.allclose(tree.derivative(ENV, "b"), 0.0)

    def test_non_differentiable_numpy_raises(self) -> None:
        # REQ-36: np.round under differentiation fails loud.
        tree = parse_expression("np.round(a)", KNOWN)
        with pytest.raises(UncertaintyCompatibilityError):
            tree.derivative(ENV, "a")


class TestErrors:
    def test_syntax_error(self) -> None:
        with pytest.raises(DataError):
            parse_expression("a +* b", KNOWN)

    def test_undefined_variable(self) -> None:
        with pytest.raises(VariableNotFoundError):
            parse_expression("a + missing", KNOWN)

    def test_unknown_function(self) -> None:
        with pytest.raises(DataError):
            parse_expression("mystery(a)", KNOWN)

    def test_unknown_numpy_attribute(self) -> None:
        with pytest.raises(DataError):
            parse_expression("np.definitely_not_a_function(a)", KNOWN)

    def test_wrong_arity(self) -> None:
        with pytest.raises(DataError):
            parse_expression("sin(a, b)", KNOWN)


class TestKeywordArgumentsRefused:
    """REV-001 ITACA-023: keywords parsed, then dropped at execution.

    `np.round(x, decimals=2)` on `[1.234, 2.345]` returned `[1., 2.]`
    instead of `[1.23, 2.35]`. Worse than a wrong number: History
    recorded the expression WITH the keyword, so the provenance showed
    an intent the execution did not honor.

    The author chose refusal over implementation. The admission gate is
    the whole NumPy namespace rather than an allowlist, and `out=`,
    `axis=`, `keepdims=`, `where=` and `dtype=` each break an ITACA
    invariant, so accepting keywords means curating them one function at
    a time. Refusal cannot produce a wrong number; the deferred half is
    registered.
    """

    @pytest.mark.parametrize(
        "text,keyword",
        [
            ("np.round(a, decimals=2)", "decimals="),
            ("np.clip(a, a_min=0.0, a_max=1.0)", "a_min="),
            ("sqrt(a, out=b)", "out="),
        ],
    )
    def test_itaca_023_keyword_argument_is_refused(
        self, text: str, keyword: str
    ) -> None:
        """The message names the function and the offending keyword."""
        with pytest.raises(DataError) as excinfo:
            parse_expression(text, KNOWN)
        message = str(excinfo.value)
        assert keyword in message
        assert "positional" in message

    def test_itaca_023_double_star_form_is_refused_and_named(self) -> None:
        """`**mapping` has `arg is None` and must not render as `None=`."""
        with pytest.raises(DataError) as excinfo:
            parse_expression("np.round(a, **b)", KNOWN)
        assert "'**'" in str(excinfo.value)

    def test_itaca_023_the_refusal_covers_every_call_path(self) -> None:
        """One check at the single funnel, so no sub-path is left open.

        There are three ways a call reaches the tree: a native function,
        an `np.*` name normalized to a native operator, and the generic
        NumpyCall. A per-path check would have to be written three times
        and would be missing from whichever one is added next.
        """
        for text in ("sqrt(a, dtype=b)", "np.sqrt(a, dtype=b)", "np.cumsum(a, axis=b)"):
            with pytest.raises(DataError, match="positional"):
                parse_expression(text, KNOWN)

    def test_itaca_023_positional_calls_still_parse(self) -> None:
        """The refusal is scoped to keywords and nothing else."""
        assert parse_expression("np.round(a)", KNOWN).evaluate(ENV) is not None
        assert parse_expression("atan2(a, b)", KNOWN).evaluate(ENV) is not None

    def test_itaca_023_a_non_callable_numpy_attribute_is_refused(self) -> None:
        """`np.pi(a)` died as a bare TypeError from outside the hierarchy.

        Same one-line-validation shape as the keyword hole, at the same
        funnel: the admission gate tested `hasattr` where it meant
        `callable`. This is also an ITACA-031 instance.
        """
        with pytest.raises(DataError, match="no callable of that name"):
            parse_expression("np.pi(a)", KNOWN)


class TestDeadBranchDerivatives:
    """REV-001 ITACA-022: `0 * nan` is `nan`, not `0`.

    Both derivative walks evaluated every operator partial and
    multiplied by the sub-derivative, so a branch whose derivative was
    exactly zero still contributed `nan` when its partial was
    domain-invalid. `u(x**2)` for a negative base was the reported
    instance; the structural cause is shared with `Unary`, so both are
    fixed together.
    """

    @pytest.mark.parametrize(
        "base,expected",
        [(-2.0, -4.0), (-3.0, -6.0), (0.0, 0.0), (2.0, 4.0)],
    )
    def test_itaca_022_constant_exponent_derivative_is_exact(
        self, base: float, expected: float
    ) -> None:
        """d(x**2)/dx is 2x for every base, including negative and zero.

        Measured before the fix: NaN for a negative base, because
        `a**b * log(a)` is NaN there, and NaN for base zero, because it
        is `-inf` there. Both were multiplied by the exactly zero
        derivative of a constant exponent, which does not recover zero.
        """
        tree = parse_expression("x ** 2", {"x"})
        got = tree.derivative({"x": np.array([base])}, "x")
        assert got[0] == pytest.approx(expected)

    def test_itaca_022_variable_exponent_that_is_not_the_target(self) -> None:
        """The predicate is variable-set membership, not is-a-constant.

        An exponent stored as a VARIABLE poisons the sum identically
        when differentiating with respect to the base, so an
        `isinstance(self.b, Const)` check would have fixed only half the
        finding.
        """
        tree = parse_expression("x ** n", {"x", "n"})
        env = {"x": np.array([-2.0, -3.0]), "n": np.array([2.0, 2.0])}
        assert tree.derivative(env, "x") == pytest.approx([-4.0, -6.0])

    def test_itaca_022_unary_dead_branch_does_not_poison(self) -> None:
        """The same structural cause in `Unary`, isolated.

        `sqrt(b)` differentiated with respect to `a` must be exactly
        zero. Measured before the fix: NaN, because `0.5/sqrt(-4)` is
        NaN and was multiplied by an exactly zero sub-derivative. This
        node is not reachable dead from `compute`, but `derivative` is
        public and the incident rule fixes both instances of one cause.
        """
        tree = parse_expression("sqrt(b)", {"a", "b"})
        assert tree.derivative({"b": np.array([-4.0])}, "a") == pytest.approx(0.0)

    def test_itaca_022_live_exponent_on_a_bad_base_stays_loud(self) -> None:
        """A genuine domain violation must NOT be silenced by the fix.

        When the exponent is live, `d(a**b)/db = a**b * log(a)` really is
        undefined for a base at or below zero. The author's call: refuse
        the whole operation rather than write NaN at the offending
        points, since a NaN uncertainty on a plausible value is the
        silence this finding group is about. The count is in the message
        so the caller can see how local the violation is.
        """
        tree = parse_expression("x ** n", {"x", "n"})
        env = {"x": np.array([-2.0, 3.0]), "n": np.array([2.0, 2.0])}
        with pytest.raises(UncertaintyCompatibilityError) as excinfo:
            tree.derivative(env, "n")
        message = str(excinfo.value)
        assert "1 of 2 point(s)" in message
        assert "x ** n" in message

    def test_itaca_022_live_exponent_on_a_good_base_still_works(self) -> None:
        """The guard fires on the domain, not on the shape."""
        tree = parse_expression("x ** n", {"x", "n"})
        env = {"x": np.array([2.0]), "n": np.array([3.0])}
        expected = 2.0**3.0 * np.log(2.0)
        assert tree.derivative(env, "n")[0] == pytest.approx(expected)
