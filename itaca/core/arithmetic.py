"""Elementwise arithmetic with covariance for db.combine (REQ-37).

Each named operation carries its exact Jacobian so that uncertainty
propagates analytically, including the optional cross-input
correlation. The origin-tag reduction follows the worst-case rule
(OQ-10).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

_Array = NDArray[Any]


@dataclass(frozen=True)
class CombineOperation:
    """A binary frame combination with its exact Jacobian.

    Parameters
    ----------
    name : str
        Operation name as passed to ``db.combine``.
    evaluate : callable
        ``f(a, b)`` elementwise.
    d_da : callable
        Partial with respect to the left input.
    d_db : callable
        Partial with respect to the right input.
    """

    name: str
    evaluate: Callable[[_Array, _Array], _Array]
    d_da: Callable[[_Array, _Array], _Array]
    d_db: Callable[[_Array, _Array], _Array]


def operations(
    weights: tuple[float, float] | None,
) -> dict[str, CombineOperation]:
    """Build the REQ-37 operation table, closing over the weights."""
    table = {
        "sum": CombineOperation(
            "sum",
            lambda a, b: a + b,
            lambda a, b: np.ones_like(a),
            lambda a, b: np.ones_like(b),
        ),
        "diff": CombineOperation(
            "diff",
            lambda a, b: a - b,
            lambda a, b: np.ones_like(a),
            lambda a, b: -np.ones_like(b),
        ),
        "product": CombineOperation(
            "product",
            lambda a, b: a * b,
            lambda a, b: b,
            lambda a, b: a,
        ),
        "ratio": CombineOperation(
            "ratio",
            lambda a, b: a / b,
            lambda a, b: 1.0 / b,
            lambda a, b: -a / b**2,
        ),
        "mean": CombineOperation(
            "mean",
            lambda a, b: 0.5 * (a + b),
            lambda a, b: np.full_like(a, 0.5),
            lambda a, b: np.full_like(b, 0.5),
        ),
    }
    if weights is not None:
        wa, wb = float(weights[0]), float(weights[1])
        total = wa + wb
        table["weighted_mean"] = CombineOperation(
            "weighted_mean",
            lambda a, b: (wa * a + wb * b) / total,
            lambda a, b: np.full_like(a, wa / total),
            lambda a, b: np.full_like(b, wb / total),
        )
    return table


def combine_components(
    operation: CombineOperation,
    values_a: _Array,
    values_b: _Array,
    u_a: _Array | None,
    u_b: _Array | None,
    cross_correlation: float,
) -> _Array | None:
    """Combine one uncertainty component through the exact Jacobian.

    A missing component on either side counts as zero; the cross-input
    correlation enters only when both sides carry the component.
    """
    if u_a is None and u_b is None:
        return None
    d_a = operation.d_da(values_a, values_b)
    d_b = operation.d_db(values_a, values_b)
    variance: _Array = np.asarray(0.0)
    if u_a is not None:
        variance = variance + np.square(d_a * u_a)
    if u_b is not None:
        variance = variance + np.square(d_b * u_b)
    if u_a is not None and u_b is not None and cross_correlation:
        variance = variance + (2.0 * d_a * d_b * cross_correlation * u_a * u_b)
    return np.asarray(np.sqrt(np.maximum(variance, 0.0)))


def worst_case_tags(tags_a: _Array, tags_b: _Array) -> _Array:
    """Reduce origin tags by the worst-case rule (OQ-10)."""
    return np.where(
        (tags_a == -1) | (tags_b == -1),
        np.int8(-1),
        np.where((tags_a == 1) | (tags_b == 1), np.int8(1), np.int8(0)),
    ).astype(np.int8)
