"""Tests for db.fitmodel and db.fitvalue (REQ-31, REQ-32).

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])
    model = db.fitmodel(along="alpha", deg=2)
    model.dims["alpha_coef"]        # labels alpha^0, alpha^1, alpha^2
    dense = model.fitvalue(coef_dims=["alpha_coef"], at={"alpha": grid})

fitvalue tags +1 within the original fit range and -1 beyond
(REQ-32, REQ-76 edge case). The REQ-98 table declares no fitmodel
row, so fitmodel raises when uncertainty is present (DD-18).
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.dimension import Dimension
from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    UncertaintyError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable


def _line(alpha: list[float], cl: list[float]) -> VarFrame:
    arr = np.column_stack([np.array(alpha), np.array(cl)])
    return itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])


@pytest.fixture
def parabola() -> VarFrame:
    alpha = [0.0, 1.0, 2.0, 3.0, 4.0]
    return _line(alpha, [a**2 for a in alpha])


class TestFitmodel:
    def test_coefficients_recovered(self, parabola: VarFrame) -> None:
        model = parabola.fitmodel(along="alpha", deg=2)
        assert list(model.dims) == ["alpha_coef"]
        assert not model.dims["alpha_coef"].is_numeric
        assert list(model.dims["alpha_coef"].coords) == [
            "alpha^0",
            "alpha^1",
            "alpha^2",
        ]
        assert np.allclose(model.vars["CL"].values, [0.0, 0.0, 1.0], atol=1e-10)

    def test_partial_fit_keeps_other_dims(self) -> None:
        rows = [[a, m, m * a] for a in (0.0, 1.0, 2.0) for m in (1.0, 2.0)]
        db = itc.load(np.array(rows), names=["alpha", "mach", "CL"]).pivot(
            dims=["alpha", "mach"]
        )
        model = db.fitmodel(along="alpha", deg=1)
        assert list(model.dims) == ["alpha_coef", "mach"]
        # Slope per mach: d(m*a)/da = m.
        assert np.allclose(model.vars["CL"].values[1], [1.0, 2.0], atol=1e-10)

    def test_fit_range_recorded(self, parabola: VarFrame) -> None:
        model = parabola.fitmodel(along="alpha", deg=2)
        assert model.dims["alpha_coef"].description is not None
        assert "alpha=[0.0, 4.0]" in model.dims["alpha_coef"].description

    def test_deg_not_below_points_rejected(self, parabola: VarFrame) -> None:
        with pytest.raises(DataError):
            parabola.fitmodel(along="alpha", deg=5)

    def test_unknown_dimension_rejected(self, parabola: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            parabola.fitmodel(along="beta", deg=1)

    def test_uncertainty_rejected(self, parabola: VarFrame) -> None:
        # The REQ-98 table has no fitmodel row: raise, never guess
        # (DD-18; queue question registered for the SRS gap).
        unc = UncFrame(
            systematic={"CL": np.full(5, 0.1)}, random={"CL": np.full(5, 0.1)}
        )
        with pytest.raises(UncertaintyError):
            dataclasses.replace(parabola, uncertainty=unc).fitmodel(
                along="alpha", deg=2
            )

    def test_recorded_in_history(self, parabola: VarFrame) -> None:
        model = parabola.fitmodel(along="alpha", deg=2, comment="polar fit")
        assert model.history.last is not None
        assert model.history.last.operation.startswith("fitmodel(")
        assert model.history.last.comment == "polar fit"

    def test_non_numeric_dimension_rejected(self, prov) -> None:  # type: ignore[no-untyped-def]
        blade = Dimension(name="blade", coords=np.array(["A", "B"]), is_numeric=False)
        cl = Variable(name="CL", values=np.array([1.0, 2.0]))
        db = VarFrame(dims={"blade": blade}, vars={"CL": cl}, provenance=prov)
        with pytest.raises(Exception, match="string-valued"):
            db.fitmodel(along="blade", deg=1)

    def test_name_collision_rejected(self) -> None:
        rows = [[a, a, a**2] for a in (0.0, 1.0, 2.0)]
        db = itc.load(np.array(rows), names=["alpha", "alpha_coef", "CL"]).pivot(
            dims=["alpha", "alpha_coef"]
        )
        with pytest.raises(DataError):
            db.fitmodel(along="alpha", deg=1)

    def test_coefficient_tags_spread_worst_case(self) -> None:
        alpha = [0.0, 1.0, 2.0, 3.0, 4.0]
        cl = [a**2 for a in alpha]
        cl[2] = np.nan
        filled = (
            _line(alpha, cl)
            .fill(along="alpha", method="linear")
            .fitmodel(along="alpha", deg=2)
        )
        assert filled.tags is not None
        # The filled line taints every coefficient it produces.
        assert np.all(filled.tags.tags["CL"] == 1)


class TestFitvalue:
    def test_round_trip_recovers_values(self, parabola: VarFrame) -> None:
        model = parabola.fitmodel(along="alpha", deg=2)
        dense = model.fitvalue(coef_dims=["alpha_coef"], at={"alpha": [0.0, 2.0, 4.0]})
        assert list(dense.dims) == ["alpha"]
        assert np.allclose(dense.vars["CL"].values, [0.0, 4.0, 16.0], atol=1e-9)

    def test_tags_inside_and_outside_fit_range(self, parabola: VarFrame) -> None:
        # REQ-32/REQ-76: +1 within the original sweep, -1 beyond.
        model = parabola.fitmodel(along="alpha", deg=2)
        dense = model.fitvalue(coef_dims=["alpha_coef"], at={"alpha": [1.0, 5.0, -1.0]})
        assert dense.tags is not None
        assert list(dense.tags.tags["CL"]) == [1, -1, -1]

    def test_unknown_coef_dim_rejected(self, parabola: VarFrame) -> None:
        model = parabola.fitmodel(along="alpha", deg=2)
        with pytest.raises(DimensionNotFoundError):
            model.fitvalue(coef_dims=["mach_coef"], at={"mach": [0.1]})

    def test_at_key_mismatch_rejected(self, parabola: VarFrame) -> None:
        model = parabola.fitmodel(along="alpha", deg=2)
        with pytest.raises(DataError, match="could not pair"):
            model.fitvalue(coef_dims=["alpha_coef"], at={"mach": [0.1]})

    def test_unused_at_key_rejected(self, parabola: VarFrame) -> None:
        # A typo'd extra grid must fail loud, not be silently ignored.
        model = parabola.fitmodel(along="alpha", deg=2)
        with pytest.raises(DataError, match="did not fit"):
            model.fitvalue(
                coef_dims=["alpha_coef"], at={"alpha": [1.0], "alpah": [2.0]}
            )

    def test_unreadable_fit_range_rejected(self, prov) -> None:  # type: ignore[no-untyped-def]
        # A hand-built coef frame without the recorded range cannot be
        # tagged in/out of range: raise rather than assume in-range.
        coef = Dimension(
            name="alpha_coef",
            coords=np.array(["alpha^0", "alpha^1"]),
            is_numeric=False,
        )
        cl = Variable(name="CL", values=np.array([1.0, 2.0]))
        db = VarFrame(dims={"alpha_coef": coef}, vars={"CL": cl}, provenance=prov)
        with pytest.raises(DataError, match="fitted range"):
            db.fitvalue(coef_dims=["alpha_coef"], at={"alpha": [1.0]})

    def test_recorded_in_history(self, parabola: VarFrame) -> None:
        model = parabola.fitmodel(along="alpha", deg=2)
        dense = model.fitvalue(
            coef_dims=["alpha_coef"], at={"alpha": [1.0]}, comment="densify"
        )
        assert dense.history.last is not None
        assert dense.history.last.operation.startswith("fitvalue(")
        assert dense.history.last.comment == "densify"

    def test_uncertainty_through_evaluation_weights(self, prov) -> None:  # type: ignore[no-untyped-def]
        # REQ-98: fitvalue propagates through the fit weights (1, t):
        # systematic |u0 + t*u1|, random RSS.
        coef = Dimension(
            name="alpha_coef",
            coords=np.array(["alpha^0", "alpha^1"]),
            is_numeric=False,
            description="polynomial fit coefficients over alpha=[0.0, 4.0]",
        )
        cl = Variable(name="CL", values=np.array([1.0, 2.0]))
        unc = UncFrame(
            systematic={"CL": np.array([0.1, 0.2])},
            random={"CL": np.array([0.1, 0.2])},
        )
        db = VarFrame(
            dims={"alpha_coef": coef},
            vars={"CL": cl},
            provenance=prov,
            uncertainty=unc,
        )
        dense = db.fitvalue(coef_dims=["alpha_coef"], at={"alpha": [2.0]})
        assert dense.uncertainty is not None
        assert dense.uncertainty.systematic["CL"][0] == pytest.approx(0.5)
        assert dense.uncertainty.random["CL"][0] == pytest.approx(
            np.sqrt(0.1**2 + 0.4**2)
        )
        assert dense.vars["CL"].values[0] == pytest.approx(5.0)
