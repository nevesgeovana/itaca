"""Reusable pipelines: record a processing sequence, replay it.

REQ-53 to REQ-55, SRS 4.5, and DD-28. A ``Pipeline`` is a contiguous
range of History entries lifted into a reusable object. It replays by
re-dispatching structured steps, not by re-parsing the History display
strings: each replayable operation records a :class:`PipelineStep` (the
VarFrame method to call, its keyword arguments, and the History
comment) as it derives, so a pipeline reconstructs the exact calls
rather than the human-facing text.

The ``.itc_pipe`` file is human-readable JSON carrying everything SRS
4.5 requires: the ITACA version that created it, the index range in the
source history, each operation's call with its keyword arguments and
attached comment (REQ-19), and a content hash for integrity
verification. DD-28 records why the encoding is JSON rather than the
TOML the SRS originally named: no Python version ships a standard
library TOML writer, TOML has no null type (and ``compute(fill=None)``
is meaningful and differs from the default), and replay arguments
nest. Writes are atomic, mirroring the ``.itc`` archive discipline.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from itaca.core.errors import DataError, HashMismatchError, PipelineCompatibilityError
from itaca.core.version import __version__

if TYPE_CHECKING:
    from itaca.core.varframe import VarFrame

PIPELINE_SCHEMA = "itaca-itc_pipe/1"
"""Versioned schema string of the ``.itc_pipe`` format.

Bumped whenever the payload layout changes in a way an older reader
cannot interpret; ``load_pipeline`` refuses any other value.
"""

REPLAYABLE_CALLS = frozenset(
    {
        "at",
        "average",
        "compute",
        "declare_vector",
        "diff",
        "expand",
        "fill",
        "fitmodel",
        "fitvalue",
        "integrate",
        "interpolate",
        "register_axis",
        "rotate",
        "select",
        "set_correlation",
        "set_uncertainty",
        "smooth",
        "squeeze",
        "translate_moments",
    }
)
"""The VarFrame methods a pipeline may replay.

A ``.itc_pipe`` file is meant to be shared, reviewed, and committed to
git, so ``load_pipeline`` validates every recorded call against this set
rather than trusting the file: without it a hand-edited recipe could
name ``save`` or ``to_csv`` and perform file IO during ``apply``.
"""


def _axis_payload(axis: Any) -> dict[str, Any]:
    """Serialize an Axis into JSON-native form (mirrors .itc axes.json)."""
    matrix = axis.rotation_matrix
    return {
        "name": axis.name,
        "rotation_matrix": (None if matrix is None else np.asarray(matrix).tolist()),
        "angles_from": (None if axis.angles_from is None else list(axis.angles_from)),
        "convention": axis.convention,
        "description": axis.description,
    }


def _axis_from_payload(payload: Mapping[str, Any]) -> Any:
    """Rebuild an Axis from its JSON-native form."""
    from itaca.core.axes import Axis

    matrix = payload["rotation_matrix"]
    angles = payload["angles_from"]
    return Axis(
        name=payload["name"],
        rotation_matrix=(None if matrix is None else np.asarray(matrix, dtype=float)),
        angles_from=(None if angles is None else tuple(angles)),
        convention=payload["convention"],
        description=payload["description"],
    )


def _rehydrate(call: str, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Restore call arguments that JSON cannot carry natively.

    Most replay arguments are JSON literals and pass through unchanged.
    Two are not: ``set_correlation`` is keyed by variable pairs (tuples
    cannot be JSON object keys, so they are recorded as ``[a, b, r]``
    triples) and ``register_axis`` takes an ``Axis`` object.
    """
    if call == "set_correlation":
        return {"spec": {(a, b): r for a, b, r in kwargs["spec"]}}
    if call == "register_axis":
        return {"axis": _axis_from_payload(kwargs["axis"])}
    return dict(kwargs)


def to_jsonable(value: Any) -> Any:
    """Normalize a replay argument into a JSON-native value.

    NumPy arrays and scalars become lists and Python numbers, and tuples
    become lists, so every recorded step serializes into a
    ``.itc_pipe`` file. A value that cannot be represented raises rather
    than being written as a non-standard token: JSON has no NaN or
    infinity in RFC 8259, and a silently unreadable recipe would defeat
    the human-readable, version-controllable promise of REQ-55.

    Parameters
    ----------
    value : object
        A replay argument recorded by an operation.

    Returns
    -------
    object
        A JSON-native equivalent.

    Raises
    ------
    DataError
        The value is not finite or has no JSON representation.

    Examples
    --------
    >>> to_jsonable(np.float64(2.5))
    2.5
    >>> to_jsonable((1, 2))
    [1, 2]
    """
    if isinstance(value, np.ndarray):
        return [to_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return to_jsonable(value.item())
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise DataError(
                f"replay argument {value!r}",
                "a pipeline step recorded a non-finite number, which RFC 8259 "
                "JSON cannot represent",
                "pass a finite value; the .itc_pipe file must stay readable by "
                "any JSON tool (REQ-55)",
            )
        return value
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    raise DataError(
        f"replay argument of type {type(value).__name__}",
        "a pipeline step recorded a value with no JSON representation",
        "record only strings, numbers, booleans, None, lists, and mappings "
        "in a replayable operation (REQ-55)",
    )


@dataclass(frozen=True)
class PipelineStep:
    """One replayable operation: a VarFrame call and its keyword arguments.

    Parameters
    ----------
    call : str
        The public ``VarFrame`` method to invoke on replay, e.g.
        ``"smooth"``. Named ``call`` rather than ``method`` because
        several operations (``smooth``, ``fill``, ``interpolate``) own a
        ``method=`` keyword of their own, which would otherwise collide
        one level down in the file.
    kwargs : mapping of str to object
        Keyword arguments for that call, as JSON literals. Stored
        read-only: the step hangs off an append-only History entry, so a
        mutable mapping would be a write path into recorded provenance.
    comment : str or None, optional
        The History comment attached to the operation (REQ-19).

    Examples
    --------
    >>> step = PipelineStep(call="smooth", kwargs={"along": "x"})
    >>> step.kwargs["along"]
    'x'
    """

    call: str
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    comment: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))

    def __hash__(self) -> int:
        return hash((self.call, self.comment, self.canonical()))

    def canonical(self) -> str:
        """Return the canonical JSON text of this step's arguments."""
        return json.dumps(dict(self.kwargs), sort_keys=True, allow_nan=False)

    def payload(self) -> dict[str, Any]:
        """Return the JSON-native record written to a ``.itc_pipe`` file."""
        return {
            "call": self.call,
            "comment": self.comment,
            "kwargs": dict(self.kwargs),
        }

    def replay(self, db: VarFrame) -> VarFrame:
        """Apply this step to ``db`` and return the derived VarFrame.

        Parameters
        ----------
        db : VarFrame
            The frame to apply the recorded call to.

        Returns
        -------
        VarFrame
            The derived frame.

        Raises
        ------
        PipelineCompatibilityError
            The recorded call is not a replayable operation.
        """
        if self.call not in REPLAYABLE_CALLS:
            raise PipelineCompatibilityError(
                f"pipeline step {self.call!r}",
                "the recorded call is not a replayable VarFrame operation",
                f"expected one of {sorted(REPLAYABLE_CALLS)}; a .itc_pipe file "
                "may only name replayable operations (REQ-54)",
            )
        bound = getattr(db, self.call)
        return bound(  # type: ignore[no-any-return]
            **_rehydrate(self.call, self.kwargs), comment=self.comment
        )


@dataclass(frozen=True)
class Pipeline:
    """A reusable, ordered sequence of replayable operations (REQ-53).

    Built by :meth:`itaca.core.history.History.to_pipeline`. Apply it to
    a new VarFrame with :meth:`apply`, or persist it with :meth:`save`
    and reload it with :func:`load_pipeline`.

    Parameters
    ----------
    steps : tuple of PipelineStep
        The recorded operations, in order.
    history_start, history_end : int, optional
        The 1-based inclusive index range in the source history that
        this pipeline was lifted from (SRS 4.5).
    itaca_version : str, optional
        The ITACA version that created the pipeline.

    Examples
    --------
    >>> import numpy as np
    >>> import itaca as itc
    >>> arr = np.column_stack([np.arange(7.0), np.arange(7.0) ** 2])
    >>> db = itc.load(arr, names=["x", "y"]).pivot(dims=["x"])
    >>> processed = db.compute("z = y + 1")
    >>> pipe = processed.history.to_pipeline()
    >>> len(pipe)
    1
    >>> "z" in pipe.apply(db).vars
    True
    """

    steps: tuple[PipelineStep, ...]
    history_start: int = 1
    history_end: int = 0
    itaca_version: str = __version__

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[PipelineStep]:
        return iter(self.steps)

    def __repr__(self) -> str:
        lines = [
            f"Pipeline({len(self.steps)} steps, "
            f"history {self.history_start}..{self.history_end})"
        ]
        lines.extend(
            f"  [{n}] {s.call}({s.canonical()})"
            + (f"  # {s.comment}" if s.comment else "")
            for n, s in enumerate(self.steps, start=1)
        )
        return "\n".join(lines)

    def content_hash(self) -> str:
        """SHA-256 over the canonical pipeline content (SRS 4.5).

        Covers the schema, the creating version, the source index range,
        and every step, so a file edited after generation is detected on
        load. Independent of the file's formatting.
        """
        canonical = json.dumps(
            {
                "schema": PIPELINE_SCHEMA,
                "itaca_version": self.itaca_version,
                "history_start": self.history_start,
                "history_end": self.history_end,
                "steps": [step.payload() for step in self.steps],
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def apply(self, db: VarFrame) -> VarFrame:
        """Replay the recorded sequence onto ``db`` (REQ-54).

        Parameters
        ----------
        db : VarFrame
            The frame to process. It must carry every variable,
            dimension, and declaration the recorded operations
            reference.

        Returns
        -------
        VarFrame
            The result of applying every step in order.

        Raises
        ------
        PipelineCompatibilityError
            A step cannot execute on ``db``, for example a variable or
            dimension it references is absent. The message names the
            failing step and keeps the underlying error's object and
            suggested fix.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([np.arange(5.0), np.arange(5.0)])
        >>> db = itc.load(arr, names=["x", "y"]).pivot(dims=["x"])
        >>> pipe = db.compute("z = y * 2").history.to_pipeline()
        >>> float(pipe.apply(db).vars["z"].values[1])
        2.0
        """
        from itaca.core.errors import ITACAError

        result = db
        for position, step in enumerate(self.steps, start=1):
            try:
                result = step.replay(result)
            except PipelineCompatibilityError:
                raise
            except ITACAError as exc:
                raise PipelineCompatibilityError(
                    f"pipeline step {position} ({step.call}) applied to {exc.obj}",
                    f"the target VarFrame is incompatible: {exc.operation}",
                    f"{exc.fix}; or re-extract the pipeline to match this "
                    "frame (REQ-54)",
                ) from exc
        return result

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the pipeline to a ``.itc_pipe`` file (REQ-55, SRS 4.5).

        The file is human-readable JSON recording the creating version,
        the source index range, every call with its arguments and
        comment, and a content hash. The write is atomic (temp file plus
        ``os.replace``).

        Parameters
        ----------
        path : str or path-like
            Destination path.

        Returns
        -------
        pathlib.Path
            The written path.

        Raises
        ------
        DataError
            A recorded argument has no JSON representation.
        """
        target = Path(path)
        payload = {
            "schema": PIPELINE_SCHEMA,
            "itaca_version": self.itaca_version,
            "history_start": self.history_start,
            "history_end": self.history_end,
            "content_hash": self.content_hash(),
            "steps": [step.payload() for step in self.steps],
        }
        text = json.dumps(payload, indent=2, allow_nan=False) + "\n"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
        return target


def _require(condition: bool, source: Path, problem: str, fix: str) -> None:
    """Raise a three-part DataError when a payload expectation fails."""
    if not condition:
        raise DataError(f"file '{source}'", f"load_pipeline {problem}", fix)


def load_pipeline(path: str | os.PathLike[str]) -> Pipeline:
    """Read a ``.itc_pipe`` file into a Pipeline (REQ-55).

    The payload is validated field by field, every recorded call is
    checked against :data:`REPLAYABLE_CALLS`, and the content hash is
    reverified, so a corrupted or hand-edited recipe fails loudly
    instead of replaying something unintended.

    Parameters
    ----------
    path : str or path-like
        Path to a ``.itc_pipe`` file written by :meth:`Pipeline.save`.

    Returns
    -------
    Pipeline
        The reconstructed pipeline.

    Raises
    ------
    DataError
        The file is unparseable, its schema is unknown, its payload is
        malformed, or it names a call that is not replayable.
    HashMismatchError
        The content hash does not match the payload.

    Examples
    --------
    >>> import numpy as np, tempfile, pathlib
    >>> import itaca as itc
    >>> arr = np.column_stack([np.arange(5.0), np.arange(5.0)])
    >>> db = itc.load(arr, names=["x", "y"]).pivot(dims=["x"])
    >>> pipe = db.compute("z = y * 2").history.to_pipeline()
    >>> target = pathlib.Path(tempfile.mkdtemp()) / "recipe.itc_pipe"
    >>> len(itc.load_pipeline(pipe.save(target)))
    1
    """
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataError(
            f"file '{source}'",
            "load_pipeline could not parse the .itc_pipe JSON",
            "pass a file written by Pipeline.save (REQ-55)",
        ) from exc
    _require(
        isinstance(payload, dict),
        source,
        "read a payload that is not a JSON object",
        "pass a file written by Pipeline.save (REQ-55)",
    )
    schema = payload.get("schema")
    _require(
        schema == PIPELINE_SCHEMA,
        source,
        f"read an unknown .itc_pipe schema {schema!r}",
        f"this build reads {PIPELINE_SCHEMA!r} (REQ-55)",
    )
    raw_steps = payload.get("steps")
    _require(
        isinstance(raw_steps, list),
        source,
        "read a payload whose 'steps' is missing or not a list",
        "pass a file written by Pipeline.save (REQ-55)",
    )
    steps: list[PipelineStep] = []
    for index, entry in enumerate(raw_steps, start=1):
        _require(
            isinstance(entry, dict),
            source,
            f"read step {index}, which is not a JSON object",
            "each step is an object with 'call', 'kwargs', and 'comment'",
        )
        call = entry.get("call")
        _require(
            isinstance(call, str),
            source,
            f"read step {index} without a string 'call'",
            "each step names the VarFrame operation to replay",
        )
        _require(
            call in REPLAYABLE_CALLS,
            source,
            f"read step {index} naming {call!r}, which is not replayable",
            f"expected one of {sorted(REPLAYABLE_CALLS)} (REQ-54)",
        )
        kwargs = entry.get("kwargs", {})
        _require(
            isinstance(kwargs, dict),
            source,
            f"read step {index} whose 'kwargs' is not a JSON object",
            "record keyword arguments as an object",
        )
        steps.append(
            PipelineStep(call=call, kwargs=kwargs, comment=entry.get("comment"))
        )
    pipeline = Pipeline(
        steps=tuple(steps),
        history_start=payload.get("history_start", 1),
        history_end=payload.get("history_end", len(steps)),
        itaca_version=payload.get("itaca_version", __version__),
    )
    recorded = payload.get("content_hash")
    if recorded is not None and recorded != pipeline.content_hash():
        raise HashMismatchError(
            f"file '{source}'",
            "the .itc_pipe content hash does not match its payload, so the "
            "file was modified after it was written",
            "re-save the pipeline with Pipeline.save, or restore the original "
            "file; the hash exists so an edited recipe cannot replay silently "
            "(SRS 4.5)",
        )
    return pipeline
