"""itc.load: the single entry point for loading data (REQ-01 to REQ-07).

Five source forms: folder, single file, coordinate dictionary (most
traceable, recommended for production), NumPy array, pandas DataFrame.
Without ``dims`` the result is in datapoint mode; with ``dims`` the
rows are assembled onto a structured grid, filling missing
combinations with NaN (REQ-06).

The History operation string is path-free so that state hashes stay
invariant to file locations (REQ-103); paths live in Provenance.
"""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.errors import DataError, LoadCoordinateError
from itaca.core.history import History, compute_state_hash
from itaca.core.provenance import (
    Provenance,
    current_mode,
    current_user,
    validate_mode,
)
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable
from itaca.core.version import __version__
from itaca.io.pivot import DATAPOINT_DIM, assemble_grid, place_on_grid

logger = logging.getLogger(__name__)

SWEPT = "*"
_REGEX_HINTS = ("\\", "+", "^", "$", "(", ")", "|")

SourceCoords = tuple[tuple[str, tuple[tuple[str, object], ...]], ...]


def load(
    source: object,
    dims: Sequence[str] | None = None,
    *,
    names: Sequence[str] | None = None,
    pattern: str | None = None,
    version: str | None = None,
    mode: str | None = None,
    user: str | None = None,
    comment: str | None = None,
) -> VarFrame:
    """Load data into a VarFrame (REQ-01).

    Parameters
    ----------
    source : path, dict, numpy.ndarray, or pandas.DataFrame
        A folder path (all compatible ``.csv`` files), a single file
        path, a dictionary mapping coordinate tuples to file paths
        (most traceable; use ``"*"`` in a tuple position for a
        dimension swept within the file), a 2-D NumPy array (with
        ``names``), or a pandas DataFrame.
    dims : sequence of str or None, optional
        Dimension names for structured loading. ``None`` yields
        datapoint mode with a single synthetic ``datapoint`` dimension.
    names : sequence of str or None, optional
        Column names for NumPy array sources (REQ-04).
    pattern : str or None, optional
        Filename filter for folder sources: glob or regular
        expression; a pattern containing regex-only tokens
        (backslash, ``+ ^ $ ( ) |``) is treated as a regex (REQ-02).
    version : str or None, optional
        User-defined version tag stored in Provenance.
    mode : str or None, optional
        Operating mode; defaults to the session mode (REQ-08).
    user : str or None, optional
        Overrides the session user identity for this load (REQ-07).
    comment : str or None, optional
        Comment stored with the load History entry (REQ-19).

    Returns
    -------
    VarFrame
        With Provenance filled and the load as History index 1.

    Raises
    ------
    DataError
        On unreadable sources, invalid arguments, or non-numeric
        variable columns.
    LoadCoordinateError
        When a dict-mode coordinate tuple length does not match
        ``dims`` (REQ-03).

    Examples
    --------
    >>> import numpy as np
    >>> db = load(np.array([[0.0, 0.1]]), names=["alpha", "CT"])
    >>> list(db.dims)
    ['datapoint']
    """
    resolved_mode = mode if mode is not None else current_mode()
    validate_mode(resolved_mode)
    if isinstance(source, np.ndarray):
        content = _from_array(source, names, dims)
    elif _is_dataframe(source):
        content = _from_dataframe(source, dims)
    elif isinstance(source, Mapping):
        content = _from_dict(source, dims)
    elif isinstance(source, (str, Path)):
        content = _from_path(Path(source), dims, pattern)
    else:
        raise DataError(
            f"source of type {type(source).__name__}",
            "itc.load received an unsupported source",
            "pass a folder, file, dict, NumPy array, or DataFrame (REQ-01)",
        )
    columns, files, source_hash, source_coords = content
    if dims is None:
        frame_dims, variables = _datapoint_frame(columns)
    else:
        frame_dims, positions, shape = assemble_grid(
            columns, list(dims), context="itc.load"
        )
        variables = {
            name: Variable(
                name=name,
                values=place_on_grid(np.asarray(values, dtype=float), positions, shape),
            )
            for name, values in columns.items()
            if name not in frame_dims
        }
    operation = (
        f"load(dims={None if dims is None else list(dims)}, "
        f"n_sources={len(files) if files else 0})"
    )
    state_hash = compute_state_hash(
        dims=frame_dims, variables=variables, operations=((operation, comment),)
    )
    provenance = Provenance(
        itaca_version=__version__,
        user=user if user is not None else current_user(),
        created_at=datetime.now(timezone.utc),
        source_files=tuple(files),
        source_hash=source_hash,
        mode=resolved_mode,
        version_tag=version,
        source_coords=source_coords,
    )
    history = History().append(
        operation=operation, state_hash=state_hash, comment=comment
    )
    logger.info(
        "loaded %d variable(s) from %d source(s) in mode %s",
        len(variables),
        len(files),
        resolved_mode,
    )
    return VarFrame(
        dims=frame_dims,
        vars=variables,
        provenance=provenance,
        history=history,
    )


_LoadContent = tuple[
    dict[str, NDArray[Any]],
    tuple[Path, ...],
    str,
    "SourceCoords | None",
]


def _is_dataframe(obj: object) -> bool:
    return any(
        t.__module__.split(".")[0] == "pandas" and t.__name__ == "DataFrame"
        for t in type(obj).__mro__
    )


def _numeric_column(name: str, values: NDArray[Any], origin: str) -> NDArray[Any]:
    array = np.asarray(values)
    if np.issubdtype(array.dtype, np.number):
        return array.astype(float)
    try:
        return array.astype(float)
    except (TypeError, ValueError):
        raise DataError(
            f"column '{name}' from {origin}",
            "loading a non-numeric column as a variable",
            "string-valued columns are supported only as dimension "
            "coordinates (dims= or dict mode)",
        ) from None


def _datapoint_frame(
    columns: dict[str, NDArray[Any]],
) -> tuple[dict[str, Dimension], dict[str, Variable]]:
    lengths = {values.shape[0] for values in columns.values()}
    n_rows = lengths.pop() if lengths else 0
    dims = {
        DATAPOINT_DIM: Dimension(
            name=DATAPOINT_DIM,
            coords=np.arange(n_rows),
            description="acquisition order (REQ-01)",
        )
    }
    variables = {
        name: Variable(name=name, values=_numeric_column(name, values, "the source"))
        for name, values in columns.items()
    }
    return dims, variables


def _from_array(
    array: NDArray[Any],
    names: Sequence[str] | None,
    dims: Sequence[str] | None,
) -> _LoadContent:
    if dims is not None:
        raise DataError(
            "NumPy array source",
            "itc.load(arr) called with dims",
            "array mode is datapoint mode; call db.pivot(dims=[...]) "
            "afterwards (REQ-04)",
        )
    if array.ndim != 2:
        raise DataError(
            f"NumPy array with ndim={array.ndim}",
            "itc.load(arr) requires a 2-D array",
            "reshape to (n_rows, n_columns) and pass names=[...]",
        )
    if names is None or len(names) != array.shape[1]:
        given = 0 if names is None else len(names)
        raise DataError(
            f"names list of length {given}",
            f"itc.load(arr) with {array.shape[1]} column(s)",
            "pass names=[...] with one name per column (REQ-04)",
        )
    columns = {
        str(name): np.asarray(array[:, index], dtype=float)
        for index, name in enumerate(names)
    }
    digest = hashlib.sha256()
    digest.update(",".join(str(n) for n in names).encode())
    digest.update(np.ascontiguousarray(array).tobytes())
    return columns, (), digest.hexdigest(), None


def _from_dataframe(source: Any, dims: Sequence[str] | None) -> _LoadContent:
    if dims is not None:
        raise DataError(
            "pandas DataFrame source",
            "itc.load(df) called with dims",
            "DataFrame mode is datapoint mode; call db.pivot(dims=[...]) "
            "afterwards (REQ-05)",
        )
    for column in source.columns:
        if not isinstance(column, str):
            raise DataError(
                f"DataFrame column name {column!r}",
                "itc.load(df) requires string column names",
                "rename the columns, e.g. df.columns = [str(c) for c in df.columns]",
            )
    columns = {
        str(column): _numeric_column(
            str(column), source[column].to_numpy(), "the DataFrame"
        )
        for column in source.columns
    }
    digest = hashlib.sha256()
    for name, values in columns.items():
        digest.update(name.encode())
        digest.update(np.ascontiguousarray(values).tobytes())
    return columns, (), digest.hexdigest(), None


def _read_csv(path: Path) -> dict[str, list[object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise DataError(
            f"source file '{path.name}'",
            f"itc.load could not read it ({error.__class__.__name__})",
            "check that the path exists and is readable",
        ) from error
    rows = [row for row in csv.reader(text.splitlines()) if row]
    if not rows:
        raise DataError(
            f"source file '{path.name}'",
            "itc.load found no header row",
            "provide a CSV with a header line naming the columns",
        )
    header = [name.strip() for name in rows[0]]
    columns: dict[str, list[object]] = {name: [] for name in header}
    for row in rows[1:]:
        for index, name in enumerate(header):
            cell = row[index].strip() if index < len(row) else ""
            if cell == "":
                columns[name].append(np.nan)
                continue
            try:
                columns[name].append(float(cell))
            except ValueError:
                columns[name].append(cell)
    return columns


def _merge_rows(
    tables: list[dict[str, list[object]]],
) -> dict[str, list[object]]:
    all_names: list[str] = []
    for table in tables:
        for name in table:
            if name not in all_names:
                all_names.append(name)
    merged: dict[str, list[object]] = {name: [] for name in all_names}
    for table in tables:
        n_rows = len(next(iter(table.values()))) if table else 0
        for name in all_names:
            merged[name].extend(table.get(name, [np.nan] * n_rows))
    return merged


def _column_arrays(
    merged: dict[str, list[object]],
) -> dict[str, NDArray[Any]]:
    arrays: dict[str, NDArray[Any]] = {}
    for name, values in merged.items():
        if any(isinstance(value, str) for value in values):
            arrays[name] = np.asarray(
                ["" if value is np.nan else str(value) for value in values]
            )
        else:
            arrays[name] = np.asarray(values, dtype=float)
    return arrays


def _hash_files(files: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
    return digest.hexdigest()


def _match(name: str, pattern: str) -> bool:
    if any(hint in pattern for hint in _REGEX_HINTS):
        return re.fullmatch(pattern, name) is not None
    return fnmatch.fnmatch(name, pattern)


def _from_path(
    path: Path, dims: Sequence[str] | None, pattern: str | None
) -> _LoadContent:
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() == ".csv")
        if pattern is not None:
            files = [p for p in files if _match(p.name, pattern)]
        if not files:
            raise DataError(
                f"folder '{path}'",
                "itc.load found no compatible (.csv) files"
                + (f" matching pattern {pattern!r}" if pattern else ""),
                "check the folder contents or adjust pattern=",
            )
    elif path.is_file():
        files = [path]
    else:
        raise DataError(
            f"source '{path}'",
            "itc.load could not find it",
            "check the path; folders and .csv files are supported",
        )
    merged = _merge_rows([_read_csv(p) for p in files])
    columns = _column_arrays(merged)
    swept = tuple(dims) if dims is not None else ()
    source_coords: SourceCoords = tuple(
        (str(p), tuple((dim, SWEPT) for dim in swept)) for p in files
    )
    return columns, tuple(files), _hash_files(files), source_coords


def _from_dict(source: Mapping[Any, Any], dims: Sequence[str] | None) -> _LoadContent:
    if dims is None:
        raise DataError(
            "dict source",
            "itc.load(dict) called without dims",
            "dict mode maps coordinate tuples to files; pass dims=[...] (REQ-03)",
        )
    dim_names = list(dims)
    tables: list[dict[str, list[object]]] = []
    files: list[Path] = []
    source_coords: list[tuple[str, tuple[tuple[str, object], ...]]] = []
    for coords, file_path in source.items():
        coord_tuple = coords if isinstance(coords, tuple) else (coords,)
        if len(coord_tuple) != len(dim_names):
            raise LoadCoordinateError(
                f"coordinate tuple {coord_tuple!r}",
                f"itc.load dict mode with dims={dim_names} expects "
                f"{len(dim_names)} coordinate(s), got {len(coord_tuple)}",
                "align each tuple positionally with dims (REQ-03)",
            )
        path = Path(file_path)
        table = _read_csv(path)
        n_rows = len(next(iter(table.values()))) if table else 0
        for dim, value in zip(dim_names, coord_tuple, strict=True):
            if value == SWEPT:
                if dim not in table:
                    raise DataError(
                        f"dimension '{dim}' declared swept in '{path.name}'",
                        "itc.load found no column with that name in the file",
                        "add the column or give an explicit coordinate",
                    )
            else:
                table[dim] = [value] * n_rows
        tables.append(table)
        files.append(path)
        source_coords.append(
            (str(path), tuple(zip(dim_names, coord_tuple, strict=True)))
        )
    columns = _column_arrays(_merge_rows(tables))
    return columns, tuple(files), _hash_files(files), tuple(source_coords)
