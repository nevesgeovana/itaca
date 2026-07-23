"""Tests for itc.concat (REQ-24): concatenate along a shared dimension.

Usage example (TDD anchor)::

    import itaca as itc
    low = itc.load(a, names=["alpha", "CT"]).pivot(dims=["alpha"])
    high = itc.load(b, names=["alpha", "CT"]).pivot(dims=["alpha"])
    both = itc.concat([low, high], along="alpha")

All inputs share every other dimension identically; overlapping values
along ``along`` raise ConcatOverlapError; components and tags are
concatenated unchanged (REQ-98).
"""

import dataclasses

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    ConcatOverlapError,
    DataError,
    DimensionNotFoundError,
    OperatingModeMixError,
    UncertaintyError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _frame(alpha: list[float], ct: list[float]) -> VarFrame:
    arr = np.column_stack([np.array(alpha), np.array(ct)])
    return itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])


@pytest.fixture
def low() -> VarFrame:
    return _frame([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])


@pytest.fixture
def high() -> VarFrame:
    return _frame([3.0, 4.0], [4.0, 5.0])


class TestConcatValues:
    def test_coords_and_values_concatenated(
        self, low: VarFrame, high: VarFrame
    ) -> None:
        result = itc.concat([low, high], along="alpha")
        assert np.allclose(result.dims["alpha"].coords, [0.0, 1.0, 2.0, 3.0, 4.0])
        assert np.allclose(result.vars["CT"].values, [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_input_order_preserved(self, low: VarFrame, high: VarFrame) -> None:
        result = itc.concat([high, low], along="alpha")
        assert np.allclose(result.dims["alpha"].coords, [3.0, 4.0, 0.0, 1.0, 2.0])

    def test_cardinalities_may_differ(self, low: VarFrame, high: VarFrame) -> None:
        # REQ-24 letter: cardinalities along `along` may differ.
        assert low.shape != high.shape
        result = itc.concat([low, high], along="alpha")
        assert result.shape == (5,)

    def test_single_input_round_trips(self, low: VarFrame) -> None:
        result = itc.concat([low], along="alpha")
        assert np.allclose(result.vars["CT"].values, low.vars["CT"].values)

    def test_two_dimensional_grid(self) -> None:
        def grid(alpha: list[float]) -> VarFrame:
            rows = [[a, m, 10.0 * a + m] for a in alpha for m in (0.1, 0.2)]
            arr = np.array(rows)
            return itc.load(arr, names=["alpha", "mach", "CT"]).pivot(
                dims=["alpha", "mach"]
            )

        result = itc.concat([grid([0.0, 1.0]), grid([2.0])], along="alpha")
        assert result.shape == (3, 2)
        assert result.vars["CT"].values[2, 1] == pytest.approx(20.2)


class TestConcatValidation:
    def test_overlap_rejected(self, low: VarFrame) -> None:
        other = _frame([2.0, 3.0], [9.0, 9.0])
        with pytest.raises(ConcatOverlapError, match="unique"):
            itc.concat([low, other], along="alpha")

    def test_overlap_message_is_three_part(self, low: VarFrame) -> None:
        other = _frame([2.0, 3.0], [9.0, 9.0])
        with pytest.raises(ConcatOverlapError) as exc:
            itc.concat([low, other], along="alpha")
        # REQ-81: object, operation, suggested fix.
        text = str(exc.value)
        assert "along 'alpha'" in text
        assert "repeats values" in text
        assert "Suggested fix:" in text

    def test_unknown_dimension_rejected(self, low: VarFrame, high: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            itc.concat([low, high], along="beta")

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(DataError):
            itc.concat([], along="alpha")

    def test_different_variable_sets_rejected(self, low: VarFrame) -> None:
        arr = np.column_stack([np.array([3.0, 4.0]), np.array([4.0, 5.0])])
        other = itc.load(arr, names=["alpha", "CQ"]).pivot(dims=["alpha"])
        with pytest.raises(DataError):
            itc.concat([low, other], along="alpha")

    def test_mismatched_other_dimension_rejected(self) -> None:
        def grid(alpha: list[float], mach: tuple[float, ...]) -> VarFrame:
            rows = [[a, m, a + m] for a in alpha for m in mach]
            return itc.load(np.array(rows), names=["alpha", "mach", "CT"]).pivot(
                dims=["alpha", "mach"]
            )

        with pytest.raises(DataError):
            itc.concat(
                [grid([0.0], (0.1, 0.2)), grid([1.0], (0.1, 0.3))], along="alpha"
            )

    def test_mixed_modes_rejected(self, low: VarFrame, high: VarFrame) -> None:
        with pytest.raises(OperatingModeMixError):
            itc.concat([low, high.demote(comment="scratch")], along="alpha")


class TestConcatBookkeeping:
    def test_recorded_in_history_of_first_input(
        self, low: VarFrame, high: VarFrame
    ) -> None:
        result = itc.concat([low, high], along="alpha", comment="two runs")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("concat(")
        assert result.history.last.comment == "two runs"

    def test_provenance_of_first_input(self, low: VarFrame, high: VarFrame) -> None:
        result = itc.concat([low, high], along="alpha")
        assert result.provenance is low.provenance

    def test_originals_untouched(self, low: VarFrame, high: VarFrame) -> None:
        itc.concat([low, high], along="alpha")
        assert low.shape == (3,)
        assert high.shape == (2,)


class TestConcatMirrors:
    def _with_unc(self, db: VarFrame, scale: float) -> VarFrame:
        n = db.shape[0]
        unc = UncFrame(
            systematic={"CT": np.full(n, scale)},
            random={"CT": np.full(n, 2.0 * scale)},
        )
        return dataclasses.replace(db, uncertainty=unc)

    def test_components_concatenated_unchanged(
        self, low: VarFrame, high: VarFrame
    ) -> None:
        result = itc.concat(
            [self._with_unc(low, 0.1), self._with_unc(high, 0.5)], along="alpha"
        )
        assert result.uncertainty is not None
        assert np.allclose(
            result.uncertainty.systematic["CT"], [0.1, 0.1, 0.1, 0.5, 0.5]
        )
        assert np.allclose(result.uncertainty.random["CT"], [0.2, 0.2, 0.2, 1.0, 1.0])

    def test_uncertainty_presence_mismatch_rejected(
        self, low: VarFrame, high: VarFrame
    ) -> None:
        # DD-18: never silently drop or invent a component.
        with pytest.raises(UncertaintyError):
            itc.concat([self._with_unc(low, 0.1), high], along="alpha")

    def test_tags_concatenated_with_zero_fill(self, high: VarFrame) -> None:
        arr = np.column_stack([np.arange(3.0), np.array([1.0, np.nan, 3.0])])
        filled = (
            itc.load(arr, names=["alpha", "CT"])
            .pivot(dims=["alpha"])
            .fill(along="alpha", method="linear")
        )
        result = itc.concat([filled, high], along="alpha")
        assert result.tags is not None
        assert list(result.tags.tags["CT"]) == [0, 1, 0, 0, 0]
