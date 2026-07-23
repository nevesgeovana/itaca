"""db.fill: gap filling along a dimension (REQ-26).

Filled values are tagged ``+1`` (SRS 4.3). Uncertainty propagates
through the interpolation weights per REQ-98: systematic through the
weight sum (fully correlated), random through the RSS of weights.
The moving-polyfit weight rule is not frozen yet (the provisional
smooth/diff/fitmodel family of REQ-98, OQ-18): filling with
uncertainty present and ``method="polyfit"`` raises rather than
guessing (DD-18).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    NonNumericDimensionError,
    UncertaintyError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild

# (position, [(neighbor index, weight), ...]) or (position, None) when
# no exact weight rule applies (polyfit).
_Fill = tuple[int, list[tuple[int, float]] | None]


def _fill_line(
    x: NDArray[Any],
    y: NDArray[Any],
    method: str,
    deg: int | None,
    window: int | None,
    global_fit: bool,
) -> list[_Fill]:
    valid = np.isfinite(y)
    gaps = np.nonzero(np.isnan(y))[0]
    if gaps.size == 0 or not valid.any():
        return []
    valid_idx = np.nonzero(valid)[0]
    fills: list[_Fill] = []
    if method == "linear":
        for position in gaps:
            left = valid_idx[valid_idx < position]
            right = valid_idx[valid_idx > position]
            if left.size and right.size:
                lo, hi = int(left[-1]), int(right[0])
                w_hi = float((x[position] - x[lo]) / (x[hi] - x[lo]))
                fills.append((int(position), [(lo, 1.0 - w_hi), (hi, w_hi)]))
    elif method == "nearest":
        for position in gaps:
            distances = np.abs(x[valid_idx] - x[position])
            nearest = int(valid_idx[int(np.argmin(distances))])
            fills.append((int(position), [(nearest, 1.0)]))
    else:  # polyfit
        assert deg is not None
        for position in gaps:
            if global_fit:
                chosen = valid_idx
            else:
                assert window is not None
                half = window // 2
                lo = max(0, int(position) - half)
                hi = min(y.size, lo + window)
                inside = valid_idx[(valid_idx >= lo) & (valid_idx < hi)]
                chosen = inside
            if chosen.size > deg:
                coeffs = np.polyfit(x[chosen], y[chosen], deg)
                y[position] = float(np.polyval(coeffs, x[position]))
                fills.append((int(position), None))
    for target, weights in fills:
        if weights is not None:
            y[target] = float(np.sum([w * y[i] for i, w in weights]))
    return fills


def fill(
    db: VarFrame,
    *,
    along: str,
    method: str = "linear",
    deg: int | None = None,
    window: int | None = None,
    global_fit: bool = False,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Fill NaN entries along a dimension (REQ-26).

    See ``VarFrame.fill`` for the full parameter description.
    """
    if along not in db.dims:
        raise DimensionNotFoundError(
            f"dimension '{along}'",
            "fill(along=...) referenced an absent dimension",
            f"available dimensions: {list(db.dims)}",
        )
    if not db.dims[along].is_numeric:
        raise NonNumericDimensionError(
            f"dimension '{along}'",
            "fill along a string-valued dimension",
            "numerical operations need numeric coordinates (SRS 4.1.3)",
        )
    if method not in ("linear", "nearest", "polyfit"):
        raise DataError(
            f"method {method!r}",
            "fill received an unknown method",
            "use 'linear', 'nearest', or 'polyfit' (REQ-26)",
        )
    if method == "polyfit":
        if deg is None:
            raise DataError(
                "fill(method='polyfit')",
                "called without deg",
                "pass deg=<polynomial degree> (REQ-26)",
            )
        if not global_fit:
            if window is None:
                raise DataError(
                    "fill(method='polyfit')",
                    "called without window and without global_fit",
                    "pass window=<points> or global_fit=True (REQ-26)",
                )
            if window <= deg:
                raise DataError(
                    f"fill window {window}",
                    f"moving polynomial fit of degree {deg} needs more "
                    "points than the degree",
                    "increase window so that window > deg",
                )
        if db.uncertainty is not None:
            raise UncertaintyError(
                "fill(method='polyfit')",
                "uncertainty propagation through moving-fit weights is "
                "not frozen yet (REQ-98 provisional row, OQ-18)",
                "fill before assigning uncertainty, or use method="
                "'linear' or 'nearest'",
            )
    content = content_of(db)
    axis = list(content.dims).index(along)
    x = np.asarray(content.dims[along].coords, dtype=float)
    n = x.size
    tags = content.tags if content.tags is not None else {}
    new_tags: dict[str, NDArray[Any]] = {
        name: np.array(
            tags.get(name, np.zeros(content.shape, dtype=np.int8)),
            dtype=np.int8,
        )
        for name in content.values
    }
    any_filled = False
    for name, values in content.values.items():
        moved = np.moveaxis(values, axis, -1).copy()
        flat = moved.reshape(-1, n)
        tag_moved = np.moveaxis(new_tags[name], axis, -1).copy()
        tag_flat = tag_moved.reshape(-1, n)
        unc_flat: dict[str, NDArray[Any]] = {}
        for label in ("systematic", "random"):
            component = getattr(content, label)
            if component is not None and name in component:
                unc_flat[label] = (
                    np.moveaxis(component[name], axis, -1).copy().reshape(-1, n)
                )
        for row in range(flat.shape[0]):
            fills = _fill_line(x, flat[row], method, deg, window, global_fit)
            for position, weights in fills:
                any_filled = True
                tag_flat[row, position] = 1
                if weights is None:
                    continue
                for label, lines in unc_flat.items():
                    neighbors = np.array([lines[row, index] for index, _ in weights])
                    w = np.array([weight for _, weight in weights])
                    if label == "systematic":
                        lines[row, position] = abs(float(np.sum(w * neighbors)))
                    else:
                        lines[row, position] = float(
                            np.sqrt(np.sum(np.square(w * neighbors)))
                        )
        content.values[name] = np.moveaxis(flat.reshape(moved.shape), -1, axis)
        new_tags[name] = np.moveaxis(tag_flat.reshape(moved.shape), -1, axis)
        for label, lines in unc_flat.items():
            component = getattr(content, label)
            component[name] = np.moveaxis(lines.reshape(moved.shape), -1, axis)
    if any_filled or content.tags is not None:
        content.tags = new_tags
    operation = (
        f"fill(along='{along}', method='{method}', deg={deg}, "
        f"window={window}, global_fit={global_fit})"
    )
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        call="fill",
        replay_kwargs={
            "along": along,
            "method": method,
            "deg": deg,
            "window": window,
            "global_fit": global_fit,
        },
    )
