"""The VarFrame, ITACA's central data structure (SRS 4.1; DD-03).

A frozen composition of NumPy arrays plus metadata. Every operation
returns a new VarFrame, records itself in History, and declares its
UncFrame effect (REQ-18, REQ-98). Arrays are read-only (REQ-102).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import cast

import numpy as np

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

_UNSET: object = object()


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

    def pivot(
        self,
        dims: Sequence[str] | None = None,
        *,
        auto_detect: bool = False,
        threshold: int = 20,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Reorganize a datapoint-mode VarFrame into a structured one.

        Delegates to :func:`itaca.io.pivot.pivot` (REQ-14); the import
        is deferred to call time to keep ``core`` free of module-level
        intra-project dependencies.

        Parameters
        ----------
        dims : sequence of str or None, optional
            Columns that become dimensions, in order.
        auto_detect : bool, optional
            Detect additional dimension candidates (REQ-14).
        threshold : int, optional
            Unique-value bound for auto-detection.
        history : bool, optional
            In draft mode, record the operation only when True.
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new structured VarFrame; ``self`` is unchanged.
        """
        from itaca.io.pivot import pivot as _pivot

        return _pivot(
            self,
            dims=dims,
            auto_detect=auto_detect,
            threshold=threshold,
            history=history,
            comment=comment,
        )

    def _derive(
        self,
        *,
        operation: str,
        comment: str | None,
        history: bool,
        dims: Mapping[str, Dimension] | None = None,
        variables: Mapping[str, Variable] | None = None,
        uncertainty: object = _UNSET,
        tags: object = _UNSET,
        correlation: object = _UNSET,
    ) -> VarFrame:
        """Return a new VarFrame with content replaced and recorded.

        Implements the shared REQ-18 contract: new object, History
        entry with the fresh state hash, draft-mode opt-in recording
        (REQ-10), and explicit mirror handling (DD-18).
        """
        new_dims = self.dims if dims is None else dims
        new_vars = self.vars if variables is None else variables
        new_unc = (
            self.uncertainty
            if uncertainty is _UNSET
            else cast("UncFrame | None", uncertainty)
        )
        new_tags = self.tags if tags is _UNSET else cast("HistoryFrame | None", tags)
        new_correlation = (
            self.correlation
            if correlation is _UNSET
            else cast("CorrelationMatrix | None", correlation)
        )
        record = self.mode == "production" or history
        new_history = self.history
        if record:
            operations = (
                *((e.operation, e.comment) for e in self.history),
                (operation, comment),
            )
            state_hash = compute_state_hash(
                dims=new_dims,
                variables=new_vars,
                operations=operations,
                uncertainty=new_unc,
                correlation=new_correlation,
                tags=new_tags,
            )
            new_history = self.history.append(
                operation=operation, state_hash=state_hash, comment=comment
            )
        return dataclasses.replace(
            self,
            dims=dict(new_dims),
            vars=dict(new_vars),
            uncertainty=new_unc,
            tags=new_tags,
            correlation=new_correlation,
            history=new_history,
        )

    def select(
        self,
        filters: Mapping[str, object],
        Frame: str = "VarFrame",  # noqa: N803  (SRS REQ-20 keyword)
        *,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Restrict to coordinates or cells matching the filters (REQ-20).

        Parameters
        ----------
        filters : mapping
            Keys are ``dim_op`` strings (name plus optional ``=``,
            ``>``, ``>=``, ``<``, ``<=``, ``!=``); values are scalars
            or lists. Dimension keys subset the grid; variable keys
            mask non-matching cells to NaN.
        Frame : str, optional
            Comparison source: ``"VarFrame"`` (values, default),
            ``"UncFrame"`` (standard uncertainty), or
            ``"HistoryFrame"`` (origin tags).
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame; ``self`` is unchanged.
        """
        from itaca.ops.select import select as _select

        return _select(self, filters, frame=Frame, history=history, comment=comment)

    def at(
        self,
        *,
        history: bool = False,
        comment: str | None = None,
        **coords: object,
    ) -> VarFrame:
        """Slice at single coordinates, removing those dims (REQ-21).

        Equivalent to ``select({dim: [value]}).squeeze()`` recorded as
        one History entry.

        Parameters
        ----------
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).
        **coords
            ``dim=value`` pairs.

        Returns
        -------
        VarFrame
            A new VarFrame without the sliced dimensions.
        """
        from itaca.ops.select import at as _at

        return _at(self, coords, history=history, comment=comment)

    def squeeze(
        self,
        along: str | None = None,
        *,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Remove unit-cardinality dimensions (REQ-22).

        Parameters
        ----------
        along : str or None, optional
            Squeeze only the named dimension (its cardinality must be
            1); by default every unit-cardinality dimension.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame; if every dimension was squeezed, a single
            ``datapoint`` dimension with one entry remains.
        """
        from itaca.ops.squeeze import squeeze as _squeeze

        return _squeeze(self, along=along, history=history, comment=comment)

    def fill(
        self,
        along: str,
        method: str = "linear",
        *,
        deg: int | None = None,
        window: int | None = None,
        global_fit: bool = False,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Fill NaN entries along a dimension (REQ-26).

        Parameters
        ----------
        along : str
            Dimension to fill along.
        method : str, optional
            ``"linear"`` (between neighbors, default), ``"nearest"``,
            or ``"polyfit"`` (moving window of ``window`` points and
            degree ``deg``; ``global_fit=True`` fits the full
            dimension instead).
        deg : int or None, optional
            Polynomial degree for ``"polyfit"``.
        window : int or None, optional
            Moving-window size for ``"polyfit"``; must exceed ``deg``.
        global_fit : bool, optional
            Fit one polynomial over the whole dimension.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with filled values tagged ``+1`` (SRS 4.3).
        """
        from itaca.ops.fill import fill as _fill

        return _fill(
            self,
            along=along,
            method=method,
            deg=deg,
            window=window,
            global_fit=global_fit,
            history=history,
            comment=comment,
        )

    def set_uncertainty(
        self,
        spec: Mapping[str, float | str],
        *,
        component: str = "systematic",
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Assign standard uncertainties to variables (REQ-39, REQ-99).

        Parameters
        ----------
        spec : mapping of str to float or str
            Per-variable standard uncertainty: a float is absolute, a
            string ending in ``"%"`` is relative to the values.
        component : str, optional
            ``"systematic"`` (default; fully correlated across points)
            or ``"random"`` (independent between points), per AIAA
            S-071A-1999 (DD-19).
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with the UncFrame created or updated.

        Raises
        ------
        UncertaintyKeyError
            If a key does not match any variable.
        UncertaintyError
            On an invalid component or a malformed relative value.
        """
        from itaca.uncertainty.assign import set_uncertainty as _set

        return _set(self, spec, component=component, history=history, comment=comment)

    def set_correlation(
        self,
        spec: Mapping[tuple[str, str], float],
        *,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Declare correlation coefficients between variables (REQ-40).

        Parameters
        ----------
        spec : mapping of (str, str) to float
            Pairwise coefficients; later declarations override earlier
            ones for the same pair.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with the correlation structure updated.

        Raises
        ------
        CorrelationKeyError
            If a referenced variable is absent.
        CorrelationMatrixError
            If a coefficient violates ``|r| <= 1``.
        """
        from itaca.uncertainty.assign import set_correlation as _set

        return _set(self, spec, history=history, comment=comment)

    def compute(
        self,
        equation: str,
        *,
        debug: bool = False,
        where: str | None = None,
        fill: float | None = np.nan,
        method: str = "symbolic",
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Derive a new variable from a string equation (REQ-33).

        Propagation of both uncertainty components is automatic when
        any expression variable carries uncertainty (REQ-41), with
        correlation terms from ``set_correlation`` (DD-14).

        Parameters
        ----------
        equation : str
            ``"VAR = expression"`` over the REQ-44 operator set.
        debug : bool, optional
            Print the parsed tokens, identified variables, a sample
            evaluation, and the partials before applying (REQ-34).
        where : str or None, optional
            Condition string; the equation applies only where it holds
            (REQ-35).
        fill : float or None, optional
            Value at filtered-out points: NaN (default), a scalar, or
            ``None`` to retain existing values of ``VAR``.
        method : str, optional
            ``"symbolic"`` (default). ``"mcm"`` ships in v0.3.0.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame containing ``VAR`` tagged ``+1``.
        """
        from itaca.ops.compute import compute as _compute

        return _compute(
            self,
            equation,
            debug=debug,
            where=where,
            fill=fill,
            method=method,
            history=history,
            comment=comment,
        )

    def combine(
        self,
        other: VarFrame,
        *,
        op: str,
        weights: tuple[float, float] | None = None,
        cross_correlation: float = 0.0,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Combine two VarFrames under a named operation (REQ-37).

        Python operators (``+ - * /``) are intentionally unsupported
        (DD-12, NREQ-08).

        Parameters
        ----------
        other : VarFrame
            Right-hand input; must share mode, dimensions, coordinates,
            and variable names.
        op : str
            ``"sum"``, ``"diff"``, ``"product"``, ``"ratio"``,
            ``"mean"``, or ``"weighted_mean"`` (requires ``weights``).
        weights : tuple of (float, float) or None, optional
            Weights for ``"weighted_mean"``.
        cross_correlation : float, optional
            Correlation between corresponding variables of the two
            inputs, 0 by default.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame; origin tags follow the worst-case rule
            (OQ-10).

        Raises
        ------
        OperatingModeMixError
            When the inputs are in different operating modes (REQ-12).
        DataError
            On grid, coordinate, or variable-set mismatches.
        """
        from itaca.core.combine import combine as _combine

        return _combine(
            self,
            other,
            op=op,
            weights=weights,
            cross_correlation=cross_correlation,
            history=history,
            comment=comment,
        )

    def to_csv(
        self,
        path: str | Path,
        *,
        split_by: str | None = None,
        allow_draft: bool = False,
    ) -> object:
        """Export to flat CSV with a provenance header (REQ-70 to REQ-72).

        Parameters
        ----------
        path : path
            Target file, or target directory when ``split_by`` is
            given (one file per coordinate, REQ-72).
        split_by : str or None, optional
            Dimension to split the export by.
        allow_draft : bool, optional
            Override the draft-mode guard, embedding a prominent
            warning in the header (REQ-11).

        Returns
        -------
        pathlib.Path or list of pathlib.Path
            The written file(s).
        """
        from itaca.io.export import to_csv as _to_csv

        return _to_csv(self, path, split_by=split_by, allow_draft=allow_draft)

    def to_json(self, path: str | Path, *, allow_draft: bool = False) -> object:
        """Export to JSON with provenance and history keys (REQ-70, REQ-71).

        Parameters
        ----------
        path : path
            Target file.
        allow_draft : bool, optional
            Override the draft-mode guard (REQ-11).

        Returns
        -------
        pathlib.Path
            The written file.
        """
        from itaca.io.export import to_json as _to_json

        return _to_json(self, path, allow_draft=allow_draft)

    def to_pandas(self, *, allow_draft: bool = False) -> object:
        """Export to a flat pandas DataFrame (REQ-70; lazy dependency).

        Parameters
        ----------
        allow_draft : bool, optional
            Override the draft-mode guard (REQ-11).

        Returns
        -------
        pandas.DataFrame
            Dimension columns followed by variable columns.

        Raises
        ------
        MissingDependencyError
            When pandas is not installed (REQ-84).
        """
        from itaca.io.export import to_pandas as _to_pandas

        return _to_pandas(self, allow_draft=allow_draft)

    def to_numpy(
        self,
        *,
        return_dims: bool = False,
        copy: bool = False,
        allow_draft: bool = False,
    ) -> object:
        """Export the variable arrays (REQ-70; read-only views, REQ-102).

        Parameters
        ----------
        return_dims : bool, optional
            Also return the coordinate arrays per dimension.
        copy : bool, optional
            Return writable copies instead of read-only views.
        allow_draft : bool, optional
            Override the draft-mode guard (REQ-11).

        Returns
        -------
        dict or tuple
            ``{var: array}``, plus ``{dim: coords}`` when
            ``return_dims`` is True.
        """
        from itaca.io.export import to_numpy as _to_numpy

        return _to_numpy(
            self, return_dims=return_dims, copy=copy, allow_draft=allow_draft
        )

    def save(self, path: str | Path, *, allow_draft: bool = False) -> object:
        """Write the VarFrame to a .itc archive (REQ-70, REQ-11).

        The archive preserves all metadata, Provenance, History,
        uncertainty, correlation, and origin tags; ``itc.open``
        revalidates the state hash on read (REQ-103).

        Parameters
        ----------
        path : path
            Target ``.itc`` file; the write is atomic.
        allow_draft : bool, optional
            Override the draft-mode guard, embedding a prominent
            warning in the archive metadata (REQ-11).

        Returns
        -------
        pathlib.Path
            The written file.
        """
        from itaca.io.formats.itc import save as _save

        return _save(self, path, allow_draft=allow_draft)

    def inspect(self, threshold: int = 20) -> None:
        """Print a dimension-vs-variable candidacy report (REQ-13).

        Delegates to :func:`itaca.io.inspector.inspect`; a no-op with
        a notice on structured VarFrames.

        Parameters
        ----------
        threshold : int, optional
            Unique-value bound for dimension candidacy, 20 by default.
        """
        from itaca.io.inspector import inspect as _inspect

        _inspect(self, threshold=threshold)

    def summary(self) -> object:
        """Print and return the one-screen summary (REQ-16).

        Returns
        -------
        itaca.io.summary.Summary
            Dimensions, variables, per-variable stats, RAM footprint,
            mode, and current history index.
        """
        from itaca.io.summary import summary as _summary

        return _summary(self)

    def diagnostics(self, log: object = None) -> object:
        """Print, optionally log, and return diagnostics (REQ-17).

        Parameters
        ----------
        log : path or None, optional
            When given, the printed output is also written there.

        Returns
        -------
        itaca.io.diagnostics.DiagnosticsReport
            Missing and non-finite counts, coverage, and warnings.
        """
        from itaca.io.diagnostics import diagnostics as _diagnostics

        return _diagnostics(self, log=log)  # type: ignore[arg-type]

    def manifest(self, path: object) -> object:
        """Export the source-file manifest as CSV or JSON (REQ-15).

        Parameters
        ----------
        path : path
            Target file; the suffix selects the format.

        Returns
        -------
        pathlib.Path
            The written path.
        """
        from itaca.io.manifest import manifest as _manifest

        return _manifest(self, path)  # type: ignore[arg-type]

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
