"""Tests for db.smooth (REQ-29): smoothing along a dimension.

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
    smoothed = db.smooth(along="alpha", method="savgol", window=5, polyorder=2)

Method-dependent kwargs adopt the REQ-105 sentinel: passing one where
it is not meaningful raises instead of being silently ignored.
Uncertainty present raises until OQ-18 freezes the kernel weight rule
(REQ-98 provisional row).
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    UncertaintyError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _line(ct: list[float]) -> VarFrame:
    alpha = np.arange(float(len(ct)))
    arr = np.column_stack([alpha, np.array(ct)])
    return itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])


@pytest.fixture
def noisy() -> VarFrame:
    # A parabola with one bumped sample.
    values = [float(a**2) for a in range(7)]
    values[3] += 1.0
    return _line(values)


class TestSmoothMethods:
    def test_savgol_preserves_polynomial(self) -> None:
        # A moving quadratic fit reproduces quadratic data exactly.
        db = _line([float(a**2) for a in range(7)])
        result = db.smooth(along="alpha", method="savgol", window=5, polyorder=2)
        assert np.allclose(result.vars["CT"].values, [float(a**2) for a in range(7)])

    def test_savgol_reduces_noise(self, noisy: VarFrame) -> None:
        result = noisy.smooth(along="alpha", method="savgol", window=5, polyorder=2)
        assert abs(result.vars["CT"].values[3] - 9.0) < 1.0

    def test_moving_avg(self) -> None:
        db = _line([0.0, 3.0, 0.0, 3.0, 0.0])
        result = db.smooth(along="alpha", method="moving_avg", window=3)
        assert result.vars["CT"].values[2] == pytest.approx(2.0)

    def test_spline_zero_smoothing_is_identity(self, noisy: VarFrame) -> None:
        result = noisy.smooth(along="alpha", method="spline", smoothing=0.0)
        assert np.allclose(result.vars["CT"].values, noisy.vars["CT"].values)

    def test_spline_large_smoothing_flattens(self) -> None:
        db = _line([0.0, 3.0, 0.0, 3.0, 0.0, 3.0])
        result = db.smooth(along="alpha", method="spline", smoothing=1e6)
        # Near the straight-line least-squares fit: variation shrinks.
        assert np.ptp(result.vars["CT"].values) < 1.5

    def test_savgol_window_without_enough_points_yields_nan(self) -> None:
        # A window left with fewer than deg+1 finite points yields NaN
        # at that sample (moving-fit contract).
        values = [0.0, 1.0, np.nan, np.nan, 4.0, 5.0, 6.0]
        db = _line(values)
        result = db.smooth(along="alpha", method="savgol", window=3, polyorder=2)
        assert np.isnan(result.vars["CT"].values[3])

    def test_spline_with_nan_smooths_populated_subset(self) -> None:
        values = [0.0, 3.0, np.nan, 3.0, 0.0, 3.0]
        db = _line(values)
        result = db.smooth(along="alpha", method="spline", smoothing=10.0)
        assert np.isnan(result.vars["CT"].values[2])
        assert np.isfinite(result.vars["CT"].values[0])


class TestSmoothSentinel:
    def test_savgol_requires_window_and_polyorder(self, noisy: VarFrame) -> None:
        with pytest.raises(DataError):
            noisy.smooth(along="alpha", method="savgol", window=5)

    def test_spline_requires_smoothing(self, noisy: VarFrame) -> None:
        with pytest.raises(DataError):
            noisy.smooth(along="alpha", method="spline")

    def test_irrelevant_kwarg_rejected(self, noisy: VarFrame) -> None:
        # REQ-105: an explicitly passed argument that is not meaningful
        # for the chosen method raises instead of being ignored.
        with pytest.raises(DataError):
            noisy.smooth(along="alpha", method="spline", smoothing=1.0, window=5)

    def test_explicit_sentinel_where_not_default_rejected(
        self, noisy: VarFrame
    ) -> None:
        with pytest.raises(DataError):
            noisy.smooth(along="alpha", method=itc.no_default)  # type: ignore[arg-type]


class TestSmoothValidation:
    def test_unknown_method_rejected(self, noisy: VarFrame) -> None:
        with pytest.raises(DataError):
            noisy.smooth(along="alpha", method="magic")

    def test_unknown_dimension_rejected(self, noisy: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            noisy.smooth(along="beta", method="moving_avg", window=3)

    def test_window_not_larger_than_polyorder_rejected(self, noisy: VarFrame) -> None:
        with pytest.raises(DataError):
            noisy.smooth(along="alpha", method="savgol", window=3, polyorder=3)


class TestSmoothBookkeeping:
    def test_smoothed_values_tagged(self, noisy: VarFrame) -> None:
        result = noisy.smooth(along="alpha", method="moving_avg", window=3)
        assert result.tags is not None
        assert np.all(result.tags.tags["CT"] == 1)

    def test_recorded_in_history(self, noisy: VarFrame) -> None:
        result = noisy.smooth(
            along="alpha", method="moving_avg", window=3, comment="derib"
        )
        assert result.history.last is not None
        assert result.history.last.operation.startswith("smooth(")
        assert result.history.last.comment == "derib"

    def test_original_untouched(self, noisy: VarFrame) -> None:
        before = noisy.vars["CT"].values.copy()
        noisy.smooth(along="alpha", method="moving_avg", window=3)
        assert np.allclose(noisy.vars["CT"].values, before)


class TestSmoothUncertainty:
    def test_uncertainty_raises_until_oq18(self, noisy: VarFrame) -> None:
        # REQ-98: the smooth/diff row is provisional (OQ-18); raising
        # is the sanctioned behavior, never guessing.
        unc = UncFrame(
            systematic={"CT": np.full(7, 0.1)}, random={"CT": np.full(7, 0.1)}
        )
        with pytest.raises(UncertaintyError):
            dataclasses.replace(noisy, uncertainty=unc).smooth(
                along="alpha", method="moving_avg", window=3
            )
