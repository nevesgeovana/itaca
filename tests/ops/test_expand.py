"""Tests for db.expand (REQ-23): add a new dimension by broadcast.

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
    swept = db.expand("rpm", [1000.0, 2000.0])
    assert swept.shape == (3, 2)

UncFrame components and origin tags broadcast unchanged (REQ-98).
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DataError
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


@pytest.fixture
def db() -> VarFrame:
    arr = np.column_stack([np.arange(3.0), np.array([1.0, 2.0, 3.0])])
    return itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])


class TestExpandShapes:
    def test_new_axis_defaults_to_last(self, db: VarFrame) -> None:
        result = db.expand("rpm", [1000.0, 2000.0])
        assert list(result.dims) == ["alpha", "rpm"]
        assert result.shape == (3, 2)
        assert np.allclose(result.vars["CT"].values[:, 0], [1.0, 2.0, 3.0])
        assert np.allclose(result.vars["CT"].values[:, 1], [1.0, 2.0, 3.0])

    def test_axis_position(self, db: VarFrame) -> None:
        result = db.expand("rpm", [1000.0, 2000.0], axis=0)
        assert list(result.dims) == ["rpm", "alpha"]
        assert result.shape == (2, 3)
        assert np.allclose(result.vars["CT"].values[0], [1.0, 2.0, 3.0])

    def test_new_coords_stored(self, db: VarFrame) -> None:
        result = db.expand("rpm", [1000.0, 2000.0])
        assert np.allclose(result.dims["rpm"].coords, [1000.0, 2000.0])

    def test_string_valued_dimension(self, db: VarFrame) -> None:
        result = db.expand("blade", ["A", "B"])
        assert not result.dims["blade"].is_numeric
        assert result.shape == (3, 2)


class TestExpandValidation:
    def test_duplicate_dimension_rejected(self, db: VarFrame) -> None:
        # REQ-76 edge case: expand with duplicate existing dimension name.
        with pytest.raises(DataError):
            db.expand("alpha", [9.0])

    def test_variable_name_collision_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.expand("CT", [9.0])

    def test_non_1d_values_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.expand("rpm", [[1.0, 2.0]])

    def test_duplicate_values_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.expand("rpm", [1000.0, 1000.0])

    def test_axis_out_of_range_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.expand("rpm", [1000.0], axis=5)


class TestExpandBookkeeping:
    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.expand("rpm", [1000.0], comment="sweep stub")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("expand(")
        assert result.history.last.comment == "sweep stub"

    def test_original_untouched(self, db: VarFrame) -> None:
        db.expand("rpm", [1000.0, 2000.0])
        assert db.shape == (3,)

    def test_uncertainty_broadcast_unchanged(self, db: VarFrame) -> None:
        # REQ-98: components are broadcast unchanged.
        unc = UncFrame(
            systematic={"CT": np.array([0.1, 0.2, 0.3])},
            random={"CT": np.array([0.4, 0.5, 0.6])},
        )
        result = dataclasses.replace(db, uncertainty=unc).expand("rpm", [1.0, 2.0])
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["CT"][:, 1], [0.1, 0.2, 0.3])
        assert np.allclose(result.uncertainty.random["CT"][:, 0], [0.4, 0.5, 0.6])

    def test_tags_broadcast_unchanged(self) -> None:
        arr = np.column_stack([np.arange(3.0), np.array([1.0, np.nan, 3.0])])
        filled = (
            itc.load(arr, names=["alpha", "CT"])
            .pivot(dims=["alpha"])
            .fill(along="alpha", method="linear")
        )
        result = filled.expand("rpm", [1.0, 2.0])
        assert result.tags is not None
        assert list(result.tags.tags["CT"][:, 0]) == [0, 1, 0]
        assert list(result.tags.tags["CT"][:, 1]) == [0, 1, 0]

    def test_result_arrays_read_only(self, db: VarFrame) -> None:
        # REQ-102 extends to broadcast results.
        result = db.expand("rpm", [1000.0, 2000.0])
        with pytest.raises((ValueError, RuntimeError)):
            result.vars["CT"].values[0, 0] = 99.0
