"""Tests for the axes data model (REQ-38, REQ-101; SRS 4.6).

Usage example (TDD anchor)::

    from itaca.core.axes import Axis, wind_axis, AxisRegistry

    body = Axis(name="rig", rotation_matrix=np.eye(3))
    wind = wind_axis()                     # condition-dependent
    reg = AxisRegistry().with_axis(body).with_axis(wind)
    R = wind.matrix_at({"alpha": 0.1, "beta": 0.0})

An Axis is either a constant 3x3 orthogonal matrix or a parametric
frame evaluated per grid point from named angles (REQ-101). The
built-in wind and stability frames follow AIAA R-004A-1992; their sign
convention is pending Geovana's SME acceptance.
"""

import numpy as np
import pytest

from itaca.core.axes import (
    Axis,
    AxisRegistry,
    body_axis,
    stability_axis,
    wind_axis,
)
from itaca.core.errors import AxisNotFoundError, RotationMatrixError, VectorGroupError


class TestAxisConstruction:
    def test_constant_matrix(self) -> None:
        axis = Axis(name="rig", rotation_matrix=np.eye(3))
        assert axis.is_constant
        assert np.allclose(axis.matrix_at({}), np.eye(3))

    def test_parametric_axis(self) -> None:
        axis = Axis(name="wind", angles_from=("alpha", "beta"), convention="wind")
        assert not axis.is_constant
        assert axis.angles_from == ("alpha", "beta")

    def test_exactly_one_definition_required(self) -> None:
        with pytest.raises(RotationMatrixError, match="exactly one"):
            Axis(name="bad", rotation_matrix=np.eye(3), angles_from=("alpha",))
        with pytest.raises(RotationMatrixError, match="exactly one"):
            Axis(name="bad")

    def test_non_orthogonal_matrix_rejected(self) -> None:
        skew = np.array([[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        with pytest.raises(RotationMatrixError, match="orthogonal"):
            Axis(name="bad", rotation_matrix=skew)

    def test_wrong_shape_matrix_rejected(self) -> None:
        with pytest.raises(RotationMatrixError, match="3x3"):
            Axis(name="bad", rotation_matrix=np.eye(2))

    def test_unknown_convention_rejected(self) -> None:
        with pytest.raises(RotationMatrixError, match="convention"):
            Axis(name="x", angles_from=("alpha",), convention="martian")

    def test_matrix_is_read_only(self) -> None:
        axis = Axis(name="rig", rotation_matrix=np.eye(3))
        with pytest.raises((ValueError, RuntimeError)):
            axis.rotation_matrix[0, 0] = 9.0  # type: ignore[index]


class TestBuiltinFrames:
    def test_body_is_identity(self) -> None:
        assert np.allclose(body_axis().matrix_at({}), np.eye(3))

    def test_stability_reduces_to_identity_at_zero_alpha(self) -> None:
        assert np.allclose(stability_axis().matrix_at({"alpha": 0.0}), np.eye(3))

    def test_wind_reduces_to_identity_at_zero_angles(self) -> None:
        m = wind_axis().matrix_at({"alpha": 0.0, "beta": 0.0})
        assert np.allclose(m, np.eye(3))

    def test_matrices_are_orthogonal(self) -> None:
        # A valid rotation preserves lengths: R^T R = I, det = +1.
        for angles in ({"alpha": 0.3, "beta": -0.2}, {"alpha": -0.5, "beta": 0.4}):
            r = wind_axis().matrix_at(angles)
            assert np.allclose(r @ r.T, np.eye(3), atol=1e-12)
            assert np.isclose(np.linalg.det(r), 1.0)

    def test_stability_orthogonal(self) -> None:
        r = stability_axis().matrix_at({"alpha": 0.4})
        assert np.allclose(r @ r.T, np.eye(3), atol=1e-12)
        assert np.isclose(np.linalg.det(r), 1.0)

    def test_stability_rotates_x_into_xz_plane(self) -> None:
        # A pure alpha rotation leaves the y component untouched.
        r = stability_axis().matrix_at({"alpha": 0.3})
        assert r[1, 1] == pytest.approx(1.0)
        assert r[1, 0] == pytest.approx(0.0)
        assert r[1, 2] == pytest.approx(0.0)


class TestParametricEvaluation:
    def test_missing_angle_rejected(self) -> None:
        with pytest.raises(VectorGroupError, match="alpha"):
            wind_axis().matrix_at({"beta": 0.0})

    def test_derivative_matches_finite_difference(self) -> None:
        # REQ-101: the chain-rule sensitivity dR/dalpha must be exact.
        axis = stability_axis()
        alpha = 0.35
        analytic = axis.d_matrix_d_angle({"alpha": alpha})["alpha"]
        eps = 1e-7
        fd = (
            axis.matrix_at({"alpha": alpha + eps})
            - axis.matrix_at({"alpha": alpha - eps})
        ) / (2.0 * eps)
        assert np.allclose(analytic, fd, atol=1e-6)

    def test_wind_derivatives_match_finite_difference(self) -> None:
        axis = wind_axis()
        base = {"alpha": 0.2, "beta": -0.15}
        grads = axis.d_matrix_d_angle(base)
        eps = 1e-7
        for angle in ("alpha", "beta"):
            plus = dict(base, **{angle: base[angle] + eps})
            minus = dict(base, **{angle: base[angle] - eps})
            fd = (axis.matrix_at(plus) - axis.matrix_at(minus)) / (2.0 * eps)
            assert np.allclose(grads[angle], fd, atol=1e-6)

    def test_constant_axis_has_zero_derivative(self) -> None:
        axis = Axis(name="rig", rotation_matrix=np.eye(3))
        assert axis.d_matrix_d_angle({}) == {}


class TestAxisRegistry:
    def test_register_and_resolve(self) -> None:
        rig = Axis(name="rig", rotation_matrix=np.eye(3))
        reg = AxisRegistry().with_axis(rig)
        assert reg.resolve("rig") is rig

    def test_immutable_with_axis_returns_new(self) -> None:
        reg0 = AxisRegistry()
        reg1 = reg0.with_axis(Axis(name="rig", rotation_matrix=np.eye(3)))
        assert "rig" not in reg0.axes
        assert "rig" in reg1.axes

    def test_unknown_axis_raises(self) -> None:
        with pytest.raises(AxisNotFoundError, match="tunnel"):
            AxisRegistry().resolve("tunnel")

    def test_builtins_present_by_default(self) -> None:
        reg = AxisRegistry.with_builtins()
        assert np.allclose(reg.resolve("body").matrix_at({}), np.eye(3))
        assert not reg.resolve("wind").is_constant
        assert not reg.resolve("stability").is_constant

    def test_duplicate_name_rejected(self) -> None:
        reg = AxisRegistry().with_axis(Axis(name="rig", rotation_matrix=np.eye(3)))
        with pytest.raises(RotationMatrixError, match="already registered"):
            reg.with_axis(Axis(name="rig", rotation_matrix=np.eye(3)))

    def test_vector_group_declaration(self) -> None:
        reg = AxisRegistry().with_vector_group("aero_force", ["FX", "FY", "FZ"])
        assert reg.vector_groups["aero_force"] == ("FX", "FY", "FZ")

    def test_vector_group_needs_three_components(self) -> None:
        with pytest.raises(VectorGroupError, match="three"):
            AxisRegistry().with_vector_group("bad", ["FX", "FY"])
