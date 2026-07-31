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
    undefined_at : callable or None, optional
        Elementwise predicate marking operand values where ``d_da`` has
        no sound value, even though it returns one. ``None`` (the
        default) means the partial is trustworthy wherever it is finite.
    undefined_reason : str, optional
        What is wrong at those points, for the refusal message.

    Notes
    -----
    ``undefined_at`` exists for a narrow case and should stay narrow
    (FND-095). Most domain failures announce themselves: ``sqrt`` and
    ``log`` at zero return an infinite partial, and ``asin`` at one does
    the same, so the result carries an infinity a reader cannot mistake
    for a measurement. ``abs`` at zero is the dangerous shape instead,
    because ``np.sign(0)`` is ``0`` and the propagated uncertainty comes
    back as a perfectly plausible EXACT ZERO: the library asserts total
    certainty precisely where the function has no derivative at all. A
    predicate is warranted when a partial is silently wrong, not merely
    when it is infinite.
    """

    name: str
    evaluate: Callable[[_Array], _Array]
    d_da: Callable[[_Array], _Array]
    undefined_at: Callable[[_Array], _Array] | None = None
    undefined_reason: str = ""


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
        UnaryOperator(
            "abs",
            np.abs,
            np.sign,
            undefined_at=lambda a: np.asarray(a == 0.0),
            undefined_reason=(
                "d|a|/da is the sign of a, which does not exist at a = 0: "
                "the left and right derivatives are -1 and +1. np.sign "
                "returns 0 there, so the propagated uncertainty came back "
                "as an exact zero, asserting certainty at the one point "
                "where the function has none"
            ),
        ),
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
