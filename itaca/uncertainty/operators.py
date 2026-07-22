"""Expression operators with analytical partial derivatives (REQ-44).

Each operator is an isolated, independently testable object exposing
``evaluate`` plus ``d_da`` (and ``d_db`` for binary operators), the
building blocks of chain-rule differentiation on the expression tree
(DD-20). Property-based tests verify every partial against finite
differences (REQ-77).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

_Array = NDArray[Any]


@dataclass(frozen=True)
class UnaryOperator:
    """A one-argument operator with its analytical derivative.

    Parameters
    ----------
    name : str
        Operator name as written in expressions, e.g. ``"sin"``.
    evaluate : callable
        Elementwise evaluation ``f(a)``.
    d_da : callable
        Analytical partial ``df/da`` evaluated at ``a``.
    """

    name: str
    evaluate: Callable[[_Array], _Array]
    d_da: Callable[[_Array], _Array]


@dataclass(frozen=True)
class BinaryOperator:
    """A two-argument operator with both analytical partials.

    Parameters
    ----------
    name : str
        Operator name, e.g. ``"add"`` or ``"atan2"``.
    evaluate : callable
        Elementwise evaluation ``f(a, b)``.
    d_da : callable
        Analytical partial ``df/da`` evaluated at ``(a, b)``.
    d_db : callable
        Analytical partial ``df/db`` evaluated at ``(a, b)``.
    """

    name: str
    evaluate: Callable[[_Array, _Array], _Array]
    d_da: Callable[[_Array, _Array], _Array]
    d_db: Callable[[_Array, _Array], _Array]


UNARY: dict[str, UnaryOperator] = {
    op.name: op
    for op in (
        UnaryOperator("neg", np.negative, lambda a: -np.ones_like(a)),
        UnaryOperator("sin", np.sin, np.cos),
        UnaryOperator("cos", np.cos, lambda a: -np.sin(a)),
        UnaryOperator("tan", np.tan, lambda a: 1.0 / np.cos(a) ** 2),
        UnaryOperator("asin", np.arcsin, lambda a: 1.0 / np.sqrt(1.0 - a**2)),
        UnaryOperator("acos", np.arccos, lambda a: -1.0 / np.sqrt(1.0 - a**2)),
        UnaryOperator("atan", np.arctan, lambda a: 1.0 / (1.0 + a**2)),
        UnaryOperator("sqrt", np.sqrt, lambda a: 0.5 / np.sqrt(a)),
        UnaryOperator("abs", np.abs, np.sign),
        UnaryOperator("log", np.log, lambda a: 1.0 / a),
        UnaryOperator("log10", np.log10, lambda a: 1.0 / (a * np.log(10.0))),
        UnaryOperator("exp", np.exp, np.exp),
    )
}

BINARY: dict[str, BinaryOperator] = {
    op.name: op
    for op in (
        BinaryOperator(
            "add",
            np.add,
            lambda a, b: np.ones_like(np.asarray(a + b, dtype=float)),
            lambda a, b: np.ones_like(np.asarray(a + b, dtype=float)),
        ),
        BinaryOperator(
            "sub",
            np.subtract,
            lambda a, b: np.ones_like(np.asarray(a + b, dtype=float)),
            lambda a, b: -np.ones_like(np.asarray(a + b, dtype=float)),
        ),
        BinaryOperator(
            "mul",
            np.multiply,
            lambda a, b: (
                np.asarray(b, dtype=float) * np.ones_like(np.asarray(a, dtype=float))
            ),
            lambda a, b: (
                np.asarray(a, dtype=float) * np.ones_like(np.asarray(b, dtype=float))
            ),
        ),
        BinaryOperator(
            "div",
            np.divide,
            lambda a, b: (
                1.0
                / np.asarray(b, dtype=float)
                * np.ones_like(np.asarray(a, dtype=float))
            ),
            lambda a, b: -np.asarray(a, dtype=float) / np.asarray(b) ** 2,
        ),
        BinaryOperator(
            "pow",
            np.power,
            lambda a, b: np.asarray(b, dtype=float) * np.power(a, b - 1.0),
            lambda a, b: np.power(a, b) * np.log(np.asarray(a, dtype=float)),
        ),
        BinaryOperator(
            "atan2",
            np.arctan2,
            lambda a, b: np.asarray(b, dtype=float) / (a**2 + b**2),
            lambda a, b: -np.asarray(a, dtype=float) / (a**2 + b**2),
        ),
    )
}
