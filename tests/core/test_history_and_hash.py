"""Tests for History and the state hash (SRS 4.4.2, REQ-103; DD-01).

History follows the append-only manifest discipline adopted from
pyflightstream: frozen entries, contiguous indices enforced on
construction, appending returns a new object.

Usage example (the contract under test)::

    from itaca.core.history import History

    history = History().append(operation="load(...)", state_hash="...")
    assert history[0].index == 1
"""

from datetime import datetime, timezone

import numpy as np
import pytest

from itaca.core.dimension import Dimension
from itaca.core.errors import ProvenanceError
from itaca.core.history import History, HistoryEntry, compute_state_hash
from itaca.core.variable import Variable


def _entry(index: int, operation: str = "op") -> HistoryEntry:
    return HistoryEntry(
        index=index,
        operation=operation,
        timestamp=datetime(2026, 7, 21, tzinfo=timezone.utc),
        state_hash="f" * 64,
    )


class TestHistory:
    def test_empty(self) -> None:
        history = History()
        assert len(history) == 0
        assert history.last is None

    def test_append_returns_new_history(self) -> None:
        # DD-03 instinct applied to History: append-only, immutable.
        h0 = History()
        h1 = h0.append(operation="load(source='a.csv')", state_hash="a" * 64)
        assert len(h0) == 0
        assert len(h1) == 1
        entry = h1[0]
        assert entry.index == 1
        assert entry.operation == "load(source='a.csv')"
        assert entry.comment is None
        assert entry.timestamp.tzinfo is not None

    def test_indices_are_sequential_from_one(self) -> None:
        history = History()
        for i in range(3):
            history = history.append(operation=f"op{i}", state_hash="a" * 64)
        assert [e.index for e in history] == [1, 2, 3]
        assert history.last is not None
        assert history.last.index == 3

    def test_comment_is_stored(self) -> None:
        # REQ-19: optional comment on every operation.
        history = History().append(
            operation="fill(along='alpha')",
            state_hash="a" * 64,
            comment="removed bad point at alpha=8.0",
        )
        assert history[0].comment == "removed bad point at alpha=8.0"

    def test_non_contiguous_indices_rejected(self) -> None:
        with pytest.raises(ProvenanceError):
            History(entries=(_entry(1), _entry(3)))

    def test_indices_must_start_at_one(self) -> None:
        with pytest.raises(ProvenanceError):
            History(entries=(_entry(2),))

    def test_repr_lists_entries_with_comments(self) -> None:
        history = History().append(
            operation="load()", state_hash="a" * 64, comment="first"
        )
        text = repr(history)
        assert "History(1 entries)" in text
        assert "[1] load()" in text
        assert "first" in text

    def test_getitem(self) -> None:
        history = History().append(operation="load()", state_hash="a" * 64)
        assert history[0] is history.entries[0]


class TestStateHash:
    def _content(
        self, values: np.ndarray | None = None
    ) -> tuple[dict[str, Dimension], dict[str, Variable]]:
        if values is None:
            values = np.arange(3.0)
        dims = {"alpha": Dimension(name="alpha", coords=np.array([0.0, 2.0, 4.0]))}
        variables = {"CT": Variable(name="CT", values=values)}
        return dims, variables

    def test_deterministic(self) -> None:
        # REQ-103: same content, same operations, same hash.
        dims_a, vars_a = self._content()
        dims_b, vars_b = self._content()
        ops = (("load(source='a.csv')", None),)
        h1 = compute_state_hash(dims=dims_a, variables=vars_a, operations=ops)
        h2 = compute_state_hash(dims=dims_b, variables=vars_b, operations=ops)
        assert h1 == h2
        assert len(h1) == 64

    def test_sensitive_to_values(self) -> None:
        dims, vars_a = self._content()
        _, vars_b = self._content(values=np.array([0.0, 1.0, 99.0]))
        h1 = compute_state_hash(dims=dims, variables=vars_a, operations=())
        h2 = compute_state_hash(dims=dims, variables=vars_b, operations=())
        assert h1 != h2

    def test_sensitive_to_operations_and_comments(self) -> None:
        dims, variables = self._content()
        h0 = compute_state_hash(dims=dims, variables=variables, operations=())
        h1 = compute_state_hash(
            dims=dims, variables=variables, operations=(("squeeze()", None),)
        )
        h2 = compute_state_hash(
            dims=dims, variables=variables, operations=(("squeeze()", "why"),)
        )
        assert len({h0, h1, h2}) == 3

    def test_variable_insertion_order_is_canonical(self) -> None:
        dims, _ = self._content()
        a = Variable(name="A", values=np.arange(3.0))
        b = Variable(name="B", values=np.arange(3.0) + 1)
        h_ab = compute_state_hash(dims=dims, variables={"A": a, "B": b}, operations=())
        h_ba = compute_state_hash(dims=dims, variables={"B": b, "A": a}, operations=())
        assert h_ab == h_ba

    def test_sensitive_to_correlation_and_tags(self) -> None:
        from itaca.core.correlation import CorrelationMatrix
        from itaca.core.historyframe import HistoryFrame
        from itaca.core.uncframe import UncFrame

        dims, variables = self._content()
        base = compute_state_hash(dims=dims, variables=variables, operations=())
        with_corr = compute_state_hash(
            dims=dims,
            variables=variables,
            operations=(),
            correlation=CorrelationMatrix(pairs={("CT", "CP"): 0.5}),
        )
        with_tags = compute_state_hash(
            dims=dims,
            variables=variables,
            operations=(),
            tags=HistoryFrame(tags={"CT": np.array([0, 1, 0])}),
        )
        with_unc = compute_state_hash(
            dims=dims,
            variables=variables,
            operations=(),
            uncertainty=UncFrame(random={"CT": np.full(3, 0.1)}),
        )
        assert len({base, with_corr, with_tags, with_unc}) == 4

    def test_dimension_order_is_semantic(self) -> None:
        # Dimension order dictates array shape (SRS 4.1.1), so it hashes.
        alpha = Dimension(name="alpha", coords=np.array([0.0, 2.0]))
        mach = Dimension(name="mach", coords=np.array([0.1, 0.2]))
        h1 = compute_state_hash(
            dims={"alpha": alpha, "mach": mach}, variables={}, operations=()
        )
        h2 = compute_state_hash(
            dims={"mach": mach, "alpha": alpha}, variables={}, operations=()
        )
        assert h1 != h2
