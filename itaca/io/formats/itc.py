"""The .itc native binary format: db.save and itc.open.

REQ-70 and the ``.itc`` section of SRS Chapter 4.

A ZIP archive of open standards (NumPy .npz plus JSON), inspectable
without ITACA. Writes are atomic (temp file plus replace); the
metadata carries a versioned schema string and the state hash, and
``itc.open`` re-validates that hash so drift fails loud
(HashMismatchError, REQ-103).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from itaca.core.axes import Axis, AxisRegistry
from itaca.core.coords import coord_system
from itaca.core.correlation import CorrelationMatrix
from itaca.core.dimension import Dimension
from itaca.core.errors import DataError, HashMismatchError
from itaca.core.history import History, HistoryEntry
from itaca.core.historyframe import HistoryFrame
from itaca.core.pipeline import REPLAYABLE_CALLS, PipelineStep
from itaca.core.provenance import Provenance
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable
from itaca.core.version import __version__
from itaca.io.export import DRAFT_WARNING, guard_draft

FORMAT_SCHEMA = "itaca-itc/3"
# Schema 3 is the authenticated canonical payload. It adds the member
# manifest (every member's digest, so an edit to ANY member is refused,
# not only one that moves the recomputed state), the coordinate-system
# tag in frame.json, and the coordinate dtype in dims.json; and it moves
# every state hash, because the framing became length-prefixed and the
# operating mode entered the digest.
#
# Schema 1 and 2 archives are REFUSED rather than read. That is a
# deliberate break and not an oversight: neither records its
# CoordSystem, so a Polar frame cannot be reconstructed from one, and
# reopening it as Cartesian is FND-037 itself. A defect must not be the
# remedy for a defect, so the only truthful option is to refuse and name
# the migration (DD-47).
_READABLE_SCHEMAS = frozenset({FORMAT_SCHEMA})
_SUPERSEDED_SCHEMAS = frozenset({"itaca-itc/1", "itaca-itc/2"})

_METADATA_MEMBER = "metadata.json"


def _member_digest(payload: bytes) -> str:
    """SHA-256 of one archive member, as written."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _member_manifest(members: Mapping[str, bytes]) -> dict[str, str]:
    """Digest every OTHER member, which is every member but this one.

    ``metadata.json`` is excluded because it is where the manifest
    lives, and the exclusion is a real hole rather than a technicality:
    an edit to a field of ``metadata.json`` that no other check reads,
    such as ``itaca_version``, is NOT refused. Measured. The fields of
    that member which do matter are covered by their own checks: the
    schema string against the readable set, ``state_hash`` against the
    recomputed state, ``steps_hash`` against the recomputed recipe.

    Before this, only the final state hash and the replay-steps digest
    were authenticated, so an individual ``HistoryEntry.state_hash``
    could be forged to 64 zeros and the archive still opened (FND-038),
    and ``provenance.json`` could be edited in ways the recomputed state
    did not cover (FND-089).

    The manifest is tamper EVIDENCE, not tamper proofing. A ``.itc``
    carries no secret, so an editor who rewrites a member and also
    rewrites ``metadata.json`` produces an archive that opens. What it
    ends is the case where an edit needs nothing else at all.
    """
    return {
        name: _member_digest(payload)
        for name, payload in members.items()
        if name != _METADATA_MEMBER
    }


def _locate_unserializable(entries: list[dict[str, Any]]) -> str:
    """Name the step and argument that has no JSON form, for the message.

    A bulk ``json.dumps`` failure carries no location, and "pass a finite
    number for that argument" is unactionable across forty history
    entries. The ``.itc_pipe`` writer names position and keyword; this
    keeps the two writers of the same structure symmetric.
    """
    for position, entry in enumerate(entries, start=1):
        step = entry.get("step")
        if not isinstance(step, dict):
            continue
        for name, value in (step.get("kwargs") or {}).items():
            try:
                json.dumps(value, allow_nan=False)
            except (TypeError, ValueError):
                return f"step {position} ({step.get('call')}) argument '{name}'"
    return "a recorded replay step"


def _steps_digest(entries: list[dict[str, Any]], *, target: Path | None = None) -> str:
    """SHA-256 over the replay steps persisted in history.json.

    The replay step is deliberately outside the REQ-103 state hash: it
    is provenance metadata, not frame state. But the archive is
    recipe-bearing, so an edited step could steer a replay while the
    state hash still matched. This digest closes that gap without
    widening REQ-103 scope (DD-30).

    ``target`` marks the READ path and names the archive. Both paths
    reach this function, and ``json.loads`` accepts ``Infinity``, so a
    hand-edited archive once told the reader that "the archive cannot be
    written" and to pass a finite argument they never passed.
    """
    try:
        canonical = json.dumps(
            [entry.get("step") for entry in entries], sort_keys=True, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        if target is not None:
            raise DataError(
                f"archive '{target}'",
                "itc.open read a replay argument with no RFC 8259 JSON "
                f"representation, so the stored recipe cannot be verified "
                f"({exc})",
                "the archive was hand-edited after it was written; "
                "re-export it from the source data (REQ-54)",
            ) from exc
        # REQ-35 admits any scalar fill, including a non-finite one, and
        # it is recorded in the replay kwargs. Only persisting it can
        # fail, and it must fail with the three parts, not with the
        # stdlib ValueError the encoder raises.
        raise DataError(
            _locate_unserializable(entries),
            "the recorded replay argument has no RFC 8259 JSON "
            f"representation, so the archive cannot be written ({exc})",
            "pass a finite number or a JSON-native value for that "
            "argument; the archive must stay readable by any JSON tool "
            "(REQ-70)",
        ) from exc
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _step_from_payload(
    payload: dict[str, Any] | None, target: Path
) -> PipelineStep | None:
    """Rebuild a replay step from its history.json member."""
    if payload is None:
        return None
    call = payload.get("call") if isinstance(payload, dict) else None
    if not isinstance(call, str) or call not in REPLAYABLE_CALLS:
        raise DataError(
            f"archive '{target}'",
            f"a recorded replay step names {call!r}, which is not a replayable "
            "operation",
            f"expected one of {sorted(REPLAYABLE_CALLS)}; the archive was "
            "hand-edited or written by a different ITACA version (REQ-54)",
        )
    kwargs = payload.get("kwargs", {})
    if not isinstance(kwargs, dict):
        raise DataError(
            f"archive '{target}'",
            f"the replay step for {call!r} has a 'kwargs' that is not an object",
            "re-export the archive from the source data (REQ-54)",
        )
    return PipelineStep(call=call, kwargs=kwargs, comment=payload.get("comment"))


def _npz_bytes(arrays: dict[str, NDArray[Any]]) -> bytes:
    buffer = io.BytesIO()
    # The numpy stubs type **kwds of savez_compressed differently across
    # interpreter versions, so an inline ignore is unused on some and
    # required on others. Casting the callable is stable either way.
    savez = cast("Any", np.savez_compressed)
    savez(buffer, **arrays)
    return buffer.getvalue()


def _read_npz_bytes(payload: bytes) -> dict[str, NDArray[Any]]:
    with np.load(io.BytesIO(payload)) as loaded:
        return {key: loaded[key] for key in loaded.files}


def _verify_members(
    raw: Mapping[str, bytes], metadata: Mapping[str, Any], target: Path
) -> None:
    """Refuse an archive whose members are not the ones it declares.

    Checks the NAME SET in both directions before the digests, because
    "a member you did not write is present" and "a member you wrote is
    gone" are different accidents from "a member changed", and a message
    that names the wrong one sends the reader to the wrong place.
    """
    recorded = metadata.get("members")
    if not isinstance(recorded, dict):
        raise DataError(
            f"archive '{target}'",
            "itc.open read an archive with no member manifest in "
            "metadata.json, so its members cannot be verified",
            "the archive is truncated or was not written by ITACA; re-export "
            "it from the source data (REQ-70)",
        )
    present = {name for name in raw if name != _METADATA_MEMBER}
    declared = set(recorded)
    if present != declared:
        added = sorted(present - declared)
        missing = sorted(declared - present)
        # Only the side that actually happened is named. Printing
        # "[...] present but undeclared, [] declared but absent" makes
        # the reader check an empty list to find out it is empty.
        clauses = []
        if added:
            clauses.append(f"{added} present but undeclared")
        if missing:
            clauses.append(f"{missing} declared but absent")
        raise DataError(
            f"archive '{target}'",
            f"its members do not match the manifest: {' and '.join(clauses)}",
            "the archive was edited after it was written; re-export it from "
            "the source data (REQ-70)",
        )
    drifted = sorted(
        name for name in declared if _member_digest(raw[name]) != recorded[name]
    )
    if drifted:
        raise HashMismatchError(
            f"archive '{target}'",
            f"itc.open found drift between the recorded and the recomputed "
            f"digest of {drifted}, so those members were modified",
            "the archive was edited after it was written; re-export it from "
            "the source data (REQ-70, REQ-103)",
        )


def _axes_from_payload(payload: dict[str, Any] | None) -> AxisRegistry:
    """Reconstruct the axis registry from its .itc JSON member."""
    registry = AxisRegistry()
    if payload is None:
        return registry
    for entry in payload["axes"]:
        matrix = entry["rotation_matrix"]
        registry = registry.with_axis(
            Axis(
                name=entry["name"],
                rotation_matrix=(np.asarray(matrix) if matrix is not None else None),
                angles_from=(
                    tuple(entry["angles_from"])
                    if entry["angles_from"] is not None
                    else None
                ),
                convention=entry["convention"],
                description=entry["description"],
            )
        )
    for name, comps, frame in payload["vector_groups"]:
        registry = registry.with_vector_group(name, comps, frame)
    return registry


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
                    # tolist() erases the dtype, and the reader rebuilt
                    # float64, so an INTACT archive holding float32 or
                    # int32 coordinates failed its own state hash on
                    # reopen (FND-091). The dtype is data, not
                    # decoration: it is inside the digest.
                    "dtype": str(dim.coords.dtype),
                    "unit": dim.unit,
                    "description": dim.description,
                    "is_numeric": dim.is_numeric,
                }
                for dim in db.dims.values()
            ]
        ).encode(),
        # The frame-level state that is neither a dimension nor a
        # variable. Today that is the coordinate-system tag, which was
        # persisted nowhere, so a Polar frame reopened Cartesian and
        # silently changed the integration element (FND-037).
        "frame.json": json.dumps({"coords": db.coords.name}).encode(),
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
                    # Replay step (REQ-54); null for entries that record
                    # none. Persisted so a reopened archive can still
                    # lift its recipe with history.to_pipeline.
                    "step": (None if entry.step is None else entry.step._payload()),
                }
                for entry in db.history
            ]
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
    if not db.axes.is_empty():
        members["axes.json"] = json.dumps(
            {
                "axes": [
                    {
                        "name": axis.name,
                        "rotation_matrix": (
                            axis.rotation_matrix.tolist()
                            if axis.rotation_matrix is not None
                            else None
                        ),
                        "angles_from": (
                            list(axis.angles_from)
                            if axis.angles_from is not None
                            else None
                        ),
                        "convention": axis.convention,
                        "description": axis.description,
                    }
                    for axis in db.axes.axes.values()
                ],
                "vector_groups": [
                    [name, list(comps), db.axes.group_axis(name)]
                    for name, comps in db.axes.vector_groups.items()
                ],
            }
        ).encode()
    if db.tags is not None:
        members["historyframe.npz"] = _npz_bytes(dict(db.tags.tags))
    # LAST, and the order is load-bearing: the manifest has to see every
    # member, so metadata.json is built once the optional members are
    # settled and is the only member the manifest cannot cover.
    members[_METADATA_MEMBER] = json.dumps(
        {
            "schema": FORMAT_SCHEMA,
            "itaca_version": __version__,
            "state_hash": db.state_hash,
            "steps_hash": _steps_digest(
                [
                    {"step": (None if e.step is None else e.step._payload())}
                    for e in db.history
                ]
            ),
            "members": _member_manifest(members),
        }
    ).encode()
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
        When the archive was written at schema ``itaca-itc/1`` or
        ``itaca-itc/2``, which are REFUSED rather than read: neither
        records a coordinate system, so a polar frame would come back
        cartesian. This is the case a v0.1.0 or v0.2.0 user meets
        first, and the remedy is to re-export from the source data
        (DD-47). Also when the file is not a readable .itc archive,
        when its members do not match the manifest, or when a member
        cannot be interpreted.
    HashMismatchError
        When a member's recomputed digest differs from the recorded
        one, or the recomputed replay-step or state hash differs from
        the recorded one (REQ-103): the archive was modified or
        corrupted.

    Notes
    -----
    Verification is tamper EVIDENCE, not tamper proofing. The archive
    carries no secret, so an editor who rewrites a member and also
    recomputes ``metadata.json`` produces a file that opens.

    Examples
    --------
    >>> import itaca as itc
    >>> db = itc.open("campaign.itc")  # doctest: +SKIP
    """
    target = Path(path)
    # Every member is read as BYTES first and parsed afterwards. The
    # manifest is a statement about bytes, so it has to be checked
    # against the bytes, before any member has been interpreted.
    try:
        with zipfile.ZipFile(target) as archive:
            raw = {name: archive.read(name) for name in archive.namelist()}
            metadata = json.loads(raw[_METADATA_MEMBER])
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        # ValueError covers json.JSONDecodeError, which is a subclass of
        # it: a malformed member used to leave the ITACAError hierarchy
        # entirely and reach the caller as a stdlib parse error
        # (FND-031).
        raise DataError(
            f"archive '{target}'",
            f"itc.open could not read it ({error.__class__.__name__}: {error})",
            "check the path; .itc files are written by db.save (REQ-70)",
        ) from error
    # Answer the schema question before reconstructing anything. Parsing
    # first meant an archive this build cannot read failed with a message
    # about a bad replay step, sending the reader to re-export a file
    # whose only problem was being newer than their ITACA.
    schema = metadata.get("schema")
    if schema in _SUPERSEDED_SCHEMAS:
        raise DataError(
            f"archive '{target}' with schema {schema!r}",
            f"itc.open reads {FORMAT_SCHEMA} only, and this archive predates "
            "it: it records no coordinate system, no coordinate dtype and no "
            "member manifest, and its state hash was computed under the "
            "superseded framing",
            "re-export it from the source data with this version. It is NOT "
            "silently reinterpreted, because a frame saved in polar "
            "coordinates would come back cartesian and integrate against the "
            "wrong area element, which is the defect this schema exists to "
            "close (REQ-70, REQ-103, DD-47)",
        )
    if schema not in _READABLE_SCHEMAS:
        raise DataError(
            f"archive '{target}' with schema {schema!r}",
            "itc.open read an unknown .itc schema",
            f"this build reads {sorted(_READABLE_SCHEMAS)}; upgrade ITACA to "
            "open a newer archive (REQ-70)",
        )
    # The manifest runs FIRST, before any member is interpreted: it is a
    # statement about bytes, it is the cheapest check, and it is the most
    # sensitive one, because it catches an edit that changes no
    # reconstructed state at all (a forged per-entry history hash).
    #
    # The consequence is deliberate and worth naming: the steps and state
    # digests below no longer fire for a plain member edit, because this
    # refuses it first with a message that NAMES the drifted member,
    # which is more specific than either of them. What they still catch
    # is an editor who rewrote a member and updated 'members' but not
    # 'steps_hash' or 'state_hash', which is a partial rewrite rather
    # than dead code. tests/io/test_itc_roundtrip.py exercises both
    # layers separately so neither can quietly become unreachable.
    _verify_members(raw, metadata, target)
    try:
        dims_payload = json.loads(raw["dims.json"])
        vars_meta = json.loads(raw["vars_meta.json"])
        provenance_payload = json.loads(raw["provenance.json"])
        history_payload = json.loads(raw["history.json"])
        frame_payload = json.loads(raw["frame.json"])
        values = _read_npz_bytes(raw["varframe.npz"])
        uncertainty_arrays = (
            _read_npz_bytes(raw["uncframe.npz"]) if "uncframe.npz" in raw else None
        )
        correlation_payload = (
            json.loads(raw["correlation.json"]) if "correlation.json" in raw else None
        )
        axes_payload = json.loads(raw["axes.json"]) if "axes.json" in raw else None
        tag_arrays = (
            _read_npz_bytes(raw["historyframe.npz"])
            if "historyframe.npz" in raw
            else None
        )
    except (KeyError, ValueError) as error:
        raise DataError(
            f"archive '{target}'",
            f"itc.open could not interpret its members "
            f"({error.__class__.__name__}: {error})",
            "re-export it from the source data (REQ-70)",
        ) from error
    dims = {
        entry["name"]: Dimension(
            name=entry["name"],
            # The recorded dtype, not whatever json.loads inferred. A
            # float32 coordinate came back float64 and broke the state
            # hash of a file nobody had touched (FND-091).
            coords=np.asarray(entry["coords"], dtype=np.dtype(entry["dtype"])),
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
    axes = _axes_from_payload(axes_payload)
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
                step=_step_from_payload(entry.get("step"), target),
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
        axes=axes,
        coords=coord_system(frame_payload["coords"]),
    )
    # The steps digest is now unconditional. It used to be gated on what
    # the archive CARRIED rather than what it claimed, because a schema
    # string is ordinary metadata that no digest covers and an editor
    # could rewrite it to 1, keep poisoned steps and skip the check.
    # What closes that hazard is the gate being GONE, not the schema
    # becoming protected: the schema still lives in metadata.json, the
    # one member the manifest cannot cover, and it is authenticated only
    # indirectly, by sitting beside the state and steps digests that a
    # forger would also have to recompute. An earlier version of this
    # comment claimed the manifest covered the schema string, which is
    # false and was offered as the reason this check is safe; a later
    # reader could have weakened the check on that premise.
    #
    # The check is kept beside the manifest rather than folded into it:
    # it names the RECIPE, and DD-30 rests on that message.
    recorded_steps = metadata.get("steps_hash")
    if not isinstance(recorded_steps, str):
        raise DataError(
            f"archive '{target}'",
            "itc.open read an archive with no 'steps_hash' in metadata.json, "
            "so its stored recipe cannot be verified",
            "the archive is truncated or was not written by ITACA; re-export "
            "it from the source data (REQ-54)",
        )
    if recorded_steps != _steps_digest(history_payload, target=target):
        raise HashMismatchError(
            f"archive '{target}'",
            "itc.open found drift between the recorded and the recomputed "
            "replay steps, so the stored recipe was modified",
            "the archive was edited after it was written; re-export it "
            "from the source data (REQ-54)",
        )
    recorded_state = metadata.get("state_hash")
    if not isinstance(recorded_state, str):
        raise DataError(
            f"archive '{target}'",
            "itc.open read an archive with no 'state_hash' in metadata.json, "
            "so the recovered state cannot be verified",
            "the archive is truncated or was not written by ITACA; re-export "
            "it from the source data (REQ-103)",
        )
    if db.state_hash != recorded_state:
        # This check used to carry a second sentence about a known false
        # positive: an archive written before the DD-40 scope change
        # recomputed to a different digest while being perfectly intact,
        # and "modified or corrupted" was false for exactly the users
        # who had done nothing wrong. Every such archive is schema 1 or
        # 2 and is now refused by name, above, with the migration
        # spelled out. So this message is once again true as written,
        # and the version advice is where it belongs rather than
        # attached to a mismatch it can no longer cause.
        raise HashMismatchError(
            f"archive '{target}'",
            "itc.open found state-hash drift between the recorded and the "
            "recomputed state",
            "the file was modified or corrupted; re-export it from the "
            "source data (REQ-103)",
        )
    return db
