"""db.select with operators and Frame targeting, and db.at (REQ-20, REQ-21)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    SelectionError,
    UncertaintyError,
    UncertaintyKeyError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import Content, content_of, rebuild, take

_COMPARATORS: dict[str, Callable[..., NDArray[np.bool_]]] = {
    ">": np.greater,
    ">=": np.greater_equal,
    "<": np.less,
    "<=": np.less_equal,
    "!=": np.not_equal,
}
_FRAMES = ("VarFrame", "UncFrame", "HistoryFrame")


def _parse_key(key: str) -> tuple[str, str]:
    for token in (">=", "<=", "!="):
        if key.endswith(token):
            return key[: -len(token)], token
    for token in (">", "<", "="):
        if key.endswith(token):
            return key[: -len(token)], token
    return key, "="


def _dim_indices(db: VarFrame, name: str, op: str, value: object) -> NDArray[np.intp]:
    coords = db.dims[name].coords
    if op == "=":
        targets = np.atleast_1d(np.asarray(value))
        present = np.isin(targets, coords)
        if not present.all():
            missing = targets[~present].tolist()
            raise SelectionError(
                f"dimension '{name}'",
                f"select requested absent coordinate(s) {missing}",
                f"available coordinates: {coords.tolist()}",
            )
        indices = np.nonzero(np.isin(coords, targets))[0]
    else:
        indices = np.nonzero(_COMPARATORS[op](coords, value))[0]
    if indices.size == 0:
        raise SelectionError(
            f"dimension '{name}'",
            f"select filter '{name}{op}' matched no coordinate",
            f"available coordinates: {coords.tolist()}",
        )
    return indices


def _condition_source(
    db: VarFrame, content: Content, name: str, frame: str
) -> NDArray[Any]:
    if name not in content.values:
        raise SelectionError(
            f"key '{name}'",
            "select key is neither a dimension nor a variable",
            "check the names listed by db.summary()",
        )
    if frame == "VarFrame":
        return content.values[name]
    if frame == "UncFrame":
        if content.systematic is None and content.random is None:
            raise UncertaintyError(
                f"variable '{name}'",
                "select with Frame='UncFrame' on a VarFrame without uncertainty",
                "assign uncertainty first via db.set_uncertainty (REQ-39)",
            )
        parts = []
        for component in (content.systematic, content.random):
            if component is not None and name in component:
                parts.append(np.square(component[name]))
        if not parts:
            raise UncertaintyKeyError(
                f"variable '{name}'",
                "select with Frame='UncFrame' found no component for it",
                "assign one via db.set_uncertainty (REQ-39)",
            )
        return np.asarray(np.sqrt(sum(parts)))
    # HistoryFrame: absent tags mean every value is original (lazy).
    if content.tags is not None and name in content.tags:
        return content.tags[name]
    return np.zeros(content.shape, dtype=np.int8)


def select(
    db: VarFrame,
    filters: Mapping[str, object],
    *,
    frame: str = "VarFrame",
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Restrict a VarFrame by coordinate subsets and cell masks (REQ-20).

    See ``VarFrame.select`` for the full parameter description.
    """
    if frame not in _FRAMES:
        raise DataError(
            f"Frame={frame!r}",
            "select received an unknown Frame target",
            f"use one of {_FRAMES}",
        )
    dim_indexers: dict[str, NDArray[np.intp]] = {}
    conditions: list[tuple[str, str, object]] = []
    for key, value in filters.items():
        name, op = _parse_key(key)
        if frame == "VarFrame" and name in db.dims:
            dim_indexers[name] = _dim_indices(db, name, op, value)
        else:
            conditions.append((name, op, value))
    content = take(content_of(db), dim_indexers)
    masked = 0
    if conditions:
        mask = np.ones(content.shape, dtype=bool)
        for name, op, value in conditions:
            source = _condition_source(db, content, name, frame)
            if op == "=":
                mask &= np.isin(source, np.atleast_1d(np.asarray(value)))
            else:
                mask &= _COMPARATORS[op](source, value)
        masked = int((~mask).sum())
        if not mask.any():
            raise SelectionError(
                f"filters {dict(filters)!r}",
                "select masked every cell",
                "loosen the filter or check the values with db.summary()",
            )
        content.values = {
            name: np.where(mask, values, np.nan)
            for name, values in content.values.items()
        }
        for component_name in ("systematic", "random"):
            component = getattr(content, component_name)
            if component is not None:
                setattr(
                    content,
                    component_name,
                    {
                        name: np.where(mask, values, np.nan)
                        for name, values in component.items()
                    },
                )
        drop_indexers: dict[str, NDArray[np.intp]] = {}
        for axis, name in enumerate(content.dims):
            other_axes = tuple(a for a in range(len(content.dims)) if a != axis)
            keep = mask.any(axis=other_axes) if other_axes else mask
            if not keep.all():
                drop_indexers[name] = np.nonzero(keep)[0]
        content = take(content, drop_indexers)
    operation = f"select(filters={dict(filters)!r}, Frame='{frame}', masked={masked})"
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        method="select",
        # The method spells the target Frame with a capital F (REQ-20).
        replay_kwargs={"filters": dict(filters), "Frame": frame},
    )


def at(
    db: VarFrame,
    coords: Mapping[str, object],
    *,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Slice at single coordinates and drop those dims (REQ-21)."""
    from itaca.ops.squeeze import drop_axes

    indexers: dict[str, NDArray[np.intp]] = {}
    for name, value in coords.items():
        if name not in db.dims:
            raise DimensionNotFoundError(
                f"dimension '{name}'",
                "at() referenced a dimension that does not exist",
                f"available dimensions: {list(db.dims)}",
            )
        matches = np.nonzero(db.dims[name].coords == np.asarray(value))[0]
        if matches.size == 0:
            raise SelectionError(
                f"dimension '{name}'",
                f"at() requested absent coordinate {value!r}",
                f"available coordinates: {db.dims[name].coords.tolist()}",
            )
        indexers[name] = matches[:1]
    content = drop_axes(take(content_of(db), indexers), list(coords))
    arguments = ", ".join(f"{k}={v!r}" for k, v in coords.items())
    return rebuild(
        db,
        content,
        operation=f"at({arguments})",
        comment=comment,
        history=history,
    )
