"""Tests for db.compute (REQ-33 to REQ-36).

Usage example (the contract under test)::

    db = db.set_uncertainty({"FZ": 0.005, "V": 0.02})
    db = db.compute("q = 0.5 * 1.225 * V**2")
    db = db.compute("CL = FZ / (q * 0.1963)")
"""

import warnings

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


class TestWhereEvaluatesOnlyInsideItsMask:
    """FND-073: `where=` masked the RESULT and not the EVALUATION.

    Values and derivatives were computed over the whole grid first and
    the mask applied to what came out, so a cell the caller excluded
    still went through the arithmetic. On a domain violation that is
    visible: `sqrt` over a masked-out negative emitted RuntimeWarnings
    the mask should have prevented, twice with an uncertainty carrier,
    once without.

    The warnings are the symptom worth testing because they are what a
    caller sees. The cause is that the excluded cell was evaluated at
    all, which is also why the fill value is asserted beside them: a
    silenced warning over a still-wrong result would pass a warning
    test alone.
    """

    @staticmethod
    def _signed() -> VarFrame:
        arr = np.column_stack([np.array([-1.0, 1.0]), np.array([1.0, 1.0])])
        return itc.load(arr, names=["v", "w"])

    def test_no_warning_from_a_masked_out_domain_violation(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = self._signed().compute("y = sqrt(v)", where="v >= 0", fill=99.0)
        assert [str(w.message) for w in caught] == []
        assert np.allclose(result.vars["y"].values, [99.0, 1.0])

    def test_no_warning_when_a_carrier_makes_derivatives_run_too(self) -> None:
        """The second half of the measurement, and a different code path.

        Without a carrier the value evaluation warns once; with one the
        derivative warns as well, from `operators.py` rather than from
        `expression.py`. A fix that masked only the value evaluation
        would leave this case warning.
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = (
                self._signed()
                .set_uncertainty({"v": 0.1})
                .compute("y = sqrt(v)", where="v >= 0", fill=99.0)
            )
        assert [str(w.message) for w in caught] == []
        assert result.uncertainty is not None
        u = result.uncertainty.systematic["y"]
        assert u[1] == pytest.approx(0.1 / (2.0 * np.sqrt(1.0)))

    def test_the_in_mask_result_is_unchanged(self) -> None:
        """All-positive data through the identical call.

        The control that keeps the fix from being "evaluate less": what
        the mask includes must come out exactly as before.
        """
        arr = np.column_stack([np.array([4.0, 9.0]), np.array([1.0, 1.0])])
        db = itc.load(arr, names=["v", "w"])
        result = db.compute("y = sqrt(v)", where="v >= 0", fill=99.0)
        assert np.allclose(result.vars["y"].values, [2.0, 3.0])

    def test_a_reduction_still_reads_the_whole_grid(self) -> None:
        """The precondition, pinned from the side that would break.

        REQ-36 admits any `np.*` function when nothing carries
        uncertainty, and a reduction reads cells other than its own. An
        unconditional NaN substitution therefore reaches the cells the
        mask was protecting: measured, this call returned `[99., nan,
        nan]` where it must return the grid-wide maximum in the two
        in-mask cells. `is_elementwise` is what keeps those trees on the
        whole-grid path.
        """
        arr = np.column_stack([np.array([-1.0, 1.0, 3.0]), np.array([1.0, 1.0, 1.0])])
        db = itc.load(arr, names=["v", "w"])
        result = db.compute("y = np.max(v)", where="v >= 0", fill=99.0)
        assert np.allclose(result.vars["y"].values, [99.0, 3.0, 3.0])

    def test_a_reduction_inside_a_larger_expression_is_caught_too(self) -> None:
        """The predicate is over the TREE, not over the root node."""
        arr = np.column_stack([np.array([-1.0, 1.0, 3.0]), np.array([1.0, 1.0, 1.0])])
        db = itc.load(arr, names=["v", "w"])
        result = db.compute("y = v + np.mean(v)", where="v >= 0", fill=99.0)
        assert np.allclose(result.vars["y"].values, [99.0, 2.0, 4.0])

    def test_an_all_false_mask_writes_the_fill_everywhere(self) -> None:
        arr = np.column_stack([np.array([-1.0, -2.0]), np.array([1.0, 1.0])])
        db = itc.load(arr, names=["v", "w"])
        result = db.compute("y = sqrt(v)", where="v >= 0", fill=99.0)
        assert np.allclose(result.vars["y"].values, [99.0, 99.0])

    def test_debug_reports_the_frames_data_not_the_mask(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """REQ-34's report reads the frame, so the mask must not reach it.

        Reported after the substitution it printed `v = nan` whenever
        grid point zero fell outside the mask, which is the ordinary
        case for a filter.
        """
        arr = np.column_stack([np.array([4.0, 9.0]), np.array([0.0, 1.0])])
        db = itc.load(arr, names=["v", "i"])
        db.compute("y = v * 2", where="i > 0", debug=True)
        out = capsys.readouterr().out
        assert "v = 4" in out, out
        assert "nan" not in out, out


class TestFillNoneKeepsThePriorState:
    """FND-090: `fill=None` kept the prior VALUE and erased the prior u.

    `fill=None` means this compute does not touch that cell. A cell that
    was not touched keeps both halves of its state, and it kept one:
    the value survived and the uncertainty came back NaN, so a surviving
    number was paired with an uncertainty that is not a number.
    """

    @staticmethod
    def _frame() -> VarFrame:
        arr = np.column_stack([np.array([100.0, 4.0]), np.array([0.0, 1.0])])
        return itc.load(arr, names=["x", "i"])

    def test_the_masked_out_cell_keeps_its_prior_uncertainty(self) -> None:
        db = self._frame().set_uncertainty({"x": 10.0})
        result = db.compute("x = x / 2", where="i > 0", fill=None)
        assert np.allclose(result.vars["x"].values, [100.0, 2.0])
        assert result.uncertainty is not None
        u = np.asarray(result.uncertainty.systematic["x"], dtype=float)
        assert u[0] == pytest.approx(10.0)
        assert u[1] == pytest.approx(5.0)

    def test_both_components_are_preserved(self) -> None:
        db = (
            self._frame()
            .set_uncertainty({"x": 10.0})
            .set_uncertainty({"x": 1.0}, component="random")
        )
        result = db.compute("x = x / 2", where="i > 0", fill=None)
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["x"][0] == pytest.approx(10.0)
        assert result.uncertainty.random["x"][0] == pytest.approx(1.0)

    def test_a_prior_uncertainty_survives_an_expression_with_no_carrier(
        self,
    ) -> None:
        """The case that would be half a rule if it were left out.

        With no carrier the propagation returns nothing and the target's
        component is dropped entirely, which erases the untouched cell's
        uncertainty by a different route than the mask. The in-mask cell
        still loses it, correctly: that cell WAS recomputed and the new
        expression implies no uncertainty for it (REQ-91, ITACA-024).
        """
        db = self._frame().set_uncertainty({"x": 10.0})
        result = db.compute("x = 7.0", where="i > 0", fill=None)
        assert np.allclose(result.vars["x"].values, [100.0, 7.0])
        assert result.uncertainty is not None
        u = np.asarray(result.uncertainty.systematic["x"], dtype=float)
        assert u[0] == pytest.approx(10.0)
        assert np.isnan(u[1])

    def test_an_explicit_fill_still_clears_the_uncertainty(self) -> None:
        """`fill=value` DOES touch the cell, so it does not keep a prior.

        The two fill modes must not converge: an explicit fill writes a
        value the expression did not produce, and pairing it with an
        uncertainty declared for the value it replaced would be a wrong
        number rather than a missing one.
        """
        db = self._frame().set_uncertainty({"x": 10.0})
        result = db.compute("x = x / 2", where="i > 0", fill=0.0)
        assert result.uncertainty is not None
        u = np.asarray(result.uncertainty.systematic["x"], dtype=float)
        assert np.isnan(u[0])

    def test_a_new_target_under_fill_none_still_has_no_prior(self) -> None:
        db = self._frame().set_uncertainty({"x": 0.5})
        result = db.compute("y = x * 2", where="i > 0", fill=None)
        assert result.uncertainty is not None
        u = np.asarray(result.uncertainty.systematic["y"], dtype=float)
        assert np.isnan(u[0])
        assert u[1] == pytest.approx(1.0)


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
    def test_debug_report(  # REQ-34: the structured pre-application report
        self, db: VarFrame, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with_unc = db.set_uncertainty({"CT": 0.1})
        with_unc.compute("f = CT * 2 + V", debug=True)
        out = capsys.readouterr().out
        assert "compute debug" in out
        assert "tokens" in out.lower()
        assert "CT" in out
        assert "partial" in out.lower()


class TestOverwriteClearsPriorState:
    """REV-001 ITACA-024: an overwrite recorded the operation while the
    mathematical state stayed the one the overwrite replaced."""

    @staticmethod
    def _frame() -> "VarFrame":
        arr = np.column_stack([[0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0]])
        return itc.load(arr, names=["a", "b"])

    def test_itaca_024_constant_recompute_clears_stale_uncertainty_and_pair(
        self,
    ) -> None:
        """`a = 42.0` makes a exact, so its old u and pairs must go.

        Measured before the fix: u(a) survived at 0.1 describing values
        that no longer existed, and corr(a, b) survived at 0.7 naming a
        variable whose meaning had been replaced. No error, no warning.
        """
        db = self._frame().set_uncertainty({"a": 0.1, "b": 0.2})
        db = db.set_correlation({("a", "b"): 0.7})
        out = db.compute("a = 42.0")

        assert out.uncertainty is not None  # b still carries its own
        assert "a" not in out.uncertainty.systematic
        assert "a" not in out.uncertainty.random
        assert out.uncertainty.systematic["b"] == pytest.approx(0.2)
        assert out.correlation is None
        assert "correlation=dropped" in out.history[-1].operation

    def test_itaca_024_recompute_on_a_frame_whose_only_uncertainty_was_the_target(
        self,
    ) -> None:
        """Clearing the last carrier returns to None, not to an empty mirror.

        REQ-91 says the UncFrame is absent until something is assigned.
        The state hash is identical either way, so this assertion is the
        only thing that can see the difference.
        """
        db = self._frame().set_uncertainty({"a": 0.1})
        out = db.compute("a = 42.0")
        assert out.uncertainty is None

    def test_itaca_024b_component_without_a_carrier_is_cleared_not_left_stale(
        self,
    ) -> None:
        """A component the new expression does not derive is deleted.

        `a = b * 0.0 + 7.0` has one carrier, b, which declares only a
        systematic component. The derived systematic u(a) is therefore
        an exact zero, and the random component has no carrier at all,
        so a's old random uncertainty must not survive.
        """
        db = self._frame().set_uncertainty({"a": 0.1})
        db = db.set_uncertainty({"a": 0.3}, component="random")
        db = db.set_uncertainty({"b": 0.2})
        out = db.compute("a = b * 0.0 + 7.0")

        assert out.uncertainty is not None
        assert out.uncertainty.systematic["a"] == pytest.approx(0.0)
        assert "a" not in out.uncertainty.random

    def test_itaca_024_new_target_keeps_unrelated_pairs(self) -> None:
        """The drop is scoped to the overwritten name, not blanket."""
        db = self._frame().set_uncertainty({"a": 0.1, "b": 0.2})
        db = db.set_correlation({("a", "b"): 0.7})
        out = db.compute("c = a + b")
        assert out.correlation is not None
        assert out.correlation.get("a", "b") == 0.7
        assert not any("c" in pair for pair in out.correlation.pairs)
