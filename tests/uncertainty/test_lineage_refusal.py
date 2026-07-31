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

import re

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    UncertaintyCompatibilityError,
    UncertaintyLineageError,
)
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
        assert "x" in message  # the shared root is named

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
        message = str(caught.value)
        assert "translate_moments" in message
        # The workaround is one call from the ORIGINAL reference point.
        assert "from_point" in message

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
        assert "0" in message  # the offending point is named

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
