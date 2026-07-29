"""Tests for db.rotate (REQ-38, REQ-101).

Usage example (TDD anchor)::

    import itaca as itc
    db = db.declare_vector("force", ["FX", "FY", "FZ"], axis="rig")
    rotated = db.rotate("wind")

Each declared vector group is transformed from its own source frame to
the target, composing through the canonical body axis (REQ-107).
Condition-dependent frames are evaluated per grid point; the rotation
matrix is the exact Jacobian, and when a referenced angle carries
uncertainty its dR/dangle sensitivity enters (REQ-101). Expected
uncertainties are recomputed here by explicit R C R^T algebra, an
oracle independent of the implementation's internals.
"""

import dataclasses

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

import itaca as itc
from itaca.core.axes import Axis
from itaca.core.correlation import CorrelationMatrix
from itaca.core.errors import (
    AxisNotFoundError,
    DataError,
    UncertaintyError,
    VectorGroupError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame

# Active 90-degree rotation about z: v_target = M @ v_body.
_M90 = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])


def _force_frame(fx: list[float], fy: list[float], fz: list[float]) -> VarFrame:
    alpha = np.arange(float(len(fx)))
    arr = np.column_stack([alpha, np.array(fx), np.array(fy), np.array(fz)])
    return itc.load(arr, names=["alpha", "FX", "FY", "FZ"]).pivot(dims=["alpha"])


@pytest.fixture
def db() -> VarFrame:
    return _force_frame([1.0, 0.0], [0.0, 2.0], [0.0, 0.0])


class TestConstantRotation:
    def test_rotates_declared_group(self, db: VarFrame) -> None:
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            db.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        # body (1,0,0) -> (0,1,0); body (0,2,0) -> (-2,0,0).
        assert np.allclose(out.vars["FX"].values, [0.0, -2.0])
        assert np.allclose(out.vars["FY"].values, [1.0, 0.0])
        assert np.allclose(out.vars["FZ"].values, [0.0, 0.0])

    def test_auto_detected_force_group(self, db: VarFrame) -> None:
        # (FX, FY, FZ) is a default-named group; no declaration needed.
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = db.register_axis(rig).rotate("rig")
        assert np.allclose(out.vars["FX"].values, [0.0, -2.0])

    def test_body_to_body_is_identity(self, db: VarFrame) -> None:
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("body")
        assert np.allclose(out.vars["FX"].values, db.vars["FX"].values)
        assert np.allclose(out.vars["FY"].values, db.vars["FY"].values)

    def test_source_frame_composed(self, db: VarFrame) -> None:
        # A group already in the rig frame, rotated back to body, undoes M.
        rig = Axis(name="rig", rotation_matrix=_M90)
        staged = db.register_axis(rig).declare_vector(
            "force", ["FX", "FY", "FZ"], axis="rig"
        )
        out = staged.rotate("body")
        # rig (1,0,0) -> body = M^T @ (1,0,0) = (0,1,0)... wait check:
        # v_body = L_rig_b^T @ v_rig = M^T @ (1,0,0) = (0,1,0)? no.
        # M^T = [[0,1,0],[-1,0,0],[0,0,1]]; M^T @ (1,0,0) = (0,-1,0).
        assert np.allclose(out.vars["FX"].values, [0.0, 2.0])
        assert np.allclose(out.vars["FY"].values, [-1.0, 0.0])


class TestConditionDependent:
    def test_wind_at_zero_is_identity(self) -> None:
        from itaca.core.dimension import Dimension

        rows = [[0.0, 0.0, 1.0, 2.0, 3.0]]
        db = itc.load(np.array(rows), names=["alpha", "beta", "FX", "FY", "FZ"]).pivot(
            dims=["alpha", "beta"]
        )
        db = dataclasses.replace(
            db,
            dims={
                "alpha": Dimension(name="alpha", coords=np.array([0.0]), unit="deg"),
                "beta": Dimension(name="beta", coords=np.array([0.0]), unit="deg"),
            },
        )
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("wind")
        assert np.allclose(out.vars["FX"].values, 1.0)
        assert np.allclose(out.vars["FY"].values, 2.0)
        assert np.allclose(out.vars["FZ"].values, 3.0)

    def test_stability_rotation_per_alpha(self) -> None:
        # target stability = Ry(alpha); a pure FX rotates in the x-z plane.
        alpha = [0.0, np.pi / 2.0]
        rows = [[a, 1.0, 0.0, 0.0] for a in alpha]
        db = itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
            dims=["alpha"]
        )
        # alpha is in radians here; declare its unit so rotate reads it.
        from itaca.core.dimension import Dimension

        db = dataclasses.replace(
            db,
            dims={"alpha": Dimension(name="alpha", coords=np.array(alpha), unit="rad")},
        )
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")
        # Ry(alpha) @ (1,0,0) = (cos a, 0, -sin a).
        assert np.allclose(out.vars["FX"].values, [1.0, 0.0], atol=1e-12)
        assert np.allclose(out.vars["FZ"].values, [0.0, -1.0], atol=1e-12)

    def test_angle_unit_degrees_converted(self) -> None:
        from itaca.core.dimension import Dimension

        rows = [[90.0, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
            dims=["alpha"]
        )
        db = dataclasses.replace(
            db,
            dims={
                "alpha": Dimension(name="alpha", coords=np.array([90.0]), unit="deg")
            },
        )
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")
        # 90 deg: Ry(pi/2) @ (1,0,0) = (0, 0, -1).
        assert out.vars["FX"].values[0] == pytest.approx(0.0, abs=1e-12)
        assert out.vars["FZ"].values[0] == pytest.approx(-1.0, abs=1e-12)

    def test_missing_angle_unit_rejected(self) -> None:
        rows = [[0.5, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
            dims=["alpha"]
        )
        # alpha has no unit metadata.
        with pytest.raises(DataError, match="unit"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")


class TestValidation:
    def test_unknown_target_rejected(self, db: VarFrame) -> None:
        with pytest.raises(AxisNotFoundError, match="tunnel"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("tunnel")

    def test_no_resolvable_group_rejected(self) -> None:
        rows = [[0.0, 1.0]]
        db = itc.load(np.array(rows), names=["alpha", "CT"]).pivot(dims=["alpha"])
        with pytest.raises(VectorGroupError):
            db.rotate("stability")

    def test_requested_unknown_group_rejected(self, db: VarFrame) -> None:
        with pytest.raises(VectorGroupError, match="ghost"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).rotate(
                "body", vector_groups=["ghost"]
            )

    def test_vector_groups_subset(self) -> None:
        rows = [[0.0, 1.0, 0.0, 0.0, 5.0, 0.0, 0.0]]
        db = itc.load(
            np.array(rows),
            names=["a", "FX", "FY", "FZ", "MX", "MY", "MZ"],
        ).pivot(dims=["a"])
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = db.register_axis(rig).rotate("rig", vector_groups=["force"])
        # force rotated, moment left alone.
        assert out.vars["FY"].values[0] == pytest.approx(1.0)
        assert out.vars["MX"].values[0] == pytest.approx(5.0)

    def test_missing_condition_angle_rejected(self) -> None:
        # target wind needs alpha and beta; the frame has neither.
        rows = [[0.0, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["idx", "FX", "FY", "FZ"]).pivot(
            dims=["idx"]
        )
        with pytest.raises(VectorGroupError, match="alpha"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("wind")


class TestAdvancedUncertainty:
    def test_random_angle_uncertainty(self) -> None:
        alpha0 = 0.25
        rows = [[0.0, alpha0, 2.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["idx", "alpha", "FX", "FY", "FZ"]).pivot(
            dims=["idx"]
        )
        db = dataclasses.replace(
            db,
            vars={
                **db.vars,
                "alpha": dataclasses.replace(db.vars["alpha"], unit="rad"),
            },
        )
        u_alpha, u_comp = 0.05, 0.1
        unc = UncFrame(
            systematic={},
            random={
                "FX": np.array([u_comp]),
                "FY": np.array([u_comp]),
                "FZ": np.array([u_comp]),
                "alpha": np.array([u_alpha]),
            },
        )
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("stability")
        )
        ca, sa = np.cos(alpha0), np.sin(alpha0)
        r = np.array([[ca, 0.0, sa], [0.0, 1.0, 0.0], [-sa, 0.0, ca]])
        dr = np.array([[-sa, 0.0, ca], [0.0, 0.0, 0.0], [-ca, 0.0, -sa]])
        v = np.array([2.0, 0.0, 0.0])
        cov = r @ np.diag(np.full(3, u_comp**2)) @ r.T
        extra = (dr @ v) ** 2 * u_alpha**2
        expected = np.sqrt(np.diag(cov) + extra)
        assert out.uncertainty is not None
        assert out.uncertainty.random["FZ"][0] == pytest.approx(expected[2])

    def test_source_frame_angle_uncertainty(self) -> None:
        # Data already in the stability frame (source), alpha uncertain,
        # rotated to body: the source-frame chain-rule term fires.
        alpha0 = 0.2
        rows = [[0.0, alpha0, 2.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["idx", "alpha", "FX", "FY", "FZ"]).pivot(
            dims=["idx"]
        )
        db = dataclasses.replace(
            db,
            vars={
                **db.vars,
                "alpha": dataclasses.replace(db.vars["alpha"], unit="rad"),
            },
        )
        u_alpha, u_comp = 0.04, 0.1
        unc = UncFrame(
            systematic={
                "FX": np.array([u_comp]),
                "FY": np.array([u_comp]),
                "FZ": np.array([u_comp]),
                "alpha": np.array([u_alpha]),
            },
            random={},
        )
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .declare_vector("force", ["FX", "FY", "FZ"], axis="stability")
            .rotate("body")
        )
        # R = L_body @ L_sb^T = L_sb^T; dR/da = (dL_sb/da)^T.
        ca, sa = np.cos(alpha0), np.sin(alpha0)
        l_sb = np.array([[ca, 0.0, sa], [0.0, 1.0, 0.0], [-sa, 0.0, ca]])
        dl_sb = np.array([[-sa, 0.0, ca], [0.0, 0.0, 0.0], [-ca, 0.0, -sa]])
        r = l_sb.T
        dr = dl_sb.T
        v = np.array([2.0, 0.0, 0.0])
        cov = r @ np.diag(np.full(3, u_comp**2)) @ r.T
        extra = (dr @ v) ** 2 * u_alpha**2
        expected = np.sqrt(np.diag(cov) + extra)
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["FX"][0] == pytest.approx(expected[0])
        assert out.uncertainty.systematic["FZ"][0] == pytest.approx(expected[2])


class TestUncertainty:
    def _expected_rotated_unc(
        self, matrix: np.ndarray, u: np.ndarray, corr: np.ndarray
    ) -> np.ndarray:
        cov = (u[:, None] * u[None, :]) * corr
        cov_t = matrix @ cov @ matrix.T
        return np.sqrt(np.diag(cov_t))

    def test_jacobian_no_correlation(self, db: VarFrame) -> None:
        u = np.array([0.1, 0.2, 0.3])
        unc = UncFrame(
            systematic={
                "FX": np.full(2, u[0]),
                "FY": np.full(2, u[1]),
                "FZ": np.full(2, u[2]),
            },
            random={
                "FX": np.full(2, u[0]),
                "FY": np.full(2, u[1]),
                "FZ": np.full(2, u[2]),
            },
        )
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        expected = self._expected_rotated_unc(_M90, u, np.eye(3))
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["FX"][0] == pytest.approx(expected[0])
        assert out.uncertainty.systematic["FY"][0] == pytest.approx(expected[1])
        assert out.uncertainty.random["FZ"][0] == pytest.approx(expected[2])

    def test_correlated_components(self, db: VarFrame) -> None:
        u = np.array([0.1, 0.1, 0.2])
        corr = np.array([[1.0, 0.5, 0.0], [0.5, 1.0, 0.0], [0.0, 0.0, 1.0]])
        unc = UncFrame(
            systematic={
                "FX": np.full(2, u[0]),
                "FY": np.full(2, u[1]),
                "FZ": np.full(2, u[2]),
            },
            random={},
        )
        # 45-degree rotation about z mixes FX and FY so the correlation
        # actually changes the propagated uncertainty.
        c = np.cos(np.pi / 4.0)
        m45 = np.array([[c, -c, 0.0], [c, c, 0.0], [0.0, 0.0, 1.0]])
        rig = Axis(name="rig", rotation_matrix=m45)
        base = dataclasses.replace(
            db,
            uncertainty=unc,
            correlation=CorrelationMatrix(pairs={("FX", "FY"): 0.5}),
        )
        out = (
            base.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        expected = self._expected_rotated_unc(m45, u, corr)
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["FX"][0] == pytest.approx(expected[0])
        assert out.uncertainty.systematic["FY"][0] == pytest.approx(expected[1])

    def test_chain_rule_angle_uncertainty(self) -> None:
        # target stability = Ry(alpha), alpha a variable carrying
        # uncertainty: the dR/dalpha term adds to the result variance.
        alpha0 = 0.3
        rows = [[0.0, alpha0, 2.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["idx", "alpha", "FX", "FY", "FZ"]).pivot(
            dims=["idx"]
        )
        db = dataclasses.replace(
            db,
            vars={
                **db.vars,
                "alpha": dataclasses.replace(db.vars["alpha"], unit="rad"),
            },
        )
        u_alpha = 0.05
        u_comp = 0.1
        unc = UncFrame(
            systematic={
                "FX": np.array([u_comp]),
                "FY": np.array([u_comp]),
                "FZ": np.array([u_comp]),
                "alpha": np.array([u_alpha]),
            },
            random={},
        )
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("stability")
        )
        # Expected: Var = [R diag(u^2) R^T]_kk + (dR/da @ v)_k^2 u_alpha^2.
        ca, sa = np.cos(alpha0), np.sin(alpha0)
        r = np.array([[ca, 0.0, sa], [0.0, 1.0, 0.0], [-sa, 0.0, ca]])
        dr = np.array([[-sa, 0.0, ca], [0.0, 0.0, 0.0], [-ca, 0.0, -sa]])
        v = np.array([2.0, 0.0, 0.0])
        cov = r @ np.diag(np.full(3, u_comp**2)) @ r.T
        extra = (dr @ v) ** 2 * u_alpha**2
        expected = np.sqrt(np.diag(cov) + extra)
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["FX"][0] == pytest.approx(expected[0])
        assert out.uncertainty.systematic["FZ"][0] == pytest.approx(expected[2])


class TestSharedAngle:
    def test_shared_angle_cancels(self) -> None:
        # Source stability (alpha) to target wind (alpha, beta) with
        # beta=0: R = Rz(0) @ Rz(0)... the composite is alpha-independent
        # for FY, so the shared-alpha sensitivity must cancel, not double
        # count. Verified: the alpha contribution to FZ is exactly zero.
        alpha0 = 0.3
        rows = [[0.0, alpha0, 0.0, 0.0, 2.0, 0.0]]
        db = itc.load(
            np.array(rows), names=["idx", "alpha", "beta", "FX", "FY", "FZ"]
        ).pivot(dims=["idx"])
        db = dataclasses.replace(
            db,
            vars={
                **db.vars,
                "alpha": dataclasses.replace(db.vars["alpha"], unit="rad"),
                "beta": dataclasses.replace(db.vars["beta"], unit="rad"),
            },
        )
        u_alpha = 0.05
        unc = UncFrame(
            systematic={
                "FX": np.array([0.0]),
                "FY": np.array([0.0]),
                "FZ": np.array([0.0]),
                "alpha": np.array([u_alpha]),
                "beta": np.array([0.0]),
            },
            random={},
        )
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .declare_vector("force", ["FX", "FY", "FZ"], axis="stability")
            .rotate("wind")
        )
        # source stability = Ry(alpha), target wind at beta=0 = Ry(alpha);
        # composite R = Ry(alpha) @ Ry(alpha)^T = I, alpha-independent, so
        # the total dR/dalpha is zero and the propagated uncertainty is 0.
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["FZ"][0] == pytest.approx(0.0, abs=1e-12)


class TestAngleCorrelationGuard:
    def test_declared_angle_correlation_rejected(self) -> None:
        """A declared correlation touching a frame angle is refused (OQ-26).

        The angle source is a VARIABLE, which is the only shape this
        guard can still see and the only one it ever needed to. Since
        ITACA-025c the VarFrame constructor refuses a correlation pair
        naming anything that is not a present variable, so the Dimension
        form this test used to build by dataclasses.replace is now
        unconstructible. Building through the public API tests the same
        guard against the state a caller can actually reach.
        """
        rows = [[0.0, 0.5, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["idx", "alpha", "FX", "FY", "FZ"]).pivot(
            dims=["idx"]
        )
        db = dataclasses.replace(
            db,
            vars={
                **db.vars,
                "alpha": dataclasses.replace(db.vars["alpha"], unit="rad"),
            },
        )
        db = db.set_uncertainty({c: 0.1 for c in ("FX", "FY", "FZ")})
        db = db.set_correlation({("alpha", "FX"): 0.3})
        with pytest.raises(Exception, match="OQ-26"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")


class TestReflectionRejected:
    def test_det_minus_one_rejected(self) -> None:
        from itaca.core.axes import Axis
        from itaca.core.errors import RotationMatrixError

        reflection = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]])
        with pytest.raises(RotationMatrixError, match="reflection"):
            Axis(name="bad", rotation_matrix=reflection)


class TestRotateProperties:
    @given(
        angle=st.floats(min_value=-1.4, max_value=1.4, allow_nan=False),
        u=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
    )
    def test_orthogonal_rotation_preserves_total_variance(
        self, angle: float, u: float
    ) -> None:
        # An orthogonal rotation of uncorrelated equal-sigma components
        # conserves the sum of variances (trace invariance).
        from itaca.core.axes import Axis

        c, s = np.cos(angle), np.sin(angle)
        m = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
        rows = [[0.0, 1.0, 2.0, 3.0]]
        db = itc.load(np.array(rows), names=["i", "FX", "FY", "FZ"]).pivot(dims=["i"])
        unc = UncFrame(
            systematic={c_: np.array([u]) for c_ in ("FX", "FY", "FZ")},
            random={},
        )
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .register_axis(Axis(name="rig", rotation_matrix=m))
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        assert out.uncertainty is not None
        total = sum(out.uncertainty.systematic[c_][0] ** 2 for c_ in ("FX", "FY", "FZ"))
        assert total == pytest.approx(3.0 * u**2)

    def test_zero_uncertainty_in_zero_out(self, db: VarFrame) -> None:
        from itaca.core.axes import Axis

        unc = UncFrame(
            systematic={c: np.zeros(2) for c in ("FX", "FY", "FZ")}, random={}
        )
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .register_axis(Axis(name="rig", rotation_matrix=_M90))
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        assert out.uncertainty is not None
        assert np.allclose(out.uncertainty.systematic["FX"], 0.0)


class TestImmutability:
    def test_rotate_result_read_only(self, db: VarFrame) -> None:
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            db.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        assert not out.vars["FX"].values.flags.writeable
        with pytest.raises((ValueError, RuntimeError)):
            out.vars["FX"].values[0] = 9.0


class TestPartialUncertainty:
    def test_missing_channel_still_propagates(self, db: VarFrame) -> None:
        # Only FX carries uncertainty; the rotated FY (which equals FX)
        # must still receive it, not be dropped.
        unc = UncFrame(systematic={"FX": np.full(2, 0.1)}, random={})
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            dataclasses.replace(db, uncertainty=unc)
            .register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        # FY' = FX, so u(FY') = u(FX) = 0.1.
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["FY"][0] == pytest.approx(0.1)


class TestBookkeeping:
    def test_tags_preserved(self) -> None:
        # rotation does not change origin tags (SRS 4.6).
        rows = [[0.0, np.nan, 0.0, 0.0], [1.0, 2.0, 0.0, 0.0]]
        filled = (
            itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"])
            .pivot(dims=["alpha"])
            .fill(along="alpha", method="nearest")
        )
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            filled.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        assert out.tags is not None
        # FY' = FX (tag of FX preserved onto the FY slot's source).
        assert list(out.tags.tags["FX"]) == list(filled.tags.tags["FX"])

    def test_recorded_in_history(self, db: VarFrame) -> None:
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate(
            "body", comment="to body"
        )
        assert out.history.last is not None
        assert out.history.last.operation.startswith("rotate(")
        assert out.history.last.comment == "to body"

    def test_original_untouched(self, db: VarFrame) -> None:
        rig = Axis(name="rig", rotation_matrix=_M90)
        staged = db.register_axis(rig).declare_vector("force", ["FX", "FY", "FZ"])
        staged.rotate("rig")
        assert np.allclose(staged.vars["FX"].values, [1.0, 0.0])


class TestRotateCorrelationLifecycle:
    """REV-001 ITACA-025e: rotate computed the full rotated covariance,
    kept its diagonal, and left the stale pre-rotation coefficient in
    the store. With u = (0.1, 0.2, 0.3) and rho(FX, FY) = 0.5, a 90
    degree frame gives cov(FX, FY) = -0.01, so the true coefficient is
    -0.5 and the stored one had the wrong SIGN."""

    def test_itaca_025e_rotate_recomputes_intra_group_pairs_and_keeps_others(
        self,
    ) -> None:
        """The coefficient follows the covariance; outsiders are untouched.

        rotate already built the full transformed covariance and threw
        away its off-diagonals. It is recomputed from cov_t here rather
        than dropped, which is what BRF-043's assertion asks for: for a
        linear transform the stored correlation equals the one implied
        by R C R^T.

        A pair naming no rotated component is not the rotation's
        business and survives untouched.
        """
        alpha = np.arange(2.0)
        arr = np.column_stack(
            [alpha, [1.0, 0.0], [0.0, 2.0], [0.0, 0.0], [5.0, 6.0], [7.0, 8.0]]
        )
        base = itc.load(arr, names=["alpha", "FX", "FY", "FZ", "p", "q"]).pivot(
            dims=["alpha"]
        )
        base = base.set_uncertainty({"FX": 0.1, "FY": 0.2, "FZ": 0.3})
        base = base.set_correlation({("FX", "FY"): 0.5, ("p", "q"): 0.3})

        c = np.cos(np.pi / 4.0)
        rig = Axis(
            name="rig",
            rotation_matrix=np.array([[c, -c, 0.0], [c, c, 0.0], [0.0, 0.0, 1.0]]),
        )
        out = (
            base.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )

        assert out.correlation is not None
        # Hand-checked against R C R^T for u = (0.1, 0.2, 0.3) and the
        # declared rho(FX, FY) = 0.5 under a 45 degree rotation about z.
        assert out.correlation.get("FX", "FY") == pytest.approx(-0.6546536707079771)
        assert out.correlation.get("p", "q") == 0.3

    def test_itaca_025e_rotate_flips_the_sign_the_review_measured(self) -> None:
        """The published case: +0.5 stored where the truth is -0.5.

        With u = (0.1, 0.2, 0.3) and rho(FX, FY) = 0.5, a 90 degree
        frame gives cov(FX, FY) = -0.01 and sd = (0.2, 0.1), so the true
        coefficient is -0.5. Before the fix the store still read +0.5:
        not merely stale, but wrong in SIGN.

        FZ is untouched by a rotation about z, so its pairs have an
        exactly zero transformed covariance and are absent rather than
        stored as a numerical zero.
        """
        db = _force_frame([1.0, 0.0], [0.0, 2.0], [0.0, 0.0])
        db = db.set_uncertainty({"FX": 0.1, "FY": 0.2, "FZ": 0.3})
        db = db.set_correlation({("FX", "FY"): 0.5})
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            db.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )

        assert out.uncertainty is not None
        assert out.uncertainty.systematic["FX"][0] == pytest.approx(0.2)
        assert out.uncertainty.systematic["FY"][0] == pytest.approx(0.1)
        assert out.uncertainty.systematic["FZ"][0] == pytest.approx(0.3)
        assert out.correlation is not None
        assert out.correlation.get("FX", "FY") == pytest.approx(-0.5)
        assert ("FX", "FZ") not in out.correlation.pairs
        assert ("FY", "FZ") not in out.correlation.pairs


class TestGroupAxisFollowsTheRotation:
    """REV-001 ITACA-020: the value moved and the metadata did not.

    rebuild() had no axes parameter, so the registry was carried through
    unchanged and group_axis kept naming the SOURCE. _resolve_groups
    reads that on the next call and re-applies the same transform, which
    is why a second rotate to the same target was a second rotation.
    REQ-107 already promised the recorded axis is the one the components
    are currently expressed in.
    """

    def test_itaca_020_group_axis_follows_the_rotation(self, db: VarFrame) -> None:
        """After rotate(target), the group's recorded axis IS target."""
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            db.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        assert out.axes.group_axis("force") == "rig"
        assert out.vars["FX"].values[0] == pytest.approx(0.0)
        assert out.vars["FY"].values[0] == pytest.approx(1.0)

    def test_itaca_020_second_rotate_is_not_a_double_transform(
        self, db: VarFrame
    ) -> None:
        """Rotating to the axis a group already occupies is the identity.

        Measured before the fix: the second call gave FX = -1.0, having
        applied the same 90 degree rotation twice.
        """
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            db.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        again = out.rotate("rig")
        assert again.vars["FX"].values[0] == pytest.approx(0.0)
        assert again.vars["FY"].values[0] == pytest.approx(1.0)
        assert again.axes.group_axis("force") == "rig"

        back = out.rotate("body")
        assert back.vars["FX"].values[0] == pytest.approx(1.0)
        assert back.vars["FY"].values[0] == pytest.approx(0.0)
        assert back.axes.group_axis("force") == "body"

    def test_itaca_020_auto_detected_group_is_registered(self, db: VarFrame) -> None:
        """A convention-detected group is promoted on first rotation.

        The recorded axis has to be durable, and both canonical_tokens
        (the REQ-103 state hash) and the .itc writer iterate
        vector_groups, so a group_axes entry with no vector_groups entry
        would be invisible to the hash and lost on save.
        """
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = db.register_axis(rig).rotate("rig")
        assert out.axes.vector_groups["force"] == ("FX", "FY", "FZ")
        assert out.axes.group_axis("force") == "rig"
        again = out.rotate("rig")
        assert again.vars["FX"].values[0] == pytest.approx(0.0)
        assert again.vars["FY"].values[0] == pytest.approx(1.0)

    def test_itaca_020b_declared_alias_group_is_rotated_once(
        self, db: VarFrame
    ) -> None:
        """A declared group over the default triplet is not detected twice.

        Measured before the fix: declaring 'aero' over (FX, FY, FZ) and
        rotating gave FX = -1.0 and recorded groups=['aero', 'force'],
        because the convention detector de-duplicated by NAME only and
        rotated the same three variables twice in one call.
        """
        rig = Axis(name="rig", rotation_matrix=_M90)
        out = (
            db.register_axis(rig)
            .declare_vector("aero", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        assert out.vars["FX"].values[0] == pytest.approx(0.0)
        assert out.vars["FY"].values[0] == pytest.approx(1.0)
        assert "aero" in out.history[-1].operation
        assert "force" not in out.history[-1].operation
        assert "force" not in out.axes.vector_groups

    def test_itaca_020_identity_rotation_invents_no_uncertainty(self) -> None:
        """A no-op rotate creates no UncFrame keys (DD-18).

        Measured before the fix: rotating a body group to 'body' with
        only FX carrying uncertainty materialized FY and FZ entries out
        of nothing, because the propagation ran anyway.
        """
        db = _force_frame([1.0], [0.0], [0.0]).set_uncertainty({"FX": 0.1})
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("body")
        assert out.uncertainty is not None
        assert sorted(out.uncertainty.systematic) == ["FX"]


class TestAngleOnlyUncertainty:
    """REV-001 ITACA-021: the angle term was reachable only from inside
    the branch that ran when a vector component carried uncertainty, so a
    rotation driven by a measured angle was presented as exact."""

    @staticmethod
    def _alpha_frame(component: str) -> VarFrame:
        rows = [[0.0, 30.0, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["i", "alpha", "FX", "FY", "FZ"]).pivot(
            dims=["i"]
        )
        db = dataclasses.replace(
            db,
            vars={
                **db.vars,
                "alpha": dataclasses.replace(db.vars["alpha"], unit="deg"),
            },
        )
        return db.set_uncertainty({"alpha": 1.0}, component=component)

    def test_itaca_021_angle_only_uncertainty_reaches_the_components(self) -> None:
        """u(alpha) = 1 deg on an exact vector propagates by chain rule.

        The oracle is restated as chain rule rather than as the two
        numbers the review published, so the test says WHY those are the
        values: the derivative of Ry(alpha) @ (1,0,0) has magnitude
        sin(alpha) in x and cos(alpha) in z.
        """
        db = self._alpha_frame("systematic")
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")

        u_alpha = np.deg2rad(1.0)
        expected_fx = u_alpha * np.sin(np.deg2rad(30.0))
        expected_fz = u_alpha * np.cos(np.deg2rad(30.0))
        assert out.uncertainty is not None
        systematic = out.uncertainty.systematic
        assert systematic["FX"][0] == pytest.approx(expected_fx)
        assert systematic["FZ"][0] == pytest.approx(expected_fz)
        assert systematic["FY"][0] == pytest.approx(0.0)
        # The published oracle, to the digit.
        assert systematic["FX"][0] == pytest.approx(0.008726646259971646)
        assert systematic["FZ"][0] == pytest.approx(0.015114994701951816)
        # And the central values are still the plausible-looking ones
        # that made the omission hard to notice.
        assert out.vars["FX"].values[0] == pytest.approx(0.8660254037844387)
        assert out.vars["FZ"].values[0] == pytest.approx(-0.5)

    def test_itaca_021_angle_only_random_component_stays_in_its_component(self) -> None:
        """The component index convention is pinned, not assumed."""
        db = self._alpha_frame("random")
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")
        assert out.uncertainty is not None
        assert out.uncertainty.random["FX"][0] == pytest.approx(0.008726646259971646)
        for name in ("FX", "FY", "FZ"):
            assert name not in out.uncertainty.systematic

    def test_itaca_021_no_uncertainty_anywhere_creates_no_entries(self) -> None:
        """The widened gate must not invent zeros for an exact frame."""
        rows = [[0.0, 30.0, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["i", "alpha", "FX", "FY", "FZ"]).pivot(
            dims=["i"]
        )
        db = dataclasses.replace(
            db,
            vars={
                **db.vars,
                "alpha": dataclasses.replace(db.vars["alpha"], unit="deg"),
            },
        )
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")
        assert out.uncertainty is None

    def test_itaca_025_angle_term_creates_perfect_component_correlation(self) -> None:
        """One uncertain angle driving two components correlates them fully.

        The angle covariance is rank one per angle, so its off-diagonal
        is exactly the product of the two sensitivities. Squaring it
        away, as the old diagonal-only form did, discarded precisely the
        term the write-back needs. FY has an exactly zero sensitivity,
        so its pairs are degenerate and absent rather than stored.
        """
        db = self._alpha_frame("systematic")
        out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")
        assert out.correlation is not None
        assert out.correlation.get("FX", "FZ") == pytest.approx(1.0)
        assert ("FX", "FY") not in out.correlation.pairs
        assert ("FY", "FZ") not in out.correlation.pairs


class TestUnrepresentableCoefficientRefusals:
    """REV-001 ITACA-025: the store holds ONE coefficient per pair.

    The write-back can produce a coefficient that is not representable
    three ways, and each raises. The QA pass found all three untested,
    on the path REQ-101 exists for: a per-point alpha sweep with a
    declared correlation is the canonical wind tunnel case.

    The asymmetry these pin is deliberate. A DECLARED coefficient that
    has become false corrupts every later propagation, so it raises. A
    coefficient the rotation CREATED is recorded as not stored, because
    refusing to invent one must not break the flagship case.
    """

    @staticmethod
    def _varying_frame() -> VarFrame:
        """Two cells whose uncertainties differ, so the coefficient does."""
        alpha = np.arange(2.0)
        arr = np.column_stack([alpha, [1.0, 0.0], [0.0, 2.0], [0.0, 0.0]])
        db = itc.load(arr, names=["alpha", "FX", "FY", "FZ"]).pivot(dims=["alpha"])
        unc = UncFrame(
            systematic={
                "FX": np.array([0.1, 0.3]),
                "FY": np.array([0.2, 0.2]),
                "FZ": np.array([0.3, 0.1]),
            },
            random={},
        )
        return dataclasses.replace(db, uncertainty=unc)

    @staticmethod
    def _rig() -> Axis:
        c = np.cos(np.pi / 4.0)
        return Axis(
            name="rig",
            rotation_matrix=np.array([[c, -c, 0.0], [c, c, 0.0], [0.0, 0.0, 1.0]]),
        )

    def test_itaca_025_a_cell_varying_declared_coefficient_is_refused(self) -> None:
        """One scalar cannot describe a coefficient that varies per point.

        The DECLARATION is load-bearing in this test: without it both
        cells would simply be recorded, and nothing would be refused.
        """
        base = self._varying_frame().set_correlation({("FX", "FY"): 0.5})
        with pytest.raises(UncertaintyError) as excinfo:
            (
                base.register_axis(self._rig())
                .declare_vector("force", ["FX", "FY", "FZ"])
                .rotate("rig")
            )
        message = str(excinfo.value)
        assert "one coefficient per pair" in message
        assert "'FX', 'FY'" in message
        # The fix must name an action that exists.
        assert "db.at" in message or "db.select" in message

    def test_itaca_025_a_created_coefficient_is_recorded_not_refused(self) -> None:
        """The same rotation with NO declaration must still succeed.

        This is the flagship REQ-101 case, and the asymmetry exists so
        that refusing to invent a coefficient never breaks it. The pair
        the rotation created is disclosed in the History instead.
        """
        out = (
            self._varying_frame()
            .register_axis(self._rig())
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        operation = out.history[-1].operation
        assert "correlation_not_stored=" in operation
        assert "FX" in operation and "FY" in operation

    def test_itaca_025_components_disagreeing_on_a_declared_pair_are_refused(
        self,
    ) -> None:
        """One coefficient is shared by both components (OQ-23).

        With different systematic and random uncertainties the two
        transformed covariances imply different coefficients, and the
        store cannot hold both.
        """
        alpha = np.arange(1.0)
        arr = np.column_stack([alpha, [1.0], [0.0], [0.0]])
        db = itc.load(arr, names=["alpha", "FX", "FY", "FZ"]).pivot(dims=["alpha"])
        unc = UncFrame(
            systematic={
                "FX": np.array([0.1]),
                "FY": np.array([0.2]),
                "FZ": np.array([0.3]),
            },
            random={
                "FX": np.array([0.3]),
                "FY": np.array([0.2]),
                "FZ": np.array([0.1]),
            },
        )
        base = dataclasses.replace(db, uncertainty=unc).set_correlation(
            {("FX", "FY"): 0.5}
        )
        with pytest.raises(UncertaintyError, match="OQ-23") as excinfo:
            (
                base.register_axis(self._rig())
                .declare_vector("force", ["FX", "FY", "FZ"])
                .rotate("rig")
            )
        assert "shared by both" in str(excinfo.value)

    def test_itaca_025_a_cross_group_declared_pair_is_refused(self) -> None:
        """rotate transforms the within-group block only (OQ-34).

        A pair with one foot inside the group and one outside would be
        left holding its pre-rotation coefficient, which is the same
        defect in a different place.
        """
        alpha = np.arange(2.0)
        arr = np.column_stack([alpha, [1.0, 0.0], [0.0, 2.0], [0.0, 0.0], [5.0, 6.0]])
        db = itc.load(arr, names=["alpha", "FX", "FY", "FZ", "q"]).pivot(dims=["alpha"])
        db = db.set_uncertainty({"FX": 0.1, "FY": 0.2, "FZ": 0.3, "q": 0.4})
        db = db.set_correlation({("FX", "q"): 0.4})
        with pytest.raises(UncertaintyError, match="OQ-34") as excinfo:
            (
                db.register_axis(self._rig())
                .declare_vector("force", ["FX", "FY", "FZ"])
                .rotate("rig")
            )
        assert "outside its group" in str(excinfo.value)
        # The fix names a verb that now exists.
        assert "drop the pair" in str(excinfo.value)

    def test_itaca_025_drop_correlation_makes_the_refusals_escapable(self) -> None:
        """The refusals prescribe dropping, so dropping must be possible.

        Before `db.drop_correlation`, every one of these messages named
        an action with no implementation: `set_correlation` merges and
        can only add or overwrite. This is the test that ties the
        refusal to its remedy.
        """
        base = self._varying_frame().set_correlation({("FX", "FY"): 0.5})
        out = (
            base.drop_correlation(["FX"])
            .register_axis(self._rig())
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("rig")
        )
        assert "correlation_not_stored=" in out.history[-1].operation
