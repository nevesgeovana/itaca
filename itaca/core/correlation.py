"""Correlation declaration and storage (SRS 4.2, REQ-40; DD-14).

Correlation coefficients between pairs of variables, declared via
``db.set_correlation`` (Phase 4) and consulted by every propagation.
Default is full independence; the pair store is canonical (sorted
pair keys) so symmetry holds by construction.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

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
        declared, duplicate declarations conflict, or the assembled
        matrix is not positive semidefinite (REQ-40).

    Notes
    -----
    The pairwise bound ``|r| <= 1`` is necessary but not sufficient:
    three variables each declared at ``r = -0.9`` satisfy it pairwise
    while the assembled matrix has eigenvalue ``-0.8``, which is not a
    correlation matrix and makes the variance of ``a + b + c``
    negative. Validation therefore assembles the matrix over the
    closure of declared names and refuses a materially negative
    eigenvalue.

    Checking at declaration time is both sufficient and complete.
    Every consumer forms ``Cov = D C D`` with ``D = diag(u) >= 0``,
    which is positive semidefinite whenever ``C`` is; and extending
    ``C`` to any larger variable set appends an identity block, whose
    spectrum adds only ones. The cost is one ``eigvalsh`` per
    construction, cubic in the number of names that appear in a pair,
    not in the number of variables in the frame.

    Examples
    --------
    >>> corr = CorrelationMatrix(pairs={("FX", "FZ"): 0.3})
    >>> corr.get("FZ", "FX")
    0.3
    >>> CorrelationMatrix(
    ...     pairs={("a", "b"): -0.9, ("a", "c"): -0.9, ("b", "c"): -0.9}
    ... )
    Traceback (most recent call last):
    itaca.core.errors.CorrelationMatrixError: ...positive semidefinite...
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
        _reject_non_psd(canonical)
        object.__setattr__(self, "pairs", MappingProxyType(canonical))

    def get(self, name_a: str, name_b: str) -> float:
        """Return ``r(a, b)``: 1 on the diagonal, 0 when undeclared."""
        if name_a == name_b:
            return 1.0
        key = (name_a, name_b) if name_a < name_b else (name_b, name_a)
        return self.pairs.get(key, 0.0)

    def restrict(self, names: Collection[str]) -> CorrelationMatrix | None:
        """Keep only pairs whose both members are in ``names``.

        Parameters
        ----------
        names : collection of str
            The variables that survive an operation.

        Returns
        -------
        CorrelationMatrix or None
            ``None`` when no pair survives, which is the documented
            representation of full independence and hashes identically
            to an empty matrix (REQ-103).

        Notes
        -----
        The result is a principal submatrix of a validated matrix and
        is therefore positive semidefinite, so the constructor check
        cannot fire on it. The class is declared ``eq=False``, so a
        caller deciding whether anything was dropped must compare
        ``dict(result.pairs)`` and never the objects, which compare by
        identity.

        Examples
        --------
        >>> corr = CorrelationMatrix(pairs={("a", "b"): 0.5, ("b", "c"): 0.2})
        >>> sorted(corr.restrict({"a", "b"}).pairs)
        [('a', 'b')]
        """
        kept = {
            pair: value
            for pair, value in self.pairs.items()
            if pair[0] in names and pair[1] in names
        }
        return CorrelationMatrix(pairs=kept) if kept else None

    def without(self, names: Collection[str]) -> CorrelationMatrix | None:
        """Drop every pair naming any member of ``names``.

        Parameters
        ----------
        names : collection of str
            The variables whose declarations no longer describe the
            values stored under their names.

        Returns
        -------
        CorrelationMatrix or None
            ``None`` when no pair survives.

        Notes
        -----
        Same principal-submatrix and ``eq=False`` notes as
        :meth:`restrict`.

        Examples
        --------
        >>> corr = CorrelationMatrix(pairs={("a", "b"): 0.5, ("b", "c"): 0.2})
        >>> sorted(corr.without({"a"}).pairs)
        [('b', 'c')]
        """
        kept = {
            pair: value
            for pair, value in self.pairs.items()
            if pair[0] not in names and pair[1] not in names
        }
        return CorrelationMatrix(pairs=kept) if kept else None


def _reject_non_psd(canonical: Mapping[tuple[str, str], float]) -> None:
    """Refuse a declared set whose assembled matrix is not PSD (REQ-40)."""
    names = sorted({name for pair in canonical for name in pair})
    if not names:
        return
    index = {name: position for position, name in enumerate(names)}
    matrix = np.eye(len(names))
    for (name_a, name_b), value in canonical.items():
        matrix[index[name_a], index[name_b]] = value
        matrix[index[name_b], index[name_a]] = value
    eigenvalues = np.linalg.eigvalsh(matrix)
    smallest = float(eigenvalues[0])
    tolerance = (
        10.0
        * len(names)
        * float(np.finfo(float).eps)
        * max(1.0, float(np.abs(eigenvalues).max()))
    )
    if smallest < -tolerance:
        raise CorrelationMatrixError(
            f"correlation matrix over {names}",
            f"declaration whose assembled matrix has smallest eigenvalue "
            f"{smallest:.6g}, which is not positive semidefinite",
            "a correlation matrix must be positive semidefinite; check the "
            "pairwise coefficients (three unit variables sharing one r need "
            "r >= -0.5) (REQ-40)",
        )
