"""db.average: collapse dimensions by arithmetic mean (REQ-27).

The mean is taken jointly over every collapsed cell, skipping NaN.
Uncertainty follows the reduction rules of REQ-98/REQ-99: the random
component gains 1/sqrt(N) over the populated cells, the systematic
component is fully correlated and keeps its magnitude. Tags follow
the worst-case rule (OQ-10).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DimensionNotFoundError
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild
from itaca.ops._reduction import (
    reduce_random,
    reduce_systematic,
    reduce_tags,
    reduced_dims,
)


def average(
    db: VarFrame,
    *,
    along: str | list[str],
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Collapse dimensions by the mean of non-NaN values (REQ-27).

    See ``VarFrame.average`` for the full parameter description.
    """
    names = [along] if isinstance(along, str) else list(along)
    for name in names:
        if name not in db.dims:
            raise DimensionNotFoundError(
                f"dimension '{name}'",
                "average(along=...) referenced an absent dimension",
                f"available dimensions: {list(db.dims)}",
            )
    content = content_of(db)
    order = list(content.dims)
    axes = tuple(sorted(order.index(name) for name in names))
    keep_scalar = len(names) == len(order)

    def _finish(array: NDArray[Any]) -> NDArray[Any]:
        return array.reshape((1,)) if keep_scalar else array

    new_values: dict[str, NDArray[Any]] = {}
    new_sys: dict[str, NDArray[Any]] = {}
    new_rand: dict[str, NDArray[Any]] = {}
    new_tags: dict[str, NDArray[Any]] = {}
    for name, values in content.values.items():
        finite = np.isfinite(values)
        counts = np.sum(finite, axis=axes)
        with np.errstate(invalid="ignore"):
            mean = np.where(
                counts > 0,
                np.nansum(np.where(finite, values, 0.0), axis=axes)
                / np.maximum(counts, 1),
                np.nan,
            )
        new_values[name] = _finish(np.asarray(mean))
        # Per-cell mean weights 1/N over the populated cells; collapse
        # the joint axes one at a time by moving them last.
        weights = np.where(
            finite,
            1.0 / np.maximum(np.expand_dims(counts, axes), 1),
            0.0,
        )
        moved_w = np.moveaxis(weights, axes, range(-len(axes), 0))
        flat_w = moved_w.reshape(*moved_w.shape[: -len(axes)], -1)
        for label, store, rule in (
            ("systematic", new_sys, reduce_systematic),
            ("random", new_rand, reduce_random),
        ):
            component = getattr(content, label)
            if component is not None and name in component:
                moved_u = np.moveaxis(
                    component[name], axes, range(-len(axes), 0)
                ).reshape(flat_w.shape)
                store[name] = _finish(rule(flat_w, moved_u, -1))
        if content.tags is not None and name in content.tags:
            moved_t = np.moveaxis(
                content.tags[name], axes, range(-len(axes), 0)
            ).reshape(flat_w.shape)
            new_tags[name] = _finish(reduce_tags(moved_t, flat_w != 0.0, -1))

    content.dims = reduced_dims(content, names)
    content.values = new_values
    content.systematic = new_sys if content.systematic is not None else None
    content.random = new_rand if content.random is not None else None
    content.tags = new_tags if content.tags is not None else None
    operation = f"average(along={names})"
    return rebuild(db, content, operation=operation, comment=comment, history=history)
