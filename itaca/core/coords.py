"""Spatial coordinate-system tags (SRS Chapter 5).

The tag affects integration (polar area element, REQ-28, from M1
onward). In M0 it is carried and persisted, nothing more.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import ClassVar


class CoordSystem(ABC):
    """Abstract base for the spatial coordinate-system tag."""

    name: ClassVar[str]


@dataclass(frozen=True)
class Cartesian(CoordSystem):
    """Cartesian spatial coordinates (the default)."""

    name: ClassVar[str] = "cartesian"


@dataclass(frozen=True)
class Polar(CoordSystem):
    """Polar spatial coordinates (r, theta); affects integration."""

    name: ClassVar[str] = "polar"


COORD_SYSTEMS: dict[str, type[CoordSystem]] = {
    Cartesian.name: Cartesian,
    Polar.name: Polar,
}
"""Name to class, for persistence and for the state hash (FND-037).

The tag was in neither the ``.itc`` schema nor ``compute_state_hash``,
so a Cartesian and a Polar frame shared a digest and a Polar frame
reopened Cartesian, silently changing the integration element it
selects. Reading the tag back needs a name-to-class map, and it lives
beside the classes so a third system cannot be added without one.
"""


def coord_system(name: str) -> CoordSystem:
    """Return the coordinate system a persisted name refers to.

    Parameters
    ----------
    name : str
        A name from ``COORD_SYSTEMS``, as written into a ``.itc``.

    Returns
    -------
    CoordSystem
        The corresponding tag instance.

    Raises
    ------
    DataError
        If the name is unknown. An unknown tag is refused rather than
        defaulted: defaulting to Cartesian is FND-037 itself, and a
        defect must not be the remedy for a defect.

    Examples
    --------
    >>> coord_system("polar").name
    'polar'
    """
    from itaca.core.errors import DataError

    if name not in COORD_SYSTEMS:
        raise DataError(
            f"coordinate system {name!r}",
            "it names no coordinate system this build knows",
            f"expected one of {sorted(COORD_SYSTEMS)}; the archive was "
            "hand-edited or written by a newer ITACA (REQ-70)",
        )
    return COORD_SYSTEMS[name]()
