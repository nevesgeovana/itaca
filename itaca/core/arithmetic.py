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

from itaca.core.uncframe import standard_uncertainty

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
    """Build the REQ-37 operation table, closing over the weights.

    A constant partial is built with :func:`numpy.full` on the operand's
    SHAPE, never with :func:`numpy.full_like` on the operand itself.
    ``full_like`` inherits the operand's dtype, so an integer-valued frame
    truncated the 0.5 of ``mean`` to 0 and the propagated uncertainty
    collapsed to zero: measured ``u = [0, 0]`` where float64 inputs gave
    ``[2.5, 2.5]``, same frames and same declared uncertainties (FND-035).

    ``ones_like`` in ``sum`` and ``diff`` is left as it is, and that is
    not an oversight: 1 survives the same cast exactly, so those partials
    are correct at any dtype. What the guard pins is the equivalence a
    user can read, not the dtype of an intermediate; ``product`` would
    fail a dtype rule and is exact, because its partial with respect to
    one operand IS the other operand.
    """
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
            lambda a, b: np.full(np.shape(a), 0.5),
            lambda a, b: np.full(np.shape(b), 0.5),
        ),
    }
    if weights is not None:
        wa, wb = float(weights[0]), float(weights[1])
        total = wa + wb
        table["weighted_mean"] = CombineOperation(
            "weighted_mean",
            lambda a, b: (wa * a + wb * b) / total,
            lambda a, b: np.full(np.shape(a), wa / total),
            lambda a, b: np.full(np.shape(b), wb / total),
        )
    return table


def combine_components(
    operation: CombineOperation,
    values_a: _Array,
    values_b: _Array,
    u_a: _Array | None,
    u_b: _Array | None,
    cross_correlation: float,
    name: str,
) -> _Array | None:
    """Combine one uncertainty component through the exact Jacobian.

    A missing component on either side counts as zero; the cross-input
    correlation enters only when both sides carry the component.

    ``name`` is required rather than optional: REQ-81 asks every error
    for the object involved, and "combined uncertainty" alone names no
    object. This is the one propagation site whose correlation arrives
    as a bare float rather than through a validated
    :class:`~itaca.core.correlation.CorrelationMatrix`, so it is also
    the one that can still reach a materially negative variance.
    """
    if u_a is None and u_b is None:
        return None
    d_a = operation.d_da(values_a, values_b)
    d_b = operation.d_db(values_a, values_b)
    variance: _Array = np.asarray(0.0)
    diagonal: _Array = np.asarray(0.0)
    if u_a is not None:
        term = np.square(d_a * u_a)
        diagonal = diagonal + term
        variance = variance + term
    if u_b is not None:
        term = np.square(d_b * u_b)
        diagonal = diagonal + term
        variance = variance + term
    if u_a is not None and u_b is not None and cross_correlation:
        variance = variance + (2.0 * d_a * d_b * cross_correlation * u_a * u_b)
    return standard_uncertainty(
        variance,
        diagonal,
        terms=3,
        obj=f"combined uncertainty of '{name}'",
        operation=(
            f"combine(op='{operation.name}', cross_correlation={cross_correlation!r})"
        ),
        fix=(
            "the cross_correlation makes the combined covariance impossible; "
            "pass a value in [-1, 1] consistent with the two inputs, or 0.0 "
            "if they are independent (REQ-37, REQ-40)"
        ),
    )


def worst_case_tags(tags_a: _Array, tags_b: _Array) -> _Array:
    """Reduce origin tags by the worst-case rule (OQ-10)."""
    return np.where(
        (tags_a == -1) | (tags_b == -1),
        np.int8(-1),
        np.where((tags_a == 1) | (tags_b == 1), np.int8(1), np.int8(0)),
    ).astype(np.int8)
