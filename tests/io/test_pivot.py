"""Tests for db.pivot (REQ-14) and its edge cases (REQ-76).

Usage example (the contract under test)::

    db = itc.load(arr, names=["mach", "alpha", "CT"])
    structured = db.pivot(dims=["mach", "alpha"])
"""

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    DimensionNotFoundError,
    PivotDuplicateError,
    PivotError,
)


@pytest.fixture
def datapoint_db() -> "itc.core.varframe.VarFrame":  # type: ignore[name-defined]
    arr = np.array(
        [
            [0.1, 0.0, 0.10],
            [0.1, 2.0, 0.12],
            [0.2, 0.0, 0.20],
            [0.2, 2.0, 0.22],
        ]
    )
    return itc.load(arr, names=["mach", "alpha", "CT"])


class TestPivot:
    def test_structures_the_grid(self, datapoint_db) -> None:  # type: ignore[no-untyped-def]
        db = datapoint_db.pivot(dims=["mach", "alpha"])
        assert list(db.dims) == ["mach", "alpha"]
        assert db.shape == (2, 2)
        assert list(db.vars) == ["CT"]
        assert db.vars["CT"].values[0, 1] == pytest.approx(0.12)

    def test_missing_combination_nan(self) -> None:
        arr = np.array([[0.1, 0.0, 1.0], [0.2, 2.0, 2.0]])
        db = itc.load(arr, names=["mach", "alpha", "CT"])
        structured = db.pivot(dims=["mach", "alpha"])
        assert np.isnan(structured.vars["CT"].values[0, 1])

    def test_recorded_in_history(self, datapoint_db) -> None:  # type: ignore[no-untyped-def]
        db = datapoint_db.pivot(dims=["mach", "alpha"], comment="grid")
        assert len(db.history) == 2
        assert db.history.last is not None
        assert db.history.last.operation.startswith("pivot(")
        assert db.history.last.comment == "grid"
        assert db.history.last.state_hash == db.state_hash

    def test_pivot_on_structured_rejected(self, datapoint_db) -> None:  # type: ignore[no-untyped-def]
        structured = datapoint_db.pivot(dims=["mach", "alpha"])
        with pytest.raises(PivotError):
            structured.pivot()

    def test_duplicate_coordinates_rejected(self) -> None:
        # REQ-14: untagged repeats fail loud with a suggestion.
        arr = np.array([[0.1, 1.0], [0.1, 2.0]])
        db = itc.load(arr, names=["mach", "CT"])
        with pytest.raises(PivotDuplicateError, match="repeat"):
            db.pivot(dims=["mach"])

    def test_unknown_dim_rejected(self, datapoint_db) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(DimensionNotFoundError):
            datapoint_db.pivot(dims=["beta"])

    def test_auto_detect(self) -> None:
        # REQ-14: auto_detect adds low-cardinality candidates.
        rng = np.linspace(0.0, 1.0, 8)
        arr = np.column_stack(
            [np.repeat([0.1, 0.2], 4), np.tile([0.0, 2.0, 4.0, 6.0], 2), rng]
        )
        db = itc.load(arr, names=["mach", "alpha", "CT"])
        structured = db.pivot(dims=["mach"], auto_detect=True)
        assert set(structured.dims) == {"mach", "alpha"}
        assert structured.shape == (2, 4)

    def test_draft_mode_records_only_on_request(self) -> None:
        arr = np.array([[0.1, 1.0], [0.2, 2.0]])
        db = itc.load(arr, names=["mach", "CT"], mode="draft")
        silent = db.pivot(dims=["mach"])
        assert len(silent.history) == 1  # only the load entry
        recorded = db.pivot(dims=["mach"], history=True)
        assert len(recorded.history) == 2


def test_itaca_025d_pivot_drops_pairs_naming_pivoted_columns() -> None:
    """REV-001 ITACA-025d: a pivoted column leaves vars and its pairs stayed.

    The assertion on the recorded hash is load-bearing: pivot computes
    the state hash and constructs the frame at two separate call sites,
    and changing only one of them records a hash for a frame that is
    not the one returned.
    """
    arr = np.column_stack(
        [[0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0], [2.0, 3.0, 4.0, 5.0]]
    )
    db = itc.load(arr, names=["alpha", "CT", "CP"])
    db = db.set_correlation({("alpha", "CT"): 0.3, ("CT", "CP"): 0.6})

    out = db.pivot(dims=["alpha"])

    assert out.correlation is not None
    assert out.correlation.get("CT", "CP") == 0.6
    assert ("CT", "alpha") not in out.correlation.pairs
    assert ("alpha", "CT") not in out.correlation.pairs
    assert "correlation=dropped" in out.history[-1].operation
    assert out.state_hash == out.history[-1].state_hash
