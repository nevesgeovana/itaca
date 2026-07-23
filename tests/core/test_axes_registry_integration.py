"""VarFrame integration of the axis registry (REQ-38, REQ-103, REQ-107).

Usage example (TDD anchor)::

    import itaca as itc
    import numpy as np
    db = itc.load(arr, names=["alpha", "FX", "FY", "FZ"]).pivot(dims=["alpha"])
    db = db.register_axis(Axis(name="rig", rotation_matrix=np.eye(3)))
    db = db.declare_vector("aero_force", ["FX", "FY", "FZ"], axis="rig")

Registering a frame or declaring a vector group returns a new VarFrame,
records History, and changes the state hash (axes are part of the
REQ-103 state, like correlation). The source frame defaults to the
canonical body axis when omitted (REQ-107).
"""

import numpy as np
import pytest

import itaca as itc
from itaca.core.axes import Axis
from itaca.core.errors import AxisNotFoundError, VectorGroupError
from itaca.core.varframe import VarFrame


def _frame() -> VarFrame:
    rows = [[a, a, 2.0 * a, 3.0 * a] for a in (0.0, 1.0, 2.0)]
    return itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
        dims=["alpha"]
    )


@pytest.fixture
def db() -> VarFrame:
    return _frame()


class TestRegisterAxis:
    def test_registers_and_returns_new(self, db: VarFrame) -> None:
        rig = Axis(name="rig", rotation_matrix=np.eye(3))
        out = db.register_axis(rig)
        assert out is not db
        assert out.axes.resolve("rig") is rig
        assert "rig" not in db.axes.axes

    def test_builtins_available_without_registration(self, db: VarFrame) -> None:
        # body, stability, wind resolve out of the box.
        assert db.axes.resolve("body").is_constant
        assert not db.axes.resolve("wind").is_constant

    def test_changes_state_hash(self, db: VarFrame) -> None:
        # REQ-103: axes are part of the state (like correlation).
        before = db.state_hash
        after = db.register_axis(Axis(name="rig", rotation_matrix=np.eye(3)))
        assert after.state_hash != before

    def test_recorded_in_history(self, db: VarFrame) -> None:
        out = db.register_axis(
            Axis(name="rig", rotation_matrix=np.eye(3)), comment="rig frame"
        )
        assert out.history.last is not None
        assert out.history.last.operation.startswith("register_axis(")
        assert out.history.last.comment == "rig frame"


class TestDeclareVector:
    def test_declares_group_with_frame(self, db: VarFrame) -> None:
        out = db.register_axis(
            Axis(name="rig", rotation_matrix=np.eye(3))
        ).declare_vector("aero_force", ["FX", "FY", "FZ"], axis="rig")
        assert out.axes.vector_groups["aero_force"] == ("FX", "FY", "FZ")

    def test_frame_defaults_to_body(self, db: VarFrame) -> None:
        # REQ-107: an omitted frame is the canonical body axis.
        out = db.declare_vector("aero_force", ["FX", "FY", "FZ"])
        assert out.axes.group_axis("aero_force") == "body"

    def test_source_frame_recorded(self, db: VarFrame) -> None:
        out = db.register_axis(
            Axis(name="rig", rotation_matrix=np.eye(3))
        ).declare_vector("aero_force", ["FX", "FY", "FZ"], axis="rig")
        assert out.axes.group_axis("aero_force") == "rig"

    def test_unknown_source_frame_rejected(self, db: VarFrame) -> None:
        # REQ-107: a group in an unregistered frame raises.
        with pytest.raises(AxisNotFoundError, match="tunnel"):
            db.declare_vector("aero_force", ["FX", "FY", "FZ"], axis="tunnel")

    def test_unknown_component_rejected(self, db: VarFrame) -> None:
        with pytest.raises(VectorGroupError, match="MZ"):
            db.declare_vector("moment", ["MX", "MY", "MZ"])

    def test_changes_state_hash(self, db: VarFrame) -> None:
        before = db.state_hash
        after = db.declare_vector("aero_force", ["FX", "FY", "FZ"])
        assert after.state_hash != before

    def test_recorded_in_history(self, db: VarFrame) -> None:
        out = db.declare_vector("aero_force", ["FX", "FY", "FZ"], comment="balance")
        assert out.history.last is not None
        assert out.history.last.operation.startswith("declare_vector(")
        assert out.history.last.comment == "balance"


class TestAxesPersistence:
    def test_round_trip_through_itc(self, db: VarFrame, tmp_path) -> None:  # type: ignore[no-untyped-def]
        rig = Axis(
            name="rig",
            rotation_matrix=np.array(
                [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
            ),
        )
        original = db.register_axis(rig).declare_vector(
            "aero_force", ["FX", "FY", "FZ"], axis="rig"
        )
        path = original.save(tmp_path / "frames.itc")
        reopened = itc.open(path)
        assert np.allclose(
            reopened.axes.resolve("rig").matrix_at({}), rig.matrix_at({})
        )
        assert reopened.axes.vector_groups["aero_force"] == ("FX", "FY", "FZ")
        assert reopened.axes.group_axis("aero_force") == "rig"
        assert reopened.state_hash == original.state_hash
