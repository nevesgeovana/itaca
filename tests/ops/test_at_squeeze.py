"""Tests for db.at (REQ-21) and db.squeeze (REQ-22)."""

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    SelectionError,
)
from itaca.core.varframe import VarFrame


@pytest.fixture
def db() -> VarFrame:
    arr = np.array(
        [
            [0.1, 0.0, 0.10],
            [0.1, 2.0, 0.12],
            [0.2, 0.0, 0.20],
            [0.2, 2.0, 0.22],
        ]
    )
    return itc.load(arr, names=["mach", "alpha", "CT"]).pivot(dims=["mach", "alpha"])


class TestAt:
    def test_removes_dimension(self, db: VarFrame) -> None:
        result = db.at(mach=0.2)
        assert list(result.dims) == ["alpha"]
        assert np.allclose(result.vars["CT"].values, [0.20, 0.22])

    def test_single_history_entry(self, db: VarFrame) -> None:
        result = db.at(mach=0.2)
        assert len(result.history) == len(db.history) + 1
        assert result.history.last is not None
        assert result.history.last.operation.startswith("at(")

    def test_multiple_dims(self, db: VarFrame) -> None:
        result = db.at(mach=0.1, alpha=2.0)
        assert list(result.dims) == ["datapoint"]
        assert result.vars["CT"].values[0] == pytest.approx(0.12)

    def test_missing_value_rejected(self, db: VarFrame) -> None:
        with pytest.raises(SelectionError):
            db.at(mach=0.5)

    def test_unknown_dim_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            db.at(beta=1.0)


class TestSqueeze:
    def test_removes_unit_dims(self, db: VarFrame) -> None:
        sliced = db.select({"mach": 0.1})
        assert sliced.shape == (1, 2)
        result = sliced.squeeze()
        assert list(result.dims) == ["alpha"]
        assert np.allclose(result.vars["CT"].values, [0.10, 0.12])

    def test_along_specific_dim(self, db: VarFrame) -> None:
        sliced = db.select({"mach": 0.1})
        result = sliced.squeeze(along="mach")
        assert list(result.dims) == ["alpha"]

    def test_along_non_unit_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.squeeze(along="alpha")

    def test_along_unknown_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            db.squeeze(along="beta")

    def test_all_unit_dims_yield_datapoint(self, db: VarFrame) -> None:
        # REQ-22: fully squeezed VarFrame keeps a single datapoint entry.
        point = db.select({"mach": 0.1, "alpha": 2.0}).squeeze()
        assert list(point.dims) == ["datapoint"]
        assert point.dims["datapoint"].cardinality == 1
        assert point.vars["CT"].values[0] == pytest.approx(0.12)

    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.select({"mach": 0.1}).squeeze()
        assert result.history.last is not None
        assert result.history.last.operation.startswith("squeeze(")
