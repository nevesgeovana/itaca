"""Hand-curated unit conversion (REQ-73, DD-13, NREQ-09).

Each unit maps to a physical group, a multiplicative factor to the
group's base unit, and an additive offset (temperatures). Adding a
unit is a ``feat:`` pull request with one table line plus tests.
External unit libraries are deliberately not used.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DataError

# unit -> (group, factor to base, offset to base)
_TABLE: dict[str, tuple[str, float, float]] = {
    # length, base m
    "m": ("length", 1.0, 0.0),
    "mm": ("length", 1.0e-3, 0.0),
    "cm": ("length", 1.0e-2, 0.0),
    "km": ("length", 1.0e3, 0.0),
    "in": ("length", 0.0254, 0.0),
    "ft": ("length", 0.3048, 0.0),
    "nmi": ("length", 1852.0, 0.0),
    # mass, base kg
    "kg": ("mass", 1.0, 0.0),
    "g": ("mass", 1.0e-3, 0.0),
    "lb": ("mass", 0.45359237, 0.0),
    "slug": ("mass", 14.59390294, 0.0),
    # time, base s
    "s": ("time", 1.0, 0.0),
    "min": ("time", 60.0, 0.0),
    "h": ("time", 3600.0, 0.0),
    # angle, base rad
    "rad": ("angle", 1.0, 0.0),
    "deg": ("angle", np.pi / 180.0, 0.0),
    "rev": ("angle", 2.0 * np.pi, 0.0),
    # rotational speed, base rad/s
    "rad/s": ("rotation", 1.0, 0.0),
    "deg/s": ("rotation", np.pi / 180.0, 0.0),
    "rpm": ("rotation", 2.0 * np.pi / 60.0, 0.0),
    "Hz": ("rotation", 2.0 * np.pi, 0.0),
    # speed, base m/s
    "m/s": ("speed", 1.0, 0.0),
    "km/h": ("speed", 1.0 / 3.6, 0.0),
    "ft/s": ("speed", 0.3048, 0.0),
    "knot": ("speed", 1852.0 / 3600.0, 0.0),
    "mph": ("speed", 0.44704, 0.0),
    # force, base N
    "N": ("force", 1.0, 0.0),
    "kN": ("force", 1.0e3, 0.0),
    "lbf": ("force", 4.4482216152605, 0.0),
    "kgf": ("force", 9.80665, 0.0),
    # pressure, base Pa
    "Pa": ("pressure", 1.0, 0.0),
    "hPa": ("pressure", 100.0, 0.0),
    "kPa": ("pressure", 1.0e3, 0.0),
    "bar": ("pressure", 1.0e5, 0.0),
    "mbar": ("pressure", 100.0, 0.0),
    "psi": ("pressure", 6894.757293168, 0.0),
    "atm": ("pressure", 101325.0, 0.0),
    # density, base kg/m^3
    "kg/m^3": ("density", 1.0, 0.0),
    "slug/ft^3": ("density", 14.59390294 / 0.3048**3, 0.0),
    # temperature, base K (affine)
    "K": ("temperature", 1.0, 0.0),
    "C": ("temperature", 1.0, 273.15),
    "F": ("temperature", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
}


def convert(value: float | NDArray[Any], from_unit: str, to_unit: str) -> NDArray[Any]:
    """Convert numeric values between units of the same group (REQ-73).

    Parameters
    ----------
    value : float or numpy.ndarray
        Value(s) expressed in ``from_unit``.
    from_unit : str
        Source unit symbol, e.g. ``"ft"``.
    to_unit : str
        Target unit symbol, e.g. ``"m"``.

    Returns
    -------
    numpy.ndarray
        The converted value(s).

    Raises
    ------
    DataError
        On an unknown unit or a conversion across physical groups.

    Examples
    --------
    >>> float(convert(1.0, "ft", "m"))
    0.3048
    """
    for unit in (from_unit, to_unit):
        if unit not in _TABLE:
            supported = ", ".join(sorted(_TABLE))
            raise DataError(
                f"unit '{unit}'",
                "convert received a unit outside the curated table",
                f"supported units: {supported}; adding one is a single "
                "table line plus tests (DD-13)",
            )
    group_from, factor_from, offset_from = _TABLE[from_unit]
    group_to, factor_to, offset_to = _TABLE[to_unit]
    if group_from != group_to:
        raise DataError(
            f"units '{from_unit}' ({group_from}) and '{to_unit}' ({group_to})",
            "convert across different physical groups",
            "convert only within a group; check the unit symbols",
        )
    base = np.asarray(value, dtype=float) * factor_from + offset_from
    return np.asarray((base - offset_to) / factor_to)
