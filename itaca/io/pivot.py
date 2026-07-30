"""db.pivot and the shared grid-assembly machinery (REQ-14).

The same assembly turns a flat row table into a structured grid for
both ``db.pivot`` and structured ``itc.load`` modes. Duplicate
coordinates fail loud (``PivotDuplicateError``): real acquisition
tables contain untagged repeats as the norm, and silently keeping one
row would destroy evidence.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    DuplicateNameError,
    PivotDuplicateError,
    PivotError,
)
from itaca.core.history import compute_state_hash
from itaca.core.historyframe import HistoryFrame
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable

logger = logging.getLogger(__name__)

DATAPOINT_DIM = "datapoint"


def is_datapoint(db: VarFrame) -> bool:
    """Return True when the VarFrame is in datapoint mode (REQ-01)."""
    return list(db.dims) == [DATAPOINT_DIM]


def _is_numeric(array: NDArray[Any]) -> bool:
    return bool(np.issubdtype(np.asarray(array).dtype, np.number))


def reject_repeated_names(
    names: Sequence[str],
    *,
    origin: str,
    role: str,
    consequence: str,
    req: str,
) -> None:
    """Refuse a repeated name at an ingestion boundary (REQ-01, REQ-04).

    The single enforcement point for the name-uniqueness invariant. Every
    boundary that turns a list of names into keys of a mapping needs it,
    because a repeat collapses two sources into one key and the loss is
    silent: the frame simply carries fewer variables than the input had
    columns.

    The consequence differs by boundary, so it is a parameter rather than
    a fixed sentence. A repeated COLUMN discards data; a repeated
    DIMENSION produces a rank mismatch instead, and citing REQ-01 for
    that would be wrong.

    Parameters
    ----------
    names : sequence of str
        The names to check, in source order.
    origin : str
        Where they came from, for the message, e.g. ``"the names= list"``.
    role : str
        What a name IS here, e.g. ``"column name"``.
    consequence : str
        What accepting the repeat would do, in the caller's own terms.
    req : str
        The requirement id to cite in the suggested fix.

    Returns
    -------
    None

    Raises
    ------
    DuplicateNameError
        A name appears more than once.

    Examples
    --------
    >>> reject_repeated_names(
    ...     ["a", "b"],
    ...     origin="the names= list",
    ...     role="column name",
    ...     consequence="one column would be discarded",
    ...     req="REQ-04",
    ... )
    """
    seen: dict[str, int] = {}
    for index, name in enumerate(names):
        if name in seen:
            raise DuplicateNameError(
                f"{role} '{name}' at positions {seen[name]} and {index} "
                f"(0-based) of {origin}",
                consequence,
                f"rename or drop the repeat so every {role} is unique ({req})",
            )
        seen[name] = index


def assemble_grid(
    columns: Mapping[str, NDArray[Any]],
    dim_names: Sequence[str],
    *,
    context: str,
    units: Mapping[str, str | None] | None = None,
) -> tuple[dict[str, Dimension], tuple[NDArray[np.intp], ...], tuple[int, ...]]:
    """Build Dimension objects and grid positions from flat columns.

    Parameters
    ----------
    columns : mapping of str to numpy.ndarray
        Flat columns of equal length (one entry per datapoint).
    dim_names : sequence of str
        Column names that become dimensions, in order.
    context : str
        Operation name used in error messages (e.g. ``"db.pivot"``).
    units : mapping of str to str or None, optional
        Unit metadata per column, carried onto the Dimension objects.

    Returns
    -------
    dims : dict of str to Dimension
        The new dimensions, in the requested order.
    positions : tuple of numpy.ndarray
        Per-dimension grid index of every input row.
    shape : tuple of int
        The grid shape.

    Raises
    ------
    DimensionNotFoundError
        If a requested dimension is not a column.
    DataError
        If a numeric dimension column contains NaN.
    PivotDuplicateError
        If two rows share identical coordinates on every requested
        dimension (REQ-14).
    DuplicateNameError
        If a dimension name is requested more than once.
    """
    units = units or {}
    dims: dict[str, Dimension] = {}
    positions: list[NDArray[np.intp]] = []
    reject_repeated_names(
        list(dim_names),
        origin=f"the dims= list passed to {context}",
        role="dimension name",
        consequence=(
            "the repeat collapses into a single dimension while one grid "
            "position per requested name is still produced, so the grid "
            "rank and the index rank disagree"
        ),
        req="REQ-14",
    )
    for name in dim_names:
        if name not in columns:
            available = ", ".join(sorted(columns))
            raise DimensionNotFoundError(
                f"dimension '{name}'",
                f"{context} referenced a column that does not exist",
                f"use one of: {available}",
            )
        column = np.asarray(columns[name])
        if _is_numeric(column):
            if np.isnan(column.astype(float)).any():
                raise DataError(
                    f"dimension column '{name}'",
                    f"{context} found NaN coordinate values",
                    "coordinates must be complete; fill or drop those rows",
                )
            coords = np.unique(column)
            positions.append(np.searchsorted(coords, column))
            dims[name] = Dimension(name=name, coords=coords, unit=units.get(name))
        else:
            text = column.astype(str)
            coords = np.unique(text)
            lookup = {value: index for index, value in enumerate(coords)}
            positions.append(
                np.asarray([lookup[value] for value in text], dtype=np.intp)
            )
            dims[name] = Dimension(
                name=name,
                coords=coords,
                unit=units.get(name),
                is_numeric=False,
            )
    shape = tuple(d.cardinality for d in dims.values())
    _reject_duplicates(tuple(positions), shape, dims, context)
    return dims, tuple(positions), shape


def _reject_duplicates(
    positions: tuple[NDArray[np.intp], ...],
    shape: tuple[int, ...],
    dims: Mapping[str, Dimension],
    context: str,
) -> None:
    if not positions or positions[0].size == 0:
        return
    flat = np.ravel_multi_index(positions, shape)
    unique, counts = np.unique(flat, return_counts=True)
    duplicated = unique[counts > 1]
    if duplicated.size:
        first = np.unravel_index(duplicated[0], shape)
        collision = ", ".join(
            f"{name}={dim.coords[position]!r}"
            for (name, dim), position in zip(dims.items(), first, strict=True)
        )
        raise PivotDuplicateError(
            f"{duplicated.size} coordinate collision(s), first at ({collision})",
            f"{context} found datapoints sharing identical coordinates on "
            "every requested dimension",
            "add a repeat dimension or deduplicate upstream; keeping one "
            "row silently would destroy evidence",
        )


def place_on_grid(
    values: NDArray[Any],
    positions: tuple[NDArray[np.intp], ...],
    shape: tuple[int, ...],
    *,
    fill: float = np.nan,
    dtype: Any = float,
) -> NDArray[Any]:
    """Scatter flat row values onto the grid, filling gaps (REQ-06)."""
    grid = np.full(shape, fill, dtype=dtype)
    grid[positions] = values
    return grid


def pivot(
    db: VarFrame,
    dims: Sequence[str] | None = None,
    *,
    auto_detect: bool = False,
    threshold: int = 20,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Reorganize a datapoint-mode VarFrame into a structured one (REQ-14).

    Parameters
    ----------
    db : VarFrame
        A datapoint-mode VarFrame.
    dims : sequence of str or None, optional
        Columns that become dimensions, in order.
    auto_detect : bool, optional
        Detect additional numeric dimension candidates by unique-value
        count (at most ``threshold`` unique values). The resolved dim
        list is reported as feedback.
    threshold : int, optional
        Unique-value bound for auto-detection, 20 by default (REQ-13).
    history : bool, optional
        In draft mode, record the operation only when True (REQ-10).
    comment : str or None, optional
        User comment for the History entry (REQ-19).

    Returns
    -------
    VarFrame
        A new structured VarFrame; ``db`` is unchanged (REQ-18).

    Raises
    ------
    PivotError
        On an already-structured VarFrame, or without dims and without
        auto-detection.
    PivotDuplicateError
        When datapoints collide on every requested dimension.
    """
    if not is_datapoint(db):
        raise PivotError(
            "VarFrame",
            "pivot() called on an already-structured VarFrame",
            "pivot applies to datapoint mode only (REQ-14)",
        )
    requested = list(dims or [])
    if auto_detect:
        for name, variable in db.vars.items():
            if name in requested or not _is_numeric(variable.values):
                continue
            finite = variable.values[np.isfinite(variable.values)]
            n_unique = np.unique(finite).size
            # A dimension candidate repeats its values across rows; a
            # column that never repeats is a variable (REQ-13 heuristic).
            if n_unique <= threshold and n_unique < finite.size:
                requested.append(name)
        logger.info("pivot auto_detect resolved dims: %s", requested)
    if not requested:
        raise PivotError(
            "VarFrame",
            "pivot() called without dims",
            "pass dims=[...] or set auto_detect=True",
        )
    columns = {name: variable.values for name, variable in db.vars.items()}
    units = {name: variable.unit for name, variable in db.vars.items()}
    new_dims, positions, shape = assemble_grid(
        columns, requested, context="db.pivot", units=units
    )
    variables = {
        name: Variable(
            name=name,
            values=place_on_grid(variable.values, positions, shape),
            unit=variable.unit,
            description=variable.description,
            long_name=variable.long_name,
        )
        for name, variable in db.vars.items()
        if name not in requested
    }
    # REQ-98: pivot carries the mirrors unchanged, per position (DD-18).
    uncertainty = None
    if db.uncertainty is not None:
        uncertainty = UncFrame(
            systematic={
                name: place_on_grid(values, positions, shape)
                for name, values in db.uncertainty.systematic.items()
            },
            random={
                name: place_on_grid(values, positions, shape)
                for name, values in db.uncertainty.random.items()
            },
        )
    tags = None
    if db.tags is not None:
        tags = HistoryFrame(
            tags={
                name: place_on_grid(values, positions, shape, fill=0, dtype=np.int8)
                for name, values in db.tags.tags.items()
            }
        )
    record = db.mode == "production" or history
    # The pivoted columns become dimensions and leave vars, so their
    # declared pairs no longer name variables of this frame. The result
    # must be used at BOTH the hash call and the construction below, or
    # the recorded hash describes a frame that is not the one returned.
    new_correlation = (
        db.correlation.restrict(set(variables)) if db.correlation is not None else None
    )
    operation = f"pivot(dims={requested})"
    if db.correlation is not None and (
        new_correlation is None
        or dict(new_correlation.pairs) != dict(db.correlation.pairs)
    ):
        operation += ", correlation=dropped"
    new_history = db.history
    if record:
        operations = (
            *((e.operation, e.comment) for e in db.history),
            (operation, comment),
        )
        state_hash = compute_state_hash(
            dims=new_dims,
            variables=variables,
            operations=operations,
            uncertainty=uncertainty,
            correlation=new_correlation,
            tags=tags,
            axes=db.axes,
        )
        new_history = db.history.append(
            operation=operation, state_hash=state_hash, comment=comment
        )
    return VarFrame(
        dims=new_dims,
        vars=variables,
        provenance=db.provenance,
        history=new_history,
        uncertainty=uncertainty,
        tags=tags,
        coords=db.coords,
        correlation=new_correlation,
        axes=db.axes,
    )
