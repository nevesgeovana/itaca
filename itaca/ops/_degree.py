"""Shared polynomial-degree validation (REQ-25, REQ-26, REQ-29 to REQ-31).

Every public ``deg`` and ``polyorder`` parameter means the same thing,
so it is validated in one place. Before this, only ``fitmodel`` checked
the lower bound: ``interpolate(method='polyfit', deg=-1)`` built an
all-zero weight matrix and returned zeros over data that was a straight
line, silently, and ``fill`` reached NumPy and raised a bare
``ValueError`` from outside the ITACA hierarchy (ITACA-033).

The rule lives here rather than on ``FitDegreeError`` because that leaf
means "too few points for this degree" (SRS 4.4), which is a different
invariant: it depends on the data, and this one does not.
"""

from __future__ import annotations

from itaca.core.errors import DataError


def require_nonnegative_degree(
    value: int, *, operation: str, parameter: str, req: str
) -> None:
    """Refuse a negative polynomial degree at a public boundary.

    Parameters
    ----------
    value : int
        The degree the caller passed.
    operation : str
        The operation name for the message, e.g.
        ``"interpolate(method='polyfit')"``.
    parameter : str
        The parameter name, ``"deg"`` or ``"polyorder"``.
    req : str
        The requirement id to cite in the suggested fix.

    Returns
    -------
    None

    Raises
    ------
    DataError
        ``value`` is negative.

    Examples
    --------
    >>> require_nonnegative_degree(
    ...     2, operation="fitmodel", parameter="deg", req="REQ-31"
    ... )
    """
    if value < 0:
        raise DataError(
            f"{parameter}={value}",
            f"{operation} needs a nonnegative polynomial degree",
            f"pass {parameter} >= 0 ({req})",
        )
