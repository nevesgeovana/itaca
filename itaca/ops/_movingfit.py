"""Moving-window polynomial kernel (internal, REQ-29, REQ-30).

Shared by ``smooth(method="savgol")`` and ``diff``: a window of
points centered on each sample is fitted with a polynomial and the
fit (or its analytical derivative) is evaluated at the sample. At
boundaries the window is asymmetric, preserving output shape; the
caller decides whether asymmetric points survive (``nan_edges``).
NaN samples inside a window drop out of the fit; a window left with
fewer points than ``deg + 1`` yields NaN.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

_Array = NDArray[Any]


def window_bounds(index: int, n: int, window: int) -> tuple[int, int, bool]:
    """Window ``[lo, hi)`` around ``index`` and whether it is centered."""
    half_left = (window - 1) // 2
    lo = max(0, index - half_left)
    hi = min(n, lo + window)
    lo = max(0, hi - window)
    centered = (index - lo == half_left) and (hi - lo == window)
    return lo, hi, centered


def moving_fit_line(
    x: _Array,
    y: _Array,
    window: int,
    deg: int,
    derivative: bool,
) -> tuple[_Array, _Array]:
    """Fit each window; return (result, asymmetric mask)."""
    n = x.size
    result = np.full(n, np.nan)
    asymmetric = np.zeros(n, dtype=bool)
    for index in range(n):
        lo, hi, centered = window_bounds(index, n, window)
        asymmetric[index] = not centered
        xw = x[lo:hi]
        yw = y[lo:hi]
        finite = np.isfinite(yw)
        if int(finite.sum()) <= deg:
            continue
        coeffs: _Array = np.polyfit(xw[finite], yw[finite], deg)
        if derivative:
            coeffs = np.polyder(coeffs)
        result[index] = float(np.polyval(coeffs, x[index]))
    return result, asymmetric


def window_tags_line(tags: _Array, window: int) -> _Array:
    """Worst-case tag over each moving window (OQ-10)."""
    n = tags.size
    out = np.zeros(n, dtype=np.int8)
    for index in range(n):
        lo, hi, _ = window_bounds(index, n, window)
        cells = tags[lo:hi]
        if np.any(cells == -1):
            out[index] = -1
        elif np.any(cells == 1):
            out[index] = 1
    return out
