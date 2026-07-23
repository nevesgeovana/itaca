"""Interpolation weight matrices (internal, REQ-25, REQ-98).

Every supported method is a linear operator on the sampled values, so
interpolation is expressed as a weight matrix W with
``y_new = W @ y_old``. The same matrix propagates both uncertainty
components exactly (REQ-98): systematic as ``|W @ u|`` (fully
correlated), random as ``sqrt(W**2 @ u**2)`` (independent points).
Targets outside the convex hull extrapolate with the edge behavior of
each method and are tagged ``-1`` by the caller.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

_Array = NDArray[Any]


def linear_matrix(x: _Array, targets: _Array) -> _Array:
    """Piecewise-linear weights; edge segments extrapolate."""
    n = x.size
    weights = np.zeros((targets.size, n))
    for row, t in enumerate(targets):
        segment = int(np.clip(np.searchsorted(x, t, side="right") - 1, 0, n - 2))
        lo, hi = x[segment], x[segment + 1]
        w_hi = (t - lo) / (hi - lo)
        weights[row, segment] = 1.0 - w_hi
        weights[row, segment + 1] = w_hi
    return weights


def nearest_matrix(x: _Array, targets: _Array) -> _Array:
    """Nearest-neighbor copy weights."""
    weights = np.zeros((targets.size, x.size))
    for row, t in enumerate(targets):
        weights[row, int(np.argmin(np.abs(x - t)))] = 1.0
    return weights


def polyfit_matrix(x: _Array, targets: _Array, deg: int) -> _Array:
    """Global least-squares polynomial weights of degree ``deg``."""
    vander = np.vander(x, deg + 1)
    vander_t = np.vander(targets, deg + 1)
    return np.asarray(vander_t @ np.linalg.pinv(vander))


def cubic_matrix(x: _Array, targets: _Array) -> _Array:
    """Natural cubic-spline weights.

    The natural spline is a linear operator on the samples; the matrix
    is assembled by passing the identity through the classic
    second-derivative formulation. Beyond the hull the end segment's
    cubic is evaluated (the caller tags those points ``-1``).
    """
    n = x.size
    if n < 3:
        return linear_matrix(x, targets)
    h = np.diff(x)
    # Second derivatives m (n x n operator on y): natural boundary
    # conditions m_0 = m_{n-1} = 0; interior rows solve the standard
    # tridiagonal system.
    system = np.zeros((n - 2, n - 2))
    rhs = np.zeros((n - 2, n))
    for i in range(1, n - 1):
        row = i - 1
        if row > 0:
            system[row, row - 1] = h[i - 1]
        system[row, row] = 2.0 * (h[i - 1] + h[i])
        if row < n - 3:
            system[row, row + 1] = h[i]
        rhs[row, i - 1] += 6.0 / h[i - 1]
        rhs[row, i] -= 6.0 / h[i - 1] + 6.0 / h[i]
        rhs[row, i + 1] += 6.0 / h[i]
    interior = np.linalg.solve(system, rhs)
    m = np.zeros((n, n))
    m[1:-1] = interior
    weights = np.zeros((targets.size, n))
    for row, t in enumerate(targets):
        segment = int(np.clip(np.searchsorted(x, t, side="right") - 1, 0, n - 2))
        lo, hi = x[segment], x[segment + 1]
        dx = hi - lo
        a = (hi - t) / dx
        b = (t - lo) / dx
        # y(t) = a*y_lo + b*y_hi + ((a^3 - a) m_lo + (b^3 - b) m_hi) dx^2 / 6
        weights[row, segment] += a
        weights[row, segment + 1] += b
        weights[row] += (a**3 - a) * dx**2 / 6.0 * m[segment]
        weights[row] += (b**3 - b) * dx**2 / 6.0 * m[segment + 1]
    return weights
