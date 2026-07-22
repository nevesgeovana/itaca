"""Tests for UncFrame, HistoryFrame, CorrelationMatrix, CoordSystem.

SRS 4.2 (two components, DD-19), 4.3 (origin tags, DD-06), REQ-40
(correlation validation), Chapter 5 (Cartesian and Polar).
"""

import numpy as np
import pytest

from itaca.core.coords import Cartesian, CoordSystem, Polar
from itaca.core.correlation import CorrelationMatrix
from itaca.core.errors import (
    CorrelationMatrixError,
    DataError,
    UncertaintyError,
)
from itaca.core.historyframe import HistoryFrame
from itaca.core.uncframe import UncFrame


class TestUncFrame:
    def test_two_components(self) -> None:
        # DD-19: systematic and random stored separately.
        unc = UncFrame(
            systematic={"CT": np.full(3, 0.004)},
            random={"CT": np.full(3, 0.003)},
        )
        assert np.allclose(unc.systematic["CT"], 0.004)
        assert np.allclose(unc.random["CT"], 0.003)

    def test_combined_is_rss(self) -> None:
        # REQ-99: u = sqrt(u_sys^2 + u_rand^2) at reporting time.
        unc = UncFrame(
            systematic={"CT": np.full(3, 3.0)},
            random={"CT": np.full(3, 4.0)},
        )
        assert np.allclose(unc.combined("CT"), 5.0)

    def test_combined_with_single_component(self) -> None:
        unc = UncFrame(systematic={"CT": np.full(3, 3.0)})
        assert np.allclose(unc.combined("CT"), 3.0)

    def test_negative_uncertainty_rejected(self) -> None:
        with pytest.raises(UncertaintyError):
            UncFrame(systematic={"CT": np.array([0.1, -0.1])})

    def test_arrays_read_only(self) -> None:
        unc = UncFrame(systematic={"CT": np.full(3, 0.1)})
        with pytest.raises(ValueError, match="read-only"):
            unc.systematic["CT"][0] = 9.0

    def test_variables_listed(self) -> None:
        unc = UncFrame(systematic={"CT": np.zeros(3)}, random={"CP": np.zeros(3)})
        assert unc.variables() == ("CP", "CT")

    def test_combined_unknown_variable_rejected(self) -> None:
        from itaca.core.errors import UncertaintyKeyError

        unc = UncFrame(systematic={"CT": np.zeros(3)})
        with pytest.raises(UncertaintyKeyError):
            unc.combined("CP")


class TestHistoryFrame:
    def test_tags_stored_as_int8(self) -> None:
        tags = HistoryFrame(tags={"CT": np.array([0, 1, -1])})
        assert tags.tags["CT"].dtype == np.int8
        assert list(tags.tags["CT"]) == [0, 1, -1]

    def test_invalid_tag_value_rejected(self) -> None:
        # SRS 4.3: only 0, +1, -1 are legal origin tags.
        with pytest.raises(DataError):
            HistoryFrame(tags={"CT": np.array([0, 2])})

    def test_arrays_read_only(self) -> None:
        tags = HistoryFrame(tags={"CT": np.array([0, 0])})
        with pytest.raises(ValueError, match="read-only"):
            tags.tags["CT"][0] = 1


class TestCorrelationMatrix:
    def test_symmetric_lookup_with_default_zero(self) -> None:
        # REQ-40: default is full independence.
        corr = CorrelationMatrix(pairs={("FX", "FZ"): 0.3})
        assert corr.get("FX", "FZ") == 0.3
        assert corr.get("FZ", "FX") == 0.3
        assert corr.get("FX", "MY") == 0.0
        assert corr.get("FX", "FX") == 1.0

    def test_out_of_range_rejected(self) -> None:
        with pytest.raises(CorrelationMatrixError):
            CorrelationMatrix(pairs={("FX", "FZ"): 1.2})

    def test_conflicting_duplicate_rejected(self) -> None:
        with pytest.raises(CorrelationMatrixError):
            CorrelationMatrix(pairs={("FX", "FZ"): 0.3, ("FZ", "FX"): 0.4})

    def test_self_pair_rejected(self) -> None:
        with pytest.raises(CorrelationMatrixError):
            CorrelationMatrix(pairs={("FX", "FX"): 1.0})

    def test_consistent_duplicate_collapses(self) -> None:
        corr = CorrelationMatrix(pairs={("FX", "FZ"): 0.3, ("FZ", "FX"): 0.3})
        assert corr.get("FX", "FZ") == 0.3


class TestCoordSystem:
    def test_cartesian_and_polar(self) -> None:
        assert isinstance(Cartesian(), CoordSystem)
        assert isinstance(Polar(), CoordSystem)
        assert Cartesian().name == "cartesian"
        assert Polar().name == "polar"
