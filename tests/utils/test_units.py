"""Tests for the hand-curated unit conversion table (REQ-73, DD-13).

Every table entry is exercised; external unit libraries are barred
(NREQ-09).
"""

import numpy as np
import pytest

from itaca.core.errors import DataError
from itaca.utils.units import convert

CASES = [
    # length
    ("ft", "m", 1.0, 0.3048),
    ("in", "mm", 1.0, 25.4),
    ("km", "m", 1.0, 1000.0),
    ("nmi", "m", 1.0, 1852.0),
    # mass
    ("lb", "kg", 1.0, 0.45359237),
    ("slug", "kg", 1.0, 14.59390294),
    ("g", "kg", 1000.0, 1.0),
    # time
    ("h", "s", 1.0, 3600.0),
    ("min", "s", 2.0, 120.0),
    # angle
    ("deg", "rad", 180.0, np.pi),
    ("rev", "rad", 1.0, 2 * np.pi),
    # rotational speed
    ("rpm", "rad/s", 60.0, 2 * np.pi),
    ("Hz", "rad/s", 1.0, 2 * np.pi),
    # speed
    ("knot", "m/s", 1.0, 0.514444444),
    ("km/h", "m/s", 3.6, 1.0),
    ("ft/s", "m/s", 1.0, 0.3048),
    ("mph", "m/s", 1.0, 0.44704),
    # force
    ("lbf", "N", 1.0, 4.4482216152605),
    ("kgf", "N", 1.0, 9.80665),
    ("kN", "N", 1.0, 1000.0),
    # pressure
    ("psi", "Pa", 1.0, 6894.757293168),
    ("bar", "Pa", 1.0, 1.0e5),
    ("atm", "Pa", 1.0, 101325.0),
    ("hPa", "Pa", 1.0, 100.0),
    ("kPa", "Pa", 1.0, 1000.0),
    # density
    ("slug/ft^3", "kg/m^3", 1.0, 515.378818),
]


@pytest.mark.parametrize(("src", "dst", "value", "expected"), CASES)
def test_table_entries(src: str, dst: str, value: float, expected: float) -> None:
    assert convert(value, src, dst) == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize(("src", "dst", "value", "expected"), CASES)
def test_round_trip(src: str, dst: str, value: float, expected: float) -> None:
    assert convert(convert(value, src, dst), dst, src) == pytest.approx(value, rel=1e-9)


class TestTemperature:
    def test_celsius_to_fahrenheit(self) -> None:
        assert convert(100.0, "C", "F") == pytest.approx(212.0)

    def test_kelvin_to_celsius(self) -> None:
        assert convert(273.15, "K", "C") == pytest.approx(0.0)

    def test_fahrenheit_to_kelvin(self) -> None:
        assert convert(32.0, "F", "K") == pytest.approx(273.15)


class TestBehavior:
    def test_vectorized(self) -> None:
        result = convert(np.array([1.0, 2.0]), "ft", "m")
        assert np.allclose(result, [0.3048, 0.6096])

    def test_incompatible_units_rejected(self) -> None:
        with pytest.raises(DataError):
            convert(1.0, "ft", "kg")

    def test_unknown_unit_rejected(self) -> None:
        with pytest.raises(DataError):
            convert(1.0, "parsec", "m")
