"""Tests for db.interpolate (REQ-25): densify or translate axis.

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
    dense = db.interpolate({"alpha": [0.0, 0.5, 1.0, 1.5, 2.0]})
    on_cl = db.interpolate(axisTranslation={"from": "alpha", "to": "CL"})

Existing coordinates are preserved unless override=True; the
HistoryFrame gets +1 inside the convex hull of the original axis and
-1 outside; uncertainty propagates through the interpolation weights
(REQ-98, both components).
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    AxisTranslationError,
    DataError,
    DimensionNotFoundError,
    NonNumericDimensionError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _line(alpha: list[float], ct: list[float], name: str = "CT") -> VarFrame:
    arr = np.column_stack([np.array(alpha), np.array(ct)])
    return itc.load(arr, names=["alpha", name]).pivot(dims=["alpha"])


def _natural_cubic_reference(
    x: np.ndarray, y: np.ndarray, targets: np.ndarray
) -> np.ndarray:
    """Independent natural cubic spline (Numerical Recipes scalar form).

    Structurally different from the kernel's weight-matrix assembly, so
    a mistake in one is unlikely to be mirrored in the other.
    """
    n = x.size
    y2 = np.zeros(n)
    u = np.zeros(n)
    for i in range(1, n - 1):
        sig = (x[i] - x[i - 1]) / (x[i + 1] - x[i - 1])
        p = sig * y2[i - 1] + 2.0
        y2[i] = (sig - 1.0) / p
        u[i] = (y[i + 1] - y[i]) / (x[i + 1] - x[i]) - (y[i] - y[i - 1]) / (
            x[i] - x[i - 1]
        )
        u[i] = (6.0 * u[i] / (x[i + 1] - x[i - 1]) - sig * u[i - 1]) / p
    for k in range(n - 2, -1, -1):
        y2[k] = y2[k] * y2[k + 1] + u[k]
    out = np.empty(targets.size)
    for j, t in enumerate(targets):
        klo = int(np.clip(np.searchsorted(x, t, side="right") - 1, 0, n - 2))
        khi = klo + 1
        h = x[khi] - x[klo]
        a = (x[khi] - t) / h
        b = (t - x[klo]) / h
        out[j] = (
            a * y[klo]
            + b * y[khi]
            + ((a**3 - a) * y2[klo] + (b**3 - b) * y2[khi]) * h**2 / 6.0
        )
    return out


@pytest.fixture
def ramp() -> VarFrame:
    # CT = 2 * alpha, exactly linear.
    return _line([0.0, 1.0, 2.0], [0.0, 2.0, 4.0])


class TestInterpolateMethods:
    def test_linear_exact_on_linear_data(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.5, 1.5]})
        assert np.allclose(result.dims["alpha"].coords, [0.5, 1.5])
        assert np.allclose(result.vars["CT"].values, [1.0, 3.0])

    def test_nearest(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.4, 1.6]}, method="nearest")
        assert np.allclose(result.vars["CT"].values, [0.0, 4.0])

    def test_cubic_reproduces_nodes_and_linear_data(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.0, 0.5, 1.0, 2.0]}, method="cubic")
        assert np.allclose(result.vars["CT"].values, [0.0, 1.0, 2.0, 4.0])

    def test_cubic_on_curved_data_matches_natural_spline(self) -> None:
        # Genuinely curved data exercises the second-derivative band of
        # the natural-spline operator (linear data zeroes it out).
        alpha = [0.0, 1.0, 2.0, 3.0, 4.0]
        db = _line(alpha, [a**3 for a in alpha])
        result = db.interpolate({"alpha": [0.5, 1.5, 2.5]}, method="cubic")
        # Natural cubic reference (second derivative zero at the ends).
        # Interior midpoints of a smooth cubic sampled on a fine grid.
        expected = _natural_cubic_reference(
            np.array(alpha, dtype=float),
            np.array([a**3 for a in alpha], dtype=float),
            np.array([0.5, 1.5, 2.5]),
        )
        assert np.allclose(result.vars["CT"].values, expected, atol=1e-9)

    def test_cubic_reproduces_curved_nodes_exactly(self) -> None:
        alpha = [0.0, 1.0, 2.0, 3.0, 4.0]
        cubic_vals = [a**3 - 2.0 * a for a in alpha]
        db = _line(alpha, cubic_vals)
        result = db.interpolate({"alpha": alpha}, method="cubic", override=True)
        assert np.allclose(result.vars["CT"].values, cubic_vals, atol=1e-9)

    def test_polyfit_exact_on_quadratic(self) -> None:
        alpha = [0.0, 1.0, 2.0, 3.0]
        db = _line(alpha, [a**2 for a in alpha])
        result = db.interpolate({"alpha": [0.5, 2.5]}, method="polyfit", deg=2)
        assert np.allclose(result.vars["CT"].values, [0.25, 6.25])

    def test_polyfit_needs_deg(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate({"alpha": [0.5]}, method="polyfit")

    def test_unknown_method_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate({"alpha": [0.5]}, method="magic")


class TestInterpolateOverride:
    def test_existing_coordinate_preserved_by_default(self) -> None:
        # REQ-76 edge case: override=False on an existing coordinate.
        # A deg-1 polyfit of quadratic data would change the value at
        # alpha=1; the original must be preserved.
        alpha = [0.0, 1.0, 2.0]
        db = _line(alpha, [a**2 for a in alpha])
        result = db.interpolate({"alpha": [0.5, 1.0]}, method="polyfit", deg=1)
        assert result.vars["CT"].values[1] == pytest.approx(1.0)

    def test_override_recomputes(self) -> None:
        alpha = [0.0, 1.0, 2.0]
        db = _line(alpha, [a**2 for a in alpha])
        result = db.interpolate(
            {"alpha": [0.5, 1.0]}, method="polyfit", deg=1, override=True
        )
        assert result.vars["CT"].values[1] != pytest.approx(1.0)

    def test_preserved_point_keeps_tag_zero(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.5, 1.0]})
        assert result.tags is not None
        assert result.tags.tags["CT"][1] == 0


class TestInterpolateTags:
    def test_hull_tags(self, ramp: VarFrame) -> None:
        # REQ-25: +1 within the convex hull of the original axis, -1
        # outside.
        result = ramp.interpolate({"alpha": [-1.0, 0.5, 3.0]})
        assert result.tags is not None
        assert list(result.tags.tags["CT"]) == [-1, 1, -1]


class TestInterpolateValidation:
    def test_unknown_dimension_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            ramp.interpolate({"beta": [0.5]})

    def test_non_numeric_dimension_rejected(self, prov) -> None:  # type: ignore[no-untyped-def]
        from itaca.core.dimension import Dimension
        from itaca.core.variable import Variable

        blade = Dimension(name="blade", coords=np.array(["A", "B"]), is_numeric=False)
        ct = Variable(name="CT", values=np.array([1.0, 2.0]))
        db = VarFrame(dims={"blade": blade}, vars={"CT": ct}, provenance=prov)
        with pytest.raises(NonNumericDimensionError):
            db.interpolate({"blade": ["C"]})

    def test_empty_call_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate({})


class TestInterpolateMultiDim:
    def test_partial_interpolation_keeps_other_dims(self) -> None:
        rows = [[a, m, 10.0 * a + m] for a in (0.0, 1.0, 2.0) for m in (0.1, 0.2)]
        db = itc.load(np.array(rows), names=["alpha", "mach", "CT"]).pivot(
            dims=["alpha", "mach"]
        )
        result = db.interpolate({"alpha": [0.5, 1.5]})
        assert result.shape == (2, 2)
        assert result.vars["CT"].values[0, 0] == pytest.approx(5.1)
        assert result.vars["CT"].values[1, 1] == pytest.approx(15.2)


class TestInterpolateUncertainty:
    def test_components_through_linear_weights(self, ramp: VarFrame) -> None:
        # Midpoint weights (0.5, 0.5): systematic through the weight
        # sum, random through the RSS (REQ-98).
        unc = UncFrame(
            systematic={"CT": np.full(3, 0.1)},
            random={"CT": np.full(3, 0.1)},
        )
        result = dataclasses.replace(ramp, uncertainty=unc).interpolate(
            {"alpha": [0.5]}
        )
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["CT"][0] == pytest.approx(0.1)
        assert result.uncertainty.random["CT"][0] == pytest.approx(0.1 / np.sqrt(2.0))


class TestAxisTranslation:
    def test_single_line_relabels_axis(self) -> None:
        rows = [[a, 0.1 * a, 2.0 * a] for a in (0.0, 1.0, 2.0)]
        db = itc.load(np.array(rows), names=["alpha", "CL", "CT"]).pivot(dims=["alpha"])
        result = db.interpolate(axisTranslation={"from": "alpha", "to": "CL"})
        assert "alpha" not in result.dims
        assert np.allclose(result.dims["CL"].coords, [0.0, 0.1, 0.2])
        assert "CL" not in result.vars
        assert np.allclose(result.vars["CT"].values, [0.0, 2.0, 4.0])

    def test_explicit_target_grid(self) -> None:
        rows = [[a, 0.1 * a, 2.0 * a] for a in (0.0, 1.0, 2.0)]
        db = itc.load(np.array(rows), names=["alpha", "CL", "CT"]).pivot(dims=["alpha"])
        result = db.interpolate(
            {"CL": [0.05, 0.15]},
            axisTranslation={"from": "alpha", "to": "CL"},
        )
        assert np.allclose(result.dims["CL"].coords, [0.05, 0.15])
        assert np.allclose(result.vars["CT"].values, [1.0, 3.0])

    def test_non_monotonic_target_rejected(self) -> None:
        rows = [[a, v, 1.0] for a, v in [(0.0, 0.0), (1.0, 1.0), (2.0, 0.5)]]
        db = itc.load(np.array(rows), names=["alpha", "CL", "CT"]).pivot(dims=["alpha"])
        with pytest.raises(AxisTranslationError, match="monotonic") as exc:
            db.interpolate(axisTranslation={"from": "alpha", "to": "CL"})
        assert "Suggested fix:" in str(exc.value)

    def test_missing_target_variable_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate(axisTranslation={"from": "alpha", "to": "CL"})


class TestInterpolateBookkeeping:
    def test_recorded_in_history(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.5]}, comment="densify")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("interpolate(")
        assert result.history.last.comment == "densify"

    def test_original_untouched(self, ramp: VarFrame) -> None:
        ramp.interpolate({"alpha": [0.5]})
        assert ramp.shape == (3,)
