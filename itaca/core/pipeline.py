"""Reusable pipelines: record a processing sequence, replay it.

REQ-53 to REQ-55, the ``.itc_pipe`` section of SRS Chapter 4, and
DD-28. A ``Pipeline`` is a contiguous
range of History entries lifted into a reusable object. It replays by
re-dispatching structured steps, not by re-parsing the History display
strings: each replayable operation records a :class:`PipelineStep` (the
VarFrame method to call, its keyword arguments, and the History
comment) as it derives, so a pipeline reconstructs the exact calls
rather than the human-facing text.

Replayed onto the frame the range was lifted from, a pipeline
reproduces the state hash. Replayed onto a different frame it
reproduces the processing, not the hash: the data differs, so the hash
of the data must differ too. That is the intended use, and the reason a
recipe is worth keeping.

The file is readable for review and for diffing in version control,
not for hand editing. The content hash rejects any change made after
the write, so a step is altered by re-running the operation and lifting
a new pipeline.

The ``.itc_pipe`` file is human-readable JSON carrying everything that
section requires: the ITACA version that created it, the index range in
the source history, each operation's call with its keyword arguments
and attached comment (REQ-19), and a content hash for integrity
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


def _to_jsonable(value: Any) -> Any:
    """Normalize a replay argument toward a JSON-native value.

    NumPy arrays and scalars become lists and Python numbers, and tuples
    become lists. This is a normalizer, not a validator: a value it
    cannot interpret passes through untouched, and whether the result is
    representable is decided at save time by
    :func:`_reject_unserializable`. Validating here would make a
    serialization rule reject an operation the user never intended to
    persist (``compute(fill=inf)`` is legal under REQ-35).

    Parameters
    ----------
    value : object
        A replay argument recorded by an operation.

    Returns
    -------
    object
        A JSON-native equivalent where one exists.

    Examples
    --------
    >>> _to_jsonable(np.float64(2.5))
    2.5
    >>> _to_jsonable((1, 2))
    [1, 2]
    """
    if isinstance(value, np.ndarray):
        return [_to_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _to_jsonable(value.item())
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _freeze(value: Any) -> Any:
    """Return a deeply immutable view of a normalized replay argument.

    A shallow ``MappingProxyType`` still lets a caller reach through a
    nested list or mapping and rewrite recorded provenance in place, so
    the freeze has to go all the way down.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Invert :func:`_freeze` for JSON output and for replay dispatch."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _sibling(source: Path) -> str:
    """Name the other reader when the suffix says which one was wanted.

    A workflow now produces two suffixes, and the suffix is a free,
    certain signal. Which fix a user saw must not depend on whether the
    bytes happened to decode as UTF-8, so both read failures use this.
    """
    if source.suffix == ".itc":
        return "; this looks like a .itc archive, which itc.open reads"
    return ""


def _reject_unserializable(position: int, step: PipelineStep) -> None:
    """Raise a three-part error for a step that cannot be written."""
    for name, value in step.kwargs.items():
        try:
            json.dumps(_thaw(value), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise DataError(
                f"step {position} ({step.call}) argument '{name}'",
                "the recorded value has no RFC 8259 JSON representation, so "
                f"the pipeline cannot be written ({exc})",
                "pass a finite number or a JSON-native value for that "
                "argument; the .itc_pipe file must stay readable by any JSON "
                "tool (REQ-55)",
            ) from exc


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
        object.__setattr__(self, "kwargs", _freeze(dict(self.kwargs)))

    def __hash__(self) -> int:
        return hash((self.call, self.comment, self._canonical()))

    def _canonical(self) -> str:
        """Canonical JSON text of this step's arguments, for hashing."""
        return json.dumps(
            _thaw(self.kwargs), sort_keys=True, default=repr, allow_nan=True
        )

    def _summary(self) -> str:
        """One-line argument summary for a bounded repr."""
        text = self._canonical()
        return text if len(text) <= 60 else text[:57] + "..."

    def _payload(self) -> dict[str, Any]:
        """Return the JSON-native record written to a ``.itc_pipe`` file."""
        return {
            "call": self.call,
            "comment": self.comment,
            "kwargs": _thaw(self.kwargs),
        }

    def replay(self, db: VarFrame, *, history: bool = False) -> VarFrame:
        """Apply this step to ``db`` and return the derived VarFrame.

        Parameters
        ----------
        db : VarFrame
            The frame to apply the recorded call to.
        history : bool, optional
            In draft mode, record the replayed operation only when True
            (REQ-10); in production mode every replayed operation is
            recorded either way. A draft-mode replay left at the default
            appends no entry for these steps, so no pipeline can be
            lifted from the result.

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
        try:
            arguments = _rehydrate(self.call, _thaw(self.kwargs))
        except (TypeError, KeyError, ValueError, AttributeError) as exc:
            raise PipelineCompatibilityError(
                f"pipeline step {self.call!r}",
                f"its recorded arguments are malformed ({type(exc).__name__}: {exc})",
                "the .itc_pipe file was hand-edited or written by a different "
                "ITACA version; re-extract the pipeline (REQ-54)",
            ) from exc
        try:
            return bound(  # type: ignore[no-any-return]
                **arguments, comment=self.comment, history=history
            )
        except (TypeError, KeyError, ValueError, AttributeError) as exc:
            raise PipelineCompatibilityError(
                f"pipeline step {self.call!r}",
                f"its recorded arguments do not match the operation "
                f"signature ({type(exc).__name__}: {exc})",
                "the recipe was written by a different ITACA version; "
                "re-extract it against this one (REQ-54)",
            ) from exc


@dataclass(frozen=True, kw_only=True)
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
        this pipeline was lifted from (SRS Chapter 4, the .itc_pipe section).
    itaca_version : str, optional
        The ITACA version that created the pipeline.

    Raises
    ------
    DataError
        ``steps`` is empty. Applying such a pipeline would return the
        target unchanged and unrecorded, so it is refused where it is
        built, where it is constructed, and where it is read.

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
    history_start: int | None = None
    history_end: int | None = None
    itaca_version: str | None = None

    def __post_init__(self) -> None:
        """Refuse the empty pipeline, which would apply as a silent no-op."""
        if not self.steps:
            raise DataError(
                "pipeline",
                "a pipeline with no steps was constructed, and applying it "
                "would return the target unchanged and unrecorded",
                "lift a range that contains at least one replayable "
                "operation with db.history.to_pipeline() (REQ-53)",
            )

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[PipelineStep]:
        return iter(self.steps)

    def __repr__(self) -> str:
        count = len(self.steps)
        plural = "" if count == 1 else "s"
        if self.history_start is None or self.history_end is None:
            span = "not lifted from a history"
        else:
            span = f"history {self.history_start}..{self.history_end}"
        lines = [f"Pipeline({count} step{plural}, {span})"]
        lines.extend(
            f"  [{n}] {s.call}({s._summary()})"
            + (f"  # {s.comment}" if s.comment else "")
            for n, s in enumerate(self.steps, start=1)
        )
        return "\n".join(lines)

    @property
    def content_hash(self) -> str:
        """SHA-256 over the canonical pipeline content.

        Required by the ``.itc_pipe`` section of SRS Chapter 4.

        Covers the schema, the creating version, the source index range,
        and every step, so a file edited after generation is detected on
        load. Independent of the file's formatting.

        Raises
        ------
        DataError
            A recorded argument has no JSON representation, for example a
            non-finite fill value. REQ-35 admits it as a value; only
            persisting it can fail, and this property persists.
        """
        for position, step in enumerate(self.steps, start=1):
            _reject_unserializable(position, step)
        canonical = json.dumps(
            {
                "schema": PIPELINE_SCHEMA,
                "itaca_version": self.itaca_version,
                "history_start": self.history_start,
                "history_end": self.history_end,
                "steps": [step._payload() for step in self.steps],
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def apply(self, db: VarFrame, *, history: bool = False) -> VarFrame:
        """Replay the recorded sequence onto ``db`` (REQ-54).

        Parameters
        ----------
        db : VarFrame
            The frame to process. It must carry every variable,
            dimension, and declaration the recorded operations
            reference.
        history : bool, optional
            In draft mode, record each replayed operation only when True
            (REQ-10); in production mode every replayed operation is
            recorded either way. A draft-mode replay left at the default
            appends no entry for these steps, so no pipeline can be
            lifted from the result.

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

        # ``apply`` reads as if it might take a path or an array, so the
        # wrong target is a likely first-try mistake. Catching it here
        # turns a bare AttributeError about a missing attribute into an
        # error that names the operation and what to pass instead.
        if not hasattr(db, "vars") or not hasattr(db, "history"):
            raise PipelineCompatibilityError(
                f"pipeline applied to {type(db).__name__}",
                "apply expects a VarFrame to replay the recorded operations "
                f"onto, and the target is a {type(db).__name__}",
                "pass a VarFrame, for example itc.open(path) or "
                "itc.load(...).pivot(...) (REQ-54)",
            )
        result = db
        for position, step in enumerate(self.steps, start=1):
            try:
                result = step.replay(result, history=history)
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
        """Write the pipeline to a ``.itc_pipe`` file (REQ-55, SRS Chapter 4).

        The file is human-readable JSON recording the creating version,
        the source index range, every call with its arguments and
        comment, and a content hash. The write is atomic (temp file plus
        ``os.replace``).

        Readable for review and for diffing in version control, not for
        hand editing: the content hash rejects any change made after the
        write, so a step is altered by re-running the operation and
        lifting a new pipeline.

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
        for position, step in enumerate(self.steps, start=1):
            _reject_unserializable(position, step)
        payload = {
            "schema": PIPELINE_SCHEMA,
            "itaca_version": self.itaca_version,
            "history_start": self.history_start,
            "history_end": self.history_end,
            "content_hash": self.content_hash,
            "steps": [step._payload() for step in self.steps],
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
        The file is missing or unreadable, unparseable, its schema is
        unknown, its payload is malformed, it records no steps, or it
        names a call that is not replayable.
    HashMismatchError
        The content hash does not match the payload. The file is
        readable for review and diffing, not for hand editing: change a
        step by re-running the operation and lifting a new pipeline.

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
            f"pass a file written by Pipeline.save (REQ-55){_sibling(source)}",
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        # A missing path and a binary file are the two likeliest first-try
        # mistakes, and both used to escape as stdlib exceptions. They
        # need different remedies: a typo wants "check the path", not
        # "re-save your pipeline", which reads as if the file were the
        # wrong kind when it is simply not there.
        if not source.exists():
            raise DataError(
                f"file '{source}'",
                f"load_pipeline could not find it ({type(exc).__name__})",
                "check the path; .itc_pipe files are written by Pipeline.save (REQ-55)",
            ) from exc
        raise DataError(
            f"file '{source}'",
            f"load_pipeline could not read it ({type(exc).__name__}: {exc})",
            f"pass a .itc_pipe file written by Pipeline.save "
            f"(REQ-55){_sibling(source)}",
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
    # History.to_pipeline refuses to build a pipeline with no steps
    # because it would apply as a silent no-op. The reader must refuse
    # the same file the writer would never produce.
    _require(
        bool(raw_steps),
        source,
        "read a payload with no steps, which would apply as a silent no-op",
        "extract the recipe with db.history.to_pipeline().save(path) rather "
        "than hand-writing the file (REQ-53)",
    )
    steps: list[PipelineStep] = []
    for index, entry in enumerate(raw_steps, start=1):
        _require(
            isinstance(entry, dict),
            source,
            f"read step {index}, which is not a JSON object",
            "each step is an object with 'call', 'kwargs', and 'comment'; "
            "re-extract the recipe with db.history.to_pipeline().save(path) "
            "rather than hand-writing the file",
        )
        call = entry.get("call")
        _require(
            isinstance(call, str),
            source,
            f"read step {index} without a string 'call'",
            "each step names the VarFrame operation to replay; re-extract "
            "the recipe with db.history.to_pipeline().save(path) rather than "
            "hand-writing the file",
        )
        _require(
            call in REPLAYABLE_CALLS,
            source,
            f"read step {index} naming {call!r}, which is not replayable",
            "re-extract the recipe with db.history.to_pipeline().save(path); "
            "the replayable operations are fixed and the file is not "
            "hand-editable, so correcting the name in place will fail the "
            "content hash (REQ-54)",
        )
        kwargs = entry.get("kwargs", {})
        _require(
            isinstance(kwargs, dict),
            source,
            f"read step {index} whose 'kwargs' is not a JSON object",
            "record keyword arguments as an object; re-extract the recipe "
            "with db.history.to_pipeline().save(path) rather than "
            "hand-writing the file",
        )
        steps.append(
            PipelineStep(call=call, kwargs=kwargs, comment=entry.get("comment"))
        )
    for field_name in ("history_start", "history_end", "itaca_version"):
        _require(
            field_name in payload,
            source,
            f"read a payload with no {field_name!r}",
            "pass a file written by Pipeline.save; the provenance fields are "
            "recorded, never invented at read time",
        )
    pipeline = Pipeline(
        steps=tuple(steps),
        history_start=payload["history_start"],
        history_end=payload["history_end"],
        itaca_version=payload["itaca_version"],
    )
    recorded = payload.get("content_hash")
    _require(
        isinstance(recorded, str),
        source,
        "read a payload with no 'content_hash', so its integrity cannot be verified",
        "pass a file written by Pipeline.save; the hash is mandatory so that "
        "deleting it cannot silently disable verification (SRS Chapter 4, the "
        ".itc_pipe section)",
    )
    if recorded != pipeline.content_hash:
        raise HashMismatchError(
            f"file '{source}'",
            "the .itc_pipe content hash does not match its payload, so the "
            "file was modified after it was written",
            "re-save the pipeline with Pipeline.save, or restore the original "
            "file; the hash exists so an edited recipe cannot replay silently "
            "(SRS Chapter 4, the .itc_pipe section)",
        )
    return pipeline
