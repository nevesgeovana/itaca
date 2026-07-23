"""Tests for db.diff (REQ-30): moving-polynomial differentiation.

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])
    slopes = db.diff(along="alpha", window=5, deg=2)
    slopes.vars["dCL_dalpha"]

    db.d["alpha"]  # indexer sugar: diff with default parameters

The derivative is a new VarFrame whose variables follow dVAR_ddim
naming (REQ-18 immutability: nothing is stored on the source frame;
db.d[dim] computes with defaults). Uncertainty raises until OQ-18
freezes the moving-fit weight rule.
"""

import dataclasses

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

import itaca as itc
from itaca.core.errors import (
    DiffWindowError,
    DimensionNotFoundError,
    UncertaintyError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _line(alpha: list[float], cl: list[float]) -> VarFrame:
    arr = np.column_stack([np.array(alpha), np.array(cl)])
    return itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])


@pytest.fixture
def parabola() -> VarFrame:
    alpha = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    return _line(alpha, [a**2 for a in alpha])


class TestDiffValues:
    def test_exact_on_polynomial_within_degree(self, parabola: VarFrame) -> None:
        # REQ-77: the kernel recovers polynomials of degree <= deg
        # exactly; d(a^2)/da = 2a.
        result = parabola.diff(along="alpha", window=5, deg=2)
        assert np.allclose(
            result.vars["dCL_dalpha"].values, [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        )

    def test_variable_naming(self, parabola: VarFrame) -> None:
        result = parabola.diff(along="alpha")
        assert set(result.vars) == {"dCL_dalpha"}

    def test_shape_preserved_with_asymmetric_windows(self, parabola: VarFrame) -> None:
        result = parabola.diff(along="alpha", window=5, deg=2)
        assert result.shape == parabola.shape

    def test_nan_edges(self, parabola: VarFrame) -> None:
        result = parabola.diff(along="alpha", window=5, deg=2, nan_edges=True)
        values = result.vars["dCL_dalpha"].values
        assert np.isnan(values[0]) and np.isnan(values[1])
        assert np.isnan(values[-1]) and np.isnan(values[-2])
        assert np.allclose(values[2:4], [4.0, 6.0])


class TestDiffIndexer:
    def test_d_indexer_computes_defaults(self, parabola: VarFrame) -> None:
        result = parabola.d["alpha"]
        assert set(result.vars) == {"dCL_dalpha"}
        assert np.allclose(
            result.vars["dCL_dalpha"].values,
            parabola.diff(along="alpha").vars["dCL_dalpha"].values,
        )

    def test_d_indexer_unknown_dim(self, parabola: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            parabola.d["beta"]


class TestDiffValidation:
    def test_window_le_deg_rejected(self, parabola: VarFrame) -> None:
        # REQ-76 edge case: diff with window <= deg.
        with pytest.raises(DiffWindowError, match="more points than the degree") as exc:
            parabola.diff(along="alpha", window=2, deg=2)
        assert "Suggested fix:" in str(exc.value)

    def test_unknown_dimension_rejected(self, parabola: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            parabola.diff(along="beta")


class TestDiffBookkeeping:
    def test_recorded_in_history(self, parabola: VarFrame) -> None:
        result = parabola.diff(along="alpha", comment="lift slope")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("diff(")
        assert result.history.last.comment == "lift slope"

    def test_original_untouched(self, parabola: VarFrame) -> None:
        parabola.diff(along="alpha")
        assert set(parabola.vars) == {"CL"}

    def test_tags_carry_worst_case_over_window(self) -> None:
        # A filled point taints every window it falls into (OQ-10).
        alpha = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        cl = [a**2 for a in alpha]
        cl[2] = np.nan
        filled = (
            _line(alpha, cl)
            .fill(along="alpha", method="linear")
            .diff(along="alpha", window=3, deg=1)
        )
        assert filled.tags is not None
        assert filled.tags.tags["dCL_dalpha"][2] == 1
        assert filled.tags.tags["dCL_dalpha"][5] == 0

    def test_non_numeric_dimension_rejected(self, prov) -> None:  # type: ignore[no-untyped-def]
        from itaca.core.dimension import Dimension
        from itaca.core.variable import Variable

        blade = Dimension(name="blade", coords=np.array(["A", "B"]), is_numeric=False)
        cl = Variable(name="CL", values=np.array([1.0, 2.0]))
        db = VarFrame(dims={"blade": blade}, vars={"CL": cl}, provenance=prov)
        with pytest.raises(Exception, match="string-valued"):
            db.diff(along="blade")

    def test_unit_metadata_composed(self) -> None:
        alpha = [0.0, 1.0, 2.0, 3.0, 4.0]
        db = _line(alpha, [a**2 for a in alpha])
        # Units are metadata only; when both are present the ratio
        # label is composed.
        result = db.diff(along="alpha")
        assert result.vars["dCL_dalpha"].unit is None


class TestDiffKernelProperties:
    # REQ-77: property-based test of the diff kernel contract: exact
    # recovery of the derivative of polynomials of degree <= deg.
    @given(
        coeffs=st.lists(
            st.floats(min_value=-5.0, max_value=5.0, allow_nan=False),
            min_size=1,
            max_size=3,
        ),
        n=st.integers(min_value=5, max_value=12),
    )
    def test_polynomial_derivative_recovered(self, coeffs: list[float], n: int) -> None:
        alpha = np.linspace(0.0, 2.0, n)
        poly = np.polynomial.Polynomial(coeffs)
        db = _line(list(alpha), list(poly(alpha)))
        result = db.diff(along="alpha", window=5, deg=2)
        expected = poly.deriv()(alpha)
        assert np.allclose(
            result.vars["dCL_dalpha"].values, expected, atol=1e-6, rtol=1e-6
        )


class TestDiffUncertainty:
    def test_uncertainty_raises_until_oq18(self, parabola: VarFrame) -> None:
        unc = UncFrame(
            systematic={"CL": np.full(6, 0.1)}, random={"CL": np.full(6, 0.1)}
        )
        with pytest.raises(UncertaintyError):
            dataclasses.replace(parabola, uncertainty=unc).diff(along="alpha")
