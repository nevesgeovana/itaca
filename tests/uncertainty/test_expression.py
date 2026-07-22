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
