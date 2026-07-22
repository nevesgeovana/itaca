"""The VarFrame, ITACA's central data structure (SRS 4.1; DD-03).

A frozen composition of NumPy arrays plus metadata. Every operation
returns a new VarFrame, records itself in History, and declares its
UncFrame effect (REQ-18, REQ-98). Arrays are read-only (REQ-102).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from itaca.core.coords import Cartesian, CoordSystem
from itaca.core.correlation import CorrelationMatrix
from itaca.core.dimension import Dimension
from itaca.core.errors import (
    DataError,
    ProvenanceError,
    UncertaintyError,
    UncertaintyKeyError,
)
from itaca.core.history import History, compute_state_hash
from itaca.core.historyframe import HistoryFrame
from itaca.core.provenance import Provenance, validate_mode
from itaca.core.uncframe import UncFrame
from itaca.core.variable import Variable


@dataclass(frozen=True, eq=False)
class VarFrame:
    """The primary multidimensional data structure (SRS 4.1).

    Parameters
    ----------
    dims : mapping of str to Dimension
        Ordered dimensions; the order dictates every variable's shape.
    vars : mapping of str to Variable
        Variables; every array has the shape given by ``dims``.
    provenance : Provenance
        Static origin record (SRS 4.4.1).
    history : History, optional
        Ordered operation record; empty by default (SRS 4.4.2).
    uncertainty : UncFrame or None, optional
        Uncertainty mirror; ``None`` until assigned (REQ-91).
    tags : HistoryFrame or None, optional
        Origin-tag mirror; ``None`` until an operation derives values.
    coords : CoordSystem, optional
        Spatial coordinate tag; Cartesian by default.
    correlation : CorrelationMatrix or None, optional
        Declared correlation structure; ``None`` means independence.

    Raises
    ------
    DataError
        On key/name mismatches, shape mismatches, or tag inconsistency.
    UncertaintyKeyError
        If the uncertainty mirror names an unknown variable.
    UncertaintyError
        If an uncertainty array shape disagrees with the dimensions.

    Examples
    --------
    >>> import numpy as np
    >>> from datetime import datetime, timezone
    >>> db = VarFrame(
    ...     dims={"alpha": Dimension(name="alpha", coords=np.array([0.0, 2.0]))},
    ...     vars={"CT": Variable(name="CT", values=np.zeros(2))},
    ...     provenance=Provenance(
    ...         itaca_version="0.1.0.dev0", user="u@h",
    ...         created_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
    ...         source_files=(), source_hash="0" * 64, mode="production",
    ...     ),
    ... )
    >>> db.shape
    (2,)
    """

    dims: Mapping[str, Dimension]
    vars: Mapping[str, Variable]
    provenance: Provenance
    history: History = field(default_factory=History)
    uncertainty: UncFrame | None = None
    tags: HistoryFrame | None = None
    coords: CoordSystem = field(default_factory=Cartesian)
    correlation: CorrelationMatrix | None = None

    def __post_init__(self) -> None:
        dims = MappingProxyType(dict(self.dims))
        variables = MappingProxyType(dict(self.vars))
        for key, dim in dims.items():
            if dim.name != key:
                raise DataError(
                    f"Dimension '{dim.name}'",
                    f"registration under the mapping key '{key}'",
                    "the mapping key must equal the object's name",
                )
        for key, var in variables.items():
            if var.name != key:
                raise DataError(
                    f"Variable '{var.name}'",
                    f"registration under the mapping key '{key}'",
                    "the mapping key must equal the object's name",
                )
        expected = tuple(d.cardinality for d in dims.values())
        for key, var in variables.items():
            if var.values.shape != expected:
                raise DataError(
                    f"Variable '{key}'",
                    f"construction with shape {var.values.shape} against "
                    f"dimension shape {expected}",
                    "align the array with the dimension order (SRS 4.1.1)",
                )
        if self.uncertainty is not None:
            self._validate_mirror_shapes(self.uncertainty, variables, expected)
        if self.tags is not None:
            for name, array in self.tags.tags.items():
                if name not in variables:
                    raise DataError(
                        f"origin tags for '{name}'",
                        "attachment to a VarFrame without that variable",
                        "tag only variables present in the VarFrame",
                    )
                if array.shape != expected:
                    raise DataError(
                        f"origin tags of '{name}'",
                        f"construction with shape {array.shape} against "
                        f"dimension shape {expected}",
                        "tags mirror the variable shape exactly (SRS 4.3)",
                    )
        object.__setattr__(self, "dims", dims)
        object.__setattr__(self, "vars", variables)

    @staticmethod
    def _validate_mirror_shapes(
        uncertainty: UncFrame,
        variables: Mapping[str, Variable],
        expected: tuple[int, ...],
    ) -> None:
        for name in uncertainty.variables():
            if name not in variables:
                raise UncertaintyKeyError(
                    f"uncertainty for '{name}'",
                    "attachment to a VarFrame without that variable",
                    "assign uncertainty only to existing variables (REQ-39)",
                )
        for component in (uncertainty.systematic, uncertainty.random):
            for name, array in component.items():
                if array.shape != expected:
                    raise UncertaintyError(
                        f"uncertainty of '{name}'",
                        f"construction with shape {array.shape} against "
                        f"dimension shape {expected}",
                        "the UncFrame mirrors the parent shape (SRS 4.2)",
                    )

    @property
    def shape(self) -> tuple[int, ...]:
        """Shape dictated by the dimension order (SRS 4.1.1)."""
        return tuple(d.cardinality for d in self.dims.values())

    @property
    def mode(self) -> str:
        """Operating mode from Provenance (REQ-08)."""
        return self.provenance.mode

    @property
    def state_hash(self) -> str:
        """Canonical hash of the current state (REQ-103)."""
        operations = tuple((e.operation, e.comment) for e in self.history)
        return compute_state_hash(
            dims=self.dims,
            variables=self.vars,
            operations=operations,
            uncertainty=self.uncertainty,
            correlation=self.correlation,
            tags=self.tags,
        )

    def promote(
        self, mode: str = "production", *, comment: str | None = None
    ) -> VarFrame:
        """Return a copy promoted to the given mode (REQ-12).

        Mode transitions are always recorded in History: they are the
        audit boundary between exploration and official results.

        Parameters
        ----------
        mode : str, optional
            Target mode, ``"production"`` by default.
        comment : str or None, optional
            User comment stored with the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new object; ``self`` is unchanged.

        Raises
        ------
        ProvenanceError
            If ``mode`` is invalid or equals the current mode (no
            silent no-ops).
        """
        return self._with_mode(mode, "promote", comment)

    def demote(self, mode: str = "draft", *, comment: str | None = None) -> VarFrame:
        """Return a copy demoted to the given mode (REQ-12).

        Parameters
        ----------
        mode : str, optional
            Target mode, ``"draft"`` by default.
        comment : str or None, optional
            User comment stored with the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new object; ``self`` is unchanged.

        Raises
        ------
        ProvenanceError
            If ``mode`` is invalid or equals the current mode.
        """
        return self._with_mode(mode, "demote", comment)

    def _with_mode(self, mode: str, verb: str, comment: str | None) -> VarFrame:
        validate_mode(mode)
        if mode == self.mode:
            raise ProvenanceError(
                f"VarFrame already in mode '{self.mode}'",
                f"{verb} to the same mode",
                "call promote/demote only to change mode; there is no silent no-op",
            )
        operation = f"{verb}(mode='{mode}')"
        operations = (
            *((e.operation, e.comment) for e in self.history),
            (operation, comment),
        )
        new_hash = compute_state_hash(
            dims=self.dims,
            variables=self.vars,
            operations=operations,
            uncertainty=self.uncertainty,
            correlation=self.correlation,
            tags=self.tags,
        )
        return dataclasses.replace(
            self,
            provenance=dataclasses.replace(self.provenance, mode=mode),
            history=self.history.append(
                operation=operation, state_hash=new_hash, comment=comment
            ),
        )

    def __str__(self) -> str:
        marker = "DRAFT " if self.mode == "draft" else ""
        dims_desc = (
            ", ".join(f"{n}: {d.cardinality}" for n, d in self.dims.items()) or "none"
        )
        return (
            f"<ITACA {marker}VarFrame | mode={self.mode} | "
            f"dims [{dims_desc}] | {len(self.vars)} vars | "
            f"history: {len(self.history)} entries>"
        )
