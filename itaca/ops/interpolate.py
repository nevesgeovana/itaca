"""db.interpolate: densify a grid or translate the sweep axis (REQ-25).

Every method is a linear operator, so both uncertainty components
propagate exactly through the weight matrix (REQ-98). Existing target
coordinates are preserved unless ``override=True``. The HistoryFrame
receives ``+1`` inside the convex hull of the original axis and
``-1`` outside; preserved points keep their original tag.

Axis translation replaces a dimension with a monotonic variable as
the sweep axis. The target variable becomes exact coordinates:
dimensions carry no UncFrame, so any uncertainty declared on it does
not transfer; the History entry says so explicitly (DD-18).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.errors import (
    AxisTranslationError,
    DataError,
    DimensionNotFoundError,
    FitDegreeError,
    NonNumericDimensionError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import Content, content_of, rebuild, recoord
from itaca.ops._interp_kernels import (
    cubic_matrix,
    linear_matrix,
    nearest_matrix,
    polyfit_matrix,
)

_Array = NDArray[Any]

_METHODS = ("linear", "cubic", "nearest", "polyfit")


def _weight_matrix(x: _Array, targets: _Array, method: str, deg: int | None) -> _Array:
    if method == "linear":
        return linear_matrix(x, targets)
    if method == "nearest":
        return nearest_matrix(x, targets)
    if method == "cubic":
        return cubic_matrix(x, targets)
    assert deg is not None
    return polyfit_matrix(x, targets, deg)


def _validate_method(db: VarFrame, method: str, deg: int | None, n: int) -> None:
    if method not in _METHODS:
        raise DataError(
            f"method {method!r}",
            "interpolate received an unknown method",
            f"use one of {list(_METHODS)} (REQ-25)",
        )
    if method == "polyfit":
        if deg is None:
            raise DataError(
                "interpolate(method='polyfit')",
                "called without deg",
                "pass deg=<polynomial degree> (REQ-25)",
            )
        if deg >= n:
            raise FitDegreeError(
                f"deg {deg} against {n} points",
                "polyfit needs more points than the degree",
                "reduce deg or densify the source first (REQ-25)",
            )


def _apply_line(flat: _Array, weights: _Array, kind: str) -> _Array:
    """Apply the weight matrix to (rows, n) lines.

    NaN poisons only the targets it actually contributes to.
    """
    finite = np.isfinite(flat)
    zeroed = np.where(finite, flat, 0.0)
    if kind == "values":
        result = zeroed @ weights.T
    elif kind == "systematic":
        result = np.abs(zeroed @ weights.T)
    else:  # random
        result = np.sqrt(np.square(zeroed) @ np.square(weights.T))
    touched = (~finite).astype(float) @ (weights != 0.0).T.astype(float)
    return np.asarray(np.where(touched > 0.0, np.nan, result))


def _interp_axis(
    content: Content,
    dim: str,
    targets: _Array,
    method: str,
    deg: int | None,
    override: bool,
) -> None:
    """Interpolate every variable along one dimension, in place."""
    order = list(content.dims)
    axis = order.index(dim)
    x = np.asarray(content.dims[dim].coords, dtype=float)
    sorter = np.argsort(x)
    weights = np.zeros((targets.size, x.size))
    weights[:, sorter] = _weight_matrix(x[sorter], targets, method, deg)
    reused = np.full(targets.size, -1, dtype=int)
    if not override:
        for row, t in enumerate(targets):
            match = np.nonzero(x == t)[0]
            if match.size:
                reused[row] = int(match[0])
                weights[row] = 0.0
                weights[row, match[0]] = 1.0
    inside = (targets >= x.min()) & (targets <= x.max())

    def _lines(array: _Array) -> _Array:
        return np.moveaxis(array, axis, -1).reshape(-1, x.size)

    def _unlines(flat: _Array, dtype: Any = float) -> _Array:
        moved_shape = (
            *np.moveaxis(np.empty(content.shape), axis, -1).shape[:-1],
            targets.size,
        )
        return np.moveaxis(flat.reshape(moved_shape), -1, axis).astype(dtype)

    new_tags: dict[str, _Array] = {}
    for name, values in content.values.items():
        source_tags = (
            content.tags[name]
            if content.tags is not None and name in content.tags
            else np.zeros(content.shape, dtype=np.int8)
        )
        tag_lines = _lines(source_tags.astype(float))
        out_tags = np.where(inside, np.int8(1), np.int8(-1))[None, :] * np.ones(
            (tag_lines.shape[0], 1), dtype=np.int8
        )
        for row, source_index in enumerate(reused):
            if source_index >= 0:
                out_tags[:, row] = tag_lines[:, source_index].astype(np.int8)
        new_tags[name] = _unlines(out_tags.astype(np.int8), np.int8)
        content.values[name] = _unlines(_apply_line(_lines(values), weights, "values"))
        for label in ("systematic", "random"):
            component = getattr(content, label)
            if component is not None and name in component:
                component[name] = _unlines(
                    _apply_line(_lines(component[name]), weights, label)
                )
    content.tags = new_tags
    content.dims[dim] = recoord(content.dims[dim], targets)


def _translate_axis(
    content: Content,
    from_dim: str,
    to_var: str,
    targets: _Array | None,
    method: str,
    deg: int | None,
    override: bool,
) -> tuple[_Array, bool]:
    """Replace ``from_dim`` with ``to_var`` as sweep axis, in place."""
    order = list(content.dims)
    axis = order.index(from_dim)
    n = content.dims[from_dim].cardinality
    v_lines = np.moveaxis(content.values[to_var], axis, -1).reshape(-1, n)
    for row in range(v_lines.shape[0]):
        deltas = np.diff(v_lines[row])
        if not (np.all(deltas > 0.0) or np.all(deltas < 0.0)):
            raise AxisTranslationError(
                f"variable '{to_var}'",
                f"axis translation from '{from_dim}' needs a strictly "
                "monotonic target along the source dimension",
                "smooth or select the non-monotonic region first (REQ-25)",
            )
    if targets is None:
        targets = np.array(v_lines[0], dtype=float)
    dropped_unc = False
    for label in ("systematic", "random"):
        component = getattr(content, label)
        if component is not None and component.pop(to_var, None) is not None:
            dropped_unc = True

    meta = content.meta[to_var]
    unit = getattr(meta, "unit", None)
    names = [name for name in content.values if name != to_var]
    moved_prefix = np.moveaxis(np.empty(content.shape), axis, -1).shape[:-1]
    out_shape_moved = (*moved_prefix, targets.size)

    new_values: dict[str, _Array] = {}
    new_sys: dict[str, _Array] = {}
    new_rand: dict[str, _Array] = {}
    new_tags: dict[str, _Array] = {}
    for name in names:
        lines = np.moveaxis(content.values[name], axis, -1).reshape(-1, n)
        out = np.empty((lines.shape[0], targets.size))
        out_sys = np.empty_like(out)
        out_rand = np.empty_like(out)
        out_tag = np.empty((lines.shape[0], targets.size), dtype=np.int8)
        sys_lines = rand_lines = None
        if content.systematic is not None and name in content.systematic:
            sys_lines = np.moveaxis(content.systematic[name], axis, -1).reshape(-1, n)
        if content.random is not None and name in content.random:
            rand_lines = np.moveaxis(content.random[name], axis, -1).reshape(-1, n)
        tag_lines = (
            np.moveaxis(content.tags[name], axis, -1).reshape(-1, n)
            if content.tags is not None and name in content.tags
            else np.zeros((lines.shape[0], n), dtype=np.int8)
        )
        for row in range(lines.shape[0]):
            x = v_lines[row]
            sorter = np.argsort(x)
            weights = np.zeros((targets.size, n))
            weights[:, sorter] = _weight_matrix(x[sorter], targets, method, deg)
            reused = np.full(targets.size, -1, dtype=int)
            if not override:
                for target_row, t in enumerate(targets):
                    match = np.nonzero(x == t)[0]
                    if match.size:
                        reused[target_row] = int(match[0])
                        weights[target_row] = 0.0
                        weights[target_row, match[0]] = 1.0
            inside = (targets >= x.min()) & (targets <= x.max())
            out[row] = _apply_line(lines[row : row + 1], weights, "values")[0]
            if sys_lines is not None:
                out_sys[row] = _apply_line(
                    sys_lines[row : row + 1], weights, "systematic"
                )[0]
            if rand_lines is not None:
                out_rand[row] = _apply_line(
                    rand_lines[row : row + 1], weights, "random"
                )[0]
            out_tag[row] = np.where(inside, np.int8(1), np.int8(-1))
            for target_row, source_index in enumerate(reused):
                if source_index >= 0:
                    out_tag[row, target_row] = tag_lines[row, source_index]

        def _restore(flat: _Array, dtype: Any = float) -> _Array:
            return np.moveaxis(flat.reshape(out_shape_moved), -1, axis).astype(dtype)

        new_values[name] = _restore(out)
        if sys_lines is not None:
            new_sys[name] = _restore(out_sys)
        if rand_lines is not None:
            new_rand[name] = _restore(out_rand)
        new_tags[name] = _restore(out_tag, np.int8)

    new_dim = Dimension(name=to_var, coords=targets, unit=unit)
    dims = [
        (to_var, new_dim) if name == from_dim else (name, content.dims[name])
        for name in order
    ]
    content.dims = dict(dims)
    content.values = new_values
    content.meta = {name: content.meta[name] for name in names}
    content.systematic = new_sys if content.systematic is not None else None
    content.random = new_rand if content.random is not None else None
    content.tags = new_tags
    return targets, dropped_unc


def interpolate(
    db: VarFrame,
    mapping: dict[str, Any] | None = None,
    *,
    method: str = "linear",
    deg: int | None = None,
    override: bool = False,
    axis_translation: dict[str, str] | None = None,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Interpolate onto a new grid or translate the axis (REQ-25).

    See ``VarFrame.interpolate`` for the full parameter description.
    """
    content = content_of(db)
    if axis_translation is not None:
        keys = set(axis_translation)
        if keys != {"from", "to"}:
            raise DataError(
                f"axisTranslation keys {sorted(keys)}",
                "axis translation needs exactly 'from' and 'to'",
                "pass axisTranslation={'from': dim, 'to': var} (REQ-25)",
            )
        from_dim = axis_translation["from"]
        to_var = axis_translation["to"]
        if from_dim not in db.dims:
            raise DimensionNotFoundError(
                f"dimension '{from_dim}'",
                "axis translation referenced an absent source dimension",
                f"available dimensions: {list(db.dims)}",
            )
        if not db.dims[from_dim].is_numeric:
            raise NonNumericDimensionError(
                f"dimension '{from_dim}'",
                "axis translation from a string-valued dimension",
                "numerical operations need numeric coordinates (SRS 4.1.3)",
            )
        if to_var not in db.vars:
            raise DataError(
                f"variable '{to_var}'",
                "axis translation referenced an absent target variable",
                f"available variables: {list(db.vars)}",
            )
        extra = set(mapping or {}) - {to_var}
        if extra:
            raise DataError(
                f"mapping keys {sorted(extra)}",
                "axis translation accepts only the target variable as an explicit grid",
                f"pass {{{to_var!r}: new_coords}} or no mapping (REQ-25)",
            )
        _validate_method(db, method, deg, db.dims[from_dim].cardinality)
        targets = None
        if mapping and to_var in mapping:
            targets = np.asarray(mapping[to_var], dtype=float)
        targets, dropped = _translate_axis(
            content, from_dim, to_var, targets, method, deg, override
        )
        note = ", axis_uncertainty=dropped" if dropped else ""
        operation = (
            f"interpolate(axisTranslation={{'from': '{from_dim}', "
            f"'to': '{to_var}'}}, method='{method}', deg={deg}, "
            f"override={override}{note})"
        )
        return rebuild(
            db,
            content,
            operation=operation,
            comment=comment,
            history=history,
            method="interpolate",
            # The method spells the selector axisTranslation (REQ-25).
            replay_kwargs={
                "axisTranslation": axis_translation,
                "method": method,
                "deg": deg,
                "override": override,
            },
        )

    if not mapping:
        raise DataError(
            "interpolate({})",
            "called without target coordinates or axisTranslation",
            "pass {dim: new_coords} or axisTranslation=... (REQ-25)",
        )
    for dim in mapping:
        if dim not in db.dims:
            raise DimensionNotFoundError(
                f"dimension '{dim}'",
                "interpolate referenced an absent dimension",
                f"available dimensions: {list(db.dims)}",
            )
        if not db.dims[dim].is_numeric:
            raise NonNumericDimensionError(
                f"dimension '{dim}'",
                "interpolate along a string-valued dimension",
                "numerical operations need numeric coordinates (SRS 4.1.3)",
            )
        _validate_method(db, method, deg, db.dims[dim].cardinality)
    for dim, new_coords in mapping.items():
        targets = np.asarray(new_coords, dtype=float)
        if targets.ndim != 1:
            raise DataError(
                f"target coordinates for '{dim}' with shape {targets.shape}",
                "interpolate needs a 1-D coordinate array per dimension",
                "pass a flat list or 1-D array (REQ-25)",
            )
        _interp_axis(content, dim, targets, method, deg, override)
    detail = {name: np.asarray(coords).tolist() for name, coords in mapping.items()}
    operation = (
        f"interpolate({detail}, method='{method}', deg={deg}, override={override})"
    )
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        method="interpolate",
        replay_kwargs={
            "mapping": detail,
            "method": method,
            "deg": deg,
            "override": override,
        },
    )
