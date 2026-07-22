"""Tests for db.compute (REQ-33 to REQ-36).

Usage example (the contract under test)::

    db = db.set_uncertainty({"FZ": 0.005, "V": 0.02})
    db = db.compute("q = 0.5 * 1.225 * V**2")
    db = db.compute("CL = FZ / (q * 0.1963)")
"""

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    DataError,
    UncertaintyCompatibilityError,
    UncertaintyError,
    VariableNotFoundError,
)
from itaca.core.varframe import VarFrame


@pytest.fixture
def db() -> VarFrame:
    arr = np.column_stack(
        [np.array([1.0, 2.0, 3.0, 4.0]), np.array([10.0, 10.0, 10.0, 10.0])]
    )
    return itc.load(arr, names=["CT", "V"])


class TestCompute:
    def test_derives_new_variable(self, db: VarFrame) -> None:
        result = db.compute("thrust = CT * 2")
        assert np.allclose(result.vars["thrust"].values, [2.0, 4.0, 6.0, 8.0])
        assert "thrust" not in db.vars  # original untouched (REQ-18)

    def test_new_variable_tagged_computed(self, db: VarFrame) -> None:
        # SRS 4.3: compute sets +1 for newly created variables.
        result = db.compute("thrust = CT * 2")
        assert result.tags is not None
        assert (result.tags.tags["thrust"] == 1).all()

    def test_recorded_in_history(self, db: VarFrame) -> None:
        result = db.compute("thrust = CT * 2", comment="dimensional")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("compute(")
        assert result.history.last.comment == "dimensional"

    def test_invalid_equation_format(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.compute("CT * 2")

    def test_undefined_variable(self, db: VarFrame) -> None:
        with pytest.raises(VariableNotFoundError):
            db.compute("f = CT * missing")

    def test_mcm_not_available_in_m0(self, db: VarFrame) -> None:
        # DD-21: Monte Carlo ships in v0.3.0 (REQ-42).
        with pytest.raises(UncertaintyError):
            db.compute("f = CT * 2", method="mcm")

    def test_unknown_method(self, db: VarFrame) -> None:
        with pytest.raises(DataError):
            db.compute("f = CT * 2", method="magic")

    def test_replaces_existing_variable(self, db: VarFrame) -> None:
        result = db.compute("CT = CT * 2")
        assert np.allclose(result.vars["CT"].values, [2.0, 4.0, 6.0, 8.0])


class TestWhereFill:
    def test_where_with_nan_default(self, db: VarFrame) -> None:
        result = db.compute("f = CT * 2", where="CT > 2")
        values = result.vars["f"].values
        assert np.isnan(values[0]) and np.isnan(values[1])
        assert values[2] == pytest.approx(6.0)

    def test_where_with_scalar_fill(self, db: VarFrame) -> None:
        result = db.compute("f = CT * 2", where="CT > 2", fill=0.0)
        assert np.allclose(result.vars["f"].values, [0.0, 0.0, 6.0, 8.0])

    def test_where_with_fill_none_keeps_existing(self, db: VarFrame) -> None:
        # REQ-35: fill=None retains existing values of VAR.
        base = db.compute("f = CT * 0")
        result = base.compute("f = CT * 2", where="CT > 2", fill=None)
        assert np.allclose(result.vars["f"].values, [0.0, 0.0, 6.0, 8.0])

    def test_where_with_fill_none_on_new_variable(self, db: VarFrame) -> None:
        result = db.compute("f = CT * 2", where="CT > 2", fill=None)
        assert np.isnan(result.vars["f"].values[0])

    def test_condition_with_logic(self, db: VarFrame) -> None:
        result = db.compute("f = CT", where="CT > 1 and not CT >= 4", fill=-1.0)
        assert np.allclose(result.vars["f"].values, [-1.0, 2.0, 3.0, -1.0])

    def test_uncertainty_only_for_filtered_in(self, db: VarFrame) -> None:
        result = db.set_uncertainty({"CT": 0.1}).compute("f = CT * 2", where="CT > 2")
        assert result.uncertainty is not None
        u = result.uncertainty.systematic["f"]
        assert np.isnan(u[0])
        assert u[2] == pytest.approx(0.2)


class TestNumpyGuard:
    def test_guard_raises_with_uncertainty(self, db: VarFrame) -> None:
        with_unc = db.set_uncertainty({"CT": 0.1})
        with pytest.raises(UncertaintyCompatibilityError):
            with_unc.compute("f = np.round(CT)")

    def test_guard_is_per_variable(self, db: VarFrame) -> None:
        # REQ-36: only variables in this expression matter.
        with_unc = db.set_uncertainty({"CT": 0.1})
        result = with_unc.compute("f = np.round(V)")
        assert np.allclose(result.vars["f"].values, 10.0)

    def test_differentiable_numpy_propagates(self, db: VarFrame) -> None:
        with_unc = db.set_uncertainty({"CT": 0.1})
        result = with_unc.compute("f = np.sqrt(CT)")
        assert result.uncertainty is not None
        expected = 0.1 / (2 * np.sqrt(db.vars["CT"].values))
        assert np.allclose(result.uncertainty.systematic["f"], expected)


class TestDebug:
    def test_debug_report(
        self, db: VarFrame, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with_unc = db.set_uncertainty({"CT": 0.1})
        with_unc.compute("f = CT * 2 + V", debug=True)
        out = capsys.readouterr().out
        assert "compute debug" in out
        assert "tokens" in out.lower()
        assert "CT" in out
        assert "partial" in out.lower()
