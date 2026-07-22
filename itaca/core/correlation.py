"""Correlation declaration and storage (SRS 4.2, REQ-40; DD-14).

Correlation coefficients between pairs of variables, declared via
``db.set_correlation`` (Phase 4) and consulted by every propagation.
Default is full independence; the pair store is canonical (sorted
pair keys) so symmetry holds by construction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from itaca.core.errors import CorrelationMatrixError


@dataclass(frozen=True, eq=False)
class CorrelationMatrix:
    """Pairwise correlation coefficients between variables.

    Parameters
    ----------
    pairs : mapping of (str, str) to float
        Correlation coefficients ``r(a, b)``. Keys are canonicalized to
        sorted order; declaring both orientations is allowed only when
        the values agree.

    Raises
    ------
    CorrelationMatrixError
        If a coefficient violates ``|r| <= 1``, a self-pair is
        declared, or duplicate declarations conflict (REQ-40).

    Examples
    --------
    >>> corr = CorrelationMatrix(pairs={("FX", "FZ"): 0.3})
    >>> corr.get("FZ", "FX")
    0.3
    """

    pairs: Mapping[tuple[str, str], float]

    def __post_init__(self) -> None:
        canonical: dict[tuple[str, str], float] = {}
        for (name_a, name_b), value in self.pairs.items():
            if name_a == name_b:
                raise CorrelationMatrixError(
                    f"correlation pair ({name_a!r}, {name_b!r})",
                    "declaration of a self-correlation",
                    "self-correlation is 1 by definition; declare distinct pairs only",
                )
            if not -1.0 <= value <= 1.0:
                raise CorrelationMatrixError(
                    f"correlation pair ({name_a!r}, {name_b!r})",
                    f"declaration with r={value!r} outside [-1, 1]",
                    "correlation coefficients satisfy |r| <= 1 (REQ-40)",
                )
            key = (name_a, name_b) if name_a < name_b else (name_b, name_a)
            if key in canonical and canonical[key] != float(value):
                raise CorrelationMatrixError(
                    f"correlation pair ({key[0]!r}, {key[1]!r})",
                    f"conflicting declarations {canonical[key]!r} and {value!r}",
                    "declare each pair once, or with consistent values",
                )
            canonical[key] = float(value)
        object.__setattr__(self, "pairs", MappingProxyType(canonical))

    def get(self, name_a: str, name_b: str) -> float:
        """Return ``r(a, b)``: 1 on the diagonal, 0 when undeclared."""
        if name_a == name_b:
            return 1.0
        key = (name_a, name_b) if name_a < name_b else (name_b, name_a)
        return self.pairs.get(key, 0.0)
