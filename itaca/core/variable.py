"""The Variable data object (SRS 4.1.4).

A Variable wraps an N-D numeric NumPy array whose shape is dictated by
the parent VarFrame's dimension order. The unit field is metadata only
(DD-13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DataError


@dataclass(frozen=True, eq=False)
class Variable:
    """A named N-D numeric array with optional metadata.

    Parameters
    ----------
    name : str
        Variable name, e.g. ``"CT"``.
    values : numpy.ndarray
        Numeric N-D array. Stored as a read-only copy (REQ-102).
        Missing combinations are ``np.nan`` (SRS 4.1.2).
    unit : str or None, optional
        Unit label, e.g. ``"N"``. Metadata only.
    description : str or None, optional
        Free-text description.
    long_name : str or None, optional
        Plot label, e.g. ``"Thrust coefficient"``.

    Raises
    ------
    DataError
        If ``values`` is not a numeric array.

    Examples
    --------
    >>> import numpy as np
    >>> ct = Variable(name="CT", values=np.zeros((3, 2)))
    >>> ct.values.shape
    (3, 2)
    """

    name: str
    values: NDArray[Any]
    unit: str | None = None
    description: str | None = None
    long_name: str | None = None

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        if not np.issubdtype(values.dtype, np.number):
            raise DataError(
                f"Variable '{self.name}'",
                f"construction with non-numeric values (dtype {values.dtype})",
                "variables hold numeric arrays; use np.nan for missing entries",
            )
        values = values.copy()
        values.setflags(write=False)
        object.__setattr__(self, "values", values)
