"""db.expand: add a new dimension by broadcast (REQ-23).

Existing arrays are broadcast across the new axis; UncFrame components
and origin tags broadcast unchanged (REQ-98). Memory cost: every
stored array is materialized at the expanded shape, so the footprint
multiplies by the new dimension's cardinality.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.errors import DataError
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild


def expand(
    db: VarFrame,
    dim_name: str,
    values: object,
    axis: int | None = None,
    *,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Add a new dimension, broadcasting existing arrays (REQ-23).

    See ``VarFrame.expand`` for the full parameter description.
    """
    if dim_name in db.dims or dim_name in db.vars:
        holder = "dimension" if dim_name in db.dims else "variable"
        raise DataError(
            f"name '{dim_name}'",
            f"expand would collide with an existing {holder}",
            "choose a name not present in dims or vars (REQ-23)",
        )
    coords = np.asarray(values)
    if coords.ndim != 1:
        raise DataError(
            f"expand values with shape {coords.shape}",
            "the new dimension needs a 1-D coordinate array",
            "pass a flat list or 1-D array of coordinates (REQ-23)",
        )
    if np.unique(coords).size != coords.size:
        raise DataError(
            f"expand values for '{dim_name}'",
            "coordinates contain duplicates",
            "grid coordinates must be unique along a dimension",
        )
    ndim = len(db.dims)
    position = ndim if axis is None else axis
    if not -ndim - 1 <= position <= ndim:
        raise DataError(
            f"axis {axis}",
            f"expand on a VarFrame with {ndim} dimension(s)",
            f"pass axis in [0, {ndim}] (default: last position)",
        )
    if position < 0:
        position += ndim + 1
    is_numeric = bool(np.issubdtype(coords.dtype, np.number))
    new_dim = Dimension(name=dim_name, coords=coords, is_numeric=is_numeric)

    content = content_of(db)
    n = new_dim.cardinality
    old_shape = content.shape
    new_shape = (*old_shape[:position], n, *old_shape[position:])

    def _broadcast(array: NDArray[Any]) -> NDArray[Any]:
        return np.broadcast_to(np.expand_dims(array, position), new_shape).copy()

    def _broadcast_all(
        arrays: dict[str, NDArray[Any]] | None,
    ) -> dict[str, NDArray[Any]] | None:
        if arrays is None:
            return None
        return {name: _broadcast(array) for name, array in arrays.items()}

    dims = list(content.dims.items())
    dims.insert(position, (dim_name, new_dim))
    content.dims = dict(dims)
    content.values = {name: _broadcast(v) for name, v in content.values.items()}
    content.systematic = _broadcast_all(content.systematic)
    content.random = _broadcast_all(content.random)
    content.tags = _broadcast_all(content.tags)

    operation = f"expand(dim='{dim_name}', n={n}, axis={position})"
    return rebuild(db, content, operation=operation, comment=comment, history=history)
