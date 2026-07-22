"""db.squeeze: remove unit-cardinality dimensions (REQ-22)."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.errors import DataError, DimensionNotFoundError
from itaca.core.varframe import VarFrame
from itaca.ops._content import Content, content_of, rebuild

DATAPOINT_DIM = "datapoint"


def drop_axes(content: Content, names: list[str]) -> Content:
    """Remove the named axes from every array in the content bundle.

    When every dimension is removed, a single ``datapoint`` dimension
    with one entry holds the scalar values (REQ-22).
    """
    order = list(content.dims)
    axes = tuple(order.index(name) for name in names)
    remaining = {name: dim for name, dim in content.dims.items() if name not in names}
    fully_squeezed = not remaining

    def _cut(arrays: dict[str, NDArray[Any]] | None) -> Any:
        if arrays is None:
            return None
        if not fully_squeezed:
            return {
                name: np.squeeze(array, axis=axes) for name, array in arrays.items()
            }
        return {name: array.reshape((1,)) for name, array in arrays.items()}

    if fully_squeezed:
        remaining = {
            DATAPOINT_DIM: Dimension(
                name=DATAPOINT_DIM,
                coords=np.arange(1),
                description="fully squeezed scalar holder (REQ-22)",
            )
        }
    return Content(
        dims=remaining,
        values=_cut(content.values),
        systematic=_cut(content.systematic),
        random=_cut(content.random),
        tags=_cut(content.tags),
        meta=content.meta,
    )


def squeeze(
    db: VarFrame,
    *,
    along: str | None = None,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Remove unit-cardinality dimensions (REQ-22).

    See ``VarFrame.squeeze`` for the full parameter description.
    """
    if along is not None:
        if along not in db.dims:
            raise DimensionNotFoundError(
                f"dimension '{along}'",
                "squeeze(along=...) referenced an absent dimension",
                f"available dimensions: {list(db.dims)}",
            )
        if db.dims[along].cardinality != 1:
            raise DataError(
                f"dimension '{along}'",
                f"squeeze(along='{along}') on cardinality {db.dims[along].cardinality}",
                "squeeze removes only unit-cardinality dimensions "
                "(REQ-22); select a single coordinate first",
            )
        names = [along]
    else:
        names = [name for name, dim in db.dims.items() if dim.cardinality == 1]
        if not names:
            raise DataError(
                "VarFrame",
                "squeeze() found no unit-cardinality dimension",
                "check cardinalities with db.summary(); there is no silent no-op",
            )
    content = drop_axes(content_of(db), names)
    return rebuild(
        db,
        content,
        operation=f"squeeze(along={names})",
        comment=comment,
        history=history,
    )
