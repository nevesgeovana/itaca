"""Reusable pipelines: record a processing sequence, replay it.

REQ-53 to REQ-55 and DD (pipeline replay representation). A
``Pipeline`` is a contiguous range of History entries lifted into a
reusable object. It replays by re-dispatching structured steps, not by
re-parsing the History display strings: each replayable operation
records a :class:`PipelineStep` (the VarFrame method name and its
keyword arguments) as it derives, so a pipeline reconstructs the exact
calls rather than the human-facing text. The ``.itc_pipe`` file is
human-readable JSON with a versioned schema, written atomically like
the ``.itc`` archive (``docs/PYFLIGHTSTREAM_ADOPTIONS.md``, Phase 5).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from itaca.core.errors import DataError

if TYPE_CHECKING:
    from itaca.core.varframe import VarFrame

PIPELINE_SCHEMA = "itaca-itc_pipe/1"


def to_jsonable(value: Any) -> Any:
    """Normalize a replay argument into a JSON-native value.

    NumPy arrays and scalars become lists and Python numbers, and
    tuples become lists, so every recorded step serializes losslessly
    into a ``.itc_pipe`` file. Values that are already JSON-native pass
    through unchanged.
    """
    if isinstance(value, np.ndarray):
        return [to_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class PipelineStep:
    """One replayable operation: a VarFrame method and its keyword call.

    Parameters
    ----------
    method : str
        The public ``VarFrame`` method to call on replay, e.g.
        ``"smooth"``.
    kwargs : mapping of str to object
        Keyword arguments passed to that method. Values are JSON
        literals (str, number, bool, None, list, dict) so the step
        serializes losslessly into a ``.itc_pipe`` file.
    """

    method: str
    kwargs: Mapping[str, Any]

    def replay(self, db: VarFrame) -> VarFrame:
        """Apply this step to ``db`` and return the derived VarFrame."""
        bound = getattr(db, self.method)
        return bound(**self.kwargs)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class Pipeline:
    """A reusable, ordered sequence of replayable operations (REQ-53).

    Built by :meth:`itaca.core.history.History.to_pipeline`. Apply it to
    a new VarFrame with :meth:`apply`, or persist it with :meth:`save`
    and reload it with :func:`load_pipeline`.

    Examples
    --------
    >>> import numpy as np
    >>> import itaca as itc
    >>> arr = np.column_stack([np.arange(7.0), np.arange(7.0) ** 2])
    >>> db = itc.load(arr, names=["x", "y"]).pivot(dims=["x"])
    >>> processed = db.compute("z = y + 1")
    >>> pipe = processed.history.to_pipeline(start=2)
    >>> len(pipe)
    1
    >>> "z" in pipe.apply(db).vars
    True
    """

    steps: tuple[PipelineStep, ...]

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[PipelineStep]:
        return iter(self.steps)

    def apply(self, db: VarFrame) -> VarFrame:
        """Replay the recorded sequence onto ``db`` (REQ-54).

        Parameters
        ----------
        db : VarFrame
            The frame to process. It must carry every variable and
            dimension the recorded operations reference.

        Returns
        -------
        VarFrame
            The result of applying every step in order.

        Raises
        ------
        PipelineCompatibilityError
            A step references a variable or dimension absent from
            ``db``.
        """
        from itaca.core.errors import PipelineCompatibilityError

        result = db
        for position, step in enumerate(self.steps, start=1):
            try:
                result = step.replay(result)
            except DataError as exc:
                raise PipelineCompatibilityError(
                    f"pipeline step {position} ({step.method})",
                    f"the target VarFrame is incompatible: {exc.operation}",
                    "apply the pipeline to a frame that carries the variables "
                    "and dimensions the recorded operations reference (REQ-54)",
                ) from exc
        return result

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the pipeline to a ``.itc_pipe`` file (REQ-55).

        The file is human-readable JSON and version-controllable. The
        write is atomic (temp file plus ``os.replace``).

        Parameters
        ----------
        path : str or path-like
            Destination path.

        Returns
        -------
        pathlib.Path
            The written path.
        """
        target = Path(path)
        payload = {
            "schema": PIPELINE_SCHEMA,
            "steps": [
                {"method": step.method, "kwargs": dict(step.kwargs)}
                for step in self.steps
            ],
        }
        text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
        return target


def load_pipeline(path: str | os.PathLike[str]) -> Pipeline:
    """Read a ``.itc_pipe`` file into a Pipeline (REQ-55).

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
        The file schema is unknown or the payload is malformed.
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
    schema = payload.get("schema")
    if schema != PIPELINE_SCHEMA:
        raise DataError(
            f"file '{source}' with schema {schema!r}",
            "load_pipeline read an unknown .itc_pipe schema",
            f"this build reads {PIPELINE_SCHEMA!r} (REQ-55)",
        )
    steps = tuple(
        PipelineStep(method=entry["method"], kwargs=entry["kwargs"])
        for entry in payload["steps"]
    )
    return Pipeline(steps=steps)
