"""Shared raw-content helpers for structural operations (internal).

A "content" bundle is the raw-array view of a VarFrame: dimensions,
variable arrays, the two uncertainty component dicts, and the tag
arrays. Operations manipulate content and rebuild through
``VarFrame._derive`` so that every path records History and carries
the mirrors explicitly (DD-18): nothing is dropped silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.historyframe import HistoryFrame
from itaca.core.pipeline import PipelineStep, _to_jsonable
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable


@dataclass
class Content:
    """Mutable raw-array view of a VarFrame used inside operations."""

    dims: dict[str, Dimension]
    values: dict[str, NDArray[Any]]
    systematic: dict[str, NDArray[Any]] | None
    random: dict[str, NDArray[Any]] | None
    tags: dict[str, NDArray[Any]] | None
    meta: dict[str, Variable]

    @property
    def shape(self) -> tuple[int, ...]:
        """Grid shape from the dimension order."""
        return tuple(d.cardinality for d in self.dims.values())


def content_of(db: VarFrame) -> Content:
    """Extract the raw-array content of a VarFrame."""
    return Content(
        dims=dict(db.dims),
        values={name: var.values for name, var in db.vars.items()},
        systematic=(
            dict(db.uncertainty.systematic) if db.uncertainty is not None else None
        ),
        random=(dict(db.uncertainty.random) if db.uncertainty is not None else None),
        tags=dict(db.tags.tags) if db.tags is not None else None,
        meta=dict(db.vars),
    )


def recoord(dim: Dimension, coords: NDArray[Any]) -> Dimension:
    """Return a Dimension with new coordinates, metadata preserved."""
    return Dimension(
        name=dim.name,
        coords=coords,
        unit=dim.unit,
        description=dim.description,
        is_numeric=dim.is_numeric,
    )


def take(content: Content, indexers: dict[str, NDArray[np.intp]]) -> Content:
    """Subset the content along the indexed dimensions (REQ-98 subset)."""
    if not indexers:
        return content
    axis_indices = [
        indexers.get(name, np.arange(dim.cardinality))
        for name, dim in content.dims.items()
    ]
    grid = np.ix_(*axis_indices)

    def _cut(arrays: dict[str, NDArray[Any]] | None) -> Any:
        if arrays is None:
            return None
        return {name: array[grid] for name, array in arrays.items()}

    return Content(
        dims={
            name: (
                recoord(dim, dim.coords[indexers[name]]) if name in indexers else dim
            )
            for name, dim in content.dims.items()
        },
        values=_cut(content.values),
        systematic=_cut(content.systematic),
        random=_cut(content.random),
        tags=_cut(content.tags),
        meta=content.meta,
    )


def rebuild(
    db: VarFrame,
    content: Content,
    *,
    operation: str,
    comment: str | None,
    history: bool,
    call: str | None = None,
    replay_kwargs: Mapping[str, Any] | None = None,
) -> VarFrame:
    """Wrap content back into frames and derive the new VarFrame.

    When ``call`` is given, the operation is replayable: a
    :class:`PipelineStep` is recorded, carrying the comment too (REQ-19),
    so ``history.to_pipeline`` can reconstruct the call (REQ-54).
    Operations that omit ``call`` (a multi-input ``concat``) are
    non-replayable by construction.
    """
    variables = {
        name: replace(content.meta[name], values=values)
        for name, values in content.values.items()
    }
    uncertainty = None
    if content.systematic is not None or content.random is not None:
        uncertainty = UncFrame(
            systematic=content.systematic or {},
            random=content.random or {},
        )
    tags = HistoryFrame(tags=content.tags) if content.tags is not None else None
    step = (
        PipelineStep(
            call=call,
            kwargs={
                name: _to_jsonable(value)
                for name, value in (replay_kwargs or {}).items()
            },
            comment=comment,
        )
        if call is not None
        else None
    )
    return db._derive(
        operation=operation,
        comment=comment,
        history=history,
        dims=content.dims,
        variables=variables,
        uncertainty=uncertainty,
        tags=tags,
        step=step,
    )
