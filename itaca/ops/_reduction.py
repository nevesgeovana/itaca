"""Shared weight rules for reduction operations (internal, REQ-98).

Reductions collapse an axis through a weight vector. Both UncFrame
components propagate through the same weights with different
correlation structure (REQ-98, REQ-99): the systematic component is
fully correlated across points, so it takes the absolute weighted sum
(no gain); the random component is independent between points, so it
takes the root sum of squares (the 1/sqrt(N) gain for a mean). Origin
tags reduce by the worst-case rule (OQ-10) over the cells that carry
nonzero weight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension

if TYPE_CHECKING:
    from itaca.ops._content import Content

_Array = NDArray[Any]

DATAPOINT_DIM = "datapoint"


def reduced_dims(content: Content, names: list[str]) -> dict[str, Dimension]:
    """Dimensions after collapsing ``names``; a datapoint holder if all go.

    Shared by ``average`` and ``integrate`` (REQ-27, REQ-28): when
    every dimension is removed, a single ``datapoint`` dimension with
    one entry holds the scalar result (REQ-22).
    """
    remaining = {name: dim for name, dim in content.dims.items() if name not in names}
    if remaining:
        return remaining
    return {
        DATAPOINT_DIM: Dimension(
            name=DATAPOINT_DIM,
            coords=np.arange(1),
            description="fully collapsed scalar holder (REQ-22)",
        )
    }


def trapezoid_weights(x: _Array) -> _Array:
    """Trapezoidal quadrature weights for coordinates ``x``.

    A single-point line integrates to zero (weight 0), matching
    ``np.trapezoid`` on one sample.
    """
    n = x.size
    if n < 2:
        return np.zeros(n)
    weights = np.empty(n)
    weights[0] = (x[1] - x[0]) / 2.0
    weights[-1] = (x[-1] - x[-2]) / 2.0
    if n > 2:
        weights[1:-1] = (x[2:] - x[:-2]) / 2.0
    return weights


def reduce_systematic(weights: _Array, component: _Array, axis: int) -> _Array:
    """Fully correlated propagation: absolute weighted sum (REQ-99)."""
    contributions = np.where(weights != 0.0, weights * component, 0.0)
    return np.asarray(np.abs(np.sum(contributions, axis=axis)))


def reduce_random(weights: _Array, component: _Array, axis: int) -> _Array:
    """Independent propagation: root sum of squares of weights (REQ-99)."""
    contributions = np.where(weights != 0.0, weights * component, 0.0)
    return np.asarray(np.sqrt(np.sum(np.square(contributions), axis=axis)))


def reduce_tags(tags: _Array, weighted: _Array, axis: int) -> _Array:
    """Worst-case tag reduction over cells with nonzero weight (OQ-10)."""
    counted_minus = np.any((tags == -1) & weighted, axis=axis)
    counted_plus = np.any((tags == 1) & weighted, axis=axis)
    return np.where(
        counted_minus, np.int8(-1), np.where(counted_plus, np.int8(1), np.int8(0))
    ).astype(np.int8)
