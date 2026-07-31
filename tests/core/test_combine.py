"""Tests for db.combine (REQ-37, REQ-12; DD-12)."""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    CorrelationMatrixError,
    DataError,
    OperatingModeMixError,
)
from itaca.core.historyframe import HistoryFrame
from itaca.core.varframe import VarFrame


def _frame(values: list[float], name: str = "CT") -> VarFrame:
    return itc.load(np.array(values).reshape(-1, 1), names=[name])


@pytest.fixture
def left() -> VarFrame:
    return _frame([1.0, 2.0])


@pytest.fixture
def right() -> VarFrame:
    return _frame([3.0, 4.0])


class TestCombine:
    @pytest.mark.parametrize(
        ("op", "expected"),
        [
            ("sum", [4.0, 6.0]),
            ("diff", [-2.0, -2.0]),
            ("product", [3.0, 8.0]),
            ("ratio", [1.0 / 3.0, 0.5]),
            ("mean", [2.0, 3.0]),
        ],
    )
    def test_operations(
        self, left: VarFrame, right: VarFrame, op: str, expected: list[float]
    ) -> None:
        result = left.combine(right, op=op)
        assert np.allclose(result.vars["CT"].values, expected)

    def test_weighted_mean(self, left: VarFrame, right: VarFrame) -> None:
        result = left.combine(right, op="weighted_mean", weights=(3.0, 1.0))
        assert np.allclose(result.vars["CT"].values, [1.5, 2.5])

    def test_weighted_mean_requires_weights(
        self, left: VarFrame, right: VarFrame
    ) -> None:
        with pytest.raises(DataError):
            left.combine(right, op="weighted_mean")

    def test_unknown_op(self, left: VarFrame, right: VarFrame) -> None:
        with pytest.raises(DataError):
            left.combine(right, op="magic")

    def test_no_operator_overloading(self, left: VarFrame, right: VarFrame) -> None:
        # DD-12 / NREQ-08: db1 + db2 is intentionally unsupported.
        with pytest.raises(TypeError):
            _ = left + right  # type: ignore[operator]

    def test_mode_mixing_rejected(self, left: VarFrame, right: VarFrame) -> None:
        # REQ-12: no implicit promotion or demotion.
        with pytest.raises(OperatingModeMixError):
            left.combine(right.demote(), op="sum")

    def test_grid_mismatch_rejected(self, left: VarFrame) -> None:
        other = _frame([1.0, 2.0, 3.0])
        with pytest.raises(DataError):
            left.combine(other, op="sum")

    def test_variable_mismatch_rejected(self, left: VarFrame) -> None:
        other = _frame([1.0, 2.0], name="CP")
        with pytest.raises(DataError):
            left.combine(other, op="sum")

    def test_history_records_partner(self, left: VarFrame, right: VarFrame) -> None:
        result = left.combine(right, op="sum")
        assert result.history.last is not None
        assert "combine(op='sum'" in result.history.last.operation
        assert "with=" in result.history.last.operation


class TestCombineUncertainty:
    def test_independent_rss(self, left: VarFrame, right: VarFrame) -> None:
        result = left.set_uncertainty({"CT": 3.0}).combine(
            right.set_uncertainty({"CT": 4.0}), op="sum"
        )
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["CT"], 5.0)

    def test_cross_correlation(self, left: VarFrame, right: VarFrame) -> None:
        result = left.set_uncertainty({"CT": 3.0}).combine(
            right.set_uncertainty({"CT": 4.0}),
            op="sum",
            cross_correlation=1.0,
        )
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["CT"], 7.0)

    def test_one_sided_uncertainty(self, left: VarFrame, right: VarFrame) -> None:
        result = left.set_uncertainty({"CT": 3.0}).combine(right, op="sum")
        assert result.uncertainty is not None
        assert np.allclose(result.uncertainty.systematic["CT"], 3.0)


class TestCombineJacobianDtype:
    """FND-035: the Jacobian is a derivative, not a sample of the data.

    The invariant is stated as an EQUIVALENCE rather than as "every
    partial is a float array", because that stronger form is false and
    harmlessly so: the partial of ``product`` with respect to one operand
    IS the other operand, and an integer one is exact. What must never
    differ is the propagated uncertainty, which is what a user reads.
    """

    @staticmethod
    def _as_int(db: VarFrame, u: float) -> VarFrame:
        """Retype the values to int64 without changing them.

        Not reachable through ``itc.load``, which casts to float64, so
        the frame is retyped directly; the defect is latent behind that
        cast rather than absent.
        """
        ints = np.asarray(db.vars["CT"].values, dtype=np.int64)
        ints.setflags(write=False)
        typed = db.set_uncertainty({"CT": u})
        return dataclasses.replace(
            typed,
            vars={"CT": dataclasses.replace(typed.vars["CT"], values=ints)},
        )

    @pytest.mark.parametrize(
        "op", ["sum", "diff", "product", "ratio", "mean", "weighted_mean"]
    )
    def test_integer_inputs_propagate_the_same_uncertainty_as_floats(
        self, op: str
    ) -> None:
        whole = _frame([10.0, 20.0])
        other = _frame([2.0, 5.0])
        weights = (1.0, 3.0) if op == "weighted_mean" else None
        kwargs = {} if weights is None else {"weights": weights}
        as_float = whole.set_uncertainty({"CT": 3.0}).combine(
            other.set_uncertainty({"CT": 4.0}), op=op, **kwargs
        )
        as_int = self._as_int(whole, 3.0).combine(
            self._as_int(other, 4.0), op=op, **kwargs
        )
        assert as_float.uncertainty is not None
        assert as_int.uncertainty is not None
        assert np.allclose(
            np.asarray(as_int.uncertainty.systematic["CT"], dtype=float),
            np.asarray(as_float.uncertainty.systematic["CT"], dtype=float),
        )


class TestCombineTags:
    def test_worst_case_rule(self, left: VarFrame, right: VarFrame) -> None:
        # OQ-10: -1 beats +1 beats 0.
        tagged_left = dataclasses.replace(
            left,
            tags=HistoryFrame(tags={"CT": np.array([1, 0], dtype=np.int8)}),
        )
        tagged_right = dataclasses.replace(
            right,
            tags=HistoryFrame(tags={"CT": np.array([-1, 0], dtype=np.int8)}),
        )
        result = tagged_left.combine(tagged_right, op="sum")
        assert result.tags is not None
        assert list(result.tags.tags["CT"]) == [-1, 0]


class TestCombineCorrelationAndCoefficient:
    """REV-001 ITACA-025f and ITACA-001c."""

    def test_itaca_001c_cross_correlation_out_of_range_rejected(
        self, left: VarFrame, right: VarFrame
    ) -> None:
        """The REQ-40 bound applies when r arrives as a keyword too.

        Measured before the fix: cross_correlation=5.0 was accepted and
        produced a variance the clamp then reported as a plausible
        uncertainty. This is the one propagation site whose correlation
        does not arrive through a validated CorrelationMatrix, so it is
        the one that still needed its own bound check.
        """
        left = left.set_uncertainty({"CT": 0.1})
        right = right.set_uncertainty({"CT": 0.2})
        with pytest.raises(CorrelationMatrixError) as excinfo:
            left.combine(right, op="sum", cross_correlation=-2.0)
        message = str(excinfo.value)
        assert "-2.0" in message
        assert "|r| <= 1" in message

    @pytest.mark.parametrize("coefficient", [-1.0, 0.0, 1.0])
    def test_itaca_001c_cross_correlation_bounds_are_inclusive(
        self, left: VarFrame, right: VarFrame, coefficient: float
    ) -> None:
        """The endpoints stay legal; only outside the interval raises."""
        left = left.set_uncertainty({"CT": 0.1})
        right = right.set_uncertainty({"CT": 0.2})
        out = left.combine(right, op="sum", cross_correlation=coefficient)
        assert out.uncertainty is not None

    def test_itaca_025f_combine_drops_correlation_from_both_inputs(
        self, left: VarFrame, right: VarFrame
    ) -> None:
        """combine recomputes every value, so no coefficient survives.

        Measured before the fix: db.correlation was carried and
        other.correlation was discarded, silently, so the result
        asserted a relationship between quantities that no longer
        existed. Identical declarations on both sides are NOT a special
        case: r(a_new, b_new) is not r(a, b) even for op='sum', by
        Cauchy-Schwarz, with equality only under a proportionality
        condition combine cannot check.
        """
        arr = np.column_stack([[1.0, 2.0], [3.0, 4.0]])
        first = itc.load(arr, names=["CT", "CP"]).set_correlation({("CT", "CP"): 0.4})
        second = itc.load(arr, names=["CT", "CP"])

        out = first.combine(second, op="sum")
        assert out.correlation is None
        assert "correlation=dropped" in out.history[-1].operation

        both = second.set_correlation({("CT", "CP"): 0.4})
        agreed = first.combine(both, op="sum")
        assert agreed.correlation is None
        assert "correlation=dropped" in agreed.history[-1].operation
