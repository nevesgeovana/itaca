"""db.smooth: smoothing along a dimension (REQ-29).

Methods: ``"savgol"`` (moving polynomial fit, general spacing),
``"spline"`` (natural smoothing spline, Reinsch formulation), and
``"moving_avg"``. Method-dependent kwargs adopt the REQ-105 sentinel:
a parameter passed where the chosen method does not consume it raises
instead of being silently ignored. Smoothed values are tagged ``+1``
(cells already ``-1`` stay ``-1``, the worst case). Uncertainty
present raises until OQ-18 freezes the kernel weight rule (the
provisional smooth/diff row of REQ-98).
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
from itaca.core.sentinels import NoDefault, no_default, reject_no_default
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild
from itaca.ops._movingfit import moving_fit_line, window_bounds

_Array = NDArray[Any]

_METHODS = ("savgol", "spline", "moving_avg")
_CONSUMES = {
    "savgol": ("window", "polyorder"),
    "spline": ("smoothing",),
    "moving_avg": ("window",),
}


def _smoothing_matrix(x: _Array, smoothing: float) -> _Array:
    """Natural smoothing-spline operator.

    Reinsch (Green and Silverman) formulation:
    f = (I + s K)^-1 y with K = D^T W^-1 D.
    """
    n = x.size
    if n < 3 or smoothing == 0.0:
        return np.eye(n)
    h = np.diff(x)
    delta = np.zeros((n - 2, n))
    weight = np.zeros((n - 2, n - 2))
    for i in range(n - 2):
        delta[i, i] = 1.0 / h[i]
        delta[i, i + 1] = -1.0 / h[i] - 1.0 / h[i + 1]
        delta[i, i + 2] = 1.0 / h[i + 1]
        weight[i, i] = (h[i] + h[i + 1]) / 3.0
        if i > 0:
            weight[i, i - 1] = h[i] / 6.0
            weight[i - 1, i] = h[i] / 6.0
    penalty = delta.T @ np.linalg.solve(weight, delta)
    return np.asarray(np.linalg.inv(np.eye(n) + smoothing * penalty))


def _moving_avg_line(y: _Array, window: int) -> _Array:
    n = y.size
    out = np.full(n, np.nan)
    for index in range(n):
        lo, hi, _ = window_bounds(index, n, window)
        cells = y[lo:hi]
        finite = np.isfinite(cells)
        if finite.any():
            out[index] = float(np.mean(cells[finite]))
    return out


def _validate(
    db: VarFrame,
    along: str,
    method: str,
    given: dict[str, object],
) -> None:
    reject_no_default(along, "smooth(along=...)", "dimension resolution")
    reject_no_default(method, "smooth(method=...)", "method resolution")
    if method not in _METHODS:
        raise DataError(
            f"method {method!r}",
            "smooth received an unknown method",
            f"use one of {list(_METHODS)} (REQ-29)",
        )
    if along not in db.dims:
        raise DimensionNotFoundError(
            f"dimension '{along}'",
            "smooth(along=...) referenced an absent dimension",
            f"available dimensions: {list(db.dims)}",
        )
    if not db.dims[along].is_numeric:
        raise NonNumericDimensionError(
            f"dimension '{along}'",
            "smooth along a string-valued dimension",
            "numerical operations need numeric coordinates (SRS 4.1.3)",
        )
    consumed = _CONSUMES[method]
    for name, value in given.items():
        if name in consumed and value is no_default:
            raise DataError(
                f"smooth(method='{method}')",
                f"called without {name}",
                f"pass {name}= (REQ-29)",
            )
        if name not in consumed and value is not no_default:
            raise DataError(
                f"argument {name}={value!r}",
                f"smooth(method='{method}') does not consume {name}",
                f"omit it; '{method}' takes {list(consumed)} (REQ-105)",
            )
    if db.uncertainty is not None:
        raise UncertaintyError(
            f"smooth(method='{method}')",
            "uncertainty propagation through smoothing kernels is not "
            "frozen yet (REQ-98 provisional row, OQ-18)",
            "smooth before assigning uncertainty; the rule freezes during v0.2.0",
        )


def smooth(
    db: VarFrame,
    *,
    along: str,
    method: str,
    window: int | NoDefault = no_default,
    polyorder: int | NoDefault = no_default,
    smoothing: float | NoDefault = no_default,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Smooth all variables along a dimension (REQ-29).

    See ``VarFrame.smooth`` for the full parameter description.
    """
    given: dict[str, object] = {
        "window": window,
        "polyorder": polyorder,
        "smoothing": smoothing,
    }
    _validate(db, along, method, given)
    if method == "savgol":
        assert isinstance(window, int) and isinstance(polyorder, int)
        if window <= polyorder:
            raise DataError(
                f"smooth window {window}",
                f"a moving fit of degree {polyorder} needs more points than the degree",
                "increase window so that window > polyorder",
            )
    if method == "moving_avg":
        assert isinstance(window, int)
        if window < 1:
            raise DataError(
                f"smooth window {window}",
                "moving average needs a positive window",
                "pass window >= 1 (REQ-29)",
            )
    if method == "spline":
        assert isinstance(smoothing, (int, float))
        if smoothing < 0.0:
            raise DataError(
                f"smoothing {smoothing}",
                "the spline penalty must be nonnegative",
                "pass smoothing >= 0 (REQ-29)",
            )

    content = content_of(db)
    axis = list(content.dims).index(along)
    x = np.asarray(content.dims[along].coords, dtype=float)
    n = x.size
    spline_operator = (
        _smoothing_matrix(x, float(smoothing))  # type: ignore[arg-type]
        if method == "spline"
        else None
    )
    tags = content.tags if content.tags is not None else {}
    new_tags: dict[str, _Array] = {}
    for name, values in content.values.items():
        moved = np.moveaxis(values, axis, -1).copy()
        flat = moved.reshape(-1, n)
        for row in range(flat.shape[0]):
            line = flat[row]
            if method == "savgol":
                assert isinstance(window, int) and isinstance(polyorder, int)
                fitted, _ = moving_fit_line(x, line, window, polyorder, False)
                flat[row] = np.where(np.isfinite(line), fitted, np.nan)
            elif method == "moving_avg":
                assert isinstance(window, int)
                averaged = _moving_avg_line(line, window)
                flat[row] = np.where(np.isfinite(line), averaged, np.nan)
            else:
                assert spline_operator is not None
                finite = np.isfinite(line)
                if finite.all():
                    flat[row] = spline_operator @ line
                elif finite.any():
                    # NaN cells stay NaN; the operator applies to the
                    # populated subset with its own penalty matrix.
                    sub = _smoothing_matrix(
                        x[finite],
                        float(smoothing),  # type: ignore[arg-type]
                    )
                    flat[row, finite] = sub @ line[finite]
        content.values[name] = np.moveaxis(flat.reshape(moved.shape), -1, axis)
        source = tags.get(name, np.zeros(content.shape, dtype=np.int8))
        smoothed_tag = np.where(
            source == -1,
            np.int8(-1),
            np.where(np.isfinite(content.values[name]), np.int8(1), source),
        ).astype(np.int8)
        new_tags[name] = smoothed_tag
    content.tags = new_tags

    knobs = {k: v for k, v in given.items() if v is not no_default}
    detail = ", ".join(f"{k}={v}" for k, v in knobs.items())
    operation = f"smooth(along='{along}', method='{method}', {detail})"
    return rebuild(db, content, operation=operation, comment=comment, history=history)
