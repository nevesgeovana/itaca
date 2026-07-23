"""Tests for db.fill (REQ-26): gap filling with origin tags and
uncertainty propagation through the interpolation weights (REQ-98).
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.dimension import Dimension
from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    NonNumericDimensionError,
    UncertaintyError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable


@pytest.fixture
def db() -> VarFrame:
    arr = np.column_stack([np.arange(5.0), np.array([1.0, np.nan, 3.0, np.nan, 5.0])])
    return itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])


class TestFillMethods:
    def test_linear_interior(self, db: VarFrame) -> None:
        result = db.fill(along="alpha", method="linear")
        assert np.allclose(result.vars["CT"].values, [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_linear_leaves_edges(self) -> None:
        arr = np.column_stack([np.arange(3.0), np.array([np.nan, 2.0, 3.0])])
        db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        result = db.fill(along="alpha", method="linear")
        assert np.isnan(result.vars["CT"].values[0])
        assert result.vars["CT"].values[1] == pytest.approx(2.0)

    def test_nearest_fills_edges(self) -> None:
        arr = np.column_stack([np.arange(3.0), np.array([np.nan, 2.0, 3.0])])
        db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        result = db.fill(along="alpha", method="nearest")
        assert result.vars["CT"].values[0] == pytest.approx(2.0)

    def test_polyfit_window(self, db: VarFrame) -> None:
        result = db.fill(along="alpha", method="polyfit", deg=1, window=3)
        assert np.allclose(result.vars["CT"].values, [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_polyfit_global(self, db: VarFrame) -> None:
        result = db.fill(along="alpha", method="polyfit", deg=1, global_fit=True)
        assert np.allclose(result.vars["CT"].values, [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_polyfit_window_le_deg_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.fill(along="alpha", method="polyfit", deg=3, window=3)

    def test_unknown_method_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.fill(along="alpha", method="magic")

    def test_unknown_dim_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            db.fill(along="beta")

    def test_non_numeric_dim_rejected(self, prov) -> None:  # type: ignore[no-untyped-def]
        blade = Dimension(name="blade", coords=np.array(["A", "B"]), is_numeric=False)
        ct = Variable(name="CT", values=np.array([1.0, np.nan]))
        db = VarFrame(dims={"blade": blade}, vars={"CT": ct}, provenance=prov)
        with pytest.raises(NonNumericDimensionError):
            db.fill(along="blade")


class TestFillDeprecation:
    def test_positional_method_warns(self, db: VarFrame) -> None:
        # Geovana's B1 call: fill's positional method is deprecated,
        # aligning with the keyword-only M1 kernel ops.
        with pytest.warns(FutureWarning, match="keyword-only"):
            result = db.fill("alpha", "linear")
        assert np.allclose(result.vars["CT"].values, [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_keyword_method_does_not_warn(self, db: VarFrame) -> None:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            db.fill("alpha", method="linear")

    def test_extra_positional_rejected(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.fill("alpha", "linear", "extra")  # type: ignore[call-arg]


class TestFillBookkeeping:
    def test_filled_values_tagged(self, db: VarFrame) -> None:
        # REQ-26: filled values are tagged +1 in the HistoryFrame.
        result = db.fill(along="alpha", method="linear")
        assert result.tags is not None
        assert list(result.tags.tags["CT"]) == [0, 1, 0, 1, 0]

    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.fill(along="alpha", method="linear", comment="gaps")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("fill(")
        assert result.history.last.comment == "gaps"

    def test_original_untouched(self, db: VarFrame) -> None:
        db.fill(along="alpha", method="linear")
        assert np.isnan(db.vars["CT"].values[1])


class TestFillUncertainty:
    def _with_unc(self, db: VarFrame) -> VarFrame:
        unc = UncFrame(
            systematic={"CT": np.array([2.0, np.nan, 2.0, np.nan, 2.0])},
            random={"CT": np.array([2.0, np.nan, 2.0, np.nan, 2.0])},
        )
        return dataclasses.replace(db, uncertainty=unc)

    def test_linear_propagates_both_components(self, db: VarFrame) -> None:
        # REQ-98: systematic through the weight sum (fully correlated),
        # random through the RSS of weights.
        result = self._with_unc(db).fill(along="alpha", method="linear")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["CT"][1] == pytest.approx(2.0)
        assert result.uncertainty.random["CT"][1] == pytest.approx(np.sqrt(2.0))

    def test_nearest_copies_components(self, db: VarFrame) -> None:
        result = self._with_unc(db).fill(along="alpha", method="nearest")
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["CT"][1] == pytest.approx(2.0)
        assert result.uncertainty.random["CT"][1] == pytest.approx(2.0)

    def test_polyfit_with_uncertainty_rejected(self, db: VarFrame) -> None:
        # DD-18: no sound rule frozen yet (REQ-98 draft): raise, never
        # silently carry or drop.
        with pytest.raises(UncertaintyError):
            self._with_unc(db).fill(along="alpha", method="polyfit", deg=1, window=3)
