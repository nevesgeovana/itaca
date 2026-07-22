"""db.manifest: the audit checkpoint between loading and analysis (REQ-15).

Maps each source file to its dimension coordinate values, writing
``*`` where a dimension is swept within the file. Backed by the
``source_coords`` record captured at load time; identity lives in the
record, never in file names.
"""

from __future__ import annotations

import json
from pathlib import Path

from itaca.core.errors import DataError
from itaca.core.varframe import VarFrame


def manifest(db: VarFrame, path: str | Path) -> Path:
    """Export the source-file manifest as CSV or JSON (REQ-15).

    Parameters
    ----------
    db : VarFrame
        A VarFrame loaded from files.
    path : path
        Target file; the suffix selects the format (``.csv`` or
        ``.json``).

    Returns
    -------
    pathlib.Path
        The written path.

    Raises
    ------
    DataError
        When the VarFrame was loaded from memory (no files to map) or
        the suffix is not a supported format.
    """
    entries = db.provenance.source_coords
    if entries is None:
        raise DataError(
            "VarFrame loaded from an in-memory source",
            "db.manifest has no source files to map",
            "the manifest applies to file and folder loads (REQ-15)",
        )
    target = Path(path)
    dim_names: list[str] = []
    for _, coords in entries:
        for dim, _ in coords:
            if dim not in dim_names:
                dim_names.append(dim)
    if target.suffix.lower() == ".csv":
        lines = [",".join(["file", *dim_names])]
        for file_path, coords in entries:
            mapping = dict(coords)
            row = [file_path] + [str(mapping.get(d, "")) for d in dim_names]
            lines.append(",".join(row))
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif target.suffix.lower() == ".json":
        payload = [
            {"file": file_path, "coords": dict(coords)} for file_path, coords in entries
        ]
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        raise DataError(
            f"manifest target '{target.name}'",
            "db.manifest supports only .csv and .json",
            "change the file suffix to .csv or .json",
        )
    return target
