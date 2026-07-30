"""Shared polynomial-degree validation (REQ-25, REQ-26, REQ-29 to REQ-31).

Every public ``deg`` and ``polyorder`` parameter means the same thing,
so it is validated in one place. Before this, only ``fitmodel`` checked
the lower bound: ``interpolate(method='polyfit', deg=-1)`` built an
all-zero weight matrix and returned zeros over data that was a straight
line, silently, and ``fill`` reached NumPy and raised a bare
``ValueError`` from outside the ITACA hierarchy (ITACA-033).

The rule lives here rather than on ``FitDegreeError`` because that leaf
means "too few points for this degree" (REQ-30), which is a different
invariant: it depends on the data, and this one does not.
"""

from __future__ import annotations

from itaca.core.errors import DataError


def require_nonnegative_degree(
    value: object, *, operation: str, parameter: str, req: str
) -> None:
    """Refuse a negative polynomial degree at a public boundary.

    Parameters
    ----------
    value : object
        The degree the caller passed. Not typed as ``int``, because
        checking the type is half of what this does: a non-integer reached
        ``<`` and escaped as a bare ``TypeError`` from outside the ITACA
        hierarchy, and ``bool`` passed an ``isinstance`` check upstream and
        was recorded as ``deg=True`` in provenance.
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
        ``value`` is not an integer (``bool`` included), or is negative.

    Examples
    --------
    >>> require_nonnegative_degree(
    ...     2, operation="fitmodel", parameter="deg", req="REQ-31"
    ... )
    """
    # TYPE first, because `<` against a non-number raises a bare
    # TypeError from outside the ITACA hierarchy, and `None` is the value
    # a reader of a signature whose default used to be `None` writes.
    # `bool` is excluded explicitly: it is an `int` subclass, so
    # `deg=True` passed and was recorded as `deg=True` in provenance.
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataError(
            f"{parameter}={value!r}",
            f"{operation} needs an integer polynomial degree, and received "
            f"{type(value).__name__}",
            f"pass an int for {parameter}, or omit it where the method does "
            f"not consume one ({req})",
        )
    if value < 0:
        raise DataError(
            f"{parameter}={value}",
            f"{operation} needs a nonnegative polynomial degree",
            f"pass {parameter} >= 0 ({req})",
        )
