"""The ast-based expression engine (DD-20; REQ-33, REQ-36, REQ-44).

Expressions are parsed with the standard-library ``ast`` module and
compiled to the ITACA operator tree; chain-rule differentiation walks
that tree numerically. Differentiable ``np.*`` calls are silently
normalized to native operators; other NumPy functions evaluate freely
but refuse differentiation (the per-variable guard of REQ-36).
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Any, Union

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    DataError,
    UncertaintyCompatibilityError,
    VariableNotFoundError,
)
from itaca.uncertainty.operators import BINARY, UNARY, BinaryOperator, UnaryOperator

_Array = NDArray[Any]
Node = Union["Const", "Var", "Unary", "Binary", "NumpyCall"]

_CONSTANTS = {"pi": np.pi, "e": np.e}
_NUMPY_NORMALIZATION = {
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "arctan2": "atan2",
    "sqrt": "sqrt",
    "abs": "abs",
    "absolute": "abs",
    "log": "log",
    "log10": "log10",
    "exp": "exp",
}
_BINARY_AST = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.Div: "div",
    ast.Pow: "pow",
}
_COMPARE_AST = {
    ast.Gt: np.greater,
    ast.GtE: np.greater_equal,
    ast.Lt: np.less,
    ast.LtE: np.less_equal,
    ast.Eq: np.equal,
    ast.NotEq: np.not_equal,
}


@dataclass(frozen=True)
class Const:
    """A numeric literal or named constant (``pi``, ``e``)."""

    value: float

    def evaluate(self, env: Mapping[str, _Array]) -> _Array:
        """Return the constant as an array scalar."""
        return np.asarray(self.value)

    def derivative(self, env: Mapping[str, _Array], name: str) -> _Array:
        """Constants have zero derivative."""
        return np.asarray(0.0)

    def variables(self) -> set[str]:
        """Constants reference no variables."""
        return set()

    def tokens(self) -> list[str]:
        """Postorder token list (RPN view) of this node."""
        return [repr(self.value)]


@dataclass(frozen=True)
class Var:
    """A reference to a VarFrame variable."""

    name: str

    def evaluate(self, env: Mapping[str, _Array]) -> _Array:
        """Look the variable up in the evaluation environment."""
        return env[self.name]

    def derivative(self, env: Mapping[str, _Array], name: str) -> _Array:
        """Kronecker delta: one for itself, zero otherwise."""
        return np.asarray(1.0 if name == self.name else 0.0)

    def variables(self) -> set[str]:
        """Return the single variable this node references."""
        return {self.name}

    def tokens(self) -> list[str]:
        """Postorder token list (RPN view) of this node."""
        return [self.name]


@dataclass(frozen=True)
class Unary:
    """A one-argument operator application."""

    op: UnaryOperator
    a: Node

    def evaluate(self, env: Mapping[str, _Array]) -> _Array:
        """Evaluate the operand, then the operator."""
        return self.op.evaluate(self.a.evaluate(env))

    def derivative(self, env: Mapping[str, _Array], name: str) -> _Array:
        """Chain rule through the operator's analytical partial."""
        return np.asarray(
            self.op.d_da(self.a.evaluate(env)) * self.a.derivative(env, name)
        )

    def variables(self) -> set[str]:
        """Variables referenced below this node."""
        return self.a.variables()

    def tokens(self) -> list[str]:
        """Postorder token list (RPN view) of this node."""
        return [*self.a.tokens(), self.op.name]


@dataclass(frozen=True)
class Binary:
    """A two-argument operator application."""

    op: BinaryOperator
    a: Node
    b: Node

    def evaluate(self, env: Mapping[str, _Array]) -> _Array:
        """Evaluate both operands, then the operator."""
        return self.op.evaluate(self.a.evaluate(env), self.b.evaluate(env))

    def derivative(self, env: Mapping[str, _Array], name: str) -> _Array:
        """Chain rule through both analytical partials."""
        value_a = self.a.evaluate(env)
        value_b = self.b.evaluate(env)
        return np.asarray(
            self.op.d_da(value_a, value_b) * self.a.derivative(env, name)
            + self.op.d_db(value_a, value_b) * self.b.derivative(env, name)
        )

    def variables(self) -> set[str]:
        """Variables referenced below this node."""
        return self.a.variables() | self.b.variables()

    def tokens(self) -> list[str]:
        """Postorder token list (RPN view) of this node."""
        return [*self.a.tokens(), *self.b.tokens(), self.op.name]


@dataclass(frozen=True)
class NumpyCall:
    """A generic ``np.*`` call: evaluates freely, refuses derivatives.

    REQ-36: with no uncertainty in the expression every NumPy function
    is allowed; under differentiation the non-differentiable ones fail
    loud with an actionable suggestion.
    """

    name: str
    args: tuple[Node, ...]

    def evaluate(self, env: Mapping[str, _Array]) -> _Array:
        """Evaluate through the NumPy function of the same name."""
        function = getattr(np, self.name)
        return np.asarray(function(*(arg.evaluate(env) for arg in self.args)))

    def derivative(self, env: Mapping[str, _Array], name: str) -> _Array:
        """Refuse: no sound derivative exists (REQ-36)."""
        raise UncertaintyCompatibilityError(
            f"np.{self.name}",
            "differentiation of a non-differentiable NumPy function with "
            "uncertainty inputs",
            "compute the derived variable before assigning uncertainty, "
            "or switch to method='mcm' (available from v0.3.0)",
        )

    def variables(self) -> set[str]:
        """Variables referenced below this node."""
        names: set[str] = set()
        for arg in self.args:
            names |= arg.variables()
        return names

    def tokens(self) -> list[str]:
        """Postorder token list (RPN view) of this node."""
        out: list[str] = []
        for arg in self.args:
            out.extend(arg.tokens())
        out.append(f"np.{self.name}")
        return out


def parse_expression(text: str, known: Set[str]) -> Node:
    """Parse an expression string into the ITACA operator tree (DD-20).

    Parameters
    ----------
    text : str
        Right-hand side of a ``compute`` equation.
    known : set of str
        Variable names available in the VarFrame.

    Returns
    -------
    Node
        The root of the operator tree.

    Raises
    ------
    DataError
        On syntax errors or unsupported constructs, with the offset
        reported by the stdlib parser.
    VariableNotFoundError
        When the expression references an unknown variable.

    Examples
    --------
    >>> import numpy as np
    >>> tree = parse_expression("0.5 * rho * V**2", {"rho", "V"})
    >>> sorted(tree.variables())
    ['V', 'rho']
    """
    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError as error:
        raise DataError(
            f"expression '{text}'",
            f"parse failed at offset {error.offset}: {error.msg}",
            "check the equation syntax (REQ-33)",
        ) from None
    return _convert(parsed.body, known, text)


def _convert(node: ast.expr, known: Set[str], text: str) -> Node:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return Const(float(node.value))
        raise DataError(
            f"literal {node.value!r} in '{text}'",
            "expressions accept numeric literals only",
            "use numbers, variables, and the REQ-44 operators",
        )
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return Const(_CONSTANTS[node.id])
        if node.id in known:
            return Var(node.id)
        raise VariableNotFoundError(
            f"variable '{node.id}'",
            f"expression '{text}' references it but the VarFrame does not contain it",
            f"available variables: {sorted(known)}",
        )
    if isinstance(node, ast.BinOp):
        op_name = _BINARY_AST.get(type(node.op))
        if op_name is None:
            raise DataError(
                f"operator {type(node.op).__name__} in '{text}'",
                "unsupported binary operator",
                "supported: + - * / ** (REQ-44)",
            )
        return Binary(
            BINARY[op_name],
            _convert(node.left, known, text),
            _convert(node.right, known, text),
        )
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return Unary(UNARY["neg"], _convert(node.operand, known, text))
        if isinstance(node.op, ast.UAdd):
            return _convert(node.operand, known, text)
        raise DataError(
            f"operator {type(node.op).__name__} in '{text}'",
            "unsupported unary operator",
            "supported: unary minus (REQ-44)",
        )
    if isinstance(node, ast.Call):
        return _convert_call(node, known, text)
    raise DataError(
        f"construct {type(node).__name__} in '{text}'",
        "unsupported expression syntax",
        "use arithmetic, the REQ-44 functions, and np.* calls",
    )


def _native(name: str, args: list[Node], text: str) -> Node:
    if name == "atan2":
        if len(args) != 2:
            raise DataError(
                f"function 'atan2' in '{text}'",
                f"called with {len(args)} argument(s)",
                "atan2 takes exactly two arguments (REQ-44)",
            )
        return Binary(BINARY["atan2"], args[0], args[1])
    if len(args) != 1:
        raise DataError(
            f"function '{name}' in '{text}'",
            f"called with {len(args)} argument(s)",
            "this function takes exactly one argument (REQ-44)",
        )
    return Unary(UNARY[name], args[0])


def _convert_call(node: ast.Call, known: Set[str], text: str) -> Node:
    args = [_convert(arg, known, text) for arg in node.args]
    if isinstance(node.func, ast.Name):
        name = node.func.id
        if name in UNARY or name == "atan2":
            return _native(name, args, text)
        raise DataError(
            f"function '{name}' in '{text}'",
            "unknown function",
            f"supported functions: {sorted([*UNARY, 'atan2'])} plus np.*",
        )
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "np"
    ):
        attribute = node.func.attr
        if attribute in _NUMPY_NORMALIZATION:
            # REQ-36: silently normalized to the native operator.
            return _native(_NUMPY_NORMALIZATION[attribute], args, text)
        if not hasattr(np, attribute):
            raise DataError(
                f"function 'np.{attribute}' in '{text}'",
                "NumPy has no such function",
                "check the spelling against the NumPy API",
            )
        return NumpyCall(attribute, tuple(args))
    raise DataError(
        f"call in '{text}'",
        "only bare functions and np.* attributes are callable",
        "use the REQ-44 functions or np.<function>(...)",
    )


def condition_mask(
    text: str, known: Set[str], env: Mapping[str, _Array]
) -> NDArray[np.bool_]:
    """Evaluate a ``where=`` condition string to a boolean mask (REQ-35).

    Supports comparisons (``> < >= <= == !=``) and the logical
    operators ``and``, ``or``, ``not`` over any expression the main
    parser accepts.

    Parameters
    ----------
    text : str
        The condition string, e.g. ``"CT > 0.1 and alpha <= 10"``.
    known : set of str
        Variable names available in the VarFrame.
    env : mapping of str to numpy.ndarray
        Evaluation environment.

    Returns
    -------
    numpy.ndarray
        Boolean mask over the VarFrame grid.

    Raises
    ------
    DataError
        On syntax errors or non-boolean constructs.
    """
    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError as error:
        raise DataError(
            f"condition '{text}'",
            f"parse failed at offset {error.offset}: {error.msg}",
            "check the where= syntax (REQ-35)",
        ) from None
    return np.asarray(_bool_eval(parsed.body, known, env, text), dtype=bool)


def _bool_eval(
    node: ast.expr,
    known: Set[str],
    env: Mapping[str, _Array],
    text: str,
) -> NDArray[np.bool_]:
    if isinstance(node, ast.Compare):
        left = _convert(node.left, known, text).evaluate(env)
        result: NDArray[np.bool_] | None = None
        for operation, comparator in zip(node.ops, node.comparators, strict=True):
            comparison = _COMPARE_AST.get(type(operation))
            if comparison is None:
                raise DataError(
                    f"comparison {type(operation).__name__} in '{text}'",
                    "unsupported comparison operator",
                    "supported: > < >= <= == != (REQ-35)",
                )
            right = _convert(comparator, known, text).evaluate(env)
            step = comparison(left, right)
            result = step if result is None else result & step
            left = right
        assert result is not None
        return result
    if isinstance(node, ast.BoolOp):
        parts = [_bool_eval(value, known, env, text) for value in node.values]
        if isinstance(node.op, ast.And):
            return np.asarray(np.logical_and.reduce(parts), dtype=bool)
        return np.asarray(np.logical_or.reduce(parts), dtype=bool)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return np.logical_not(_bool_eval(node.operand, known, env, text))
    raise DataError(
        f"construct {type(node).__name__} in condition '{text}'",
        "conditions must be comparisons combined with and/or/not",
        'example: "CT > 0.1 and not alpha >= 10" (REQ-35)',
    )
