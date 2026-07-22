"""Tests for db.select with operators and Frame targeting (REQ-20).

Usage example (the contract under test)::

    subset = db.select({"alpha>=": 2.0})
    original_only = db.select({"CT": 0}, Frame="HistoryFrame")
    precise_only = db.select({"CT<": 0.005}, Frame="UncFrame")
"""

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DataError, SelectionError, UncertaintyError
from itaca.core.historyframe import HistoryFrame
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


@pytest.fixture
def db() -> VarFrame:
    arr = np.array(
        [
            [0.1, 0.0, 0.10],
            [0.1, 2.0, 0.12],
            [0.1, 4.0, 0.14],
            [0.2, 0.0, 0.20],
            [0.2, 2.0, 0.22],
            [0.2, 4.0, 0.24],
        ]
    )
    return itc.load(arr, names=["mach", "alpha", "CT"]).pivot(dims=["mach", "alpha"])


class TestDimensionFilters:
    def test_equality_scalar(self, db: VarFrame) -> None:
        result = db.select({"mach": 0.1})
        assert result.shape == (1, 3)
        assert np.array_equal(result.dims["mach"].coords, [0.1])
        assert db.shape == (2, 3)  # original untouched (REQ-18)

    def test_equality_list(self, db: VarFrame) -> None:
        result = db.select({"alpha": [0.0, 4.0]})
        assert result.shape == (2, 2)
        assert np.array_equal(result.dims["alpha"].coords, [0.0, 4.0])

    def test_comparison_operator(self, db: VarFrame) -> None:
        result = db.select({"alpha>=": 2.0})
        assert result.shape == (2, 2)
        assert np.array_equal(result.dims["alpha"].coords, [2.0, 4.0])

    def test_not_equal_operator(self, db: VarFrame) -> None:
        result = db.select({"alpha!=": 2.0})
        assert np.array_equal(result.dims["alpha"].coords, [0.0, 4.0])

    def test_missing_coordinate_rejected(self, db: VarFrame) -> None:
        with pytest.raises(SelectionError):
            db.select({"mach": 0.3})

    def test_empty_comparison_rejected(self, db: VarFrame) -> None:
        with pytest.raises(SelectionError):
            db.select({"alpha>": 99.0})

    def test_unknown_key_rejected(self, db: VarFrame) -> None:
        with pytest.raises(SelectionError):
            db.select({"beta": 1.0})

    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.select({"mach": 0.1}, comment="first sweep")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("select(")
        assert "masked=" in result.history.last.operation
        assert result.history.last.comment == "first sweep"


class TestVariableFilters:
    def test_masks_cells_and_keeps_dims(self, db: VarFrame) -> None:
        result = db.select({"CT>": 0.11})
        # mach=0.1/alpha=0.0 (CT=0.10) fails the filter; the mach=0.1
        # slice survives through its other alphas, so dims are kept.
        assert result.shape == (2, 3)
        assert np.isnan(result.vars["CT"].values[0, 0])
        assert result.vars["CT"].values[0, 1] == pytest.approx(0.12)

    def test_masked_count_in_history(self, db: VarFrame) -> None:
        result = db.select({"CT>": 0.11})
        assert result.history.last is not None
        assert "masked=1" in result.history.last.operation

    def test_fully_masked_slices_dropped(self, db: VarFrame) -> None:
        result = db.select({"CT>=": 0.20})
        # The whole mach=0.1 slice fails: its coordinate is dropped.
        assert np.array_equal(result.dims["mach"].coords, [0.2])
        assert result.shape == (1, 3)

    def test_all_cells_masked_rejected(self, db: VarFrame) -> None:
        with pytest.raises(SelectionError):
            db.select({"CT>": 99.0})


class TestFrameTargeting:
    def test_historyframe_filter(self, db: VarFrame) -> None:
        tags = HistoryFrame(
            tags={"CT": np.array([[0, 1, 0], [0, 0, -1]], dtype=np.int8)}
        )
        import dataclasses

        tagged = dataclasses.replace(db, tags=tags)
        result = tagged.select({"CT": 0}, Frame="HistoryFrame")
        assert np.isnan(result.vars["CT"].values[0, 1])
        assert result.vars["CT"].values[0, 0] == pytest.approx(0.10)

    def test_historyframe_filter_without_tags_keeps_all(self, db: VarFrame) -> None:
        # No HistoryFrame means every value is original (lazy semantics).
        result = db.select({"CT": 0}, Frame="HistoryFrame")
        assert not np.isnan(result.vars["CT"].values).any()

    def test_uncframe_filter(self, db: VarFrame) -> None:
        import dataclasses

        unc = UncFrame(systematic={"CT": np.full((2, 3), 0.004)})
        with_unc = dataclasses.replace(db, uncertainty=unc)
        result = with_unc.select({"CT<": 0.005}, Frame="UncFrame")
        assert not np.isnan(result.vars["CT"].values).any()
        with pytest.raises(SelectionError):
            with_unc.select({"CT<": 0.001}, Frame="UncFrame")

    def test_uncframe_filter_without_uncertainty_rejected(self, db: VarFrame) -> None:
        with pytest.raises(UncertaintyError):
            db.select({"CT<": 0.005}, Frame="UncFrame")

    def test_invalid_frame_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.select({"CT": 0.1}, Frame="Nonsense")


class TestModes:
    def test_draft_records_only_on_request(self, db: VarFrame) -> None:
        draft = db.demote()
        base_len = len(draft.history)
        silent = draft.select({"mach": 0.1})
        assert len(silent.history) == base_len
        recorded = draft.select({"mach": 0.1}, history=True)
        assert len(recorded.history) == base_len + 1
