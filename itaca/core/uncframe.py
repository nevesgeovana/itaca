"""The UncFrame uncertainty mirror (SRS 4.2; DD-05, DD-19).

Structurally a VarFrame restricted to standard uncertainties: same
dimensions, same variable names as its parent. Two components are
stored per variable: systematic (fully correlated across points) and
random (independent between points), per AIAA S-071A-1999. They
recombine as RSS at reporting time (REQ-99).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import UncertaintyError, UncertaintyKeyError


def _normalize(
    component: Mapping[str, NDArray[Any]], label: str
) -> Mapping[str, NDArray[Any]]:
    normalized: dict[str, NDArray[Any]] = {}
    for name, values in component.items():
        array = np.asarray(values, dtype=float)
        finite = array[np.isfinite(array)]
        if finite.size and np.any(finite < 0):
            raise UncertaintyError(
                f"{label} uncertainty of variable '{name}'",
                "assignment of a negative standard uncertainty",
                "standard uncertainties are non-negative (GUM clause 2.3.1)",
            )
        array = array.copy()
        array.setflags(write=False)
        normalized[name] = array
    return MappingProxyType(normalized)


@dataclass(frozen=True, eq=False)
class UncFrame:
    """Two-component standard-uncertainty mirror of a VarFrame.

    Parameters
    ----------
    systematic : mapping of str to numpy.ndarray, optional
        Systematic component per variable (calibration and installation
        biases; fully correlated across points).
    random : mapping of str to numpy.ndarray, optional
        Random component per variable (measurement scatter; independent
        between points).

    Raises
    ------
    UncertaintyError
        If any assigned standard uncertainty is negative.

    Examples
    --------
    >>> import numpy as np
    >>> unc = UncFrame(systematic={"CT": np.full(3, 3.0)},
    ...                random={"CT": np.full(3, 4.0)})
    >>> unc.combined("CT")
    array([5., 5., 5.])
    """

    systematic: Mapping[str, NDArray[Any]] = field(default_factory=dict)
    random: Mapping[str, NDArray[Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "systematic", _normalize(self.systematic, "systematic")
        )
        object.__setattr__(self, "random", _normalize(self.random, "random"))

    def variables(self) -> tuple[str, ...]:
        """Sorted names of all variables carrying any component."""
        return tuple(sorted(set(self.systematic) | set(self.random)))

    def combined(self, name: str) -> NDArray[Any]:
        """Return the RSS-combined standard uncertainty of a variable.

        Parameters
        ----------
        name : str
            Variable name.

        Returns
        -------
        numpy.ndarray
            ``sqrt(u_sys**2 + u_rand**2)``; a missing component counts
            as zero (REQ-99).

        Raises
        ------
        UncertaintyKeyError
            If the variable carries no uncertainty component at all.
        """
        if name not in self.systematic and name not in self.random:
            raise UncertaintyKeyError(
                f"variable '{name}'",
                "combined uncertainty requested but no component is assigned",
                f"assign one via set_uncertainty; known: {self.variables()}",
            )
        total: NDArray[Any] | None = None
        for component in (self.systematic, self.random):
            if name in component:
                squared = np.square(component[name])
                total = squared if total is None else total + squared
        assert total is not None
        return np.asarray(np.sqrt(total))
