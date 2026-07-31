"""Arrays the caller cannot make writeable again (REQ-102).

``setflags(write=False)`` is not enough on its own. An array that owns
its own memory can have the flag set straight back to ``True``, so a
public array handed out with ``write=False`` could be re-enabled and
written, mutating recorded state with a changed state hash and no
History entry (FND-071).

NumPy will not re-enable the flag on a VIEW whose base is itself not
writeable. So the array is stored as a read-only view OF a read-only
base: the caller holds the view, nothing holds a writeable reference to
the base, and ``setflags(write=True)`` raises ``ValueError``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray


def readonly(values: Any, *, dtype: Any = None) -> NDArray[Any]:
    """Return a read-only view of a private read-only copy of ``values``.

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
        A view whose ``writeable`` flag is ``False`` and cannot be set
        back to ``True``, because its base is read-only too.

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
    >>> protected.copy().flags.writeable
    True
    """
    base = np.array(values, dtype=dtype, copy=True)
    base.setflags(write=False)
    view = base.view()
    view.setflags(write=False)
    return view
