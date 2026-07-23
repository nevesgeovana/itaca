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
    from itaca.core.uncframe import UncFrame

_SEP = b"\x1f"


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
    """

    index: int
    operation: str
    timestamp: datetime
    state_hash: str
    comment: str | None = None


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
        )
        return History(entries=(*self.entries, entry))

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
    and origin-tag content when present. It excludes every volatile
    field: timestamps, user identity, source paths, and the ITACA
    version.

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
