"""db.diff: moving-polynomial numerical differentiation (REQ-30).

The derivative is returned as a new VarFrame whose variables follow
the ``dVAR_ddim`` naming convention; ``db.d[dim]`` is indexer sugar
computing the same with default parameters (REQ-18 immutability:
nothing is stored on the source frame). Uncertainty present raises
until OQ-18 freezes the moving-fit weight rule (the provisional
smooth/diff row of REQ-98). Output tags carry the worst case over
each moving window (OQ-10).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    DimensionNotFoundError,
    FitDegreeError,
    NonNumericDimensionError,
    UncertaintyError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild
from itaca.ops._movingfit import moving_fit_line, window_tags_line

_Array = NDArray[Any]


class DiffIndexer:
    """``db.d[dim]``: derivative with default parameters (REQ-30).

    Examples
    --------
    >>> import numpy as np
    >>> import itaca as itc
    >>> arr = np.column_stack([np.arange(5.0), np.arange(5.0) ** 2])
    >>> db = itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])
    >>> list(db.d["alpha"].vars)
    ['dCL_dalpha']
    """

    def __init__(self, db: VarFrame) -> None:
        self._db = db

    def __getitem__(self, dim: str) -> VarFrame:
        if not isinstance(dim, str):
            raise DimensionNotFoundError(
                f"index {dim!r}",
                "the db.d[...] indexer takes a single dimension name",
                "pass one dimension string, e.g. db.d['alpha'] (REQ-30)",
            )
        return diff(self._db, along=dim)


def diff(
    db: VarFrame,
    *,
    along: str,
    window: int = 5,
    deg: int = 2,
    nan_edges: bool = False,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Differentiate all variables along a dimension (REQ-30).

    See ``VarFrame.diff`` for the full parameter description.
    """
    if along not in db.dims:
        raise DimensionNotFoundError(
            f"dimension '{along}'",
            "diff(along=...) referenced an absent dimension",
            f"available dimensions: {list(db.dims)}",
        )
    if not db.dims[along].is_numeric:
        raise NonNumericDimensionError(
            f"dimension '{along}'",
            "diff along a string-valued dimension",
            "numerical operations need numeric coordinates (SRS 4.1.3)",
        )
    if window <= deg:
        raise FitDegreeError(
            f"window {window} against deg {deg}",
            "the moving polynomial fit needs more points than the degree",
            "increase window so that window > deg (REQ-30)",
        )
    if db.uncertainty is not None:
        raise UncertaintyError(
            "diff",
            "uncertainty propagation through moving-fit weights is not "
            "frozen yet (REQ-98 provisional row, OQ-18)",
            "diff before assigning uncertainty; the rule freezes during v0.2.0",
        )

    content = content_of(db)
    axis = list(content.dims).index(along)
    x = np.asarray(content.dims[along].coords, dtype=float)
    n = x.size
    dim_unit = content.dims[along].unit
    tags = content.tags if content.tags is not None else {}

    new_values: dict[str, _Array] = {}
    new_meta: dict[str, Any] = {}
    new_tags: dict[str, _Array] = {}
    has_tags = content.tags is not None
    for name, values in content.values.items():
        out_name = f"d{name}_d{along}"
        moved = np.moveaxis(values, axis, -1).copy()
        flat = moved.reshape(-1, n)
        for row in range(flat.shape[0]):
            fitted, asymmetric = moving_fit_line(x, flat[row], window, deg, True)
            if nan_edges:
                fitted = np.where(asymmetric, np.nan, fitted)
            flat[row] = fitted
        new_values[out_name] = np.moveaxis(flat.reshape(moved.shape), -1, axis)
        meta = content.meta[name]
        var_unit = getattr(meta, "unit", None)
        out_unit = f"{var_unit}/{dim_unit}" if var_unit and dim_unit else None
        new_meta[out_name] = replace(
            meta, name=out_name, values=new_values[out_name], unit=out_unit
        )
        if has_tags:
            source = tags.get(name, np.zeros(content.shape, dtype=np.int8))
            moved_t = np.moveaxis(source, axis, -1).copy()
            flat_t = moved_t.reshape(-1, n)
            for row in range(flat_t.shape[0]):
                flat_t[row] = window_tags_line(flat_t[row], window)
            new_tags[out_name] = np.moveaxis(flat_t.reshape(moved_t.shape), -1, axis)

    content.values = new_values
    content.meta = new_meta
    content.tags = new_tags if has_tags else None
    operation = (
        f"diff(along='{along}', window={window}, deg={deg}, nan_edges={nan_edges})"
    )
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        method="diff",
        replay_kwargs={
            "along": along,
            "window": window,
            "deg": deg,
            "nan_edges": nan_edges,
        },
    )
