"""Tests for accessor registration (REQ-106).

Usage example (TDD anchor)::

    import itaca as itc

    @itc.register_accessor("campaign")
    class CampaignAccessor:
        def __init__(self, db):
            self._db = db
        def n_points(self):
            return int(np.prod(self._db.shape))

    db.campaign.n_points()

Registering a name that collides with an existing attribute or another
accessor raises at registration time (REQ-106). An AttributeError
escaping the accessor's __init__ is re-raised as RuntimeError so the
attribute machinery never swallows a real defect. The registry
supports snapshot and restore for tests (autouse fixture below).
"""

import numpy as np
import pytest

import itaca as itc
from itaca.core import accessors
from itaca.core.errors import AccessorRegistrationError
from itaca.core.varframe import VarFrame


@pytest.fixture(autouse=True)
def _reset_accessors():  # type: ignore[no-untyped-def]
    snapshot = accessors.snapshot()
    yield
    accessors.restore(snapshot)


def _frame() -> VarFrame:
    rows = [[0.0, 1.0], [1.0, 2.0]]
    return itc.load(np.array(rows), names=["alpha", "CT"]).pivot(dims=["alpha"])


class TestRegistration:
    def test_registers_and_accesses(self) -> None:
        @itc.register_accessor("campaign")
        class Campaign:
            def __init__(self, db: VarFrame) -> None:
                self._db = db

            def n_points(self) -> int:
                return int(np.prod(self._db.shape))

        assert _frame().campaign.n_points() == 2  # type: ignore[attr-defined]

    def test_cached_per_instance(self) -> None:
        @itc.register_accessor("cache_probe")
        class Probe:
            def __init__(self, db: VarFrame) -> None:
                self._db = db

        db = _frame()
        assert db.cache_probe is db.cache_probe  # type: ignore[attr-defined]

    def test_separate_instances_get_separate_accessors(self) -> None:
        @itc.register_accessor("probe2")
        class Probe:
            def __init__(self, db: VarFrame) -> None:
                self._db = db

        a, b = _frame(), _frame()
        assert a.probe2 is not b.probe2  # type: ignore[attr-defined]

    def test_accessor_sees_the_frame(self) -> None:
        @itc.register_accessor("peek")
        class Peek:
            def __init__(self, db: VarFrame) -> None:
                self._db = db

            def first_ct(self) -> float:
                return float(self._db.vars["CT"].values[0])

        assert _frame().peek.first_ct() == 1.0  # type: ignore[attr-defined]


class TestCollisions:
    def test_existing_attribute_collision_rejected(self) -> None:
        with pytest.raises(AccessorRegistrationError, match="rotate"):

            @itc.register_accessor("rotate")
            class Bad:
                def __init__(self, db: VarFrame) -> None:
                    self._db = db

    def test_non_identifier_name_rejected(self) -> None:
        with pytest.raises(AccessorRegistrationError, match="identifier"):

            @itc.register_accessor("not an identifier")
            class Bad:
                def __init__(self, db: VarFrame) -> None:
                    self._db = db

    def test_duplicate_accessor_rejected(self) -> None:
        @itc.register_accessor("dup")
        class First:
            def __init__(self, db: VarFrame) -> None:
                self._db = db

        with pytest.raises(AccessorRegistrationError, match="already"):

            @itc.register_accessor("dup")
            class Second:
                def __init__(self, db: VarFrame) -> None:
                    self._db = db


class TestErrorTrap:
    def test_attribute_error_in_init_becomes_runtime_error(self) -> None:
        @itc.register_accessor("broken")
        class Broken:
            def __init__(self, db: VarFrame) -> None:
                raise AttributeError("real defect in the accessor")

        db = _frame()
        with pytest.raises(RuntimeError) as exc:
            _ = db.broken  # type: ignore[attr-defined]
        assert isinstance(exc.value.__cause__, AttributeError)
        assert "real defect" in str(exc.value.__cause__)


class TestSnapshotRestore:
    def test_restore_removes_registered(self) -> None:
        snapshot = accessors.snapshot()

        @itc.register_accessor("temporary")
        class Temp:
            def __init__(self, db: VarFrame) -> None:
                self._db = db

        assert hasattr(VarFrame, "temporary")
        accessors.restore(snapshot)
        assert not hasattr(VarFrame, "temporary")

    def test_restore_readds_dropped(self) -> None:
        @itc.register_accessor("keeper")
        class Keeper:
            def __init__(self, db: VarFrame) -> None:
                self._db = db

        snapshot = accessors.snapshot()
        # Drop it, then restore should re-add it from the snapshot.
        accessors.restore({})
        assert not hasattr(VarFrame, "keeper")
        accessors.restore(snapshot)
        assert hasattr(VarFrame, "keeper")
        assert "keeper" in accessors.snapshot()
