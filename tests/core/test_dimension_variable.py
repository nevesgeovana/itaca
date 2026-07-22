"""Tests for Dimension and Variable (SRS 4.1.3, 4.1.4; REQ-102).

Usage example (the contract under test)::

    from itaca.core.dimension import Dimension
    from itaca.core.variable import Variable

    alpha = Dimension(name="alpha", coords=np.array([0.0, 2.0, 4.0]), unit="deg")
    ct = Variable(name="CT", values=np.zeros((3,)), long_name="Thrust coefficient")
"""

import dataclasses

import numpy as np
import pytest

from itaca.core.dimension import Dimension
from itaca.core.errors import DataError
from itaca.core.variable import Variable


class TestDimension:
    def test_construction_and_metadata(self) -> None:
        dim = Dimension(
            name="alpha",
            coords=np.array([0.0, 2.0, 4.0]),
            unit="deg",
            description="angle of attack",
        )
        assert dim.name == "alpha"
        assert dim.unit == "deg"
        assert dim.is_numeric
        assert dim.cardinality == 3
        assert np.array_equal(dim.coords, [0.0, 2.0, 4.0])

    def test_coords_are_read_only(self) -> None:
        # REQ-102: in-place mutation of any stored array raises.
        dim = Dimension(name="alpha", coords=np.array([0.0, 2.0]))
        with pytest.raises(ValueError, match="read-only"):
            dim.coords[0] = 99.0

    def test_frozen_dataclass(self) -> None:
        dim = Dimension(name="alpha", coords=np.array([0.0]))
        with pytest.raises(dataclasses.FrozenInstanceError):
            dim.name = "beta"  # type: ignore[misc]

    def test_coords_must_be_one_dimensional(self) -> None:
        with pytest.raises(DataError):
            Dimension(name="alpha", coords=np.zeros((2, 2)))

    def test_string_coords_require_non_numeric_flag(self) -> None:
        with pytest.raises(DataError):
            Dimension(name="blade_type", coords=np.array(["A", "B"]))

    def test_non_numeric_dimension(self) -> None:
        dim = Dimension(
            name="blade_type", coords=np.array(["A", "B"]), is_numeric=False
        )
        assert not dim.is_numeric
        assert dim.cardinality == 2

    def test_numeric_coords_with_non_numeric_flag_rejected(self) -> None:
        with pytest.raises(DataError):
            Dimension(name="alpha", coords=np.array([0.0, 1.0]), is_numeric=False)

    def test_mutating_source_array_does_not_affect_dimension(self) -> None:
        source = np.array([0.0, 2.0, 4.0])
        dim = Dimension(name="alpha", coords=source)
        source[0] = 99.0
        assert dim.coords[0] == 0.0


class TestVariable:
    def test_construction_and_metadata(self) -> None:
        var = Variable(
            name="CT",
            values=np.zeros((3, 2)),
            unit=None,
            long_name="Thrust coefficient",
        )
        assert var.name == "CT"
        assert var.long_name == "Thrust coefficient"
        assert var.values.shape == (3, 2)

    def test_values_are_read_only(self) -> None:
        var = Variable(name="CT", values=np.zeros((3,)))
        with pytest.raises(ValueError, match="read-only"):
            var.values[0] = 99.0

    def test_frozen_dataclass(self) -> None:
        var = Variable(name="CT", values=np.zeros((1,)))
        with pytest.raises(dataclasses.FrozenInstanceError):
            var.unit = "N"  # type: ignore[misc]

    def test_mutating_source_array_does_not_affect_variable(self) -> None:
        source = np.zeros((3,))
        var = Variable(name="CT", values=source)
        source[0] = 99.0
        assert var.values[0] == 0.0

    def test_non_numeric_values_rejected(self) -> None:
        with pytest.raises(DataError):
            Variable(name="CT", values=np.array(["a", "b"]))
