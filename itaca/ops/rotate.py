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
from itaca.core.errors import DataError, UncertaintyError, VectorGroupError
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
    """Return name -> (components, source axis) for the groups to rotate."""
    resolved: dict[str, tuple[tuple[str, str, str], str]] = {}
    for name, comps in db.axes.vector_groups.items():
        resolved[name] = (comps, db.axes.group_axis(name))  # type: ignore[assignment]
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


def _component_field(
    component: dict[str, _Array], name: str, shape: tuple[int, ...]
) -> _Array:
    """Uncertainty of a channel, or zeros when it carries none.

    A group where only some channels carry uncertainty still propagates
    (the missing channels contribute zero variance), rather than
    silently dropping the whole group (DD-18).
    """
    if name in component:
        return component[name]
    return np.zeros(shape)


def _reject_angle_correlation(
    db: VarFrame,
    comps: tuple[str, str, str],
    dl_tb: dict[str, _Array],
    dl_sb: dict[str, _Array],
) -> None:
    """Fail loud on a declared correlation involving a frame angle (OQ-26).

    The rotation propagation treats frame angles as mutually independent
    and independent of the vector components. Consulting a declared
    angle correlation (the cross terms of the joint covariance) is an
    open modeling question (OQ-26); until it is resolved, a declared
    correlation touching an angle variable raises rather than being
    silently dropped (REQ-40).
    """
    if db.correlation is None:
        return
    angles = set(dl_tb) | set(dl_sb)
    if not angles:
        return
    for pair in db.correlation.pairs:
        touched = angles.intersection(pair)
        if touched:
            raise UncertaintyError(
                f"declared correlation {pair}",
                "rotation propagation does not yet consult a correlation "
                "involving a frame angle (angle independence, OQ-26)",
                "drop the angle correlation, or await the OQ-26 "
                "resolution; the angle-independent rule is applied "
                "otherwise",
            )


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
        _reject_angle_correlation(db, comps, dl_tb, dl_sb)
        # Composite source-to-target rotation, per cell: R = L_tb @ L_sb^T.
        r = np.einsum("...kj,...mj->...km", l_tb, l_sb)
        v = np.stack([content.values[c] for c in comps], axis=-1)
        rotated = np.einsum("...kj,...j->...k", r, v)
        for i, comp in enumerate(comps):
            content.values[comp] = rotated[..., i]

        for label in ("systematic", "random"):
            component = getattr(content, label)
            if component is None or not any(c in component for c in comps):
                continue
            u = np.stack(
                [_component_field(component, c, shape) for c in comps], axis=-1
            )
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
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        call="rotate",
        replay_kwargs={
            "target_axis": target_axis,
            "vector_groups": vector_groups,
        },
    )


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
    """Chain-rule variance from uncertain frame angles (REQ-101).

    Sensitivities to the same angle variable through the target frame
    (``dL_tb @ L_sb^T``) and the source frame (``L_tb @ dL_sb^T``) are
    accumulated into a single ``dR/dtheta`` before squaring, so a shared
    angle does not double-count and cancels correctly when the two
    contributions oppose. Angles are treated as mutually independent
    and independent of the vector components; a declared correlation
    involving an angle variable is rejected upstream (OQ-26).
    """
    idx = 0 if label == "systematic" else 1
    # Accumulate the total sensitivity dR/dtheta @ v per distinct angle
    # variable, from both the target and source frames.
    sens_by_angle: dict[str, _Array] = {}
    unc_by_angle: dict[str, _Array] = {}
    for name, d_l_tb in dl_tb.items():
        u_angle = tgt_unc[name][idx]
        if u_angle is None:
            continue
        d_r = np.einsum("...kj,...mj->...km", d_l_tb, l_sb)
        sens = np.einsum("...kj,...j->...k", d_r, v)
        sens_by_angle[name] = sens_by_angle.get(name, np.zeros(v.shape)) + sens
        unc_by_angle[name] = u_angle
    for name, d_l_sb in dl_sb.items():
        u_angle = src_unc[name][idx]
        if u_angle is None:
            continue
        d_r = np.einsum("...kj,...mj->...km", l_tb, d_l_sb)
        sens = np.einsum("...kj,...j->...k", d_r, v)
        sens_by_angle[name] = sens_by_angle.get(name, np.zeros(v.shape)) + sens
        unc_by_angle[name] = u_angle
    extra = np.zeros(v.shape)
    for name, sens in sens_by_angle.items():
        extra += sens**2 * unc_by_angle[name][..., None] ** 2
    return extra
