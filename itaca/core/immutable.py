"""Arrays the caller cannot make writeable again (REQ-102).

``setflags(write=False)`` is not enough on its own. An array that owns
its own memory can have the flag set straight back to ``True``, so a
public array handed out with ``write=False`` could be re-enabled and
written, mutating recorded state with a changed state hash and no
History entry (FND-071).

A read-only VIEW of a read-only ndarray is not enough either, and the
reason is worth stating because it is the trap this module exists to
avoid. NumPy refuses to re-enable the flag on a view whose base is not
writeable, so the one-step attack fails. But the base is reachable as
``array.base``, and an ndarray that OWNS its memory may always
re-enable its own flag, so a two-step attack restores the defect
exactly::

    values.base.setflags(write=True)   # the owner allows itself
    values.setflags(write=True)        # now the view allows it too
    values[0] = 99.0                   # state mutated, nothing recorded

So the array is backed by an immutable ``bytes`` buffer instead. The
ownership chain is ``view -> ndarray -> bytes``, and it terminates in an
object that has no ``setflags`` at all, so there is no owner anywhere
along it that can grant write access.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DataError


def readonly(values: Any, *, dtype: Any = None) -> NDArray[Any]:
    """Return an array backed by an immutable buffer.

    Parameters
    ----------
    values : array-like
        The data to protect. It is copied, so the caller's array is
        never the one stored.
    dtype : data-type, optional
        Coerce to this dtype while copying.

    Returns
    -------
    numpy.ndarray
        An array whose ``writeable`` flag is ``False`` and cannot be set
        back to ``True`` through it or through anything reachable from
        its ``base``.

    Raises
    ------
    DataError
        If the data has ``object`` dtype. Such an array stores POINTERS,
        so copying it through a byte buffer would produce an array of
        addresses rather than of values. No caller passes one today; the
        refusal is here so that a future one cannot introduce it
        silently.

    Examples
    --------
    >>> import numpy as np
    >>> protected = readonly(np.array([1.0, 2.0]))
    >>> protected.flags.writeable
    False
    >>> protected.setflags(write=True)
    Traceback (most recent call last):
        ...
    ValueError: cannot set WRITEABLE flag to True of this array
    >>> protected.base.setflags(write=True)
    Traceback (most recent call last):
        ...
    ValueError: cannot set WRITEABLE flag to True of this array
    >>> protected.copy().flags.writeable
    True
    """
    source = np.array(values, dtype=dtype, copy=True, order="C")
    if source.dtype == object:
        raise DataError(
            f"an array of dtype {source.dtype}",
            "read-only protection of an object array, whose buffer holds "
            "pointers rather than values",
            "pass a numeric or string array; object arrays are not part of "
            "the VarFrame data model (REQ-102, SRS 4.1.4)",
        )
    buffered = np.frombuffer(source.tobytes(), dtype=source.dtype)
    return buffered.reshape(source.shape)
