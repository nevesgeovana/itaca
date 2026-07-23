"""Axes and custom coordinate frames (REQ-38, REQ-100, REQ-101; SRS 4.6).

An ``Axis`` is a first-class coordinate frame, defined either by a
constant 3x3 orthogonal ``rotation_matrix`` from the canonical body
axis or parametrically via ``angles_from`` with a named angle
convention, in which case the matrix is evaluated per grid point
(REQ-101). Parametric frames also expose the analytical sensitivity
``dR/dangle`` so that angle uncertainty enters rotation propagation by
the chain rule.

The built-in ``"wind"`` and ``"stability"`` frames follow AIAA
R-004A-1992 in the standard Etkin body-to-wind form
(``v_target = L @ v_body``; stability = active ``Ry(alpha)``, wind =
active ``Rz(-beta) @ Ry(alpha)``), SME-accepted by Geovana at the M1
Phase B2 checkpoint (2026-07-23) and cross-validated against scipy
(DD-26). The elementary factors below are the coordinate (transposed)
form, so this module writes wind as ``Rz(beta) @ Ry(alpha)``.

This module is NumPy-only (DD-02).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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

# A convention is a general direction-cosine matrix built by composing
# elementary coordinate rotations (DD-26: pure-NumPy general
# formulation, scipy is only a dev-only test oracle). Each convention
# is an ordered sequence of (axis, angle-position) factors whose matrix
# product, left to right, is the body-to-frame DCM. The angle-position
# indexes into the frame's angles_from tuple.
#
# ``_elementary(axis, theta)`` is the body-to-frame (coordinate /
# transposed) elementary factor, so this module's ``Rz(beta)`` equals
# the standard active ``Rz(-beta)`` (the scipy oracle confirms it):
#
#   stability:  Ry(alpha)                 (AIAA R-004A)
#   wind:       Rz(beta) @ Ry(alpha)      = active Rz(-beta) @ Ry(alpha)
_CONVENTION_SEQ: dict[str, tuple[tuple[int, int], ...]] = {
    "stability": ((1, 0),),
    "wind": ((2, 1), (1, 0)),
}
_CONVENTION_ANGLES: dict[str, tuple[str, ...]] = {
    "stability": ("alpha",),
    "wind": ("alpha", "beta"),
}
CONVENTIONS: tuple[str, ...] = tuple(_CONVENTION_SEQ)


def _elementary(axis: int, theta: float) -> _Matrix:
    """Elementary coordinate rotation about ``axis`` (0=x, 1=y, 2=z)."""
    c, s = np.cos(theta), np.sin(theta)
    if axis == 0:
        return np.array([[1.0, 0.0, 0.0], [0.0, c, s], [0.0, -s, c]], dtype=float)
    if axis == 1:
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=float)
    return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def _d_elementary(axis: int, theta: float) -> _Matrix:
    """Differentiate the elementary rotation with respect to ``theta``."""
    c, s = np.cos(theta), np.sin(theta)
    if axis == 0:
        return np.array([[0.0, 0.0, 0.0], [0.0, -s, c], [0.0, -c, -s]], dtype=float)
    if axis == 1:
        return np.array([[-s, 0.0, c], [0.0, 0.0, 0.0], [-c, 0.0, -s]], dtype=float)
    return np.array([[-s, c, 0.0], [-c, -s, 0.0], [0.0, 0.0, 0.0]], dtype=float)


def _compose_matrix(convention: str, values: Sequence[float]) -> _Matrix:
    """Body-to-frame DCM: product of the convention's elementary factors."""
    matrix = np.eye(3)
    for axis, pos in _CONVENTION_SEQ[convention]:
        matrix = matrix @ _elementary(axis, values[pos])
    return matrix


def _compose_derivatives(
    convention: str, values: Sequence[float]
) -> dict[int, _Matrix]:
    """Per-angle sensitivities of the composed DCM (product rule)."""
    factors = _CONVENTION_SEQ[convention]
    grads: dict[int, _Matrix] = {}
    for target in range(len(factors)):
        matrix = np.eye(3)
        for i, (axis, pos) in enumerate(factors):
            block = (
                _d_elementary(axis, values[pos])
                if i == target
                else _elementary(axis, values[pos])
            )
            matrix = matrix @ block
        _, angle_pos = factors[target]
        grads[angle_pos] = grads.get(angle_pos, np.zeros((3, 3))) + matrix
    return grads


def _convention_angles(convention: str) -> tuple[str, ...]:
    return _CONVENTION_ANGLES[convention]


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
        if self.parent is not None:
            raise NotImplementedError(
                f"Axis '{self.name}': chained transforms via parent are "
                "not implemented yet; leave parent=None (REQ-38)"
            )
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
            if not np.isclose(np.linalg.det(matrix), 1.0, atol=1e-9):
                raise RotationMatrixError(
                    f"Axis '{self.name}'",
                    f"rotation_matrix is a reflection (det = "
                    f"{np.linalg.det(matrix):.3f}, not +1), not a proper "
                    "rotation",
                    "provide a proper rotation matrix (det = +1) (REQ-101)",
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
            Values (in radians) for the ``angles_from`` names; ignored
            for a constant frame.

        Returns
        -------
        numpy.ndarray
            The 3x3 direction cosine matrix.

        Raises
        ------
        VectorGroupError
            A required angle is missing from ``angles``.

        Examples
        --------
        >>> import numpy as np
        >>> from itaca.core.axes import stability_axis
        >>> m = stability_axis().matrix_at({"alpha": 0.0})
        >>> bool(np.allclose(m, np.eye(3)))
        True
        """
        if self.rotation_matrix is not None:
            return np.array(self.rotation_matrix, dtype=float)
        values = self._angle_values(angles)
        assert self.convention is not None
        return _compose_matrix(self.convention, values)

    def d_matrix_d_angle(self, angles: Mapping[str, float]) -> dict[str, _Matrix]:
        """Analytical sensitivities ``dR/dangle`` at the given point.

        Parameters
        ----------
        angles : mapping of str to float
            Values (in radians) for the ``angles_from`` names.

        Returns
        -------
        dict of str to numpy.ndarray
            The ``dR/dangle`` 3x3 matrix per angle name (REQ-101 chain
            rule); an empty dict for a constant frame.

        Raises
        ------
        VectorGroupError
            A required angle is missing from ``angles``.

        Examples
        --------
        >>> from itaca.core.axes import stability_axis
        >>> sorted(stability_axis().d_matrix_d_angle({"alpha": 0.1}))
        ['alpha']
        """
        if self.rotation_matrix is not None:
            return {}
        values = self._angle_values(angles)
        assert self.angles_from is not None and self.convention is not None
        by_position = _compose_derivatives(self.convention, values)
        return {self.angles_from[pos]: grad for pos, grad in by_position.items()}


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


# The frames every registry knows without explicit registration.
_BUILTINS: dict[str, Callable[[], Axis]] = {
    "body": body_axis,
    "stability": stability_axis,
    "wind": wind_axis,
}


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
    group_axes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", MappingProxyType(dict(self.axes)))
        object.__setattr__(
            self, "vector_groups", MappingProxyType(dict(self.vector_groups))
        )
        object.__setattr__(self, "group_axes", MappingProxyType(dict(self.group_axes)))

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
            An axis of the same name is already registered.
        """
        if axis.name in self.axes:
            raise RotationMatrixError(
                f"axis '{axis.name}'",
                "an axis of that name is already registered",
                "choose a distinct axis name, or resolve the existing one",
            )
        return AxisRegistry(
            axes={**self.axes, axis.name: axis},
            vector_groups=self.vector_groups,
            group_axes=self.group_axes,
        )

    def with_vector_group(
        self, name: str, components: Sequence[str], axis: str = "body"
    ) -> AxisRegistry:
        """Return a new registry declaring a named component triplet.

        Parameters
        ----------
        name : str
            Group name.
        components : sequence of str
            Exactly three component variable names (x, y, z).
        axis : str, optional
            The axis system the components are currently expressed in;
            defaults to the canonical body axis (REQ-107). It must be a
            registered or built-in axis.

        Raises
        ------
        VectorGroupError
            The group does not have exactly three components, or a
            group of the same name is already declared.
        AxisNotFoundError
            ``axis`` is not registered or built in.
        """
        comps = tuple(components)
        if len(comps) != 3:
            raise VectorGroupError(
                f"vector group '{name}'",
                f"declared with {len(comps)} components, not three",
                "a vector group is a triplet (x, y, z) (REQ-38)",
            )
        if name in self.vector_groups:
            raise VectorGroupError(
                f"vector group '{name}'",
                "a group of that name is already declared",
                "choose a distinct group name, or resolve the existing one (REQ-38)",
            )
        if axis != "body":
            self.resolve(axis)
        return AxisRegistry(
            axes=self.axes,
            vector_groups={**self.vector_groups, name: comps},
            group_axes={**self.group_axes, name: axis},
        )

    def group_axis(self, name: str) -> str:
        """Return the source axis system declared for a vector group (REQ-107)."""
        return self.group_axes.get(name, "body")

    def is_empty(self) -> bool:
        """Return True when nothing user-defined is stored (built-ins aside)."""
        return not self.axes and not self.vector_groups

    def canonical_tokens(self) -> list[str]:
        """Deterministic tokens for the state hash (REQ-103).

        An empty registry yields no tokens, so a VarFrame that never
        registers a custom axis keeps the state hash it had before the
        axis registry existed.
        """
        tokens: list[str] = []
        for name in sorted(self.axes):
            axis = self.axes[name]
            if axis.rotation_matrix is not None:
                tokens.append(f"axis|{name}|M|{axis.rotation_matrix.tobytes().hex()}")
            else:
                tokens.append(f"axis|{name}|P|{axis.convention}|{axis.angles_from}")
        for name in sorted(self.vector_groups):
            comps = self.vector_groups[name]
            tokens.append(f"vg|{name}|{comps}|{self.group_axis(name)}")
        return tokens

    def resolve(self, name: str) -> Axis:
        """Return the registered frame, or raise ``AxisNotFoundError``.

        The built-in body, stability, and wind frames resolve without
        explicit registration, so an empty registry (the VarFrame
        default) still knows them and contributes nothing to the state
        hash until the user registers custom frames.
        """
        if name in self.axes:
            return self.axes[name]
        if name in _BUILTINS:
            return _BUILTINS[name]()
        known = sorted({*self.axes, *_BUILTINS})
        raise AxisNotFoundError(
            f"axis '{name}'",
            "an unregistered axis system was referenced",
            f"register it first, or use one of {known} (REQ-38)",
        )
