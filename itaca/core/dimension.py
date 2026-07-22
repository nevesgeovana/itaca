"""The Dimension coordinate object (SRS 4.1.3).

A Dimension holds a 1-D coordinate array plus optional unit metadata.
The unit field is metadata only; conversion happens exclusively through
``utils.units.convert`` on demand (DD-13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DataError


@dataclass(frozen=True, eq=False)
class Dimension:
    """A named 1-D coordinate axis of a VarFrame.

    Parameters
    ----------
    name : str
        Dimension name, e.g. ``"alpha"``.
    coords : numpy.ndarray
        1-D coordinate array. Stored as a read-only copy (REQ-102).
    unit : str or None, optional
        Unit label, e.g. ``"deg"``. Metadata only.
    description : str or None, optional
        Free-text description.
    is_numeric : bool, optional
        ``False`` for string-valued dimensions (e.g. blade type sweeps).
        Numerical operations on non-numeric dimensions raise
        ``NonNumericDimensionError`` (SRS 4.1.3).

    Raises
    ------
    DataError
        If ``coords`` is not 1-D, or its dtype disagrees with
        ``is_numeric``.

    Examples
    --------
    >>> import numpy as np
    >>> alpha = Dimension(name="alpha", coords=np.array([0.0, 2.0]), unit="deg")
    >>> alpha.cardinality
    2
    """

    name: str
    coords: NDArray[Any]
    unit: str | None = None
    description: str | None = None
    is_numeric: bool = True

    def __post_init__(self) -> None:
        coords = np.asarray(self.coords)
        if coords.ndim != 1:
            raise DataError(
                f"Dimension '{self.name}'",
                f"construction with a {coords.ndim}-D coordinate array",
                "provide a 1-D coordinate array",
            )
        is_number = bool(np.issubdtype(coords.dtype, np.number))
        if self.is_numeric and not is_number:
            raise DataError(
                f"Dimension '{self.name}'",
                f"construction with non-numeric coordinates (dtype {coords.dtype})",
                "pass is_numeric=False for string-valued dimensions",
            )
        if not self.is_numeric:
            if is_number:
                raise DataError(
                    f"Dimension '{self.name}'",
                    "construction with is_numeric=False but numeric coordinates",
                    "drop is_numeric=False or provide string coordinates",
                )
            coords = coords.astype(np.str_)
        coords = coords.copy()
        coords.setflags(write=False)
        object.__setattr__(self, "coords", coords)

    @property
    def cardinality(self) -> int:
        """Number of coordinate entries along this dimension."""
        return int(self.coords.shape[0])
