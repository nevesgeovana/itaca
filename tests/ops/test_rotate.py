"""Tests for db.rotate (REQ-38, REQ-101).

Usage example (TDD anchor)::

    import itaca as itc
    db = db.declare_vector("force", ["FX", "FY", "FZ"], frame="rig")
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

import itaca as itc
from itaca.core.axes import Axis
from itaca.core.correlation import CorrelationMatrix
from itaca.core.errors import AxisNotFoundError, DataError, VectorGroupError
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
            "force", ["FX", "FY", "FZ"], frame="rig"
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
            .declare_vector("force", ["FX", "FY", "FZ"], frame="stability")
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
