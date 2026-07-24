"""History: the append-only operation record, and the state hash.

SRS 4.4.2 and REQ-103; DD-01. The mechanics follow the append-only
manifest discipline adopted from pyflightstream
(``docs/PYFLIGHTSTREAM_ADOPTIONS.md``): frozen entries, contiguous
indices enforced on construction, appending returns a new object, and
the state hash is a canonical, formatting-independent SHA-256.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.errors import ProvenanceError
from itaca.core.variable import Variable

if TYPE_CHECKING:
    from itaca.core.axes import AxisRegistry
    from itaca.core.correlation import CorrelationMatrix
    from itaca.core.historyframe import HistoryFrame
    from itaca.core.pipeline import Pipeline, PipelineStep
    from itaca.core.uncframe import UncFrame

_SEP = b"\x1f"

_PREPARATION_OPS = frozenset({"load", "pivot"})
"""Operations that build the input frame rather than transform it.

``to_pipeline`` omits these when they lead the requested range: they
construct the frame a pipeline is applied *to*, so replaying them makes
no sense. The set is an explicit allowlist rather than "records no
step", because that test would also swallow a transform that simply was
not wired for replay and silently change the result (REQ-53).
"""


@dataclass(frozen=True)
class HistoryEntry:
    """A single History record (SRS Table: fields of a History entry).

    Parameters
    ----------
    index : int
        Sequential index within the VarFrame, starting at 1.
    operation : str
        Operation name with normalized arguments.
    timestamp : datetime.datetime
        When the operation was applied (timezone-aware).
    state_hash : str
        SHA-256 of the resulting VarFrame state (REQ-103).
    comment : str or None, optional
        User comment passed via ``comment=`` (REQ-19).
    step : PipelineStep or None, optional
        The replayable step this entry contributes to a pipeline
        (REQ-54). ``None`` marks a non-replayable entry: the initial
        ``load`` anchor, or a state-only or multi-input operation. It is
        excluded from the state hash (replay metadata, not state).
    """

    index: int
    operation: str
    timestamp: datetime
    state_hash: str
    comment: str | None = None
    step: PipelineStep | None = None

    @property
    def replayable(self) -> bool:
        """Whether this entry contributes a step to a Pipeline (REQ-54)."""
        return self.step is not None

    @property
    def name(self) -> str:
        """The operation name without its arguments, e.g. ``"smooth"``."""
        return self.operation.split("(", 1)[0]


@dataclass(frozen=True)
class History:
    """Ordered, append-only sequence of operations (SRS 4.4.2).

    Appending returns a new ``History``; entries are never mutated.
    Indices are validated to be contiguous from 1 so a hand-built or
    corrupted sequence is rejected at construction.

    Examples
    --------
    >>> history = History().append(operation="load()", state_hash="0" * 64)
    >>> history[0].index
    1
    """

    entries: tuple[HistoryEntry, ...] = ()

    def __post_init__(self) -> None:
        for position, entry in enumerate(self.entries, start=1):
            if entry.index != position:
                raise ProvenanceError(
                    f"History entry with index {entry.index}",
                    f"construction at position {position}: indices must be "
                    "contiguous starting at 1",
                    "build histories only through History.append",
                )

    def append(
        self,
        *,
        operation: str,
        state_hash: str,
        comment: str | None = None,
        timestamp: datetime | None = None,
        step: PipelineStep | None = None,
    ) -> History:
        """Return a new History with one entry appended.

        Parameters
        ----------
        operation : str
            Operation name with normalized arguments.
        state_hash : str
            SHA-256 of the resulting VarFrame state.
        comment : str or None, optional
            User comment (REQ-19).
        timestamp : datetime.datetime or None, optional
            Defaults to the current UTC time.
        step : PipelineStep or None, optional
            The replayable pipeline step, when the operation supports
            replay (REQ-54).

        Returns
        -------
        History
            A new object; ``self`` is unchanged.
        """
        stamp = timestamp if timestamp is not None else datetime.now(timezone.utc)
        entry = HistoryEntry(
            index=len(self.entries) + 1,
            operation=operation,
            timestamp=stamp,
            state_hash=state_hash,
            comment=comment,
            step=step,
        )
        return History(entries=(*self.entries, entry))

    def to_pipeline(self, start: int | None = None, end: int | None = None) -> Pipeline:
        """Extract a contiguous index range as a reusable Pipeline (REQ-53).

        Parameters
        ----------
        start : int or None, optional
            First history index, 1-based and inclusive: the number shown
            by ``print(db.history)``. Defaults to the first entry. Note
            that ``history[0]`` is 0-based positional indexing, a
            different convention from this one.
        end : int or None, optional
            Last history index (1-based, inclusive). Defaults to the
            last entry.

        Returns
        -------
        Pipeline
            The replayable steps in the requested range. Frame
            construction entries (``load`` and ``pivot``) are input
            preparation: they are omitted when they lead the range, so
            the pipeline is usually shorter than the range itself.

        Raises
        ------
        DataError
            The history is empty, or the range is out of bounds.
        PipelineCompatibilityError
            The range spans an operation that records no replayable step
            and is not frame construction (a multi-input ``concat`` or
            ``combine``), or the range yields no replayable step at all.
            The latter happens on a draft-mode frame, where operations
            record only with ``history=True``, and on a frame reopened
            from a ``.itc`` archive written before steps were persisted;
            it raises rather than returning a pipeline that would apply
            as a silent no-op.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([np.arange(5.0), np.arange(5.0)])
        >>> db = itc.load(arr, names=["x", "y"]).pivot(dims=["x"])
        >>> pipe = db.compute("z = y * 2").history.to_pipeline()
        >>> len(pipe)
        1
        """
        from itaca.core.errors import DataError, PipelineCompatibilityError
        from itaca.core.pipeline import Pipeline

        count = len(self.entries)
        if count == 0:
            raise DataError(
                "an empty History",
                "to_pipeline was called on a VarFrame with no recorded operations",
                "process the frame first; in draft mode pass history=True per "
                "operation, or switch to production mode (REQ-10, REQ-53)",
            )
        lo = 1 if start is None else start
        hi = count if end is None else end
        if lo < 1 or hi > count or lo > hi:
            raise DataError(
                f"history range start={start}, end={end}",
                f"to_pipeline received a range outside 1..{count}",
                "pass 1-based indices with start <= end within the history (REQ-53)",
            )
        steps: list[PipelineStep] = []
        for entry in self.entries[lo - 1 : hi]:
            if entry.step is not None:
                steps.append(entry.step)
                continue
            if not steps and entry.name in _PREPARATION_OPS:
                continue  # frame construction: the input, never replayed
            raise PipelineCompatibilityError(
                f"history entry [{entry.index}] {entry.operation}",
                "to_pipeline spans an operation that records no replayable "
                "step, so the sequence cannot be reproduced faithfully",
                "narrow the range to the replayable transforms; operations "
                "that merge frames (concat, combine) are not part of a "
                "reusable pipeline (REQ-53)",
            )
        if not steps:
            raise PipelineCompatibilityError(
                f"history range {lo}..{hi}",
                "to_pipeline found no replayable operation in the range, so "
                "the pipeline would apply as a silent no-op",
                "re-run the processing in draft mode with history=True per "
                "operation, or switch to production mode, and lift the "
                "pipeline from that frame; a frame reopened from a pre-0.2.0 "
                ".itc archive carries no replay steps, so re-export the "
                "archive with this version first (REQ-10, REQ-53)",
            )
        from itaca.core.version import __version__

        return Pipeline(
            steps=tuple(steps),
            history_start=lo,
            history_end=hi,
            itaca_version=__version__,
        )

    @property
    def last(self) -> HistoryEntry | None:
        """The most recent entry, or ``None`` for an empty history."""
        return self.entries[-1] if self.entries else None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[HistoryEntry]:
        return iter(self.entries)

    def __getitem__(self, position: int) -> HistoryEntry:
        return self.entries[position]

    def __repr__(self) -> str:
        lines = [f"History({len(self.entries)} entries)"]
        lines.extend(
            f"  [{e.index}] {e.operation}" + (f"  # {e.comment}" if e.comment else "")
            for e in self.entries
        )
        return "\n".join(lines)


def _update_with_array(digest: Any, array: NDArray[Any]) -> None:
    contiguous = np.ascontiguousarray(array)
    digest.update(str(contiguous.dtype).encode())
    digest.update(_SEP)
    digest.update(str(contiguous.shape).encode())
    digest.update(_SEP)
    digest.update(contiguous.tobytes())
    digest.update(_SEP)


def compute_state_hash(
    *,
    dims: Mapping[str, Dimension],
    variables: Mapping[str, Variable],
    operations: Sequence[tuple[str, str | None]],
    uncertainty: UncFrame | None = None,
    correlation: CorrelationMatrix | None = None,
    tags: HistoryFrame | None = None,
    axes: AxisRegistry | None = None,
) -> str:
    """Compute the canonical VarFrame state hash (REQ-103).

    The hash covers dimension names and coordinates (in order, since
    dimension order dictates array shape), variable names and values
    (sorted by name, since insertion order is incidental), the ordered
    operation sequence with comments, and the uncertainty, correlation,
    origin-tag, and axis-registry content when present. It excludes
    every volatile field: timestamps, user identity, source paths, and
    the ITACA version.

    Parameters
    ----------
    dims : mapping of str to Dimension
        Ordered dimensions of the frame.
    variables : mapping of str to Variable
        Variables of the frame.
    operations : sequence of (str, str or None)
        Normalized operation strings with their comments, in order.
    uncertainty : UncFrame or None, optional
        Uncertainty mirror, when present.
    correlation : CorrelationMatrix or None, optional
        Declared correlation structure, when present.
    tags : HistoryFrame or None, optional
        Origin-tag mirror, when present.
    axes : AxisRegistry or None, optional
        Registered frames and vector-group declarations; an empty
        registry contributes no tokens, so a frame that registers no
        custom axis keeps the hash it had before the registry existed.

    Returns
    -------
    str
        64-character hexadecimal SHA-256 digest.

    Examples
    --------
    >>> import numpy as np
    >>> h = compute_state_hash(
    ...     dims={"x": Dimension(name="x", coords=np.array([0.0]))},
    ...     variables={},
    ...     operations=(),
    ... )
    >>> len(h)
    64
    """
    digest = hashlib.sha256()
    for name, dim in dims.items():
        digest.update(b"dim")
        digest.update(_SEP)
        digest.update(name.encode())
        digest.update(_SEP)
        _update_with_array(digest, dim.coords)
    for name in sorted(variables):
        digest.update(b"var")
        digest.update(_SEP)
        digest.update(name.encode())
        digest.update(_SEP)
        _update_with_array(digest, variables[name].values)
    for operation, comment in operations:
        digest.update(b"op")
        digest.update(_SEP)
        digest.update(operation.encode())
        digest.update(_SEP)
        digest.update((comment or "").encode())
        digest.update(_SEP)
    if uncertainty is not None:
        for label, component in (
            ("sys", uncertainty.systematic),
            ("rand", uncertainty.random),
        ):
            for name in sorted(component):
                digest.update(b"unc")
                digest.update(_SEP)
                digest.update(label.encode())
                digest.update(_SEP)
                digest.update(name.encode())
                digest.update(_SEP)
                _update_with_array(digest, component[name])
    if correlation is not None:
        for pair in sorted(correlation.pairs):
            digest.update(b"corr")
            digest.update(_SEP)
            digest.update(pair[0].encode())
            digest.update(_SEP)
            digest.update(pair[1].encode())
            digest.update(_SEP)
            digest.update(repr(correlation.pairs[pair]).encode())
            digest.update(_SEP)
    if tags is not None:
        for name in sorted(tags.tags):
            digest.update(b"tag")
            digest.update(_SEP)
            digest.update(name.encode())
            digest.update(_SEP)
            _update_with_array(digest, tags.tags[name])
    if axes is not None:
        for token in axes.canonical_tokens():
            digest.update(b"axes")
            digest.update(_SEP)
            digest.update(token.encode())
            digest.update(_SEP)
    return digest.hexdigest()
