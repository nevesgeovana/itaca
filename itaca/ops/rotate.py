"""db.rotate: express vector groups in a target frame (REQ-38, REQ-101).

Each declared vector group is transformed from its own source frame to
the target, composing through the canonical body axis: the composite
rotation is ``R = L_tb @ L_sb^T`` where ``L_xb`` is the body-to-x
direction-cosine matrix (REQ-107 handles per-group source frames).
Condition-dependent frames are evaluated per grid point from their
angle fields, whose values are read in the unit of the source
Dimension or Variable and converted to radians.

Uncertainty is the exact Jacobian ``R`` applied to the within-cell
component covariance (built from the declared correlation, OQ-23), so
both UncFrame components propagate as ``diag(R C R^T)``. When a
referenced angle carries uncertainty, its chain-rule sensitivity
``dR/dangle @ v`` adds to the variance (REQ-101). Origin tags are
preserved unchanged (SRS 4.6).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.axes import Axis
from itaca.core.errors import DataError, VectorGroupError
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild
from itaca.utils.units import convert

_Array = NDArray[Any]

# Default-named vector groups detected without an explicit declaration.
_DEFAULT_GROUPS: dict[str, tuple[str, str, str]] = {
    "force": ("FX", "FY", "FZ"),
    "moment": ("MX", "MY", "MZ"),
}


def _resolve_groups(
    db: VarFrame, requested: Sequence[str] | None
) -> dict[str, tuple[tuple[str, str, str], str]]:
    """Return name -> (components, source frame) for the groups to rotate."""
    resolved: dict[str, tuple[tuple[str, str, str], str]] = {}
    for name, comps in db.axes.vector_groups.items():
        resolved[name] = (comps, db.axes.group_frame(name))  # type: ignore[assignment]
    for name, comps in _DEFAULT_GROUPS.items():
        if name not in resolved and all(c in db.vars for c in comps):
            resolved[name] = (comps, "body")
    if requested is not None:
        missing = [name for name in requested if name not in resolved]
        if missing:
            raise VectorGroupError(
                f"vector groups {missing}",
                "rotate could not resolve them from declarations or the "
                "naming convention",
                "declare them with db.declare_vector, or use the "
                "(FX, FY, FZ) / (MX, MY, MZ) convention (REQ-38)",
            )
        resolved = {name: resolved[name] for name in requested}
    if not resolved:
        raise VectorGroupError(
            "the VarFrame",
            "rotate found no vector group to transform",
            "declare a group with db.declare_vector, or provide "
            "(FX, FY, FZ) / (MX, MY, MZ) variables (REQ-38)",
        )
    return resolved


def _angle_field(
    db: VarFrame, name: str
) -> tuple[_Array, _Array | None, _Array | None]:
    """Full-grid angle field in radians, plus its uncertainty fields.

    Reads the value in the unit of the source Dimension or Variable and
    converts to radians (fail-loud if the unit is absent). Only a
    Variable source can carry uncertainty.
    """
    shape = db.shape
    if name in db.dims:
        dim = db.dims[name]
        unit = dim.unit
        axis = list(db.dims).index(name)
        bshape = [1] * len(shape)
        bshape[axis] = dim.cardinality
        field = np.broadcast_to(
            np.asarray(dim.coords, dtype=float).reshape(bshape), shape
        ).astype(float)
        u_sys = u_rand = None
    elif name in db.vars:
        unit = db.vars[name].unit
        field = np.asarray(db.vars[name].values, dtype=float)
        u_sys = (
            db.uncertainty.systematic.get(name) if db.uncertainty is not None else None
        )
        u_rand = db.uncertainty.random.get(name) if db.uncertainty is not None else None
    else:
        raise VectorGroupError(
            f"angle source '{name}'",
            "rotate needs it as a dimension or variable to evaluate a "
            "condition-dependent frame",
            f"provide '{name}' in the VarFrame (REQ-101)",
        )
    if unit is None:
        raise DataError(
            f"angle source '{name}'",
            "rotate cannot read a condition-dependent angle without a unit",
            "set the Dimension or Variable unit to 'deg' or 'rad' (REQ-101)",
        )
    field_rad = np.asarray(convert(field, unit, "rad"), dtype=float)
    if u_sys is not None:
        u_sys = np.asarray(convert(u_sys, unit, "rad"), dtype=float)
    if u_rand is not None:
        u_rand = np.asarray(convert(u_rand, unit, "rad"), dtype=float)
    return field_rad, u_sys, u_rand


def _dcm_fields(
    db: VarFrame, axis: Axis, shape: tuple[int, ...]
) -> tuple[_Array, dict[str, _Array], dict[str, tuple[_Array | None, _Array | None]]]:
    """Per-cell DCM field, its angle derivatives, and the angle unc fields."""
    if axis.is_constant:
        matrix = axis.matrix_at({})
        field = np.broadcast_to(matrix, (*shape, 3, 3)).astype(float)
        return field, {}, {}
    assert axis.angles_from is not None
    angle_data = {name: _angle_field(db, name) for name in axis.angles_from}
    field = np.empty((*shape, 3, 3))
    d_fields = {name: np.zeros((*shape, 3, 3)) for name in axis.angles_from}
    for idx in np.ndindex(shape):
        angles = {name: float(angle_data[name][0][idx]) for name in axis.angles_from}
        field[idx] = axis.matrix_at(angles)
        for name, grad in axis.d_matrix_d_angle(angles).items():
            d_fields[name][idx] = grad
    unc = {
        name: (angle_data[name][1], angle_data[name][2]) for name in axis.angles_from
    }
    return field, d_fields, unc


def _corr_matrix(db: VarFrame, comps: tuple[str, str, str]) -> _Array:
    """Build the 3x3 within-cell correlation matrix for the group (OQ-23)."""
    corr = np.eye(3)
    if db.correlation is None:
        return corr
    for i in range(3):
        for j in range(3):
            corr[i, j] = db.correlation.get(comps[i], comps[j])
    return corr


def rotate(
    db: VarFrame,
    target_axis: str,
    *,
    vector_groups: Sequence[str] | None = None,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Express detected vector groups in the target frame (REQ-38).

    See ``VarFrame.rotate`` for the full parameter description.
    """
    target = db.axes.resolve(target_axis)
    groups = _resolve_groups(db, vector_groups)
    shape = db.shape
    content = content_of(db)
    l_tb, dl_tb, tgt_unc = _dcm_fields(db, target, shape)

    source_cache: dict[str, tuple[_Array, dict[str, _Array], Any]] = {}
    for comps, source_name in groups.values():
        if source_name not in source_cache:
            source_cache[source_name] = _dcm_fields(
                db, db.axes.resolve(source_name), shape
            )
        l_sb, dl_sb, src_unc = source_cache[source_name]
        # Composite source-to-target rotation, per cell: R = L_tb @ L_sb^T.
        r = np.einsum("...kj,...mj->...km", l_tb, l_sb)
        v = np.stack([content.values[c] for c in comps], axis=-1)
        rotated = np.einsum("...kj,...j->...k", r, v)
        for i, comp in enumerate(comps):
            content.values[comp] = rotated[..., i]

        for label in ("systematic", "random"):
            component = getattr(content, label)
            if component is None or not all(c in component for c in comps):
                continue
            u = np.stack([component[c] for c in comps], axis=-1)
            corr = _corr_matrix(db, comps)
            cov = (u[..., :, None] * u[..., None, :]) * corr
            cov_t = np.einsum("...kj,...jl,...ml->...km", r, cov, r)
            var = np.einsum("...kk->...k", cov_t).copy()
            var += _angle_terms(
                label, comps, v, l_tb, dl_tb, tgt_unc, l_sb, dl_sb, src_unc
            )
            for i, comp in enumerate(comps):
                component[comp] = np.sqrt(np.maximum(var[..., i], 0.0))

    detail = f"target='{target_axis}', groups={sorted(groups)}"
    operation = f"rotate({detail})"
    return rebuild(db, content, operation=operation, comment=comment, history=history)


def _angle_terms(
    label: str,
    comps: tuple[str, str, str],
    v: _Array,
    l_tb: _Array,
    dl_tb: dict[str, _Array],
    tgt_unc: dict[str, tuple[_Array | None, _Array | None]],
    l_sb: _Array,
    dl_sb: dict[str, _Array],
    src_unc: dict[str, tuple[_Array | None, _Array | None]],
) -> _Array:
    """Chain-rule variance from uncertain frame angles (REQ-101)."""
    idx = 0 if label == "systematic" else 1
    extra = np.zeros(v.shape)
    # Target-frame angles: dR/dtheta = (dL_tb/dtheta) @ L_sb^T.
    for name, d_l_tb in dl_tb.items():
        u_angle = tgt_unc[name][idx]
        if u_angle is None:
            continue
        d_r = np.einsum("...kj,...mj->...km", d_l_tb, l_sb)
        sens = np.einsum("...kj,...j->...k", d_r, v)
        extra += sens**2 * u_angle[..., None] ** 2
    # Source-frame angles: dR/dtheta = L_tb @ (dL_sb/dtheta)^T.
    for name, d_l_sb in dl_sb.items():
        u_angle = src_unc[name][idx]
        if u_angle is None:
            continue
        d_r = np.einsum("...kj,...mj->...km", l_tb, d_l_sb)
        sens = np.einsum("...kj,...j->...k", d_r, v)
        extra += sens**2 * u_angle[..., None] ** 2
    return extra
