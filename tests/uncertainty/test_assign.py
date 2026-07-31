"""Tests for db.set_uncertainty (REQ-39, REQ-99) and db.set_correlation
(REQ-40).
"""

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    CorrelationKeyError,
    CorrelationMatrixError,
    UncertaintyError,
    UncertaintyKeyError,
)
from itaca.core.varframe import VarFrame


@pytest.fixture
def db() -> VarFrame:
    arr = np.column_stack([np.array([10.0, 20.0]), np.array([1.0, 2.0])])
    return itc.load(arr, names=["FZ", "V"])


class TestSetUncertainty:
    def test_absolute_creates_uncframe_lazily(self, db: VarFrame) -> None:
        assert db.uncertainty is None  # REQ-91
        result = db.set_uncertainty({"FZ": 0.005})
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["FZ"], 0.005)
        assert db.uncertainty is None  # original untouched

    def test_relative_percent(self, db: VarFrame) -> None:
        # REQ-39: string ending in percent is relative.
        result = db.set_uncertainty({"FZ": "10%"})
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["FZ"], [1.0, 2.0])

    def test_random_component(self, db: VarFrame) -> None:
        # REQ-99: component="random" fills the second component.
        result = db.set_uncertainty({"V": 0.02}, component="random")
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.random["V"], 0.02)
        assert "V" not in result.uncertainty.systematic

    def test_merges_with_existing(self, db: VarFrame) -> None:
        result = db.set_uncertainty({"FZ": 0.005}).set_uncertainty(
            {"V": 0.02}, component="random"
        )
        assert result.uncertainty is not None
        assert "FZ" in result.uncertainty.systematic
        assert "V" in result.uncertainty.random

    def test_unknown_key_rejected(self, db: VarFrame) -> None:
        with pytest.raises(UncertaintyKeyError):
            db.set_uncertainty({"missing": 0.1})

    def test_invalid_component_rejected(self, db: VarFrame) -> None:
        with pytest.raises(UncertaintyError):
            db.set_uncertainty({"FZ": 0.1}, component="bias")

    def test_invalid_percent_rejected(self, db: VarFrame) -> None:
        with pytest.raises(UncertaintyError):
            db.set_uncertainty({"FZ": "0.05"})

    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.set_uncertainty({"FZ": 0.005}, comment="balance cal")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("set_uncertainty(")
        assert result.history.last.comment == "balance cal"


class TestRelativeSpecResolution:
    """FND-040: a valid spec must not resolve to an invalid uncertainty.

    The refusal is at the DECLARATION boundary and on the resolved array
    only. It is deliberately not the finiteness rule on the assembled
    UncFrame that OQ-40 asks about: `compute(where=)` writes NaN into that
    array on purpose, so the rule there cannot be added until the two
    meanings of NaN are distinguishable, and this one does not need it.
    """

    @staticmethod
    def _with(values: list[float]) -> VarFrame:
        return itc.load(np.array(values).reshape(-1, 1), names=["x"])

    @pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
    def test_relative_spec_over_non_finite_data_is_refused(self, bad: float) -> None:
        with pytest.raises(UncertaintyError) as raised:
            self._with([1.0, bad]).set_uncertainty({"x": "5%"})
        message = str(raised.value)
        assert "5%" in message
        assert "'x'" in message

    def test_the_refusal_names_the_object_the_cause_and_the_fix(self) -> None:
        """REQ-81's three parts, on the part a caller can act on.

        The count matters: a caller reading "1 of 2" knows the variable is
        partly populated and that filling is the remedy, where a bare
        "not finite" reads as a broken declaration.
        """
        with pytest.raises(UncertaintyError) as raised:
            self._with([1.0, np.nan]).set_uncertainty({"x": "5%"})
        message = str(raised.value)
        assert "1 of 2" in message
        assert "REQ-39" in message

    def test_an_absolute_spec_over_the_same_data_is_still_accepted(self) -> None:
        """The refusal is about RESOLUTION, not about the data.

        An absolute magnitude does not read the values at all, so a
        variable with a hole still takes one. Without this the fix would
        be a ban on declaring uncertainty over sparse data, which is not
        what REQ-39 says and not what was measured.
        """
        result = self._with([1.0, np.nan]).set_uncertainty({"x": 0.5})
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["x"], 0.5)

    def test_a_relative_spec_over_finite_data_is_unchanged(self) -> None:
        result = self._with([1.0, 2.0]).set_uncertainty({"x": "5%"})
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["x"], [0.05, 0.1])


class TestSetCorrelation:
    def test_declares_pairs(self, db: VarFrame) -> None:
        assert db.correlation is None  # REQ-91
        result = db.set_correlation({("FZ", "V"): 0.3})
        assert result.correlation is not None
        assert result.correlation.get("V", "FZ") == 0.3

    def test_merge_overrides_pair(self, db: VarFrame) -> None:
        result = db.set_correlation({("FZ", "V"): 0.3}).set_correlation(
            {("V", "FZ"): 0.5}
        )
        assert result.correlation is not None
        assert result.correlation.get("FZ", "V") == 0.5

    def test_unknown_variable_rejected(self, db: VarFrame) -> None:
        with pytest.raises(CorrelationKeyError):
            db.set_correlation({("FZ", "missing"): 0.3})

    def test_invalid_coefficient_rejected(self, db: VarFrame) -> None:
        with pytest.raises(CorrelationMatrixError):
            db.set_correlation({("FZ", "V"): 1.5})

    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.set_correlation({("FZ", "V"): 0.3})
        assert result.history.last is not None
        assert result.history.last.operation.startswith("set_correlation(")


class TestCorrelationDeclarationValidity:
    """REV-001 ITACA-001a and ITACA-028, both reached through the public
    API: canonicalizing before validating hid two different defects."""

    def test_itaca_001_set_correlation_refuses_non_psd_merge(self) -> None:
        """The check applies to the ACCUMULATED store, not to one call.

        No single call here declares anything out of range; the third
        one completes a triple whose assembled matrix has eigenvalue
        1 + 2r = -0.2. Coefficients are -0.6 rather than -0.9 on
        purpose: at -0.9 the SECOND call would already be refused
        (determinant 1 - 0.81 - 0.81 < 0), which would not test the
        merge at all.
        """
        arr = np.column_stack([[10.0, 20.0], [1.0, 2.0], [3.0, 4.0]])
        db = itc.load(arr, names=["a", "b", "c"])
        db = db.set_correlation({("a", "b"): -0.6})
        db = db.set_correlation({("a", "c"): -0.6})
        with pytest.raises(CorrelationMatrixError, match="positive semidefinite"):
            db.set_correlation({("b", "c"): -0.6})

    def test_itaca_028_conflicting_orientations_in_one_call_rejected(
        self, db: VarFrame
    ) -> None:
        """Two orientations of one pair in one call is a contradiction.

        Measured before the fix: the spec was canonicalized into a dict
        before the conflict detector ever saw it, so the two keys
        collapsed to one and 0.9 won by dictionary order. The detector
        existed and was unreachable from this entry point.
        """
        with pytest.raises(CorrelationMatrixError) as excinfo:
            db.set_correlation({("FZ", "V"): 0.1, ("V", "FZ"): 0.9})
        message = str(excinfo.value)
        assert "conflicting declarations" in message
        assert "0.1" in message
        assert "0.9" in message

    def test_itaca_028_consistent_duplicate_orientations_still_collapse(
        self, db: VarFrame
    ) -> None:
        """Agreeing duplicates are not a conflict; they are one pair."""
        out = db.set_correlation({("FZ", "V"): 0.4, ("V", "FZ"): 0.4})
        assert out.correlation is not None
        assert sorted(out.correlation.pairs) == [("FZ", "V")]
        assert out.correlation.get("V", "FZ") == 0.4
