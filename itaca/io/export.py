"""Export family: to_csv, to_json, to_pandas, to_numpy (REQ-70 to REQ-72).

Every export embeds Provenance metadata and a History summary
(REQ-71). Draft-mode exports are blocked without ``allow_draft=True``
(REQ-11); when forced, a prominent warning lands in the output
(OQ-22 scope: result exports only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DraftModeExportError, MissingDependencyError
from itaca.core.varframe import VarFrame

DRAFT_WARNING = (
    "DRAFT-MODE EXPORT: this data was produced in draft mode; history "
    "recording was opt-in and the content is not suitable for official "
    "results (REQ-11)"
)


def guard_draft(db: VarFrame, allow_draft: bool, operation: str) -> None:
    """Enforce the draft-mode export guard (REQ-11)."""
    if db.mode == "draft" and not allow_draft:
        raise DraftModeExportError(
            "VarFrame in draft mode",
            f"{operation} blocked by the draft export guard",
            "promote to production first, or pass allow_draft=True as a "
            "deliberate second decision (REQ-11)",
        )


def _header_lines(db: VarFrame) -> list[str]:
    provenance = db.provenance
    lines = [
        f"# ITACA export | version: {provenance.itaca_version} | "
        f"user: {provenance.user} | created: "
        f"{provenance.created_at.isoformat()} | mode: {provenance.mode}",
        f"# source_hash: {provenance.source_hash}",
    ]
    if db.mode == "draft":
        lines.append(f"# {DRAFT_WARNING}")
    lines.extend(
        f"# history[{entry.index}]: {entry.operation}"
        + (f"  # {entry.comment}" if entry.comment else "")
        for entry in db.history
    )
    return lines


def _flat_columns(db: VarFrame) -> tuple[list[str], list[NDArray[Any]]]:
    names = [*db.dims, *db.vars]
    if db.shape:
        indices = np.indices(db.shape)
        columns: list[NDArray[Any]] = [
            dim.coords[indices[axis].ravel()]
            for axis, dim in enumerate(db.dims.values())
        ]
    else:
        columns = []
    columns.extend(var.values.ravel() for var in db.vars.values())
    return names, columns


def to_csv(
    db: VarFrame,
    path: str | Path,
    *,
    split_by: str | None = None,
    allow_draft: bool = False,
) -> Path | list[Path]:
    """Export to flat CSV with a provenance header (REQ-70 to REQ-72).

    See ``VarFrame.to_csv`` for the parameter description.
    """
    guard_draft(db, allow_draft, "to_csv")
    if split_by is not None:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for coordinate in db.dims[split_by].coords:
            value = (
                float(coordinate) if db.dims[split_by].is_numeric else str(coordinate)
            )
            piece = db.select({split_by: value}, history=False)
            stem = str(value).replace(".", "p")
            target = directory / f"{split_by}_{stem}.csv"
            result = to_csv(piece, target, allow_draft=allow_draft)
            written.append(Path(str(result)))
        return written
    target = Path(path)
    names, columns = _flat_columns(db)
    lines = _header_lines(db)
    lines.append(",".join(names))
    n_rows = columns[0].shape[0] if columns else 0
    for row in range(n_rows):
        lines.append(",".join(str(column[row]) for column in columns))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def to_json(db: VarFrame, path: str | Path, *, allow_draft: bool = False) -> Path:
    """Export to JSON with provenance and history keys (REQ-70, REQ-71).

    See ``VarFrame.to_json`` for the parameter description.
    """
    guard_draft(db, allow_draft, "to_json")
    provenance = db.provenance
    payload: dict[str, Any] = {
        "provenance": {
            "itaca_version": provenance.itaca_version,
            "user": provenance.user,
            "created_at": provenance.created_at.isoformat(),
            "source_files": [str(p) for p in provenance.source_files],
            "source_hash": provenance.source_hash,
            "mode": provenance.mode,
            "version_tag": provenance.version_tag,
        },
        "history": [
            {
                "index": entry.index,
                "operation": entry.operation,
                "timestamp": entry.timestamp.isoformat(),
                "state_hash": entry.state_hash,
                "comment": entry.comment,
            }
            for entry in db.history
        ],
        "dims": {
            name: {
                "coords": dim.coords.tolist(),
                "unit": dim.unit,
                "is_numeric": dim.is_numeric,
            }
            for name, dim in db.dims.items()
        },
        "variables": {
            name: {"values": var.values.tolist(), "unit": var.unit}
            for name, var in db.vars.items()
        },
    }
    if db.mode == "draft":
        payload["warning"] = DRAFT_WARNING
    if db.uncertainty is not None:
        payload["uncertainty"] = {
            "systematic": {
                name: values.tolist()
                for name, values in db.uncertainty.systematic.items()
            },
            "random": {
                name: values.tolist() for name, values in db.uncertainty.random.items()
            },
        }
    target = Path(path)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def to_pandas(db: VarFrame, *, allow_draft: bool = False) -> Any:
    """Export to a flat pandas DataFrame (REQ-70; lazy dependency).

    See ``VarFrame.to_pandas`` for the parameter description.
    """
    guard_draft(db, allow_draft, "to_pandas")
    try:
        import pandas as pd
    except ImportError:
        raise MissingDependencyError(
            "pandas",
            "to_pandas requires the optional pandas bridge",
            "install it via pip install itaca[pandas] (REQ-84)",
        ) from None
    names, columns = _flat_columns(db)
    return pd.DataFrame(dict(zip(names, columns, strict=True)))


def to_numpy(
    db: VarFrame,
    *,
    return_dims: bool = False,
    copy: bool = False,
    allow_draft: bool = False,
) -> Any:
    """Export the variable arrays (REQ-70; read-only views, REQ-102).

    See ``VarFrame.to_numpy`` for the parameter description.
    """
    guard_draft(db, allow_draft, "to_numpy")
    arrays = {
        name: var.values.copy() if copy else var.values for name, var in db.vars.items()
    }
    if not return_dims:
        return arrays
    coords = {
        name: dim.coords.copy() if copy else dim.coords for name, dim in db.dims.items()
    }
    return arrays, coords
