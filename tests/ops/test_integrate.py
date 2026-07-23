"""Tests for db.integrate (REQ-28): numerical integration.

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
    total = db.integrate("CT", over=["alpha"])

Trapezoidal quadrature over the coordinate grid; coords="polar"
applies the polar area element r dr dtheta (theta in radians). NaN
inside the domain makes the result NaN unless skipna=True, which
integrates populated cells only, records the populated fraction in
History, and tags the result +1 (fail-loud default, REQ-76).
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    VariableNotFoundError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _line(alpha: list[float], ct: list[float]) -> VarFrame:
    arr = np.column_stack([np.array(alpha), np.array(ct)])
    return itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])


@pytest.fixture
def ramp() -> VarFrame:
    # CT = 2 * alpha: the exact integral over [0, 3] is 9.
    return _line([0.0, 1.0, 2.0, 3.0], [0.0, 2.0, 4.0, 6.0])


class TestIntegrateCartesian:
    def test_trapezoid_exact_on_linear(self, ramp: VarFrame) -> None:
        result = ramp.integrate("CT", over=["alpha"])
        assert list(result.dims) == ["datapoint"]
        assert result.vars["CT"].values[0] == pytest.approx(9.0)

    def test_partial_reduction_keeps_other_dims(self) -> None:
        rows = [[a, m, 1.0] for a in (0.0, 1.0, 2.0) for m in (0.1, 0.2)]
        db = itc.load(np.array(rows), names=["alpha", "mach", "CT"]).pivot(
            dims=["alpha", "mach"]
        )
        result = db.integrate("CT", over=["alpha"])
        assert list(result.dims) == ["mach"]
        assert np.allclose(result.vars["CT"].values, [2.0, 2.0])

    def test_double_integral(self) -> None:
        rows = [[a, m, 1.0] for a in (0.0, 1.0, 2.0) for m in (0.0, 0.5, 1.0)]
        db = itc.load(np.array(rows), names=["alpha", "mach", "CT"]).pivot(
            dims=["alpha", "mach"]
        )
        result = db.integrate("CT", over=["alpha", "mach"])
        assert result.vars["CT"].values[0] == pytest.approx(2.0)

    def test_only_integrated_variable_kept(self) -> None:
        rows = [[a, 2.0 * a, 3.0 * a] for a in (0.0, 1.0)]
        db = itc.load(np.array(rows), names=["alpha", "CT", "CQ"]).pivot(dims=["alpha"])
        result = db.integrate("CT", over=["alpha"])
        assert set(result.vars) == {"CT"}


class TestIntegratePolar:
    def test_disk_area(self) -> None:
        # Integrand 1 over r in [0, 1], theta in [0, 2pi]: area pi.
        rows = [[r, t, 1.0] for r in (0.0, 0.5, 1.0) for t in (0.0, np.pi, 2.0 * np.pi)]
        db = itc.load(np.array(rows), names=["r", "theta", "CT"]).pivot(
            dims=["r", "theta"]
        )
        result = db.integrate("CT", over=["r", "theta"], coords="polar")
        assert result.vars["CT"].values[0] == pytest.approx(np.pi)

    def test_polar_needs_exactly_two_dims(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.integrate("CT", over=["alpha"], coords="polar")


class TestIntegrateValidation:
    def test_unknown_variable_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(VariableNotFoundError):
            ramp.integrate("CQ", over=["alpha"])

    def test_unknown_dimension_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            ramp.integrate("CT", over=["beta"])

    def test_unknown_coords_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.integrate("CT", over=["alpha"], coords="spherical")


class TestIntegrateMissingValues:
    def test_nan_poisons_by_default(self) -> None:
        # REQ-76 Integrate edge case: skipna=False yields NaN.
        db = _line([0.0, 1.0, 2.0], [1.0, np.nan, 1.0])
        result = db.integrate("CT", over=["alpha"])
        assert np.isnan(result.vars["CT"].values[0])

    def test_skipna_integrates_populated_cells(self) -> None:
        db = _line([0.0, 1.0, 2.0], [1.0, np.nan, 1.0])
        result = db.integrate("CT", over=["alpha"], skipna=True)
        # Populated cells are alpha 0 and 2: trapezoid over [0, 2].
        assert result.vars["CT"].values[0] == pytest.approx(2.0)

    def test_skipna_records_fraction_and_tags(self) -> None:
        db = _line([0.0, 1.0, 2.0], [1.0, np.nan, 1.0])
        result = db.integrate("CT", over=["alpha"], skipna=True)
        assert result.history.last is not None
        assert "skipna=True" in result.history.last.operation
        assert "populated=2/3" in result.history.last.operation
        assert result.tags is not None
        assert result.tags.tags["CT"][0] == 1


class TestIntegrateBookkeeping:
    def test_recorded_in_history(self, ramp: VarFrame) -> None:
        result = ramp.integrate("CT", over=["alpha"], comment="thrust")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("integrate(")
        assert result.history.last.comment == "thrust"

    def test_original_untouched(self, ramp: VarFrame) -> None:
        ramp.integrate("CT", over=["alpha"])
        assert ramp.shape == (4,)


class TestIntegrateUncertainty:
    def test_components_follow_reduction_rules(self, ramp: VarFrame) -> None:
        # REQ-98: systematic through the weight sum, random through the
        # RSS of weights. Trapezoid weights on [0, 1, 2, 3] are
        # [0.5, 1, 1, 0.5].
        unc = UncFrame(
            systematic={"CT": np.full(4, 0.1)},
            random={"CT": np.full(4, 0.1)},
        )
        result = dataclasses.replace(ramp, uncertainty=unc).integrate(
            "CT", over=["alpha"]
        )
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["CT"][0] == pytest.approx(0.3)
        assert result.uncertainty.random["CT"][0] == pytest.approx(
            0.1 * np.sqrt(0.25 + 1.0 + 1.0 + 0.25)
        )
