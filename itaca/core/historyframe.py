"""The HistoryFrame origin-tag mirror (SRS 4.3; DD-06).

For each variable, an ``int8`` array of identical shape tags every
value: ``0`` original, ``+1`` interpolated or computed inside the
convex hull, ``-1`` extrapolated outside it. Reductions follow the
worst-case rule (OQ-10).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DataError
from itaca.core.immutable import readonly

VALID_TAGS = (-1, 0, 1)


@dataclass(frozen=True, eq=False)
class HistoryFrame:
    """Origin tags per variable (SRS 4.3).

    Parameters
    ----------
    tags : mapping of str to numpy.ndarray, optional
        Per-variable integer arrays with values in ``{-1, 0, +1}``.
        Stored as ``int8`` copies backed by an immutable buffer, so the
        caller can neither write through them nor restore the write flag
        through them or their base (REQ-102).

    Raises
    ------
    DataError
        If any tag value is outside ``{-1, 0, +1}``.

    Examples
    --------
    >>> import numpy as np
    >>> tags = HistoryFrame(tags={"CT": np.array([0, 1, -1])})
    >>> tags.tags["CT"].dtype
    dtype('int8')
    """

    tags: Mapping[str, NDArray[np.int8]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[str, NDArray[np.int8]] = {}
        for name, values in self.tags.items():
            array = np.asarray(values)
            if not np.isin(array, VALID_TAGS).all():
                raise DataError(
                    f"origin tags of variable '{name}'",
                    "construction with tag values outside {-1, 0, +1}",
                    "use 0 (original), +1 (interpolated/computed), "
                    "-1 (extrapolated); see SRS 4.3",
                )
            normalized[name] = readonly(array, dtype=np.int8)
        object.__setattr__(self, "tags", MappingProxyType(normalized))
