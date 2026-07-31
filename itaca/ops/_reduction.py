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
from itaca.core.errors import UncertaintyLineageError
from itaca.uncertainty._lineage import interpolated_dims

if TYPE_CHECKING:
    from itaca.core.varframe import VarFrame
    from itaca.ops._content import Content

_Array = NDArray[Any]

DATAPOINT_DIM = "datapoint"


def refuse_correlated_reduction(db: VarFrame, names: list[str], operation: str) -> None:
    """Refuse a RANDOM reduction over points an interpolation correlated.

    FND-088, SEAT-UNC. ``reduce_random`` below is the root sum of
    squares, which is the propagation rule for INDEPENDENT points. After
    ``interpolate`` the points along that dimension are each a linear
    combination of the same source points, so they are not independent
    and the rule understates: measured 0.559 where 0.707 is correct, 21
    percent low.

    Only the random component is affected, and that asymmetry is real
    rather than an accident of where the check sits.
    ``reduce_systematic`` is the absolute weighted sum, which already
    assumes FULL correlation across points, and a fully correlated
    assumption stays valid when interpolation makes points more
    correlated. So a systematic-only frame reduces exactly as before.

    Placed here, in the module both ``average`` and ``integrate`` take
    their weight rules from, because both take ``reduce_random`` from it
    and the defect belongs to the rule and not to either caller.
    """
    if db.uncertainty is None or not db.uncertainty.random:
        return
    touched = interpolated_dims(db.history) & set(names)
    if not touched:
        return
    carried = sorted(db.uncertainty.random)
    raise UncertaintyLineageError(
        f"random uncertainty on {carried} over dimension(s) {sorted(touched)}",
        f"{operation} propagates the random component as a root sum of "
        f"squares, which is only valid for INDEPENDENT points, and "
        f"interpolate made each point along {sorted(touched)} a linear "
        f"combination of the same source points: the result would "
        f"UNDERSTATE (measured 21 percent low)",
        "reduce on the source grid and interpolate afterwards, or reduce "
        "along a dimension the interpolation did not touch (interpolating "
        "onto a common grid and then averaging ACROSS runs is unaffected). "
        "A frame carrying only a systematic component is also unaffected, "
        "since that rule already assumes full correlation. Reducing over "
        "interpolated points correctly needs the point-to-point covariance "
        "and is v0.3.0 work (SEAT-UNC, REQ-98, REQ-99)",
    )


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
