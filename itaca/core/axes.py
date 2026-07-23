"""Axes and custom coordinate frames (REQ-38, REQ-100, REQ-101; SRS 4.6).

An ``Axis`` is a first-class coordinate frame, defined either by a
constant 3x3 orthogonal ``rotation_matrix`` from the canonical body
axis or parametrically via ``angles_from`` with a named angle
convention, in which case the matrix is evaluated per grid point
(REQ-101). Parametric frames also expose the analytical sensitivity
``dR/dangle`` so that angle uncertainty enters rotation propagation by
the chain rule.

The built-in ``"wind"`` and ``"stability"`` frames follow AIAA
R-004A-1992. The exact sign convention of the direction-cosine
matrices is the standard Etkin body-to-wind form and is pending
Geovana's SME acceptance (numerical-analyst and domain-expert seats),
like the wind-tunnel processors of the stretch lane.

This module is NumPy-only (DD-02).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    AxisNotFoundError,
    RotationMatrixError,
    VectorGroupError,
)

_Matrix = NDArray[np.float64]

# Angle conventions the built-in and user parametric frames may use;
# each maps its ordered angle names to a matrix builder and a
# per-angle derivative builder.
CONVENTIONS: tuple[str, ...] = ("stability", "wind")


def _stability_matrix(alpha: float) -> _Matrix:
    """Body-to-stability DCM: rotation by alpha about body y (AIAA R-004A)."""
    ca, sa = np.cos(alpha), np.sin(alpha)
    return np.array([[ca, 0.0, sa], [0.0, 1.0, 0.0], [-sa, 0.0, ca]], dtype=float)


def _d_stability_matrix(alpha: float) -> _Matrix:
    ca, sa = np.cos(alpha), np.sin(alpha)
    return np.array([[-sa, 0.0, ca], [0.0, 0.0, 0.0], [-ca, 0.0, -sa]], dtype=float)


def _wind_matrix(alpha: float, beta: float) -> _Matrix:
    """Body-to-wind DCM: alpha then beta (AIAA R-004A, Etkin convention)."""
    ca, sa = np.cos(alpha), np.sin(alpha)
    cb, sb = np.cos(beta), np.sin(beta)
    return np.array(
        [
            [ca * cb, sb, sa * cb],
            [-ca * sb, cb, -sa * sb],
            [-sa, 0.0, ca],
        ],
        dtype=float,
    )


def _d_wind_matrix(alpha: float, beta: float) -> dict[str, _Matrix]:
    ca, sa = np.cos(alpha), np.sin(alpha)
    cb, sb = np.cos(beta), np.sin(beta)
    d_alpha = np.array(
        [
            [-sa * cb, 0.0, ca * cb],
            [sa * sb, 0.0, -ca * sb],
            [-ca, 0.0, -sa],
        ],
        dtype=float,
    )
    d_beta = np.array(
        [
            [-ca * sb, cb, -sa * sb],
            [-ca * cb, -sb, -sa * cb],
            [0.0, 0.0, 0.0],
        ],
        dtype=float,
    )
    return {"alpha": d_alpha, "beta": d_beta}


def _convention_angles(convention: str) -> tuple[str, ...]:
    return {"stability": ("alpha",), "wind": ("alpha", "beta")}[convention]


@dataclass(frozen=True, eq=False)
class Axis:
    """A named coordinate frame relative to the canonical body axis.

    Exactly one of ``rotation_matrix`` and ``angles_from`` must be
    provided (REQ-101).

    Parameters
    ----------
    name : str
        Frame name, e.g. ``"stability"``, ``"rig"``.
    rotation_matrix : numpy.ndarray or None, optional
        Constant 3x3 orthogonal matrix from body axis; stored
        read-only.
    angles_from : tuple of str or None, optional
        Names of the VarFrame dimensions or variables the parametric
        frame reads its angles from, in the convention's order.
    convention : str or None, optional
        Angle convention for a parametric frame (``"stability"`` or
        ``"wind"``).
    parent : Axis or None, optional
        Parent frame for chained transforms (reserved).
    description : str or None, optional
        Free-text description.

    Raises
    ------
    RotationMatrixError
        Neither or both definitions given, a non-3x3 or non-orthogonal
        matrix, or an unknown convention.

    Examples
    --------
    >>> import numpy as np
    >>> rig = Axis(name="rig", rotation_matrix=np.eye(3))
    >>> rig.is_constant
    True
    """

    name: str
    rotation_matrix: _Matrix | None = None
    angles_from: tuple[str, ...] | None = None
    convention: str | None = None
    parent: Axis | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        has_matrix = self.rotation_matrix is not None
        has_angles = self.angles_from is not None
        if has_matrix == has_angles:
            raise RotationMatrixError(
                f"Axis '{self.name}'",
                "definition gives neither or both of rotation_matrix and angles_from",
                "provide exactly one of rotation_matrix or angles_from (REQ-101)",
            )
        if has_matrix:
            matrix = np.asarray(self.rotation_matrix, dtype=float)
            if matrix.shape != (3, 3):
                raise RotationMatrixError(
                    f"Axis '{self.name}'",
                    f"rotation_matrix has shape {matrix.shape}, not 3x3",
                    "provide a 3x3 rotation matrix (REQ-101)",
                )
            if not np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-9):
                raise RotationMatrixError(
                    f"Axis '{self.name}'",
                    "rotation_matrix is not orthogonal (R R^T != I)",
                    "provide an orthogonal rotation matrix (REQ-101)",
                )
            matrix = matrix.copy()
            matrix.setflags(write=False)
            object.__setattr__(self, "rotation_matrix", matrix)
        else:
            if self.convention not in CONVENTIONS:
                raise RotationMatrixError(
                    f"Axis '{self.name}'",
                    f"unknown angle convention {self.convention!r}",
                    f"use one of {list(CONVENTIONS)} (REQ-101)",
                )
            expected = _convention_angles(self.convention)
            if len(self.angles_from or ()) != len(expected):
                raise RotationMatrixError(
                    f"Axis '{self.name}'",
                    f"convention {self.convention!r} needs {len(expected)} "
                    f"angle(s), got {len(self.angles_from or ())}",
                    f"pass angles_from with {expected} order (REQ-101)",
                )

    @property
    def is_constant(self) -> bool:
        """True when the frame is a constant matrix (not parametric)."""
        return self.rotation_matrix is not None

    def _angle_values(self, angles: Mapping[str, float]) -> list[float]:
        assert self.angles_from is not None
        values: list[float] = []
        for name in self.angles_from:
            if name not in angles:
                raise VectorGroupError(
                    f"Axis '{self.name}'",
                    f"parametric frame needs a value for angle '{name}'",
                    f"provide {list(self.angles_from)} at evaluation (REQ-101)",
                )
            values.append(float(angles[name]))
        return values

    def matrix_at(self, angles: Mapping[str, float]) -> _Matrix:
        """Return the 3x3 rotation matrix at the given angle values.

        Parameters
        ----------
        angles : mapping of str to float
            Values for the ``angles_from`` names; ignored for a
            constant frame.

        Returns
        -------
        numpy.ndarray
            The 3x3 direction cosine matrix.
        """
        if self.rotation_matrix is not None:
            return np.array(self.rotation_matrix, dtype=float)
        values = self._angle_values(angles)
        if self.convention == "stability":
            return _stability_matrix(values[0])
        return _wind_matrix(values[0], values[1])

    def d_matrix_d_angle(self, angles: Mapping[str, float]) -> dict[str, _Matrix]:
        """Analytical sensitivities ``dR/dangle`` at the given point.

        Returns an empty dict for a constant frame (REQ-101 chain rule).
        """
        if self.rotation_matrix is not None:
            return {}
        values = self._angle_values(angles)
        assert self.angles_from is not None
        if self.convention == "stability":
            return {self.angles_from[0]: _d_stability_matrix(values[0])}
        grads = _d_wind_matrix(values[0], values[1])
        return {
            self.angles_from[0]: grads["alpha"],
            self.angles_from[1]: grads["beta"],
        }


def body_axis() -> Axis:
    """Return the canonical body axis (identity frame)."""
    return Axis(
        name="body",
        rotation_matrix=np.eye(3),
        description="canonical AIAA R-004A body axis",
    )


def stability_axis() -> Axis:
    """Return the stability frame (parametric in alpha; AIAA R-004A)."""
    return Axis(
        name="stability",
        angles_from=("alpha",),
        convention="stability",
        description="body-to-stability, rotation by alpha (AIAA R-004A)",
    )


def wind_axis() -> Axis:
    """Return the wind frame (parametric in alpha and beta; AIAA R-004A)."""
    return Axis(
        name="wind",
        angles_from=("alpha", "beta"),
        convention="wind",
        description="body-to-wind, alpha then beta (AIAA R-004A)",
    )


@dataclass(frozen=True)
class AxisRegistry:
    """Immutable registry of named frames and vector-group declarations.

    Every mutating call returns a new registry (DD-03). Vector groups
    name the component triplets that ``db.rotate`` transforms.

    Examples
    --------
    >>> import numpy as np
    >>> reg = AxisRegistry().with_axis(Axis(name="rig", rotation_matrix=np.eye(3)))
    >>> reg.resolve("rig").name
    'rig'
    """

    axes: Mapping[str, Axis] = field(default_factory=dict)
    vector_groups: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", MappingProxyType(dict(self.axes)))
        object.__setattr__(
            self, "vector_groups", MappingProxyType(dict(self.vector_groups))
        )

    @classmethod
    def with_builtins(cls) -> AxisRegistry:
        """Return a registry preloaded with body, stability, and wind."""
        builtins = {a.name: a for a in (body_axis(), stability_axis(), wind_axis())}
        return cls(axes=builtins)

    def with_axis(self, axis: Axis) -> AxisRegistry:
        """Return a new registry with ``axis`` added.

        Raises
        ------
        RotationMatrixError
            A frame of the same name is already registered.
        """
        if axis.name in self.axes:
            raise RotationMatrixError(
                f"axis '{axis.name}'",
                "a frame of that name is already registered",
                "choose a distinct axis name, or resolve the existing one",
            )
        return AxisRegistry(
            axes={**self.axes, axis.name: axis}, vector_groups=self.vector_groups
        )

    def with_vector_group(self, name: str, components: Sequence[str]) -> AxisRegistry:
        """Return a new registry declaring a named component triplet.

        Raises
        ------
        VectorGroupError
            The group does not have exactly three components.
        """
        comps = tuple(components)
        if len(comps) != 3:
            raise VectorGroupError(
                f"vector group '{name}'",
                f"declared with {len(comps)} components, not three",
                "a vector group is a triplet (x, y, z) (REQ-38)",
            )
        return AxisRegistry(
            axes=self.axes,
            vector_groups={**self.vector_groups, name: comps},
        )

    def resolve(self, name: str) -> Axis:
        """Return the registered frame, or raise ``AxisNotFoundError``."""
        if name not in self.axes:
            raise AxisNotFoundError(
                f"axis '{name}'",
                "rotate referenced an unregistered frame",
                f"register it first, or use one of {sorted(self.axes)} (REQ-38)",
            )
        return self.axes[name]
