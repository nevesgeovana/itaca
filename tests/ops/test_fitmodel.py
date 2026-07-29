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
    FitDegreeError,
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
        # Shared FitDegreeError leaf (unified at B1).
        with pytest.raises(FitDegreeError):
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

    def test_uncertainty_rejected(self, prov) -> None:  # type: ignore[no-untyped-def]
        # An author call at the M1 Phase B1 checkpoint (OQ-24): fitvalue
        # defers with fitmodel and raises
        # when uncertainty is present until the coefficient-space rule
        # (OQ-24) is frozen, keeping forward and inverse coherent.
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
        with pytest.raises(UncertaintyError, match="OQ-24"):
            db.fitvalue(coef_dims=["alpha_coef"], at={"alpha": [2.0]})


def test_itaca_025g_fitmodel_and_fitvalue_drop_correlation() -> None:
    """REV-001 ITACA-025g: both keep the names and replace what they hold.

    After fitmodel the arrays are polynomial coefficients; after
    fitvalue they are values evaluated from coefficients. Because the
    variable names do not change, a declared pair keyed on a name would
    silently retarget onto a different quantity, which is exactly the
    failure this finding group is about. Reachable with no uncertainty,
    which both operations refuse (OQ-24).
    """
    arr = np.column_stack(
        [[0.0, 1.0, 2.0, 3.0], [1.0, 3.0, 5.0, 7.0], [2.0, 4.0, 6.0, 8.0]]
    )
    db = itc.load(arr, names=["x", "a", "b"]).pivot(dims=["x"])
    db = db.set_correlation({("a", "b"): 0.4})

    coeffs = db.fitmodel(along="x", deg=1)
    assert coeffs.correlation is None
    assert "correlation=dropped" in coeffs.history[-1].operation

    redeclared = coeffs.set_correlation({("a", "b"): 0.4})
    values = redeclared.fitvalue(coef_dims=["x_coef"], at={"x": [0.5, 1.5]})
    assert values.correlation is None
    assert "correlation=dropped" in values.history[-1].operation


class TestMultiDimensionalTagAccumulation:
    """REV-001 ITACA-027, on the path the finding is actually about.

    Every other `fitvalue` call in this suite passes ONE coefficient
    dimension, so the multi-dimension branch was never entered and the
    accumulation was unexecuted array math. The QA pass caught that: the
    fix shipped with coverage reporting its own lines missing.
    """

    @staticmethod
    def _two_axis_coefficients() -> "VarFrame":
        """v = 1 + x + y fitted along both x and y."""
        rows = [[xi, yi, 1.0 + xi + yi] for xi in range(4) for yi in range(3)]
        db = itc.load(np.array(rows, dtype=float), names=["x", "y", "v"]).pivot(
            dims=["x", "y"]
        )
        return db.fitmodel(along="x", deg=1).fitmodel(along="y", deg=1)

    @pytest.mark.parametrize("coef_dims", [["x_coef", "y_coef"], ["y_coef", "x_coef"]])
    @pytest.mark.parametrize(
        "at,expected,why",
        [
            ({"x": [1.0], "y": [1.0]}, 1, "both inside the fitted range"),
            ({"x": [99.0], "y": [1.0]}, -1, "x extrapolates, y does not"),
            ({"x": [1.0], "y": [99.0]}, -1, "y extrapolates, x does not"),
            ({"x": [99.0], "y": [99.0]}, -1, "both extrapolate"),
        ],
    )
    def test_itaca_027_the_tag_is_the_worst_case_across_coefficient_dimensions(
        self, coef_dims: list[str], at: dict[str, list[float]], expected: int, why: str
    ) -> None:
        """The tag must not depend on the ORDER of coef_dims.

        Measured before the fix, and this is the whole finding: the tag
        reflected only the LAST coefficient dimension processed, because
        `new_tags` was rebuilt per dimension and assigned over the
        previous one. So `x=99, y=1` reported `+1` under
        `['x_coef','y_coef']` and `-1` under `['y_coef','x_coef']`, and
        which extrapolation was hidden depended on argument order.

        REQ-32 requires -1 beyond the fitted domain. A point outside on
        ANY fitted axis is outside.
        """
        out = self._two_axis_coefficients().fitvalue(coef_dims=coef_dims, at=at)
        tags = out.tags.tags["v"].ravel()
        assert tags[0] == expected, (
            f"{why}: expected tag {expected} with coef_dims={coef_dims}, got "
            f"{tags[0]}. The tag is the semantic worst case over every "
            "coefficient dimension and must not depend on their order "
            "(REQ-32, ITACA-027)."
        )
