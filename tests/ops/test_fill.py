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
        # An author call at the M1 Phase B1 checkpoint: fill's positional
        # method is deprecated,
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


class TestPolyfitLinearity:
    """The measurement REQ-98 argues from, made reproducible.

    REQ-98 states that ``fill(method="polyfit")`` is provisional because
    its path emits no weights, and explicitly NOT because the moving
    polynomial fit has data-dependent weights. That second claim was
    measured false, and the requirement cites this module for the
    measurement. Asserting it here is what stops the requirement arguing
    from a number nothing reproduces (``ITC-20260729-1450``, OQ-42).

    Linearity matters to OQ-42 rather than being trivia: if the fit is
    linear in the variable values then an exact weight rule EXISTS to be
    adopted, and the open question is whether the interpolation matrix is
    the right one over a support chosen from the non-NaN cells. A
    nonlinear fit would settle OQ-42 the other way outright.
    """

    @staticmethod
    def _filled(values: list[float], **kwargs: object) -> np.ndarray:
        alpha = np.arange(float(len(values)))
        arr = np.column_stack([alpha, np.asarray(values, dtype=float)])
        db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        out = db.fill(along="alpha", method="polyfit", deg=2, **kwargs)  # type: ignore[arg-type]
        return np.asarray(out.vars["CT"].values, dtype=float)

    @pytest.mark.parametrize(
        ("label", "kwargs"),
        [("moving window", {"window": 5}), ("global fit", {"global_fit": True})],
    )
    def test_superposition_holds_to_round_off(
        self, label: str, kwargs: dict[str, object]
    ) -> None:
        """fill(a) + fill(b) == fill(a + b) over one NaN pattern.

        Both paths are checked. The moving-window path is the one REQ-98
        names; ``global_fit`` is included because OQ-42's second option
        turns on it specifically, and its support is the whole valid set
        rather than the whole grid, which is the property that
        distinguishes it from interpolation.
        """
        gaps = [2, 5]
        rng = np.random.default_rng(20260729)
        worst = 0.0
        for _ in range(50):
            a = rng.normal(size=11) * 10.0
            b = rng.normal(size=11) * 10.0
            for index in gaps:
                a[index] = np.nan
                b[index] = np.nan
            left = self._filled(list(a), **kwargs) + self._filled(list(b), **kwargs)
            right = self._filled(list(a + b), **kwargs)
            scale = max(1.0, float(np.max(np.abs(right[gaps]))))
            worst = max(worst, float(np.max(np.abs(left[gaps] - right[gaps]))) / scale)
        assert worst < 1e-12, (
            f"the {label} polyfit fill departs from superposition by {worst:.3e}, "
            "so it is not linear in the variable values. REQ-98 argues from "
            "that linearity and OQ-42 depends on it; if this fails, the "
            "requirement's stated ground has to change with it."
        )
        # The bound is loose on purpose: what REQ-98 needs is the ORDER,
        # and pinning the digits of one platform's round-off would make
        # this a fragile assertion about numpy rather than about fill. A
        # bit-exact result is also linear, so there is no lower bound to
        # assert here.


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
        # DD-18: no sound weight rule is frozen for this path, so it
        # raises rather than silently carrying or dropping. REQ-98 is
        # STABLE and its table places fill with interpolate as exact,
        # which this refusal contradicts; the disagreement is registered
        # and is the author's to settle, not this test's to assert away.
        with pytest.raises(UncertaintyError):
            self._with_unc(db).fill(along="alpha", method="polyfit", deg=1, window=3)
