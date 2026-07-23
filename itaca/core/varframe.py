"""The VarFrame, ITACA's central data structure (SRS 4.1; DD-03).

A frozen composition of NumPy arrays plus metadata. Every operation
returns a new VarFrame, records itself in History, and declares its
UncFrame effect (REQ-18, REQ-98). Arrays are read-only (REQ-102).
"""

from __future__ import annotations

import dataclasses
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import numpy as np

from itaca.core.axes import Axis, AxisRegistry
from itaca.core.coords import Cartesian, CoordSystem
from itaca.core.correlation import CorrelationMatrix
from itaca.core.dimension import Dimension
from itaca.core.errors import (
    DataError,
    ProvenanceError,
    UncertaintyError,
    UncertaintyKeyError,
    VectorGroupError,
)
from itaca.core.history import History, compute_state_hash
from itaca.core.historyframe import HistoryFrame
from itaca.core.provenance import Provenance, validate_mode
from itaca.core.sentinels import NoDefault, no_default
from itaca.core.uncframe import UncFrame
from itaca.core.variable import Variable

if TYPE_CHECKING:
    from itaca.core.pipeline import PipelineStep
    from itaca.ops.diff import DiffIndexer

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
    axes : AxisRegistry, optional
        Registered coordinate frames and vector-group declarations;
        empty by default and part of the state hash (REQ-103).

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
    axes: AxisRegistry = field(default_factory=AxisRegistry)

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
            axes=self.axes,
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
            axes=self.axes,
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

        Examples
        --------
        >>> db = itc.load(folder).pivot(dims=["mach", "alpha"])  # doctest: +SKIP
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
        axes: object = _UNSET,
        step: PipelineStep | None = None,
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
        new_axes = self.axes if axes is _UNSET else cast("AxisRegistry", axes)
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
                axes=new_axes,
            )
            new_history = self.history.append(
                operation=operation,
                state_hash=state_hash,
                comment=comment,
                step=step,
            )
        return dataclasses.replace(
            self,
            dims=dict(new_dims),
            vars=dict(new_vars),
            uncertainty=new_unc,
            tags=new_tags,
            correlation=new_correlation,
            axes=new_axes,
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

    def expand(
        self,
        dim_name: str,
        values: object,
        axis: int | None = None,
        *,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Add a new dimension, broadcasting existing arrays (REQ-23).

        Every stored array (values, uncertainty components, origin
        tags) is materialized at the expanded shape, so the memory
        footprint multiplies by the new dimension's cardinality.

        Parameters
        ----------
        dim_name : str
            Name of the new dimension; must not collide with an
            existing dimension or variable.
        values : array-like
            1-D coordinate array for the new dimension; entries must
            be unique. String values create a non-numeric dimension.
        axis : int or None, optional
            Position of the new axis; defaults to the last position.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with the added dimension; ``self`` is
            unchanged. UncFrame components and origin tags broadcast
            unchanged (REQ-98).

        Raises
        ------
        DataError
            Name collision, non-1-D or duplicate values, or an axis
            outside ``[0, ndim]``.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([[0.0, 2.0], [1.0, 2.0]])
        >>> db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        >>> swept = db.expand("rpm", [1000.0, 2000.0])
        >>> swept.shape
        (2, 2)
        """
        from itaca.ops.expand import expand as _expand

        return _expand(self, dim_name, values, axis, history=history, comment=comment)

    def interpolate(
        self,
        mapping: dict[str, object] | None = None,
        method: str = "linear",
        deg: int | None = None,
        override: bool = False,
        *,
        axisTranslation: dict[str, str] | None = None,  # noqa: N803  (SRS REQ-25)
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Interpolate onto a new grid or translate the axis (REQ-25).

        Parameters
        ----------
        mapping : dict or None, optional
            ``{dim: new_coords}`` targets, applied dimension by
            dimension. With ``axisTranslation``, the only allowed key
            is the target variable, providing an explicit new grid
            (default: the target values of the first sweep line).
        method : str, optional
            ``"linear"`` (default), ``"cubic"`` (natural spline),
            ``"nearest"``, or ``"polyfit"`` (global fit of degree
            ``deg``).
        deg : int or None, optional
            Polynomial degree for ``"polyfit"``.
        override : bool, optional
            By default a target that already exists in the original
            dimension keeps the existing value (and its origin tag);
            ``True`` forces recomputation everywhere.
        axisTranslation : dict or None, optional
            ``{"from": dim, "to": var}`` replaces the dimension with
            the strictly monotonic variable as sweep axis. The target
            variable becomes exact coordinates; any uncertainty
            declared on it does not transfer (recorded in History).
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame on the target grid. Both uncertainty
            components propagate exactly through the interpolation
            weights (REQ-98). Origin tags: ``+1`` inside the convex
            hull of the original axis, ``-1`` outside, original tag on
            preserved points.

        Raises
        ------
        DimensionNotFoundError
            A referenced dimension is absent.
        NonNumericDimensionError
            Interpolation along a string-valued dimension.
        AxisTranslationError
            The translation target is not strictly monotonic.
        DataError
            Unknown method, missing ``deg``, empty call, or malformed
            targets.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([[0.0, 1.0, 2.0], [0.0, 2.0, 4.0]])
        >>> db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        >>> dense = db.interpolate({"alpha": [0.5, 1.5]})
        >>> dense.vars["CT"].values.tolist()
        [1.0, 3.0]
        """
        from itaca.ops.interpolate import interpolate as _interpolate

        return _interpolate(
            self,
            mapping,
            method=method,
            deg=deg,
            override=override,
            axis_translation=axisTranslation,
            history=history,
            comment=comment,
        )

    def average(
        self,
        along: str | list[str],
        *,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Collapse dimensions by the mean of non-NaN values (REQ-27).

        Parameters
        ----------
        along : str or list of str
            Dimension(s) to collapse; the mean is taken jointly over
            every collapsed cell, skipping NaN.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A reduced-order VarFrame. The random uncertainty component
            gains 1/sqrt(N) over the populated cells; the systematic
            component is fully correlated and keeps its magnitude
            (REQ-98, REQ-99). Tags follow the worst-case rule (OQ-10).

        Raises
        ------
        DimensionNotFoundError
            A named dimension is absent.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> rows = [[0.0, 1.0, 2.0], [0.0, 2.0, 4.0]]
        >>> db = itc.load(np.array(rows), names=["alpha", "rep", "CT"])
        >>> mean = db.pivot(dims=["alpha", "rep"]).average(along="rep")
        >>> float(mean.vars["CT"].values[0])
        3.0
        """
        from itaca.ops.average import average as _average

        return _average(self, along=along, history=history, comment=comment)

    def integrate(
        self,
        var: str,
        *,
        over: str | list[str],
        coords: str | None = None,
        skipna: bool = False,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Integrate a variable over dimensions (REQ-28).

        Trapezoidal quadrature over the coordinate grid, applied
        sequentially over ``over``.

        Parameters
        ----------
        var : str
            Variable to integrate; the result keeps only this
            variable.
        over : str or list of str
            Dimension(s) to integrate over. With ``coords="polar"``,
            exactly ``[r_dim, theta_dim]`` in that order.
        coords : str or None, optional
            ``"polar"`` applies the polar area element r dr dtheta
            (theta in radians); default is Cartesian.
        skipna : bool, optional
            By default any NaN inside the domain makes the result NaN
            (a partial quadrature is silently biased). ``True``
            integrates populated cells only, records the populated
            fraction in History, and tags the result ``+1``.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A reduced-order VarFrame with the integrated quantity.
            Uncertainty propagates through the quadrature weights
            (REQ-98): systematic as the absolute weighted sum, random
            as the root sum of squares.

        Raises
        ------
        VariableNotFoundError
            ``var`` is absent.
        DimensionNotFoundError
            A dimension in ``over`` is absent.
        NonNumericDimensionError
            A dimension in ``over`` is string-valued.
        DataError
            Unknown ``coords`` or a polar call without exactly two
            dimensions.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([[0.0, 1.0, 2.0], [0.0, 2.0, 4.0]])
        >>> db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        >>> total = db.integrate("CT", over=["alpha"])
        >>> float(total.vars["CT"].values[0])
        4.0
        """
        from itaca.ops.integrate import integrate as _integrate

        return _integrate(
            self,
            var,
            over=over,
            coords=coords,
            skipna=skipna,
            history=history,
            comment=comment,
        )

    def smooth(
        self,
        *,
        along: str,
        method: str,
        window: int | NoDefault = no_default,
        polyorder: int | NoDefault = no_default,
        smoothing: float | NoDefault = no_default,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Smooth all variables along a dimension (REQ-29).

        Parameters
        ----------
        along : str
            Dimension to smooth along.
        method : str
            ``"savgol"`` (moving polynomial fit; takes ``window`` and
            ``polyorder``), ``"spline"`` (natural smoothing spline;
            takes ``smoothing``), or ``"moving_avg"`` (takes
            ``window``).
        window : int, optional
            Moving-window size; consumed by ``"savgol"`` and
            ``"moving_avg"`` only (REQ-105: passing it elsewhere
            raises).
        polyorder : int, optional
            Fit degree for ``"savgol"``; must be below ``window``.
        smoothing : float, optional
            Nonnegative spline penalty; ``0`` is the identity.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with smoothed values tagged ``+1`` (cells
            already ``-1`` stay ``-1``).

        Raises
        ------
        DataError
            Unknown method, a missing or non-consumed method kwarg
            (REQ-105), or invalid window/degree combinations.
        DimensionNotFoundError
            ``along`` is absent.
        NonNumericDimensionError
            ``along`` is string-valued.
        UncertaintyError
            Uncertainty is present (OQ-18: the kernel weight rule is
            not frozen yet).

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([np.arange(7.0), np.arange(7.0) ** 2])
        >>> db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        >>> out = db.smooth(along="alpha", method="savgol", window=5, polyorder=2)
        >>> bool(np.allclose(out.vars["CT"].values, db.vars["CT"].values))
        True
        """
        from itaca.ops.smooth import smooth as _smooth

        return _smooth(
            self,
            along=along,
            method=method,
            window=window,
            polyorder=polyorder,
            smoothing=smoothing,
            history=history,
            comment=comment,
        )

    def diff(
        self,
        *,
        along: str,
        window: int = 5,
        deg: int = 2,
        nan_edges: bool = False,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Differentiate all variables along a dimension (REQ-30).

        A window of ``window`` points centered on each point is fitted
        with a polynomial of degree ``deg`` and the analytical
        derivative of the fit is evaluated at the point. At the
        boundaries the window is asymmetric, preserving output shape.

        Parameters
        ----------
        along : str
            Dimension to differentiate along.
        window : int, optional
            Moving-window size; must exceed ``deg`` (REQ-30).
        deg : int, optional
            Polynomial degree of the moving fit.
        nan_edges : bool, optional
            Set asymmetric-window points to NaN instead.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame whose variables follow the ``dVAR_ddim``
            naming convention (e.g. ``dCL_dalpha``). Output tags carry
            the worst case over each moving window (OQ-10).

        Raises
        ------
        DiffWindowError
            ``window <= deg``.
        DimensionNotFoundError
            ``along`` is absent.
        NonNumericDimensionError
            ``along`` is string-valued.
        UncertaintyError
            Uncertainty is present (OQ-18: the moving-fit weight rule
            is not frozen yet).

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([np.arange(6.0), np.arange(6.0) ** 2])
        >>> db = itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])
        >>> slopes = db.diff(along="alpha", window=5, deg=2)
        >>> float(slopes.vars["dCL_dalpha"].values[1])
        2.0
        """
        from itaca.ops.diff import diff as _diff

        return _diff(
            self,
            along=along,
            window=window,
            deg=deg,
            nan_edges=nan_edges,
            history=history,
            comment=comment,
        )

    @property
    def d(self) -> DiffIndexer:
        """``db.d[dim]``: derivative with default parameters (REQ-30).

        Indexer sugar for ``db.diff(along=dim)``; nothing is stored on
        the source frame (REQ-18 immutability).

        Returns
        -------
        DiffIndexer
            Supports ``db.d["alpha"]`` returning the derivative
            VarFrame.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([np.arange(5.0), np.arange(5.0) ** 2])
        >>> db = itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])
        >>> list(db.d["alpha"].vars)
        ['dCL_dalpha']
        """
        from itaca.ops.diff import DiffIndexer

        return DiffIndexer(self)

    def fitmodel(
        self,
        *,
        along: str,
        deg: int,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Fit a polynomial along a dimension (REQ-31).

        Every variable is fitted with a polynomial of degree ``deg``
        along ``along``; the dimension is replaced by
        ``<along>_coef`` with ``deg + 1`` string labels ``dim^0`` to
        ``dim^N`` (ascending exponents). The original sweep range is
        recorded in the coefficient dimension's description so that
        ``fitvalue`` can tag beyond-range evaluations ``-1``.

        Parameters
        ----------
        along : str
            Dimension to fit along.
        deg : int
            Polynomial degree; needs more points than the degree.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame holding polynomial coefficients.

        Raises
        ------
        DimensionNotFoundError
            ``along`` is absent.
        NonNumericDimensionError
            ``along`` is string-valued.
        DataError
            ``deg`` negative or not below the point count, or a name
            collision with ``<along>_coef``.
        UncertaintyError
            Uncertainty is present (the REQ-98 table declares no
            fitmodel row; DD-18).

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([np.arange(5.0), np.arange(5.0) ** 2])
        >>> db = itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])
        >>> model = db.fitmodel(along="alpha", deg=2)
        >>> model.dims["alpha_coef"].coords.tolist()
        ['alpha^0', 'alpha^1', 'alpha^2']
        """
        from itaca.ops.fitmodel import fitmodel as _fitmodel

        return _fitmodel(self, along=along, deg=deg, history=history, comment=comment)

    def fitvalue(
        self,
        *,
        coef_dims: list[str],
        at: dict[str, object],
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Evaluate fitmodel coefficients at coordinates (REQ-32).

        Parameters
        ----------
        coef_dims : list of str
            Coefficient dimensions produced by ``fitmodel`` (their
            names end in ``_coef``).
        at : dict
            ``{dim: array}`` evaluation grids, keyed by the original
            (pre-fit) dimension names.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame where the coefficient dimensions are
            replaced by the evaluation dimensions. Values within the
            original fit range are tagged ``+1``; beyond it, ``-1``
            (REQ-32). The forward evaluation is exact and linear in the
            coefficients, but it defers with ``fitmodel`` and raises
            when uncertainty is present until the coefficient-space
            rule is frozen (OQ-24).

        Raises
        ------
        DimensionNotFoundError
            A coefficient dimension is absent.
        DataError
            A coefficient dimension cannot be paired with an ``at``
            grid, an ``at`` key was not used, or the fitted range is
            unreadable.
        UncertaintyError
            Uncertainty is present (deferred with fitmodel, OQ-24).

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([np.arange(5.0), np.arange(5.0) ** 2])
        >>> db = itc.load(arr, names=["alpha", "CL"]).pivot(dims=["alpha"])
        >>> model = db.fitmodel(along="alpha", deg=2)
        >>> dense = model.fitvalue(coef_dims=["alpha_coef"], at={"alpha": [2.0]})
        >>> float(round(dense.vars["CL"].values[0], 6))
        4.0
        """
        from itaca.ops.fitmodel import fitvalue as _fitvalue

        return _fitvalue(
            self, coef_dims=coef_dims, at=at, history=history, comment=comment
        )

    def fill(
        self,
        along: str,
        *args: str,
        method: str = "linear",
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
            dimension instead). Keyword-only: passing it positionally
            is deprecated and warns (it becomes keyword-only in a
            future release, aligning with the M1 kernel ops).
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

        Raises
        ------
        DataError
            Unknown method, or more than one positional argument.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> arr = np.column_stack([[0.0, 1.0, 2.0], [1.0, np.nan, 3.0]])
        >>> db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        >>> filled = db.fill("alpha", method="linear")
        >>> float(filled.vars["CT"].values[1])
        2.0
        """
        if args:
            if len(args) > 1:
                raise DataError(
                    f"fill positional arguments {args}",
                    "fill takes at most the dimension and (deprecated) "
                    "the method positionally",
                    "pass method= and the rest as keywords (REQ-26)",
                )
            warnings.warn(
                "passing 'method' to fill positionally is deprecated and "
                "will become keyword-only in a future release; pass "
                "method= as a keyword (aligns fill with the M1 kernel "
                "ops smooth/diff)",
                FutureWarning,
                stacklevel=2,
            )
            method = args[0]

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

    def register_axis(
        self, axis: Axis, *, history: bool = False, comment: str | None = None
    ) -> VarFrame:
        """Register a coordinate frame on the VarFrame (REQ-38).

        Parameters
        ----------
        axis : Axis
            The frame to register; its name must be distinct from any
            already registered frame.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with the frame registered. The registry is
            part of the state hash (REQ-103), so registering a frame
            changes it.

        Raises
        ------
        RotationMatrixError
            A frame of the same name is already registered.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> from itaca.core.axes import Axis
        >>> arr = np.column_stack([[0.0, 1.0], [1.0, 2.0]])
        >>> db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
        >>> out = db.register_axis(Axis(name="rig", rotation_matrix=np.eye(3)))
        >>> out.axes.resolve("rig").name
        'rig'
        """
        return self._derive(
            operation=f"register_axis(name='{axis.name}')",
            comment=comment,
            history=history,
            axes=self.axes.with_axis(axis),
        )

    def declare_vector(
        self,
        name: str,
        components: Sequence[str],
        *,
        axis: str = "body",
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Declare a named vector group and its source axis (REQ-38, REQ-107).

        Parameters
        ----------
        name : str
            Group name.
        components : sequence of str
            Exactly three component variable names (x, y, z), each
            present in the VarFrame.
        axis : str, optional
            The axis system the components are currently expressed in;
            defaults to the canonical body axis (REQ-107). Must be a
            registered or built-in axis.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with the group declared; part of the state
            hash (REQ-103).

        Raises
        ------
        VectorGroupError
            Not exactly three components, or a component is absent.
        AxisNotFoundError
            ``axis`` is not registered.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> rows = [[0.0, 1.0, 2.0, 3.0]]
        >>> db = itc.load(np.array(rows), names=["a", "FX", "FY", "FZ"]).pivot(
        ...     dims=["a"]
        ... )
        >>> out = db.declare_vector("force", ["FX", "FY", "FZ"])
        >>> out.axes.group_axis("force")
        'body'
        """
        missing = [c for c in components if c not in self.vars]
        if missing:
            raise VectorGroupError(
                f"components {missing}",
                f"declare_vector('{name}') names variables absent from the frame",
                f"declare only present variables: {list(self.vars)} (REQ-38)",
            )
        new_axes = self.axes.with_vector_group(name, components, axis)
        return self._derive(
            operation=(
                f"declare_vector(name='{name}', components={list(components)}, "
                f"axis='{axis}')"
            ),
            comment=comment,
            history=history,
            axes=new_axes,
        )

    def rotate(
        self,
        target_axis: str,
        *,
        vector_groups: Sequence[str] | None = None,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Express detected vector groups in the target axis (REQ-38).

        Each declared or default-named vector group is transformed from
        its own source axis to ``target_axis``, composing through the
        canonical body axis (REQ-107). Condition-dependent axes are
        evaluated per grid point (REQ-101); the rotation is the exact
        Jacobian, and angle uncertainty enters by the chain rule.

        Parameters
        ----------
        target_axis : str
            Name of the registered or built-in target axis.
        vector_groups : sequence of str or None, optional
            Restrict to these group names; by default every declared
            group plus the auto-detected ``(FX, FY, FZ)`` and
            ``(MX, MY, MZ)`` groups.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with the group components expressed in the
            target axis. Uncertainty propagates through the rotation
            (REQ-98, REQ-101); origin tags are preserved unchanged.

        Raises
        ------
        AxisNotFoundError
            The target or a group's source axis is not registered.
        VectorGroupError
            No vector group resolves, or a requested group is unknown.
        DataError
            A condition-dependent angle source lacks a unit.

        Examples
        --------
        Rotate a body-frame force to the condition-dependent wind frame
        at 90 degrees angle of attack (the angle is read in the
        Dimension's unit):

        >>> import numpy as np
        >>> import itaca as itc
        >>> from itaca.core.dimension import Dimension
        >>> import dataclasses
        >>> rows = [[90.0, 0.0, 1.0, 0.0, 0.0]]
        >>> db = itc.load(
        ...     np.array(rows), names=["alpha", "beta", "FX", "FY", "FZ"]
        ... ).pivot(dims=["alpha", "beta"])
        >>> deg = {"unit": "deg"}
        >>> db = dataclasses.replace(
        ...     db,
        ...     dims={
        ...         "alpha": Dimension(name="alpha", coords=np.array([90.0]), **deg),
        ...         "beta": Dimension(name="beta", coords=np.array([0.0]), **deg),
        ...     },
        ... )
        >>> out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("wind")
        >>> float(round(out.vars["FZ"].values[0, 0], 6))
        -1.0
        """
        from itaca.ops.rotate import rotate as _rotate

        return _rotate(
            self,
            target_axis,
            vector_groups=vector_groups,
            history=history,
            comment=comment,
        )

    def translate_moments(
        self,
        *,
        to_point: Sequence[float],
        from_point: Sequence[float] | None = None,
        axis: str | None = None,
        force: str | None = None,
        moment: str | None = None,
        history: bool = False,
        comment: str | None = None,
    ) -> VarFrame:
        """Transfer declared moments to a new reference point (REQ-100).

        Applies ``M' = M + r x F`` to the moment group, with
        ``r = from_point - to_point`` (the rigid transfer
        ``M_B = M_A + (r_A - r_B) x F``).

        Parameters
        ----------
        to_point : sequence of float
            The new moment reference point ``[x, y, z]``.
        from_point : sequence of float or None, optional
            The current reference point; defaults to the origin.
        axis : str or None, optional
            The axis system the offset is expressed in; must match the
            force and moment groups' axis (they are all taken in one
            axis system). ``None`` uses the groups' own axis.
        force : str or None, optional
            Name of the declared force group to transfer with; by
            default the group named ``"force"`` or the ``(FX, FY, FZ)``
            variables.
        moment : str or None, optional
            Name of the declared moment group to transfer; by default
            the group named ``"moment"`` or the ``(MX, MY, MZ)``
            variables.
        history : bool, optional
            In draft mode, record only when True (REQ-10).
        comment : str or None, optional
            User comment for the History entry (REQ-19).

        Returns
        -------
        VarFrame
            A new VarFrame with the moment components transferred. The
            Jacobian ``[skew(r) | I]`` is exact; force-moment
            covariance propagates when declared (REQ-98, OQ-23). Origin
            tags are preserved.

        Raises
        ------
        VectorGroupError
            No resolvable force or moment group.
        DataError
            A reference point is not length three, the groups are in
            different axis systems, or ``axis`` differs from theirs.

        Examples
        --------
        >>> import numpy as np
        >>> import itaca as itc
        >>> rows = [[0.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0]]
        >>> db = itc.load(
        ...     np.array(rows), names=["i", "FX", "FY", "FZ", "MX", "MY", "MZ"]
        ... ).pivot(dims=["i"])
        >>> db = db.declare_vector("force", ["FX", "FY", "FZ"])
        >>> db = db.declare_vector("moment", ["MX", "MY", "MZ"])
        >>> moved = db.translate_moments(to_point=[0.1, 0.0, 0.0])
        >>> float(round(moved.vars["MY"].values[0], 6))
        0.3
        """
        from itaca.ops.moments import translate_moments as _translate

        return _translate(
            self,
            to_point=to_point,
            from_point=from_point,
            axis=axis,
            force=force,
            moment=moment,
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

        Examples
        --------
        >>> db = db.set_uncertainty({"FZ": 0.005, "rho": "0.05%"})  # doctest: +SKIP
        >>> db = db.set_uncertainty({"FZ": 0.01}, component="random")  # doctest: +SKIP
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

        Examples
        --------
        >>> db = db.set_correlation({("FX", "FZ"): 0.3})  # doctest: +SKIP
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

        Examples
        --------
        >>> db = db.compute("q_inf = 0.5 * rho * V**2")  # doctest: +SKIP
        >>> db = db.compute("CL = FZ / (q_inf * S)", debug=True)  # doctest: +SKIP
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

        Examples
        --------
        >>> delta = db_on.combine(db_off, op="diff")  # doctest: +SKIP
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

        Examples
        --------
        >>> db.save("campaign.itc")  # doctest: +SKIP
        >>> reopened = itc.open("campaign.itc")  # doctest: +SKIP
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
