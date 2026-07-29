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
from itaca.core.correlation import CorrelationMatrix
from itaca.core.errors import DataError, UncertaintyError, VectorGroupError
from itaca.core.uncframe import standard_uncertainty
from itaca.core.varframe import _UNSET, VarFrame
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
    # De-duplicate the convention-detected groups by COMPONENTS, not only
    # by name: a group declared under another name over the same triplet
    # already claims those variables, and detecting them again rotates
    # them twice in one call (ITACA-020b). moments.py resolves the alias
    # case the same way.
    claimed = {tuple(comps) for comps in db.axes.vector_groups.values()}
    for name, comps in _DEFAULT_GROUPS.items():
        if (
            name not in resolved
            and comps not in claimed
            and all(c in db.vars for c in comps)
        ):
            # group_axis defaults to 'body', so this is behavior-preserving
            # on a fresh frame while no longer contradicting an axis that
            # a previous rotate recorded.
            resolved[name] = (comps, db.axes.group_axis(name))
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


def _angles_carry_uncertainty(
    label: str,
    dl_tb: dict[str, _Array],
    tgt_unc: dict[str, tuple[_Array | None, _Array | None]],
    dl_sb: dict[str, _Array],
    src_unc: dict[str, tuple[_Array | None, _Array | None]],
) -> bool:
    """Report whether a frame angle carries this component's uncertainty.

    A constant axis contributes no angles at all, so both dicts are
    empty and the answer is False.
    """
    idx = 0 if label == "systematic" else 1
    return any(tgt_unc[name][idx] is not None for name in dl_tb) or any(
        src_unc[name][idx] is not None for name in dl_sb
    )


def _reject_cross_group_correlation(db: VarFrame, comps: tuple[str, str, str]) -> None:
    """Fail loud on a pair joining a rotated component to an outsider (OQ-34).

    The rotation transforms the covariance WITHIN a vector group. A pair
    with one foot inside the group and one outside would be left holding
    its pre-rotation coefficient, which is the ITACA-025 defect in a
    different place. The joint treatment is an open modeling question,
    so the pair is refused rather than silently kept or silently
    dropped. A declared coefficient of exactly zero does not fire: a
    zero cross covariance transforms to zero.
    """
    if db.correlation is None:
        return
    inside = set(comps)
    for pair, value in db.correlation.pairs.items():
        if value and len(inside.intersection(pair)) == 1:
            raise UncertaintyError(
                f"declared correlation {pair}",
                "rotate transforms the covariance within a vector group "
                "only, so a pair that joins a rotated component to a "
                "variable outside its group would be left holding its "
                "pre-rotation coefficient",
                "drop the pair before rotating and declare it again in the "
                "target axis, or await the OQ-34 joint-covariance "
                "resolution (REQ-40)",
            )


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

    pairs = dict(db.correlation.pairs) if db.correlation is not None else {}
    declared = set(pairs)
    not_stored: list[tuple[str, str]] = []
    registry = db.axes
    source_cache: dict[str, tuple[_Array, dict[str, _Array], Any]] = {}
    for name, (comps, source_name) in groups.items():
        # A group already expressed in the target is left exactly alone:
        # no propagation, no invented UncFrame keys, no guard. Identity is
        # decided by axis NAME and never by matrix equality, so a
        # parametric frame cannot drift by a rounding step.
        if source_name == target_axis:
            continue
        if source_name not in source_cache:
            source_cache[source_name] = _dcm_fields(
                db, db.axes.resolve(source_name), shape
            )
        l_sb, dl_sb, src_unc = source_cache[source_name]
        _reject_angle_correlation(db, comps, dl_tb, dl_sb)
        _reject_cross_group_correlation(db, comps)
        # Composite source-to-target rotation, per cell: R = L_tb @ L_sb^T.
        r = np.einsum("...kj,...mj->...km", l_tb, l_sb)
        v = np.stack([content.values[c] for c in comps], axis=-1)
        rotated = np.einsum("...kj,...j->...k", r, v)
        for i, comp in enumerate(comps):
            content.values[comp] = rotated[..., i]

        cov_by_label: dict[str, _Array] = {}
        for label in ("systematic", "random"):
            component = getattr(content, label)
            if component is None:
                continue
            has_comp = any(c in component for c in comps)
            # REQ-101: a rotation driven by a MEASURED angle is not exact,
            # even when every vector component is. The old gate reached
            # the angle term only from inside the component branch.
            has_angle = _angles_carry_uncertainty(label, dl_tb, tgt_unc, dl_sb, src_unc)
            if not has_comp and not has_angle:
                continue
            u = np.stack(
                [_component_field(component, c, shape) for c in comps], axis=-1
            )
            corr = _corr_matrix(db, comps)
            cov = (u[..., :, None] * u[..., None, :]) * corr
            cov_t = np.einsum("...kj,...jl,...ml->...km", r, cov, r)
            cov_t = cov_t + _angle_covariance(
                label, v, l_tb, dl_tb, tgt_unc, l_sb, dl_sb, src_unc
            )
            cov_by_label[label] = cov_t
            var = np.einsum("...kk->...k", cov_t)
            diagonal = np.einsum("...kj,...j->...k", r**2, u**2)
            for i, comp in enumerate(comps):
                component[comp] = standard_uncertainty(
                    var[..., i],
                    diagonal[..., i],
                    terms=9,
                    obj=f"{label} uncertainty of '{comp}'",
                    operation=f"rotate to '{target_axis}'",
                )

        # Skip entirely when nothing was propagated: a frame declaring a
        # correlation but carrying no uncertainty must keep its
        # declaration rather than have it deleted by an operation that
        # computed no covariance at all (OQ-36).
        if cov_by_label:
            _rewrite_group_correlation(pairs, declared, comps, cov_by_label, not_stored)
        registry = (
            registry.with_vector_group(name, comps)
            if (name not in registry.vector_groups)
            else registry
        )
        registry = registry.with_group_axis(name, target_axis)

    detail = f"target='{target_axis}', groups={sorted(groups)}"
    if not_stored:
        detail += f", correlation_not_stored={sorted(not_stored)}"
    operation = f"rotate({detail})"
    new_correlation: object = _UNSET
    if db.correlation is not None or pairs:
        new_correlation = CorrelationMatrix(pairs=pairs) if pairs else None
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        correlation=new_correlation,
        axes=registry if registry is not db.axes else _UNSET,
        call="rotate",
        replay_kwargs={
            "target_axis": target_axis,
            "vector_groups": vector_groups,
        },
    )


# The primary degeneracy mask is sd == 0 or a non-finite quotient:
# measured, a rank-deficient rotation gives a transformed variance of
# EXACTLY 0.0 and a 0/0 quotient, not a tiny positive number. This
# relative floor is a secondary defense against round-off dust, measured
# up to 1.3e-16 relative in genuinely rank-deficient rotations. Its
# value is an engineering constant and is NOT frozen: see OQ-35.
_VAR_FLOOR = 1e-24
# Below this the recomputed coefficient is treated as no correlation at
# all rather than stored as numerical noise (OQ-35).
_RHO_FLOOR = 1e-12


def _rewrite_group_correlation(
    pairs: dict[tuple[str, str], float],
    declared: set[tuple[str, str]],
    comps: tuple[str, str, str],
    cov_by_label: dict[str, _Array],
    not_stored: list[tuple[str, str]],
) -> None:
    """Write the transformed covariance back as pair coefficients.

    ``rotate`` already builds the full transformed covariance and used
    to keep only its diagonal, leaving the declared off-diagonal in
    place. After a rotation that coefficient is not merely stale: with
    ``u = (0.1, 0.2, 0.3)`` and ``rho(FX, FY) = 0.5`` a 90 degree frame
    gives ``cov(FX, FY) = -0.01``, so the stored ``+0.5`` has the wrong
    SIGN.

    The store holds one scalar per pair, so a coefficient that varies
    from cell to cell, or that differs between the two uncertainty
    components, is not representable. It is refused when it was
    declared, because a declared coefficient that has become false
    corrupts every later propagation; it is recorded as not stored when
    the rotation created it, because refusing to invent a coefficient
    must not break the flagship REQ-101 case.
    """
    for i, j in ((0, 1), (0, 2), (1, 2)):
        name_a, name_b = comps[i], comps[j]
        key = (name_a, name_b) if name_a < name_b else (name_b, name_a)
        per_label: dict[str, float | None | str] = {}
        for label, cov_t in cov_by_label.items():
            per_label[label] = _reduce_coefficient(cov_t, i, j)
        values = [value for value in per_label.values() if value is not None]
        if not values:
            pairs.pop(key, None)
            continue
        if any(value == "varying" for value in values):
            _refuse_unrepresentable(key, declared, not_stored, varying=True)
            pairs.pop(key, None)
            continue
        numeric = [float(value) for value in values]
        if len(numeric) == 2 and not np.isclose(
            numeric[0], numeric[1], rtol=1e-9, atol=1e-12
        ):
            _refuse_unrepresentable(
                key, declared, not_stored, varying=False, values=numeric
            )
            pairs.pop(key, None)
            continue
        coefficient = float(np.clip(numeric[0], -1.0, 1.0))
        if abs(coefficient) <= _RHO_FLOOR:
            pairs.pop(key, None)
        else:
            pairs[key] = coefficient


def _reduce_coefficient(cov_t: _Array, i: int, j: int) -> float | None | str:
    """Reduce one pair's per-cell coefficient to a value, None or 'varying'."""
    var_i = cov_t[..., i, i]
    var_j = cov_t[..., j, j]
    total = np.einsum("...kk->...", cov_t)
    floor = _VAR_FLOOR * np.abs(total)
    sd_i = np.sqrt(np.maximum(var_i, 0.0))
    sd_j = np.sqrt(np.maximum(var_j, 0.0))
    denominator = sd_i * sd_j
    defined = (sd_i > 0.0) & (sd_j > 0.0) & (var_i > floor) & (var_j > floor)
    quotient = np.divide(
        cov_t[..., i, j],
        denominator,
        out=np.zeros_like(denominator),
        where=defined,
    )
    defined = defined & np.isfinite(quotient)
    if not np.any(defined):
        return None
    present = quotient[defined]
    if not np.allclose(present, present.flat[0], rtol=1e-9, atol=1e-12):
        return "varying"
    return float(present.flat[0])


def _refuse_unrepresentable(
    key: tuple[str, str],
    declared: set[tuple[str, str]],
    not_stored: list[tuple[str, str]],
    *,
    varying: bool,
    values: list[float] | None = None,
) -> None:
    """Raise for a declared pair, record one the rotation created."""
    if key not in declared:
        not_stored.append(key)
        return
    if varying:
        raise UncertaintyError(
            f"correlation pair {key}",
            "rotate recomputed a coefficient that differs from cell to "
            "cell, and the correlation store holds one coefficient per pair",
            "rotate one condition at a time with db.at or db.select, or "
            "drop the declaration before rotating (REQ-40)",
        )
    assert values is not None
    raise UncertaintyError(
        f"correlation pair {key}",
        f"rotate recomputed {values[0]!r} for the systematic component "
        f"and {values[1]!r} for the random component, and one coefficient "
        f"is shared by both (OQ-23)",
        "rotate a frame carrying a single uncertainty component, or drop "
        "the declaration before rotating (REQ-40)",
    )


def _angle_covariance(
    label: str,
    v: _Array,
    l_tb: _Array,
    dl_tb: dict[str, _Array],
    tgt_unc: dict[str, tuple[_Array | None, _Array | None]],
    l_sb: _Array,
    dl_sb: dict[str, _Array],
    src_unc: dict[str, tuple[_Array | None, _Array | None]],
) -> _Array:
    """Chain-rule covariance from uncertain frame angles (REQ-101).

    Sensitivities to the same angle variable through the target frame
    (``dL_tb @ L_sb^T``) and the source frame (``L_tb @ dL_sb^T``) are
    accumulated into a single ``dR/dtheta`` before the outer product, so
    a shared angle does not double-count and cancels correctly when the
    two contributions oppose. Angles are treated as mutually independent
    and independent of the vector components; a declared correlation
    involving an angle variable is rejected upstream (OQ-26).

    Returns the full ``(..., 3, 3)`` contribution rather than only its
    diagonal, which is how ``docs/derivations/uncertainty_kernels.md``
    section 4 writes the accepted model. The off-diagonal is the
    covariance a shared uncertain angle induces BETWEEN the rotated
    components: it is rank one per angle, so a single uncertain angle
    driving two components correlates them perfectly. Squaring it away,
    as the previous diagonal-only form did, discarded exactly the term
    the correlation write-back needs. The diagonal is unchanged to the
    last bit, since it is the same product in the same loop order.
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
    extra = np.zeros((*v.shape, 3))
    for name, sens in sens_by_angle.items():
        outer = sens[..., :, None] * sens[..., None, :]
        extra = extra + outer * unc_by_angle[name][..., None, None] ** 2
    return extra
