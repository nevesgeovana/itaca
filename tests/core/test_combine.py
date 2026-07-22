"""Tests for db.combine (REQ-37, REQ-12; DD-12)."""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DataError, OperatingModeMixError
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
