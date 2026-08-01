"""The interim refusal for uncertainty lineage lost between operations.

Reproduction (the defect these tests pin), measured on ``dde261c`` before
any fix existed::

    db = itc.load(np.column_stack([[1.0, 2.0]]), names=["x"])
    db = db.set_uncertainty({"x": 0.1})

    db.compute("p = 3*x").compute("q = 2*x").compute("r = p - q")
        u(r) = 0.36055513      <- 3.6x overstatement
    db.compute("r = 3*x - 2*x")
        u(r) = 0.1             <- correct

The engine is RIGHT within a single expression and loses lineage BETWEEN
calls, which is what makes refusing acceptable rather than mutilating:
for every composition it refuses there is a single expression that is
already correct, and the refusal names it.

SEAT-UNC (author decision, 2026-07-31) chose this interim refusal with an
actionable workaround over the structural fix, which is owed to v0.3.0.
FND-058, FND-074, FND-088, FND-095; evidence in BRF-059.
"""

import dataclasses
import re

import numpy as np
import pytest

import itaca as itc
from itaca.core.dimension import Dimension
from itaca.core.errors import (
    UncertaintyCompatibilityError,
    UncertaintyLineageError,
)
from itaca.core.history import History, HistoryEntry
from itaca.core.pipeline import PipelineStep
from itaca.core.varframe import VarFrame


@pytest.fixture
def db() -> VarFrame:
    arr = np.column_stack([np.array([1.0, 2.0])])
    return itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})


@pytest.fixture
def two_roots() -> VarFrame:
    arr = np.column_stack([np.array([1.0, 2.0]), np.array([10.0, 20.0])])
    return itc.load(arr, names=["FZ", "V"]).set_uncertainty({"FZ": 0.5, "V": 0.2})


class TestComputeSharedAncestry:
    """FND-058: composition across compute calls loses induced covariance."""

    def test_refuses_two_carriers_from_one_root(self, db: VarFrame) -> None:
        chain = db.compute("p = 3*x").compute("q = 2*x")
        with pytest.raises(UncertaintyLineageError):
            chain.compute("r = p - q")

    def test_refuses_derived_against_its_own_root(self, db: VarFrame) -> None:
        # u(z) was 0.28284271 where zero is exactly correct.
        chain = db.compute("y = 2*x")
        with pytest.raises(UncertaintyLineageError):
            chain.compute("z = y - 2*x")

    def test_message_names_the_expression_that_works(self, db: VarFrame) -> None:
        # The whole point of the refusal: not a lecture about covariance,
        # a single expression the user can paste.
        chain = db.compute("p = 3*x").compute("q = 2*x")
        with pytest.raises(UncertaintyLineageError) as caught:
            chain.compute("r = p - q")
        message = str(caught.value)
        assert "r = (3*x) - (2*x)" in message
        assert "derived from 'x'" in message  # the shared root is named

    def test_the_named_expression_is_actually_correct(self, db: VarFrame) -> None:
        # A workaround nobody verified is not a workaround. Take the
        # expression out of the refusal and run it.
        chain = db.compute("p = 3*x").compute("q = 2*x")
        with pytest.raises(UncertaintyLineageError) as caught:
            chain.compute("r = p - q")
        suggested = _suggested_equation(str(caught.value))
        assert suggested is not None
        result = db.compute(suggested)
        assert np.allclose(result.uncertainty.systematic["r"], 0.1)

    def test_independent_derivations_still_compose(self, two_roots: VarFrame) -> None:
        # The library's flagship example. FZ and V are independent roots,
        # so q derives from V alone and CL from FZ and q is CORRECT. A
        # detector that refused this would break the documented workflow.
        chain = two_roots.compute("q = 0.5 * 1.225 * V**2")
        result = chain.compute("CL = FZ / (q * 0.1963)")
        assert result.uncertainty is not None
        assert "CL" in result.uncertainty.systematic

    def test_single_expression_is_never_refused(self, db: VarFrame) -> None:
        # The control: the same arithmetic in one call already works.
        result = db.compute("r = 3*x - 2*x")
        assert np.allclose(result.uncertainty.systematic["r"], 0.1)

    def test_one_carrier_is_never_refused(self, db: VarFrame) -> None:
        result = db.compute("p = 3*x").compute("r = p * 2")
        assert np.allclose(result.uncertainty.systematic["r"], 0.6)

    def test_declared_correlation_is_the_second_escape_hatch(
        self, db: VarFrame
    ) -> None:
        # A user who declares the pair has taken responsibility for it and
        # the clause-5 engine uses it, so the refusal steps aside. p = 3*x
        # and q = 2*x are perfectly correlated, and r = p - q with r = 1
        # gives u = |3 - 2| * 0.1 = 0.1, the correct answer.
        chain = db.compute("p = 3*x").compute("q = 2*x")
        declared = chain.set_correlation({("p", "q"): 1.0})
        result = declared.compute("r = p - q")
        assert np.allclose(result.uncertainty.systematic["r"], 0.1)

    def test_an_unreadable_equation_confers_unknown_ancestry(self) -> None:
        # QA F1. The conservatism DD-46 rests on: an equation this module
        # cannot parse must read as sharing ancestry with everything, not
        # as having none. Deleting that branch passed 124 targeted tests,
        # so it is pinned here by forging the History entry directly,
        # which is the only way to get an unparsable equation on record.
        db = _frame_with_recorded_equation("p = 3*x ((", carrier="p")
        with pytest.raises(UncertaintyLineageError) as caught:
            db.compute("r = p - x")
        message = str(caught.value)
        # VV-10's wording: an unreadable record is not evidence that the
        # two ARE related, so the message says what is missing rather
        # than asserting a derivation it cannot see.
        assert "cannot rule out" in message
        assert "compute('p = ...')" in message

    def test_an_unreadable_operation_poisons_even_root_variables(self) -> None:
        # ARCH-3. A step-less entry that is not a known-safe preparation
        # leaves this module unable to say what happened, and a ROOT
        # variable is absent from the derivation map, so marking only
        # derived entries would let two roots keep reading as
        # independent. Poisoning has to reach the roots.
        arr = np.column_stack([np.array([1.0, 2.0]), np.array([3.0, 4.0])])
        db = itc.load(arr, names=["a", "b"]).set_uncertainty({"a": 0.1, "b": 0.2})
        forged = _append_stepless(db, "combine(op='diff')")
        with pytest.raises(UncertaintyLineageError):
            forged.compute("r = a - b")

    def test_a_step_less_preparation_entry_does_not_poison(self) -> None:
        # The other side of the same rule: load is step-less on every
        # frame ever built, so an allowlist that missed it would refuse
        # every two-carrier expression in the library.
        arr = np.column_stack([np.array([1.0, 2.0]), np.array([3.0, 4.0])])
        db = itc.load(arr, names=["a", "b"]).set_uncertainty({"a": 0.1, "b": 0.2})
        result = db.compute("r = a - b")
        assert np.allclose(result.uncertainty.systematic["r"], np.hypot(0.1, 0.2))

    def test_a_masked_ancestor_suppresses_the_suggestion(self) -> None:
        # ARCH-2, measured: with p computed under where="x > 1", p is
        # [nan, 6., 9.] and the expansion r = (3*x) - (2*x) returns
        # [1., 2., 3.]. The expansion changed the VALUES, and DD-46's
        # whole argument is that it does not, so no suggestion is offered.
        arr = np.column_stack([np.array([1.0, 2.0, 3.0])])
        db = itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})
        chain = db.compute("p = 3*x", where="x > 1").compute("q = 2*x")
        with pytest.raises(UncertaintyLineageError) as caught:
            chain.compute("r = p - q")
        assert _suggested_equation(str(caught.value)) is None
        assert "single compute expression" in str(caught.value)

    def test_a_redeclared_ancestor_suppresses_the_suggestion(self) -> None:
        # VV-4. set_uncertainty overrides what propagation produced, so
        # expanding past p would propagate from x again and silently
        # discard the declared 0.9.
        arr = np.column_stack([np.array([1.0, 2.0])])
        db = itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})
        chain = db.compute("p = 3*x").set_uncertainty({"p": 0.9}).compute("q = 2*x")
        with pytest.raises(UncertaintyLineageError) as caught:
            chain.compute("r = p - q")
        assert _suggested_equation(str(caught.value)) is None

    def test_a_root_redeclared_after_a_derivation_suppresses_it(self) -> None:
        # QA round four, and this one was reported FIXED in round three
        # and was not. The round-three mark ran forward only, so a
        # variable derived BEFORE the re-declaration kept faithful=True.
        # Measured: with u(x) re-declared to 5.0 after p = 3*x, the
        # suggestion r = (3*x) - x was still offered as "already
        # correct" and returns 10.0, against a stored u(p) = 0.3 and
        # u(x) = 5.0, which no correlation admits.
        arr = np.column_stack([np.array([1.0, 2.0])])
        db = itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})
        chain = db.compute("p = 3*x").set_uncertainty({"x": 5.0})
        with pytest.raises(UncertaintyLineageError) as caught:
            chain.compute("r = p - x")
        assert _suggested_equation(str(caught.value)) is None

    def test_a_redeclared_ancestor_suppresses_it_transitively(self) -> None:
        # VV-8. The first fix checked only names spliced DIRECTLY into
        # the refused equation, so one more level of indirection walked
        # past it: with u(p) declared 5.0 and q = 2*p, the suggestion
        # r = (2*(3*x)) - x returned about 0.5 against the 10.0 the frame
        # implies. Re-declaration is now marked on the derivation itself,
        # in the forward walk, so it travels to everything that splices it.
        arr = np.column_stack([np.array([1.0, 2.0])])
        db = itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})
        chain = db.compute("p = 3*x").set_uncertainty({"p": 5.0}).compute("q = 2*p")
        with pytest.raises(UncertaintyLineageError) as caught:
            chain.compute("r = q - x")
        assert _suggested_equation(str(caught.value)) is None

    def test_a_variable_carrying_no_uncertainty_is_not_a_carrier(self) -> None:
        # Shared ancestry among values that carry no uncertainty induces
        # no covariance, so there is nothing to refuse.
        arr = np.column_stack([np.array([1.0, 2.0])])
        plain = itc.load(arr, names=["x"])
        result = plain.compute("p = 3*x").compute("q = 2*x").compute("r = p - q")
        assert result.uncertainty is None


class TestReductionOverInterpolatedPoints:
    """FND-088: interpolate then average loses point-to-point covariance."""

    @staticmethod
    def _frame() -> VarFrame:
        arr = np.column_stack([np.array([0.0, 1.0]), np.array([0.0, 1.0])])
        frame = itc.load(arr, names=["x", "Y"]).pivot(dims=["x"])
        return frame.set_uncertainty({"Y": 1.0}, component="random")

    def test_refuses_averaging_along_an_interpolated_dimension(self) -> None:
        # Measured before the fix, Y on x = [0, 1] with random u = 1.0,
        # interpolated to x = [0.25, 0.75] and then averaged:
        #     u(Y) after interpolate   = 0.7905694150420949
        #     composed interpolate->average = 0.5590169943749475
        #     direct equivalent average     = 0.7071067811865476
        # 21 percent UNDERSTATED. Both routes are the same function
        # 0.5*Y0 + 0.5*Y1, so the gap is covariance loss and nothing else:
        # each interpolated point is a linear combination of the SAME two
        # source points, and reduce_random assumes points are independent.
        fine = self._frame().interpolate({"x": np.array([0.25, 0.75])})
        with pytest.raises(UncertaintyLineageError):
            fine.average(along="x")

    def test_the_systematic_component_alone_is_not_refused(self) -> None:
        # REQ-99's systematic rule is the absolute weighted sum, which
        # assumes FULL correlation and therefore composes correctly
        # through interpolation. Only the random half was wrong, so only
        # the random half is refused.
        arr = np.column_stack([np.array([0.0, 1.0]), np.array([0.0, 1.0])])
        frame = itc.load(arr, names=["x", "Y"]).pivot(dims=["x"])
        frame = frame.set_uncertainty({"Y": 1.0})
        fine = frame.interpolate({"x": np.array([0.25, 0.75])})
        reduced = fine.average(along="x")
        assert reduced.uncertainty is not None
        assert "Y" in reduced.uncertainty.systematic

    def test_averaging_a_different_dimension_is_not_refused(self) -> None:
        # The common wind-tunnel workflow: interpolate runs onto a shared
        # alpha grid, then average ACROSS runs. The induced correlation
        # lies along alpha, not along run, so this must keep working.
        arr = np.column_stack(
            [
                np.repeat([0.0, 1.0], 2),  # alpha
                np.tile([0.0, 1.0], 2),  # run
                np.array([1.0, 2.0, 3.0, 4.0]),  # Y
            ]
        )
        frame = itc.load(arr, names=["alpha", "run", "Y"]).pivot(dims=["alpha", "run"])
        frame = frame.set_uncertainty({"Y": 1.0}, component="random")
        fine = frame.interpolate({"alpha": np.array([0.25, 0.75])})
        reduced = fine.average(along="run")
        assert reduced.uncertainty is not None
        assert "Y" in reduced.uncertainty.random

    def test_refuses_integrating_along_an_interpolated_dimension(self) -> None:
        # QA F2. `integrate` is a SECOND call site of the same rule, and
        # deleting its guard passed the entire suite: average was tested
        # and integrate was not, so `interpolate` then `integrate` still
        # understated by the same 21 percent.
        fine = self._frame().interpolate({"x": np.array([0.25, 0.75])})
        with pytest.raises(UncertaintyLineageError):
            fine.integrate("Y", over=["x"])

    def test_refuses_after_an_axis_translating_interpolate(self) -> None:
        # QA F3. The axisTranslation branch of the detector was uncovered,
        # and disabling it survived. An axis translation replaces the
        # dimension with a variable's values and correlates the points
        # exactly as a mapping interpolate does.
        arr = np.column_stack(
            [np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 4.0]), np.ones(3)]
        )
        frame = itc.load(arr, names=["x", "CL", "Y"]).pivot(dims=["x"])
        frame = frame.set_uncertainty({"Y": 1.0}, component="random")
        moved = frame.interpolate(axisTranslation={"from": "x", "to": "CL"})
        with pytest.raises(UncertaintyLineageError):
            moved.average(along="CL")

    def test_averaging_without_interpolation_is_untouched(self) -> None:
        reduced = self._frame().average(along="x")
        assert reduced.uncertainty is not None
        assert reduced.uncertainty.random["Y"] == pytest.approx(1.0 / np.sqrt(2.0))


class TestSequentialMomentTransfer:
    """FND-074: translate_moments discards the induced force-moment covariance."""

    @staticmethod
    def _frame() -> VarFrame:
        arr = np.column_stack(
            [
                np.array([0.0]),  # FX
                np.array([2.0]),  # FY
                np.array([3.0]),  # FZ
                np.array([0.0]),  # MX
                np.array([0.0]),  # MY
                np.array([0.0]),  # MZ
            ]
        )
        frame = itc.load(arr, names=["FX", "FY", "FZ", "MX", "MY", "MZ"])
        return frame.set_uncertainty({"FY": 1.0, "FZ": 1.0})

    def test_refuses_a_second_transfer(self) -> None:
        # Measured before the fix:
        #     direct  (one transfer, offset 2) u(M) = {MY: 2.0, MZ: 2.0}
        #     two-step (offset 1, then 1)      u(M) = {MY: 1.414, MZ: 1.414}
        # The VALUES agree on both routes, so the physics ran twice
        # correctly; only the uncertainty is wrong, and it UNDERSTATES by
        # 29 percent because step one wrote no F-M' correlation.
        once = self._frame().translate_moments(to_point=[1.0, 0.0, 0.0])
        with pytest.raises(UncertaintyLineageError):
            once.translate_moments(to_point=[2.0, 0.0, 0.0], from_point=[1.0, 0.0, 0.0])

    def test_the_message_names_the_single_transfer_that_works(self) -> None:
        once = self._frame().translate_moments(to_point=[1.0, 0.0, 0.0])
        with pytest.raises(UncertaintyLineageError) as caught:
            once.translate_moments(to_point=[2.0, 0.0, 0.0], from_point=[1.0, 0.0, 0.0])
        # QA F4: take the suggestion out of the message and RUN it,
        # the way the compute case already does. Asserting the substring
        # "from_point" left the recorded-from_point branch unexecuted and
        # the workaround unverified.
        suggested = _suggested_transfer(str(caught.value))
        assert suggested is not None
        base = self._frame()
        repaired = base.translate_moments(**suggested)
        assert repaired.uncertainty is not None
        assert repaired.uncertainty.systematic["MY"] == pytest.approx(2.0)
        assert repaired.uncertainty.systematic["MZ"] == pytest.approx(2.0)
        # And it reaches the same moments the refused two-step would have.
        assert np.allclose(repaired.vars["MY"].values, once.vars["MY"].values + 3.0)

    def test_the_suggestion_starts_where_the_journey_started(self) -> None:
        # QA Q2. The recorded-from_point branch never executed, because
        # every test's first transfer omitted from_point and took the
        # origin default; deleting the branch passed the full suite. A
        # user whose first transfer NAMED a reference point was being
        # handed a suggestion starting from the origin instead, which is
        # a wrong workaround, and DD-46 says that is worse than none.
        base = self._frame()
        once = base.translate_moments(
            to_point=[1.0, 0.0, 0.0], from_point=[5.0, 0.0, 0.0]
        )
        with pytest.raises(UncertaintyLineageError) as caught:
            once.translate_moments(to_point=[2.0, 0.0, 0.0], from_point=[1.0, 0.0, 0.0])
        suggested = _suggested_transfer(str(caught.value))
        assert suggested == {"to_point": [2.0, 0.0, 0.0], "from_point": [5.0, 0.0, 0.0]}
        # And it reproduces the two-step journey's moments exactly. Run on
        # the uncertainty-free twin, where the second transfer is
        # permitted so both routes can be compared at all.
        plain = _plain_loads()
        direct = plain.translate_moments(**suggested)
        stepwise = plain.translate_moments(
            to_point=[1.0, 0.0, 0.0], from_point=[5.0, 0.0, 0.0]
        ).translate_moments(to_point=[2.0, 0.0, 0.0], from_point=[1.0, 0.0, 0.0])
        for component in ("MX", "MY", "MZ"):
            assert np.allclose(
                direct.vars[component].values, stepwise.vars[component].values
            )

    def test_a_first_transfer_is_untouched(self) -> None:
        moved = self._frame().translate_moments(to_point=[2.0, 0.0, 0.0])
        assert moved.uncertainty is not None
        assert moved.uncertainty.systematic["MY"] == pytest.approx(2.0)
        assert moved.uncertainty.systematic["MZ"] == pytest.approx(2.0)

    def test_a_second_transfer_without_uncertainty_is_untouched(self) -> None:
        # No uncertainty on the channels means no covariance to lose.
        arr = np.column_stack([np.array([0.0])] * 6)
        plain = itc.load(arr, names=["FX", "FY", "FZ", "MX", "MY", "MZ"])
        once = plain.translate_moments(to_point=[1.0, 0.0, 0.0])
        twice = once.translate_moments(to_point=[2.0, 0.0, 0.0])
        assert twice.uncertainty is None

    def test_the_single_transfer_workaround_is_equivalent(self) -> None:
        # What makes "do it in one call" a workaround rather than a
        # different answer: the two routes agree on the VALUES. Measured
        # on the uncertainty-free frame, where the second transfer is
        # permitted, so both routes can be run and compared.
        arr = np.column_stack(
            [
                np.array([0.0]),
                np.array([2.0]),
                np.array([3.0]),
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
            ]
        )
        plain = itc.load(arr, names=["FX", "FY", "FZ", "MX", "MY", "MZ"])
        # from_point must be threaded, since it defaults to the origin on
        # every call: two hops of one are [0->1] then [1->2], not two
        # transfers measured from zero.
        direct = plain.translate_moments(to_point=[2.0, 0.0, 0.0])
        stepwise = plain.translate_moments(to_point=[1.0, 0.0, 0.0]).translate_moments(
            to_point=[2.0, 0.0, 0.0], from_point=[1.0, 0.0, 0.0]
        )
        for component in ("MX", "MY", "MZ"):
            assert np.allclose(
                direct.vars[component].values, stepwise.vars[component].values
            )


class TestCrossVariableOperations:
    """Ancestry conferred by operations that are not ``compute``.

    QA Q1: the block that fixes ARCH-1 and VV-1 shipped with NO test.
    Setting ``_CROSS_VARIABLE_CALLS`` to an empty set passed 490 tests,
    which is the same shape as the finding it was answering, one round
    earlier. These are the guards for that guard.
    """

    @staticmethod
    def _loads() -> VarFrame:
        arr = np.column_stack(
            [
                np.array([0.0]),
                np.array([2.0]),
                np.array([3.0]),
                np.array([0.0]),
                np.array([0.0]),
                np.array([0.0]),
            ]
        )
        frame = itc.load(arr, names=["FX", "FY", "FZ", "MX", "MY", "MZ"])
        return frame.set_uncertainty({"FZ": 1.0})

    def test_a_transferred_moment_shares_ancestry_with_the_force(self) -> None:
        # Measured before the fix: u = 1.41421356 for BOTH of these,
        # where MY - FZ is exactly 0 and MY + FZ is 2.0, because after
        # the transfer dMY'/dFZ is +1. FND-058's own shape, through the
        # translate_moments door.
        once = self._loads().translate_moments(to_point=[1.0, 0.0, 0.0])
        with pytest.raises(UncertaintyLineageError) as caught:
            once.compute("c = MY - FZ")
        assert "FZ" in str(caught.value)

    def test_the_transfer_is_what_confers_it(self) -> None:
        # The control: without the transfer, MY and FZ are independent
        # roots and the same expression is fine. This is what stops the
        # test above from passing for the wrong reason.
        result = self._loads().compute("c = MY - FZ")
        assert result.uncertainty.systematic["c"] == pytest.approx(1.0)

    def test_a_rotated_group_shares_ancestry_across_its_components(self) -> None:
        alpha = [0.4]
        rows = [[a, 1.0, 2.0, 3.0] for a in alpha]
        frame = itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
            dims=["alpha"]
        )
        frame = dataclasses.replace(
            frame,
            dims={"alpha": Dimension(name="alpha", coords=np.array(alpha), unit="rad")},
        )
        frame = frame.declare_vector("force", ["FX", "FY", "FZ"])
        frame = frame.set_uncertainty({"FX": 0.1, "FZ": 0.2})
        turned = frame.rotate("stability")

        # rotate records what it induces WHEN IT CAN, as an ordinary
        # declared pair, and the coefficient is asserted by value: a
        # version of rotate that wrote 0.0 here, claiming independence,
        # passed the earlier membership-only assertion (QA round three).
        assert turned.correlation is not None
        assert turned.correlation.get("FX", "FZ") == pytest.approx(0.47379635782970037)
        result = turned.compute("c = FX - FZ")
        assert result.uncertainty is not None

        # The ancestry net is the backstop for when that declaration is
        # not there. Dropping the pair leaves two variables the rotation
        # genuinely mixed and nothing saying so, and then it refuses.
        stripped = dataclasses.replace(turned, correlation=None)
        with pytest.raises(UncertaintyLineageError):
            stripped.compute("c = FX - FZ")

    def test_rotate_refuses_to_invent_a_coefficient_it_cannot_represent(
        self,
    ) -> None:
        # VV-13. The contrast above holds only where the induced
        # coefficient resolves to ONE scalar across the grid. A
        # CorrelationMatrix pair is a single number, and on an ordinary
        # REQ-101 condition sweep the induced value varies per cell, so
        # rotate declines to store it and records
        # `correlation_not_stored` instead. This is the case that makes
        # OQ-51 a real question rather than a copy of rotate: the
        # asymmetry with translate_moments is narrower than it looks.
        alpha = [0.2, 0.5]
        rows = [[a, 1.0, 2.0, 3.0] for a in alpha]
        frame = itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
            dims=["alpha"]
        )
        frame = dataclasses.replace(
            frame,
            dims={"alpha": Dimension(name="alpha", coords=np.array(alpha), unit="rad")},
        )
        frame = frame.declare_vector("force", ["FX", "FY", "FZ"])
        frame = frame.set_uncertainty({"FX": 0.1, "FZ": 0.2})
        turned = frame.rotate("stability")

        assert turned.correlation is None
        assert "correlation_not_stored" in turned.history.last.operation
        # And the ancestry net is what stops the understatement there.
        with pytest.raises(UncertaintyLineageError):
            turned.compute("c = FX - FZ")


# `TestConcatDiscardedLineage` stood here, six tests, and was REMOVED by
# the author's decision of 2026-08-02 together with the guard it covered.
# The tests were: an ordinary concat of roots is untouched (ARCH-8), a
# discarded derivation is refused at the concat (ARCH-5), the first
# input's derivation is not asserted over the others (VV-16), identically
# derived inputs are allowed (ARCH-14), an unreadable input is refused
# (ARCH-13), and a discarded derivation without uncertainty is allowed.
#
# They are named rather than deleted silently because four of the six pin
# a REGRESSION of a fix, not the fix itself: each records a way an earlier
# attempt at this guard was wrong. If a `concat` refusal is ever designed
# again, this list is where its case set starts. What removing them costs
# is written in CHANGELOG.md under Known open, class 1, with the number:
# `derive, concat, then declare` reaches u = 0.36055513 where 0.1 is
# correct, and it did so WITH the guard in place, which is why the guard
# went (ARCH-15, ITC-20260731-1730, DD-52).
#
# The three other lineage refusals are untouched and are covered above.


class TestNonDifferentiablePoint:
    """FND-095: abs at zero asserted certainty where it has no derivative."""

    def test_refuses_abs_at_a_non_differentiable_point(self) -> None:
        # Measured before the fix, x = [0, 3, -3] with u(x) = 0.1:
        #     u(abs(x)) = [0.  0.1 0.1]
        # np.sign(0) is 0, so the chain rule returned u = 0 EXACTLY: a
        # claim of perfect certainty at the one point where the function
        # has no derivative at all.
        arr = np.column_stack([np.array([0.0, 3.0, -3.0])])
        db = itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})
        with pytest.raises(UncertaintyCompatibilityError) as caught:
            db.compute("y = abs(x)")
        message = str(caught.value)
        assert "abs" in message
        # F5: the offending VALUE, not a count that happens to contain a
        # zero. This assertion must fail if the numbers in the message
        # are wrong, which the earlier `"0" in message` did not.
        assert "operand value 0," in message
        assert "1 of 3 point(s)" in message

    def test_abs_away_from_zero_is_untouched(self) -> None:
        arr = np.column_stack([np.array([3.0, -3.0])])
        db = itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})
        result = db.compute("y = abs(x)")
        assert np.allclose(result.uncertainty.systematic["y"], 0.1)

    def test_abs_without_uncertainty_still_evaluates_at_zero(self) -> None:
        # No uncertainty carrier means no derivative is taken, so there is
        # nothing to refuse and abs(0) = 0 is simply correct.
        arr = np.column_stack([np.array([0.0, 3.0])])
        db = itc.load(arr, names=["x"])
        result = db.compute("y = abs(x)")
        assert np.allclose(result.vars["y"].values, [0.0, 3.0])

    def test_a_masked_out_zero_does_not_refuse(self) -> None:
        # where= excludes the cell, and compute substitutes NaN into the
        # environment for it, so the derivative is never taken at zero.
        arr = np.column_stack([np.array([0.0, 3.0])])
        db = itc.load(arr, names=["x"]).set_uncertainty({"x": 0.1})
        result = db.compute("y = abs(x)", where="x > 1")
        assert np.allclose(result.uncertainty.systematic["y"][1], 0.1)


def _suggested_equation(message: str) -> str | None:
    """Pull the suggested single expression out of a refusal message."""
    found = re.search(r'db\.compute\("([^"]+)"\)', message)
    return found.group(1) if found is not None else None


def _plain_loads() -> VarFrame:
    """The six load channels with no uncertainty, for value comparisons."""
    arr = np.column_stack(
        [
            np.array([0.0]),
            np.array([2.0]),
            np.array([3.0]),
            np.array([0.0]),
            np.array([0.0]),
            np.array([0.0]),
        ]
    )
    return itc.load(arr, names=["FX", "FY", "FZ", "MX", "MY", "MZ"])


def _suggested_transfer(message: str) -> dict[str, list[float]] | None:
    """Pull the suggested one-call transfer out of a refusal message."""
    found = re.search(
        r"db\.translate_moments\(to_point=(\[[^\]]+\]), from_point=(\[[^\]]+\])\)",
        message,
    )
    if found is None:
        return None
    return {
        "to_point": [float(v) for v in found.group(1).strip("[]").split(",")],
        "from_point": [float(v) for v in found.group(2).strip("[]").split(",")],
    }


def _replace_history(db: VarFrame, entries: tuple[HistoryEntry, ...]) -> VarFrame:
    """Rebuild a frame around a hand-made History.

    Two review findings (QA F1, ARCH-3) are about History shapes no
    public call produces: an equation the parser cannot read, and a
    step-less entry from a schema-1 archive or a multi-input ``combine``.
    Forging the record is the only way to reach them, and reaching them
    is the point, since both are the conservative branches the whole
    posture rests on.
    """
    return dataclasses.replace(db, history=History(entries=entries))


def _append_step(
    db: VarFrame, operation: str, call: str, kwargs: dict[str, object]
) -> VarFrame:
    """Append a replayable entry, for records no public call reaches here."""
    last = db.history[len(db.history) - 1]
    forged = HistoryEntry(
        index=len(db.history) + 1,
        operation=operation,
        timestamp=last.timestamp,
        state_hash=last.state_hash,
        step=PipelineStep(call=call, kwargs=kwargs),
    )
    return _replace_history(db, (*db.history.entries, forged))


def _append_stepless(db: VarFrame, operation: str) -> VarFrame:
    """Append a non-replayable entry, as concat, combine and old archives do."""
    last = db.history[len(db.history) - 1]
    forged = HistoryEntry(
        index=len(db.history) + 1,
        operation=operation,
        timestamp=last.timestamp,
        state_hash=last.state_hash,
    )
    return _replace_history(db, (*db.history.entries, forged))


def _frame_with_recorded_equation(equation: str, *, carrier: str) -> VarFrame:
    """A frame whose History records ``equation`` verbatim, parsable or not."""
    arr = np.column_stack([np.array([1.0, 2.0]), np.array([3.0, 6.0])])
    db = itc.load(arr, names=["x", carrier])
    db = db.set_uncertainty({"x": 0.1, carrier: 0.3})
    last = db.history[len(db.history) - 1]
    forged = HistoryEntry(
        index=len(db.history) + 1,
        operation=f"compute('{equation}')",
        timestamp=last.timestamp,
        state_hash=last.state_hash,
        step=PipelineStep(call="compute", kwargs={"equation": equation}),
    )
    return _replace_history(db, (*db.history.entries, forged))
