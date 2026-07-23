"""Tests for db.translate_moments (REQ-100).

Usage example (TDD anchor)::

    import itaca as itc
    db = db.declare_vector("force", ["FX", "FY", "FZ"])
    db = db.declare_vector("moment", ["MX", "MY", "MZ"])
    moved = db.translate_moments(to_point=[0.1, 0.0, 0.0])

Transfers every declared moment group between reference points via
M' = M + r x F with r = from_point - to_point (the standard rigid
transfer M_B = M_A + (r_A - r_B) x F). The Jacobian [skew(r) | I] is
exact; force-moment covariance is included when declared. Expected
uncertainties are recomputed here by explicit J Cov J^T algebra.
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.correlation import CorrelationMatrix
from itaca.core.errors import VectorGroupError
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _skew(r: np.ndarray) -> np.ndarray:
    return np.array([[0.0, -r[2], r[1]], [r[2], 0.0, -r[0]], [-r[1], r[0], 0.0]])


def _balance(
    fx: float, fy: float, fz: float, mx: float, my: float, mz: float
) -> VarFrame:
    rows = [[0.0, fx, fy, fz, mx, my, mz]]
    return itc.load(
        np.array(rows), names=["idx", "FX", "FY", "FZ", "MX", "MY", "MZ"]
    ).pivot(dims=["idx"])


@pytest.fixture
def db() -> VarFrame:
    return _balance(1.0, 2.0, 3.0, 0.0, 0.0, 0.0)


def _declared(db: VarFrame) -> VarFrame:
    return db.declare_vector("force", ["FX", "FY", "FZ"]).declare_vector(
        "moment", ["MX", "MY", "MZ"]
    )


class TestTransfer:
    def test_offset_adds_r_cross_f(self, db: VarFrame) -> None:
        # r = from(0) - to(0.1,0,0) = (-0.1,0,0); r x F with F=(1,2,3).
        out = _declared(db).translate_moments(to_point=[0.1, 0.0, 0.0])
        r = np.array([-0.1, 0.0, 0.0])
        expected = np.cross(r, np.array([1.0, 2.0, 3.0]))
        assert out.vars["MX"].values[0] == pytest.approx(expected[0])
        assert out.vars["MY"].values[0] == pytest.approx(expected[1])
        assert out.vars["MZ"].values[0] == pytest.approx(expected[2])

    def test_zero_offset_is_identity(self, db: VarFrame) -> None:
        moved = _declared(db).translate_moments(to_point=[0.0, 0.0, 0.0])
        assert np.allclose(moved.vars["MX"].values, db.vars["MX"].values)

    def test_explicit_from_point(self) -> None:
        db = _declared(_balance(1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        out = db.translate_moments(to_point=[0.0, 0.0, 0.0], from_point=[0.0, 1.0, 0.0])
        # r = (0,1,0) - (0,0,0) = (0,1,0); r x F, F=(1,0,0): (0,0,-1).
        assert out.vars["MZ"].values[0] == pytest.approx(-1.0)

    def test_adds_to_existing_moment(self) -> None:
        db = _declared(_balance(1.0, 2.0, 3.0, 10.0, 20.0, 30.0))
        out = db.translate_moments(to_point=[0.1, 0.0, 0.0])
        r = np.array([-0.1, 0.0, 0.0])
        expected = np.array([10.0, 20.0, 30.0]) + np.cross(r, np.array([1.0, 2.0, 3.0]))
        assert out.vars["MY"].values[0] == pytest.approx(expected[1])


class TestValidation:
    def test_requires_force_group(self) -> None:
        rows = [[0.0, 1.0, 2.0, 3.0]]
        db = itc.load(np.array(rows), names=["idx", "MX", "MY", "MZ"]).pivot(
            dims=["idx"]
        )
        with pytest.raises(VectorGroupError, match="force"):
            db.declare_vector("moment", ["MX", "MY", "MZ"]).translate_moments(
                to_point=[0.1, 0.0, 0.0]
            )

    def test_requires_moment_group(self) -> None:
        rows = [[0.0, 1.0, 2.0, 3.0]]
        db = itc.load(np.array(rows), names=["idx", "FX", "FY", "FZ"]).pivot(
            dims=["idx"]
        )
        with pytest.raises(VectorGroupError, match="moment"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).translate_moments(
                to_point=[0.1, 0.0, 0.0]
            )

    def test_bad_point_length_rejected(self, db: VarFrame) -> None:
        with pytest.raises(Exception, match="three"):
            _declared(db).translate_moments(to_point=[0.1, 0.0])


class TestUncertainty:
    def test_jacobian_with_force_moment_covariance(self) -> None:
        db = _declared(_balance(1.0, 2.0, 3.0, 0.0, 0.0, 0.0))
        names = ["FX", "FY", "FZ", "MX", "MY", "MZ"]
        u = np.array([0.1, 0.1, 0.1, 0.2, 0.2, 0.2])
        unc = UncFrame(
            systematic={n: np.array([u[i]]) for i, n in enumerate(names)},
            random={},
        )
        # Declare a force-moment cross correlation so it enters the
        # transfer covariance.
        corr = CorrelationMatrix(pairs={("FY", "MZ"): 0.4})
        base = dataclasses.replace(db, uncertainty=unc, correlation=corr)
        to_point = [0.1, 0.0, 0.0]
        out = base.translate_moments(to_point=to_point)

        r = np.array([-0.1, 0.0, 0.0])
        jac = np.hstack([_skew(r), np.eye(3)])  # 3x6, M' = [S | I] @ [F; M]
        corr6 = np.eye(6)
        corr6[1, 5] = corr6[5, 1] = 0.4  # FY (idx 1) - MZ (idx 5)
        cov6 = (u[:, None] * u[None, :]) * corr6
        cov_m = jac @ cov6 @ jac.T
        expected = np.sqrt(np.diag(cov_m))
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["MX"][0] == pytest.approx(expected[0])
        assert out.uncertainty.systematic["MZ"][0] == pytest.approx(expected[2])


class TestDeclaredGroups:
    def test_honors_declared_force_moment_frames(self) -> None:
        from itaca.core.axes import Axis

        db = _balance(1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
        rig = Axis(name="rig", rotation_matrix=np.eye(3))
        staged = (
            db.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"], frame="rig")
            .declare_vector("moment", ["MX", "MY", "MZ"], frame="rig")
        )
        out = staged.translate_moments(to_point=[0.1, 0.0, 0.0])
        r = np.array([-0.1, 0.0, 0.0])
        expected = np.cross(r, np.array([1.0, 2.0, 3.0]))
        assert out.vars["MY"].values[0] == pytest.approx(expected[1])

    def test_mismatched_frames_rejected(self) -> None:
        from itaca.core.axes import Axis
        from itaca.core.errors import DataError

        db = _balance(1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
        rig = Axis(name="rig", rotation_matrix=np.eye(3))
        staged = (
            db.register_axis(rig)
            .declare_vector("force", ["FX", "FY", "FZ"], frame="rig")
            .declare_vector("moment", ["MX", "MY", "MZ"], frame="body")
        )
        with pytest.raises(DataError, match="same frame"):
            staged.translate_moments(to_point=[0.1, 0.0, 0.0])

    def test_mismatched_offset_frame_rejected(self, db: VarFrame) -> None:
        from itaca.core.errors import DataError

        with pytest.raises(DataError, match="offset"):
            _declared(db).translate_moments(to_point=[0.1, 0.0, 0.0], frame="stability")


class TestPartialAndRandom:
    def test_random_component_propagates(self) -> None:
        db = _declared(_balance(1.0, 2.0, 3.0, 0.0, 0.0, 0.0))
        names = ["FX", "FY", "FZ", "MX", "MY", "MZ"]
        u = np.array([0.1, 0.1, 0.1, 0.2, 0.2, 0.2])
        unc = UncFrame(
            systematic={},
            random={n: np.array([u[i]]) for i, n in enumerate(names)},
        )
        out = dataclasses.replace(db, uncertainty=unc).translate_moments(
            to_point=[0.1, 0.0, 0.0]
        )
        r = np.array([-0.1, 0.0, 0.0])
        jac = np.hstack([_skew(r), np.eye(3)])
        cov6 = np.diag(u**2)
        expected = np.sqrt(np.diag(jac @ cov6 @ jac.T))
        assert out.uncertainty is not None
        assert out.uncertainty.random["MZ"][0] == pytest.approx(expected[2])

    def test_force_only_uncertainty_reaches_moment(self) -> None:
        # Force carries uncertainty, moment channels do not; the
        # transferred moment must still receive the r x F contribution.
        db = _declared(_balance(1.0, 2.0, 3.0, 0.0, 0.0, 0.0))
        unc = UncFrame(
            systematic={c: np.array([0.1]) for c in ("FX", "FY", "FZ")},
            random={},
        )
        out = dataclasses.replace(db, uncertainty=unc).translate_moments(
            to_point=[0.0, 0.1, 0.0]
        )
        r = np.array([0.0, -0.1, 0.0])
        jac = np.hstack([_skew(r), np.eye(3)])
        u6 = np.array([0.1, 0.1, 0.1, 0.0, 0.0, 0.0])
        expected = np.sqrt(np.diag(jac @ np.diag(u6**2) @ jac.T))
        assert out.uncertainty is not None
        assert out.uncertainty.systematic["MX"][0] == pytest.approx(expected[0])

    def test_result_read_only(self, db: VarFrame) -> None:
        out = _declared(db).translate_moments(to_point=[0.1, 0.0, 0.0])
        assert not out.vars["MX"].values.flags.writeable
        with pytest.raises((ValueError, RuntimeError)):
            out.vars["MX"].values[0] = 9.0


class TestBookkeeping:
    def test_force_unchanged(self, db: VarFrame) -> None:
        out = _declared(db).translate_moments(to_point=[0.1, 0.0, 0.0])
        assert out.vars["FX"].values[0] == pytest.approx(1.0)

    def test_recorded_in_history(self, db: VarFrame) -> None:
        out = _declared(db).translate_moments(to_point=[0.1, 0.0, 0.0], comment="to CG")
        assert out.history.last is not None
        assert out.history.last.operation.startswith("translate_moments(")
        assert out.history.last.comment == "to CG"

    def test_original_untouched(self, db: VarFrame) -> None:
        staged = _declared(db)
        staged.translate_moments(to_point=[0.1, 0.0, 0.0])
        assert staged.vars["MX"].values[0] == pytest.approx(0.0)
