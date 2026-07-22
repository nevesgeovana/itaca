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
