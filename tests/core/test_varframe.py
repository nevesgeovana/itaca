"""Tests for the VarFrame core structure (SRS 4.1; DD-03, REQ-18, REQ-102).

Usage example (the contract under test)::

    from itaca.core.dimension import Dimension
    from itaca.core.variable import Variable
    from itaca.core.varframe import VarFrame

    db = VarFrame(
        dims={"alpha": alpha, "mach": mach},
        vars={"CT": ct},
        provenance=prov,
    )
    db2 = db.demote(comment="exploring")     # new object, original intact
"""

import dataclasses

import numpy as np
import pytest

from itaca.core.coords import Cartesian
from itaca.core.correlation import CorrelationMatrix
from itaca.core.dimension import Dimension
from itaca.core.errors import (
    CorrelationKeyError,
    DataError,
    ProvenanceError,
    UncertaintyError,
    UncertaintyKeyError,
)
from itaca.core.historyframe import HistoryFrame
from itaca.core.provenance import Provenance
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable


@pytest.fixture
def frame(prov: Provenance) -> VarFrame:
    alpha = Dimension(name="alpha", coords=np.array([0.0, 2.0, 4.0]), unit="deg")
    mach = Dimension(name="mach", coords=np.array([0.1, 0.2]))
    ct = Variable(name="CT", values=np.arange(6.0).reshape(3, 2))
    return VarFrame(
        dims={"alpha": alpha, "mach": mach}, vars={"CT": ct}, provenance=prov
    )


class TestConstruction:
    def test_basic_attributes(self, frame: VarFrame) -> None:
        assert frame.shape == (3, 2)
        assert frame.mode == "production"
        assert frame.uncertainty is None
        assert frame.tags is None
        assert frame.correlation is None
        assert isinstance(frame.coords, Cartesian)
        assert len(frame.history) == 0

    def test_empty_varframe(self, prov: Provenance) -> None:
        # REQ-76 Load edge case: the empty VarFrame is constructible.
        db = VarFrame(dims={}, vars={}, provenance=prov)
        assert db.shape == ()
        assert db.state_hash

    def test_shape_mismatch_rejected(self, prov: Provenance) -> None:
        alpha = Dimension(name="alpha", coords=np.array([0.0, 2.0, 4.0]))
        bad = Variable(name="CT", values=np.zeros((2,)))
        with pytest.raises(DataError):
            VarFrame(dims={"alpha": alpha}, vars={"CT": bad}, provenance=prov)

    def test_key_name_mismatch_rejected(self, prov: Provenance) -> None:
        alpha = Dimension(name="alpha", coords=np.array([0.0]))
        ct = Variable(name="CT", values=np.zeros((1,)))
        with pytest.raises(DataError):
            VarFrame(dims={"beta": alpha}, vars={"CT": ct}, provenance=prov)

    def test_uncertainty_unknown_variable_rejected(self, prov: Provenance) -> None:
        alpha = Dimension(name="alpha", coords=np.array([0.0]))
        ct = Variable(name="CT", values=np.zeros((1,)))
        unc = UncFrame(systematic={"CP": np.zeros((1,))})
        with pytest.raises(UncertaintyKeyError):
            VarFrame(
                dims={"alpha": alpha},
                vars={"CT": ct},
                provenance=prov,
                uncertainty=unc,
            )

    def test_uncertainty_shape_mismatch_rejected(self, prov: Provenance) -> None:
        alpha = Dimension(name="alpha", coords=np.array([0.0, 1.0]))
        ct = Variable(name="CT", values=np.zeros((2,)))
        unc = UncFrame(systematic={"CT": np.zeros((3,))})
        with pytest.raises(UncertaintyError):
            VarFrame(
                dims={"alpha": alpha},
                vars={"CT": ct},
                provenance=prov,
                uncertainty=unc,
            )

    def test_variable_key_name_mismatch_rejected(self, prov: Provenance) -> None:
        alpha = Dimension(name="alpha", coords=np.array([0.0]))
        ct = Variable(name="CT", values=np.zeros((1,)))
        with pytest.raises(DataError):
            VarFrame(dims={"alpha": alpha}, vars={"CP": ct}, provenance=prov)

    def test_tags_shape_mismatch_rejected(self, prov: Provenance) -> None:
        alpha = Dimension(name="alpha", coords=np.array([0.0, 1.0]))
        ct = Variable(name="CT", values=np.zeros((2,)))
        tags = HistoryFrame(tags={"CT": np.zeros((3,), dtype=np.int8)})
        with pytest.raises(DataError):
            VarFrame(
                dims={"alpha": alpha},
                vars={"CT": ct},
                provenance=prov,
                tags=tags,
            )

    def test_tags_unknown_variable_rejected(self, prov: Provenance) -> None:
        alpha = Dimension(name="alpha", coords=np.array([0.0]))
        ct = Variable(name="CT", values=np.zeros((1,)))
        tags = HistoryFrame(tags={"CP": np.zeros((1,), dtype=np.int8)})
        with pytest.raises(DataError):
            VarFrame(
                dims={"alpha": alpha},
                vars={"CT": ct},
                provenance=prov,
                tags=tags,
            )


class TestImmutability:
    def test_frozen_dataclass(self, frame: VarFrame) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            frame.mode_x = 1  # type: ignore[attr-defined]

    def test_stored_arrays_read_only(self, frame: VarFrame) -> None:
        # REQ-102: db.vars["CT"].values[0] = 99 must raise.
        with pytest.raises(ValueError, match="read-only"):
            frame.vars["CT"].values[0, 0] = 99.0

    def test_mappings_read_only(self, frame: VarFrame) -> None:
        with pytest.raises(TypeError):
            frame.vars["new"] = frame.vars["CT"]  # type: ignore[index]
        with pytest.raises(TypeError):
            frame.dims["new"] = frame.dims["alpha"]  # type: ignore[index]


class TestModes:
    def test_demote_promote_round_trip_preserves_data(self, frame: VarFrame) -> None:
        # REQ-76 Modes edge case: promote/demote round trip preserves data.
        draft = frame.demote(comment="exploring")
        assert draft.mode == "draft"
        assert frame.mode == "production"
        back = draft.promote()
        assert back.mode == "production"
        assert np.array_equal(back.vars["CT"].values, frame.vars["CT"].values)

    def test_mode_transitions_recorded_in_history(self, frame: VarFrame) -> None:
        draft = frame.demote()
        assert len(draft.history) == 1
        assert draft.history.last is not None
        assert "demote" in draft.history.last.operation
        back = draft.promote(comment="validated")
        assert back.history.last is not None
        assert "promote" in back.history.last.operation
        assert back.history.last.comment == "validated"

    def test_history_hash_matches_state(self, frame: VarFrame) -> None:
        draft = frame.demote()
        assert draft.history.last is not None
        assert draft.history.last.state_hash == draft.state_hash

    def test_same_mode_transition_rejected(self, frame: VarFrame) -> None:
        # No silent no-ops (house rule; DD-16 instinct).
        with pytest.raises(ProvenanceError):
            frame.promote()

    def test_draft_clearly_identified_in_print(self, frame: VarFrame) -> None:
        # REQ-10: draft VarFrames are clearly identified by print(db).
        assert "draft" in str(frame.demote()).lower()
        assert "production" in str(frame).lower()


class TestStateHash:
    def test_hash_excludes_provenance_volatiles(
        self, frame: VarFrame, prov: Provenance
    ) -> None:
        # REQ-103: user identity and timestamps do not enter the hash.
        other_prov = dataclasses.replace(prov, user="someone-else@elsewhere")
        twin = VarFrame(
            dims=dict(frame.dims), vars=dict(frame.vars), provenance=other_prov
        )
        assert twin.state_hash == frame.state_hash

    def test_hash_sensitive_to_values(self, frame: VarFrame, prov: Provenance) -> None:
        other = VarFrame(
            dims=dict(frame.dims),
            vars={"CT": Variable(name="CT", values=np.ones((3, 2)))},
            provenance=prov,
        )
        assert other.state_hash != frame.state_hash

    def test_hash_sensitive_to_uncertainty(self, frame: VarFrame) -> None:
        with_unc = VarFrame(
            dims=dict(frame.dims),
            vars=dict(frame.vars),
            provenance=frame.provenance,
            uncertainty=UncFrame(systematic={"CT": np.full((3, 2), 0.01)}),
        )
        assert with_unc.state_hash != frame.state_hash


class TestCorrelationConstructorInvariant:
    """REV-001 ITACA-025c: the UncFrame had this invariant and the
    CorrelationMatrix did not, so the identical defect failed loud on
    one mirror and was silent on the other."""

    def test_itaca_025_constructor_refuses_pair_naming_absent_variable(
        self, frame: VarFrame
    ) -> None:
        """A pair may not name something the frame does not carry.

        This is what makes a forgotten per-operation policy impossible
        rather than merely unlikely: an operation that drops or renames
        a variable and does not drop its pairs now fails here, at the
        first construction, including an operation added later.
        """
        with pytest.raises(CorrelationKeyError) as excinfo:
            dataclasses.replace(
                frame,
                correlation=CorrelationMatrix(pairs={("CT", "ghost"): 0.5}),
            )
        message = str(excinfo.value)
        assert "'CT', 'ghost'" in message
        assert "'ghost'" in message
        assert "['CT'" in message  # the available variables are listed

    def test_itaca_025_constructor_accepts_pair_over_present_variables(
        self, frame: VarFrame, prov: Provenance
    ) -> None:
        """The happy path still constructs.

        The `frame` fixture carries only CT, so a second variable is
        added here rather than widening a fixture every other test in
        this module depends on.
        """
        second = Variable(name="CP", values=np.ones((3, 2)))
        widened = dataclasses.replace(frame, vars={**frame.vars, "CP": second})
        out = dataclasses.replace(
            widened, correlation=CorrelationMatrix(pairs={("CT", "CP"): 0.5})
        )
        assert out.correlation is not None
        assert out.correlation.get("CT", "CP") == 0.5
