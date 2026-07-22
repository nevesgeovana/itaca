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
