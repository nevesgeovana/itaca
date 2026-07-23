"""db.integrate: numerical integration over dimensions (REQ-28).

Trapezoidal quadrature over the coordinate grid, applied sequentially
over the requested dimensions. ``coords="polar"`` applies the polar
area element r dr dtheta (theta in radians; convert degrees first
with utils.units). NaN inside the domain poisons the result unless
``skipna=True``, which integrates populated cells only, records the
populated fraction in History, and tags the result +1 (REQ-76).
Uncertainty propagates through the quadrature weights per REQ-98.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    NonNumericDimensionError,
    VariableNotFoundError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild
from itaca.ops._reduction import (
    reduce_random,
    reduce_systematic,
    reduce_tags,
    reduced_dims,
    trapezoid_weights,
)

_Array = NDArray[Any]


def _integrate_axis(
    values: _Array,
    x: _Array,
    axis: int,
    skipna: bool,
    unc: dict[str, _Array],
    tags: _Array | None,
) -> tuple[_Array, dict[str, _Array], _Array | None]:
    """Collapse one axis by trapezoid; propagate components and tags."""
    moved = np.moveaxis(values, axis, -1)
    flat = moved.reshape(-1, x.size)
    weights = np.empty_like(flat)
    if skipna:
        for row in range(flat.shape[0]):
            line = flat[row]
            mask = np.isfinite(line)
            w = np.zeros(x.size)
            if mask.any():
                w[mask] = trapezoid_weights(x[mask])
            weights[row] = w
    else:
        weights[:] = trapezoid_weights(x)
    contributions = np.where(weights != 0.0, weights * flat, 0.0)
    empty = ~np.isfinite(flat).any(axis=-1)
    result = np.sum(contributions, axis=-1)
    if skipna:
        result = np.where(empty, np.nan, result)
    else:
        result = np.where(np.isfinite(flat).all(axis=-1), result, np.nan)
    out_shape = moved.shape[:-1]
    new_unc: dict[str, _Array] = {}
    for label, line_unc in unc.items():
        rule = reduce_systematic if label == "systematic" else reduce_random
        moved_u = np.moveaxis(line_unc, axis, -1).reshape(flat.shape)
        new_unc[label] = rule(weights, moved_u, -1).reshape(out_shape)
    new_tags: _Array | None = None
    if tags is not None:
        moved_t = np.moveaxis(tags, axis, -1).reshape(flat.shape)
        new_tags = reduce_tags(moved_t, weights != 0.0, -1).reshape(out_shape)
    return result.reshape(out_shape), new_unc, new_tags


def integrate(
    db: VarFrame,
    var: str,
    *,
    over: str | list[str],
    coords: str | None = None,
    skipna: bool = False,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Integrate a variable over dimensions (REQ-28).

    See ``VarFrame.integrate`` for the full parameter description.
    """
    over = [over] if isinstance(over, str) else list(over)
    if var not in db.vars:
        raise VariableNotFoundError(
            f"variable '{var}'",
            "integrate referenced an absent variable",
            f"available variables: {list(db.vars)}",
        )
    if not over:
        raise DataError(
            "integrate(over=[])",
            "called without integration dimensions",
            "pass over=[dim, ...] (REQ-28)",
        )
    for name in over:
        if name not in db.dims:
            raise DimensionNotFoundError(
                f"dimension '{name}'",
                "integrate(over=...) referenced an absent dimension",
                f"available dimensions: {list(db.dims)}",
            )
        if not db.dims[name].is_numeric:
            raise NonNumericDimensionError(
                f"dimension '{name}'",
                "integrate along a string-valued dimension",
                "numerical operations need numeric coordinates (SRS 4.1.3)",
            )
    if coords not in (None, "polar"):
        raise DataError(
            f"coords {coords!r}",
            "integrate received an unknown coordinate system",
            "use coords='polar' for r dr dtheta, or omit for Cartesian",
        )
    if coords == "polar" and len(over) != 2:
        raise DataError(
            f"over={over}",
            "polar integration needs exactly the radial and azimuthal "
            "dimensions, in that order",
            "pass over=[r_dim, theta_dim] with coords='polar' (REQ-28)",
        )

    content = content_of(db)
    values = np.array(content.values[var], dtype=float)
    unc: dict[str, _Array] = {}
    for label in ("systematic", "random"):
        component = getattr(content, label)
        if component is not None and var in component:
            unc[label] = np.array(component[var], dtype=float)
    tags = None
    if content.tags is not None and var in content.tags:
        tags = np.array(content.tags[var], dtype=np.int8)

    domain_finite = int(np.sum(np.isfinite(values)))
    domain_total = int(values.size)

    if coords == "polar":
        # The polar area element scales the integrand (and hence its
        # uncertainty, linearly) by r before Cartesian quadrature.
        radial_axis = list(content.dims).index(over[0])
        r = np.asarray(db.dims[over[0]].coords, dtype=float)
        shape = [1] * values.ndim
        shape[radial_axis] = r.size
        scale = r.reshape(shape)
        values = values * scale
        unc = {label: component * np.abs(scale) for label, component in unc.items()}

    remaining = list(content.dims)
    for name in over:
        axis = remaining.index(name)
        x = np.asarray(db.dims[name].coords, dtype=float)
        values, unc, tags = _integrate_axis(values, x, axis, skipna, unc, tags)
        remaining.remove(name)

    keep_scalar = not remaining

    def _finish(array: _Array) -> _Array:
        return array.reshape((1,)) if keep_scalar else array

    if skipna and tags is None:
        tags = np.zeros(values.shape, dtype=np.int8)
    if skipna and tags is not None:
        tags = np.where(tags == -1, tags, np.int8(1)).astype(np.int8)

    content.dims = reduced_dims(content, list(over))
    content.values = {var: _finish(values)}
    content.meta = {var: content.meta[var]}
    content.systematic = (
        {var: _finish(unc["systematic"])} if "systematic" in unc else None
    )
    content.random = {var: _finish(unc["random"])} if "random" in unc else None
    content.tags = {var: _finish(tags)} if tags is not None else None

    detail = f"var='{var}', over={over}, coords={coords!r}, skipna={skipna}"
    if skipna:
        detail += f", populated={domain_finite}/{domain_total}"
    operation = f"integrate({detail})"
    return rebuild(db, content, operation=operation, comment=comment, history=history)
