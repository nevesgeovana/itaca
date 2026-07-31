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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from itaca.core.canonical import feed, feed_array, text
from itaca.core.dimension import Dimension
from itaca.core.errors import ProvenanceError
from itaca.core.provenance import validate_mode
from itaca.core.variable import Variable

if TYPE_CHECKING:
    from itaca.core.axes import AxisRegistry
    from itaca.core.coords import CoordSystem
    from itaca.core.correlation import CorrelationMatrix
    from itaca.core.historyframe import HistoryFrame
    from itaca.core.pipeline import Pipeline, PipelineStep
    from itaca.core.uncframe import UncFrame

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
        stamp = timestamp if timestamp is not None else datetime.now(UTC)
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
                "apply at least one replayable operation before lifting a "
                "pipeline; if you did, either the frame is in draft mode and "
                "the operations ran without history=True, or it was reopened "
                "from a pre-0.2.0 .itc archive that carries no replay steps, "
                "which needs re-exporting with this version (REQ-10, REQ-53)",
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


def _update_with_metadata(
    digest: Any, kind: bytes, name: str, fields: Sequence[tuple[str, str | None]]
) -> None:
    """Emit every metadata field, set or not.

    Under the separator framing an unset field had to emit NOTHING, so
    that a frame declaring no metadata kept the digest it had before
    metadata entered the scope (DD-40). Canonical framing distinguishes
    absent from empty on its own (``-`` against ``0:``), so the field is
    always emitted and the special case is gone. The digest values that
    the omission preserved are not preserved by this change; they move
    once, with every other digest, at the schema 3 migration.
    """
    for field, value in fields:
        feed(digest, kind, text(name), text(field), text(value))


def compute_state_hash(
    *,
    dims: Mapping[str, Dimension],
    variables: Mapping[str, Variable],
    operations: Sequence[tuple[str, str | None]],
    coords: CoordSystem,
    mode: str,
    uncertainty: UncFrame | None = None,
    correlation: CorrelationMatrix | None = None,
    tags: HistoryFrame | None = None,
    axes: AxisRegistry | None = None,
) -> str:
    """Compute the canonical VarFrame state hash (REQ-103).

    The hash covers dimension names and coordinates (in order, since
    dimension order dictates array shape), variable names and values
    (sorted by name, since insertion order is incidental), the ordered
    operation sequence with comments, the spatial coordinate system, the
    operating mode, and the uncertainty, correlation, origin-tag and
    axis-registry content when present. It excludes every volatile
    field: timestamps, user identity, source paths, and the ITACA
    version.

    ``coords`` and ``mode`` are REQUIRED rather than defaulted, and that
    is the whole structural point of FND-089 and FND-037. Both were
    state that decided behavior from outside the digest: ``mode`` gates
    every export, ``coords`` selects the integration element. A field
    that a caller can forget to pass is a field that will be forgotten,
    which is the shape the defect had. A new call site now fails to
    type-check rather than silently narrowing what is authenticated.

    What this DOES NOT give is authentication against an adversary. A
    ``.itc`` carries no secret, so an editor who rewrites a member AND
    recomputes ``metadata.json`` produces an archive that opens. The
    guarantee is drift detection, which is what REQ-103 states: after
    this change a one-field edit no longer passes, where before
    ``mode`` could be flipped with no digest consequence at all.

    Parameters
    ----------
    dims : mapping of str to Dimension
        Ordered dimensions of the frame.
    variables : mapping of str to Variable
        Variables of the frame.
    operations : sequence of (str, str or None)
        Normalized operation strings with their comments, in order.
    coords : CoordSystem
        The spatial coordinate-system tag (REQ-28).
    mode : str
        The operating mode, ``"production"`` or ``"draft"`` (REQ-08).
    uncertainty : UncFrame or None, optional
        Uncertainty mirror, when present.
    correlation : CorrelationMatrix or None, optional
        Declared correlation structure, when present.
    tags : HistoryFrame or None, optional
        Origin-tag mirror, when present.
    axes : AxisRegistry or None, optional
        Registered frames and vector-group declarations; an empty
        registry contributes no tokens. That no longer preserves any
        historical digest, since every digest moved once at DD-47; it
        remains true of the mechanism.

    Returns
    -------
    str
        64-character hexadecimal SHA-256 digest.

    Raises
    ------
    ProvenanceError
        If ``mode`` is not a valid operating mode. A misspelled mode
        would otherwise yield a well formed digest that nothing ever
        reproduces (REQ-08).

    Examples
    --------
    >>> import numpy as np
    >>> from itaca.core.coords import Cartesian
    >>> h = compute_state_hash(
    ...     dims={"x": Dimension(name="x", coords=np.array([0.0]))},
    ...     variables={},
    ...     operations=(),
    ...     coords=Cartesian(),
    ...     mode="production",
    ... )
    >>> len(h)
    64
    """
    # Required-ness closes the omission, and validation closes the typo.
    # mode is a plain str and now decides the digest, so mode="Production"
    # would produce a perfectly well formed 64-hex value that no other
    # frame ever reproduces. Validating here rather than trusting the
    # caller is the same argument that made the argument required.
    validate_mode(mode)
    digest = hashlib.sha256()
    for name, dim in dims.items():
        feed(digest, b"dim", text(name))
        feed_array(digest, dim.coords)
        _update_with_metadata(
            digest,
            b"dimmeta",
            name,
            (("unit", dim.unit), ("description", dim.description)),
        )
    for name in sorted(variables):
        variable = variables[name]
        feed(digest, b"var", text(name))
        feed_array(digest, variable.values)
        _update_with_metadata(
            digest,
            b"varmeta",
            name,
            (
                ("unit", variable.unit),
                ("description", variable.description),
                ("long_name", variable.long_name),
            ),
        )
    for operation, comment in operations:
        feed(digest, b"op", text(operation), text(comment))
    feed(digest, b"coords", text(coords.name))
    feed(digest, b"mode", text(mode))
    if uncertainty is not None:
        for label, component in (
            ("sys", uncertainty.systematic),
            ("rand", uncertainty.random),
        ):
            for name in sorted(component):
                feed(digest, b"unc", text(label), text(name))
                feed_array(digest, component[name])
    if correlation is not None:
        for pair in sorted(correlation.pairs):
            feed(
                digest,
                b"corr",
                text(pair[0]),
                text(pair[1]),
                text(repr(correlation.pairs[pair])),
            )
    if tags is not None:
        for name in sorted(tags.tags):
            feed(digest, b"tag", text(name))
            feed_array(digest, tags.tags[name])
    if axes is not None:
        for token in axes.canonical_tokens():
            feed(digest, b"axes", text(token))
    return digest.hexdigest()
