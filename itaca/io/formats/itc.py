"""The .itc native binary format: db.save and itc.open (REQ-70, SRS 4.5).

A ZIP archive of open standards (NumPy .npz plus JSON), inspectable
without ITACA. Writes are atomic (temp file plus replace); the
metadata carries a versioned schema string and the state hash, and
``itc.open`` re-validates that hash so drift fails loud
(HashMismatchError, REQ-103).
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.correlation import CorrelationMatrix
from itaca.core.dimension import Dimension
from itaca.core.errors import DataError, HashMismatchError
from itaca.core.history import History, HistoryEntry
from itaca.core.historyframe import HistoryFrame
from itaca.core.provenance import Provenance
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable
from itaca.core.version import __version__
from itaca.io.export import DRAFT_WARNING, guard_draft

FORMAT_SCHEMA = "itaca-itc/1"


def _npz_bytes(arrays: dict[str, NDArray[Any]]) -> bytes:
    buffer = io.BytesIO()
    # The numpy stubs type **kwds of savez_compressed too narrowly.
    np.savez_compressed(buffer, **arrays)  # type: ignore[arg-type]
    return buffer.getvalue()


def _read_npz(archive: zipfile.ZipFile, name: str) -> dict[str, NDArray[Any]]:
    with np.load(io.BytesIO(archive.read(name))) as loaded:
        return {key: loaded[key] for key in loaded.files}


def save(db: VarFrame, path: str | Path, *, allow_draft: bool = False) -> Path:
    """Write a VarFrame to a .itc archive (REQ-70, REQ-11).

    See ``VarFrame.save`` for the parameter description.
    """
    guard_draft(db, allow_draft, "save")
    target = Path(path)
    provenance = db.provenance
    provenance_payload: dict[str, Any] = {
        "itaca_version": provenance.itaca_version,
        "user": provenance.user,
        "created_at": provenance.created_at.isoformat(),
        "source_files": [str(p) for p in provenance.source_files],
        "source_hash": provenance.source_hash,
        "mode": provenance.mode,
        "version_tag": provenance.version_tag,
        "source_coords": (
            [
                [file_path, [[dim, value] for dim, value in coords]]
                for file_path, coords in provenance.source_coords
            ]
            if provenance.source_coords is not None
            else None
        ),
    }
    if db.mode == "draft":
        provenance_payload["warning"] = DRAFT_WARNING
    members: dict[str, bytes] = {
        "varframe.npz": _npz_bytes({name: var.values for name, var in db.vars.items()}),
        "dims.json": json.dumps(
            [
                {
                    "name": dim.name,
                    "coords": dim.coords.tolist(),
                    "unit": dim.unit,
                    "description": dim.description,
                    "is_numeric": dim.is_numeric,
                }
                for dim in db.dims.values()
            ]
        ).encode(),
        "vars_meta.json": json.dumps(
            {
                name: {
                    "unit": var.unit,
                    "description": var.description,
                    "long_name": var.long_name,
                }
                for name, var in db.vars.items()
            }
        ).encode(),
        "provenance.json": json.dumps(provenance_payload).encode(),
        "history.json": json.dumps(
            [
                {
                    "index": entry.index,
                    "operation": entry.operation,
                    "timestamp": entry.timestamp.isoformat(),
                    "state_hash": entry.state_hash,
                    "comment": entry.comment,
                }
                for entry in db.history
            ]
        ).encode(),
        "metadata.json": json.dumps(
            {
                "schema": FORMAT_SCHEMA,
                "itaca_version": __version__,
                "state_hash": db.state_hash,
            }
        ).encode(),
    }
    if db.uncertainty is not None:
        members["uncframe.npz"] = _npz_bytes(
            {
                **{
                    f"sys__{name}": values
                    for name, values in db.uncertainty.systematic.items()
                },
                **{
                    f"rand__{name}": values
                    for name, values in db.uncertainty.random.items()
                },
            }
        )
    if db.correlation is not None:
        members["correlation.json"] = json.dumps(
            [[a, b, r] for (a, b), r in db.correlation.pairs.items()]
        ).encode()
    if db.tags is not None:
        members["historyframe.npz"] = _npz_bytes(dict(db.tags.tags))
    temporary = target.with_suffix(target.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    os.replace(temporary, target)
    return target


def open_itc(path: str | Path) -> VarFrame:
    """Read a .itc archive into a VarFrame, revalidating its state hash.

    Parameters
    ----------
    path : path
        A ``.itc`` archive written by ``db.save``.

    Returns
    -------
    VarFrame
        The reconstructed VarFrame.

    Raises
    ------
    DataError
        When the file is not a readable .itc archive.
    HashMismatchError
        When the recomputed state hash differs from the recorded one
        (REQ-103): the archive was modified or corrupted.

    Examples
    --------
    >>> import itaca as itc
    >>> db = itc.open("campaign.itc")  # doctest: +SKIP
    """
    target = Path(path)
    try:
        with zipfile.ZipFile(target) as archive:
            metadata = json.loads(archive.read("metadata.json"))
            dims_payload = json.loads(archive.read("dims.json"))
            vars_meta = json.loads(archive.read("vars_meta.json"))
            provenance_payload = json.loads(archive.read("provenance.json"))
            history_payload = json.loads(archive.read("history.json"))
            values = _read_npz(archive, "varframe.npz")
            names = archive.namelist()
            uncertainty_arrays = (
                _read_npz(archive, "uncframe.npz") if "uncframe.npz" in names else None
            )
            correlation_payload = (
                json.loads(archive.read("correlation.json"))
                if "correlation.json" in names
                else None
            )
            tag_arrays = (
                _read_npz(archive, "historyframe.npz")
                if "historyframe.npz" in names
                else None
            )
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise DataError(
            f"archive '{target}'",
            f"itc.open could not read it ({error.__class__.__name__})",
            "check the path; .itc files are written by db.save (REQ-70)",
        ) from error
    dims = {
        entry["name"]: Dimension(
            name=entry["name"],
            coords=np.asarray(entry["coords"]),
            unit=entry["unit"],
            description=entry["description"],
            is_numeric=entry["is_numeric"],
        )
        for entry in dims_payload
    }
    variables = {
        name: Variable(
            name=name,
            values=array,
            unit=vars_meta[name]["unit"],
            description=vars_meta[name]["description"],
            long_name=vars_meta[name]["long_name"],
        )
        for name, array in values.items()
    }
    uncertainty = None
    if uncertainty_arrays is not None:
        uncertainty = UncFrame(
            systematic={
                key.removeprefix("sys__"): array
                for key, array in uncertainty_arrays.items()
                if key.startswith("sys__")
            },
            random={
                key.removeprefix("rand__"): array
                for key, array in uncertainty_arrays.items()
                if key.startswith("rand__")
            },
        )
    correlation = (
        CorrelationMatrix(pairs={(a, b): r for a, b, r in correlation_payload})
        if correlation_payload is not None
        else None
    )
    tags = HistoryFrame(tags=tag_arrays) if tag_arrays is not None else None
    provenance = Provenance(
        itaca_version=provenance_payload["itaca_version"],
        user=provenance_payload["user"],
        created_at=datetime.fromisoformat(provenance_payload["created_at"]),
        source_files=tuple(Path(p) for p in provenance_payload["source_files"]),
        source_hash=provenance_payload["source_hash"],
        mode=provenance_payload["mode"],
        version_tag=provenance_payload["version_tag"],
        source_coords=(
            tuple(
                (
                    file_path,
                    tuple((dim, value) for dim, value in coords),
                )
                for file_path, coords in provenance_payload["source_coords"]
            )
            if provenance_payload["source_coords"] is not None
            else None
        ),
    )
    history = History(
        entries=tuple(
            HistoryEntry(
                index=entry["index"],
                operation=entry["operation"],
                timestamp=datetime.fromisoformat(entry["timestamp"]),
                state_hash=entry["state_hash"],
                comment=entry["comment"],
            )
            for entry in history_payload
        )
    )
    db = VarFrame(
        dims=dims,
        vars=variables,
        provenance=provenance,
        history=history,
        uncertainty=uncertainty,
        tags=tags,
        correlation=correlation,
    )
    if db.state_hash != metadata["state_hash"]:
        raise HashMismatchError(
            f"archive '{target}'",
            "itc.open found state-hash drift between the recorded and the "
            "recomputed state",
            "the file was modified or corrupted; re-export it from the "
            "source data (REQ-103)",
        )
    return db
