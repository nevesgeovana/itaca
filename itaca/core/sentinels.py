"""Typed no-default sentinel (REQ-105).

A single sentinel object, ``itc.no_default``, distinguishes an argument
that was not passed from an argument explicitly set to ``None`` in
signatures where ``None`` is meaningful. It is an enum singleton so the
type is expressible in annotations and ``mypy --strict`` narrows the
``is`` identity check. Annotate parameters with ``NoDefault``, imported
from this module (``from itaca.core.sentinels import NoDefault``); the
``Literal`` spelling is reserved for the typed constant at the bottom
of this module.

Adoption contract for public signatures (REQ-105): declare
``no_default`` as the default wherever not-passed must be distinguished
from an explicit ``None``; branch with ``value is no_default``; and
raise wherever the sentinel arrives as a value and is not the declared
default, so it can never act as data. The raise is enforced per
adopting signature (M1 Phase B1 onward), not by this module.
"""

from enum import Enum
from typing import Final, Literal

__all__ = ["NoDefault", "no_default", "reject_no_default"]


class NoDefault(Enum):
    """Type of the :data:`no_default` sentinel (REQ-105).

    A single-member enum: annotate parameters with ``NoDefault`` in a
    union with the real parameter types, and test with
    ``value is no_default``.

    Examples
    --------
    >>> import itaca as itc
    >>> from itaca.core.sentinels import NoDefault
    >>> def resample(
    ...     weights: list[float] | None | NoDefault = itc.no_default,
    ... ) -> str:
    ...     if weights is itc.no_default:
    ...         return "not passed"
    ...     return "disabled" if weights is None else "passed"
    >>> resample()
    'not passed'
    >>> resample(None)
    'disabled'
    """

    no_default = "no_default"

    def __repr__(self) -> str:
        return "<no_default>"

    __str__ = __repr__


no_default: Final[Literal[NoDefault.no_default]] = NoDefault.no_default
"""The sentinel marking an argument that was not passed (REQ-105)."""


def reject_no_default(value: object, obj: str, operation: str) -> None:
    """Raise if ``value`` is the sentinel where it is not the default.

    The shared enforcement helper for the REQ-105 raise clause: an
    adopting signature calls this on every parameter whose declared
    default is not ``no_default``, so the sentinel can never act as a
    data value.

    Parameters
    ----------
    value : object
        The received argument.
    obj : str
        The object part of the three-part message (REQ-81).
    operation : str
        The operation part of the three-part message.

    Raises
    ------
    DataError
        ``value`` is the sentinel.

    Examples
    --------
    >>> reject_no_default(0.5, "smooth(method=...)", "method resolution")
    >>> reject_no_default(
    ...     no_default, "smooth(method=...)", "method resolution"
    ... )  # doctest: +ELLIPSIS
    Traceback (most recent call last):
    itaca.core.errors.DataError: ...
    """
    if value is no_default:
        from itaca.core.errors import DataError

        raise DataError(
            obj,
            f"{operation} received the no_default sentinel where it "
            "is not the declared default",
            "omit the argument or pass a real value (REQ-105)",
        )
