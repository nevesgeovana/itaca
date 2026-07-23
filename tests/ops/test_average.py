"""Tests for db.average (REQ-27): collapse dimensions by mean.

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "rep", "CT"]).pivot(dims=["alpha", "rep"])
    mean = db.average(along="rep")

REQ-98/REQ-99: the random component gains 1/sqrt(N) (independence
between points), the systematic component is fully correlated (no
gain). HistoryFrame tags follow the worst-case rule.
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DimensionNotFoundError
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _grid() -> VarFrame:
    rows = [[a, r, 10.0 * a + r] for a in (0.0, 1.0) for r in (1.0, 2.0, 3.0, 4.0)]
    return itc.load(np.array(rows), names=["alpha", "rep", "CT"]).pivot(
        dims=["alpha", "rep"]
    )


@pytest.fixture
def db() -> VarFrame:
    return _grid()


class TestAverageValues:
    def test_collapses_one_dimension(self, db: VarFrame) -> None:
        result = db.average(along="rep")
        assert list(result.dims) == ["alpha"]
        assert np.allclose(result.vars["CT"].values, [2.5, 12.5])

    def test_collapses_multiple_dimensions(self, db: VarFrame) -> None:
        result = db.average(along=["alpha", "rep"])
        assert list(result.dims) == ["datapoint"]
        assert result.vars["CT"].values[0] == pytest.approx(7.5)

    def test_nan_values_skipped(self) -> None:
        rows = np.array([[0.0, 1.0, 2.0], [0.0, 2.0, np.nan], [0.0, 3.0, 4.0]])
        db = itc.load(rows, names=["alpha", "rep", "CT"]).pivot(dims=["alpha", "rep"])
        result = db.average(along="rep")
        assert result.vars["CT"].values[0] == pytest.approx(3.0)

    def test_all_nan_slice_stays_nan(self) -> None:
        rows = np.array([[0.0, 1.0, np.nan], [0.0, 2.0, np.nan]])
        db = itc.load(rows, names=["alpha", "rep", "CT"]).pivot(dims=["alpha", "rep"])
        result = db.average(along="rep")
        assert np.isnan(result.vars["CT"].values[0])

    def test_unknown_dimension_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            db.average(along="beta")


class TestAverageBookkeeping:
    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.average(along="rep", comment="repeat mean")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("average(")
        assert result.history.last.comment == "repeat mean"

    def test_original_untouched(self, db: VarFrame) -> None:
        db.average(along="rep")
        assert db.shape == (2, 4)

    def test_tags_follow_worst_case(self) -> None:
        rows = np.array([[0.0, 1.0, 2.0], [0.0, 2.0, np.nan], [0.0, 3.0, 4.0]])
        filled = (
            itc.load(rows, names=["alpha", "rep", "CT"])
            .pivot(dims=["alpha", "rep"])
            .fill(along="rep", method="linear")
        )
        result = filled.average(along="rep")
        assert result.tags is not None
        assert result.tags.tags["CT"][0] == 1


class TestAverageUncertainty:
    def _with_unc(self, db: VarFrame) -> VarFrame:
        shape = db.shape
        unc = UncFrame(
            systematic={"CT": np.full(shape, 0.2)},
            random={"CT": np.full(shape, 0.4)},
        )
        return dataclasses.replace(db, uncertainty=unc)

    def test_random_gains_one_over_sqrt_n(self, db: VarFrame) -> None:
        # REQ-76 edge case: repeat averaging reduces the random
        # component by 1/sqrt(N) and leaves the systematic unchanged.
        result = self._with_unc(db).average(along="rep")
        assert result.uncertainty is not None
        assert result.uncertainty.random["CT"][0] == pytest.approx(0.4 / 2.0)

    def test_systematic_unchanged(self, db: VarFrame) -> None:
        result = self._with_unc(db).average(along="rep")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["CT"][0] == pytest.approx(0.2)

    def test_nan_aware_weights(self) -> None:
        # A NaN cell drops out of the weights: N=2 for the populated
        # cells, so random gains 1/sqrt(2) and systematic stays.
        rows = np.array([[0.0, 1.0, 2.0], [0.0, 2.0, np.nan], [0.0, 3.0, 4.0]])
        db = itc.load(rows, names=["alpha", "rep", "CT"]).pivot(dims=["alpha", "rep"])
        unc = UncFrame(
            systematic={"CT": np.full((1, 3), 0.2)},
            random={"CT": np.full((1, 3), 0.4)},
        )
        result = dataclasses.replace(db, uncertainty=unc).average(along="rep")
        assert result.uncertainty is not None
        assert result.uncertainty.random["CT"][0] == pytest.approx(0.4 / np.sqrt(2.0))
        assert result.uncertainty.systematic["CT"][0] == pytest.approx(0.2)
