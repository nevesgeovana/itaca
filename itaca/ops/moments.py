"""db.translate_moments: transfer moments between reference points (REQ-100).

Applies the rigid moment transfer ``M' = M + r x F`` to each declared
moment vector group, where ``r = from_point - to_point`` is the offset
between the old and new reference points (the standard result
``M_B = M_A + (r_A - r_B) x F``). The transfer is linear in the force
and moment channels, so the Jacobian ``[skew(r) | I]`` is exact and
the covariance between force and moment channels propagates when
declared (OQ-23). Origin tags are preserved unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    DataError,
    UncertaintyLineageError,
    VectorGroupError,
)
from itaca.core.uncframe import standard_uncertainty
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild
from itaca.uncertainty._lineage import earlier_transfer

_Array = NDArray[Any]

_FORCE = ("FX", "FY", "FZ")
_MOMENT = ("MX", "MY", "MZ")


def _skew(r: _Array) -> _Array:
    """Skew matrix S(r) such that S(r) @ F = r x F."""
    return np.array(
        [
            [0.0, -r[2], r[1]],
            [r[2], 0.0, -r[0]],
            [-r[1], r[0], 0.0],
        ]
    )


def _group(
    db: VarFrame,
    role: str,
    default: tuple[str, str, str],
    selected: str | None,
) -> tuple[tuple[str, str, str], str]:
    """Resolve the components and source axis of the force/moment group.

    An explicit ``selected`` group name wins; otherwise a group
    declared under the role name (``"force"`` / ``"moment"``), honoring
    its per-group source axis (REQ-107); otherwise the default-named
    ``(FX, FY, FZ)`` / ``(MX, MY, MZ)`` variables in the body axis.
    """
    if selected is not None:
        if selected not in db.axes.vector_groups:
            raise VectorGroupError(
                f"the {role} group '{selected}'",
                "translate_moments could not find that declared group",
                f"declare it with db.declare_vector, or drop {role}= (REQ-100)",
            )
        comps = db.axes.vector_groups[selected]
        return comps, db.axes.group_axis(selected)  # type: ignore[return-value]
    if role in db.axes.vector_groups:
        comps = db.axes.vector_groups[role]
        return comps, db.axes.group_axis(role)  # type: ignore[return-value]
    for name, comps in db.axes.vector_groups.items():
        if tuple(comps) == default:
            return default, db.axes.group_axis(name)
    if all(c in db.vars for c in default):
        return default, "body"
    raise VectorGroupError(
        f"the {role} vector group",
        f"translate_moments needs a resolvable {role} group",
        f"declare it with db.declare_vector, or provide {list(default)} (REQ-100)",
    )


def _point(value: Sequence[float] | None, name: str) -> _Array:
    if value is None:
        return np.zeros(3)
    array = np.asarray(value, dtype=float)
    if array.shape != (3,):
        raise DataError(
            f"{name}={list(np.atleast_1d(array))}",
            "translate_moments needs a three-component reference point",
            "pass a length-three [x, y, z] point (REQ-100)",
        )
    return array


def translate_moments(
    db: VarFrame,
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

    See ``VarFrame.translate_moments`` for the full parameter
    description.
    """
    force_comps, force_axis = _group(db, "force", _FORCE, force)
    moment_comps, moment_axis = _group(db, "moment", _MOMENT, moment)
    if force_axis != moment_axis:
        raise DataError(
            f"force axis '{force_axis}' and moment axis '{moment_axis}'",
            "translate_moments needs the force and moment groups in the "
            "same axis system",
            "rotate them into a common axis first (REQ-100)",
        )
    if axis is not None and axis != force_axis:
        raise DataError(
            f"axis='{axis}' against the group axis '{force_axis}'",
            "translate_moments takes the offset in the group's own axis "
            "system; a differing offset axis is not rotated yet",
            f"pass axis='{force_axis}' or None, or rotate the data first (REQ-100)",
        )
    to_pt = _point(to_point, "to_point")
    from_pt = _point(from_point, "from_point")
    offset = from_pt - to_pt
    skew = _skew(offset)

    channels = (*force_comps, *moment_comps)
    # FND-074, SEAT-UNC. Refused BEFORE anything is computed, so a frame
    # is never half-transferred. The FIRST transfer is exact: it builds
    # the full 6x6 covariance from the declared correlations and applies
    # the Jacobian. What it cannot do is RECORD that its output moments
    # are now correlated with the forces, because a correlation induced
    # by an operation has nowhere to live in this frame. A second
    # transfer therefore reads them as independent and understates.
    _refuse_second_transfer(db, channels, to_pt)

    content = content_of(db)
    shape = db.shape
    f = np.stack([content.values[c] for c in force_comps], axis=-1)
    m = np.stack([content.values[c] for c in moment_comps], axis=-1)
    # M' = M + r x F, per cell.
    transferred = m + np.einsum("kj,...j->...k", skew, f)
    for i, comp in enumerate(moment_comps):
        content.values[comp] = transferred[..., i]

    jac = np.hstack([skew, np.eye(3)])  # 3x6: M' = [S | I] @ [F; M]
    for label in ("systematic", "random"):
        component = getattr(content, label)
        if component is None or not any(c in component for c in channels):
            continue
        u = np.stack([_channel_field(component, c, shape) for c in channels], axis=-1)
        corr = _corr6(db, channels)
        cov = (u[..., :, None] * u[..., None, :]) * corr
        cov_m = np.einsum("ki,...ij,lj->...kl", jac, cov, jac)
        var = np.einsum("...kk->...k", cov_m)
        diagonal = np.einsum("ki,...i->...k", jac**2, u**2)
        for i, comp in enumerate(moment_comps):
            component[comp] = standard_uncertainty(
                var[..., i],
                diagonal[..., i],
                terms=36,
                obj=f"{label} uncertainty of '{comp}'",
                operation="translate_moments rigid transfer",
                fix=(
                    f"the declared correlation among {list(channels)} makes "
                    "their joint covariance impossible, so the transferred "
                    "variance is negative; review those pairs with "
                    "db.correlation (REQ-40)"
                ),
            )

    # Only the moment components are rewritten; the force components are
    # untouched, so a blanket drop would discard a still-valid
    # declaration. Pairs naming a moment no longer describe what that
    # name holds.
    new_correlation = (
        db.correlation.without(set(moment_comps))
        if db.correlation is not None
        else None
    )
    axis_note = f", axis='{axis}'" if axis is not None else ""
    operation = (
        f"translate_moments(to_point={list(to_pt)}, "
        f"from_point={list(from_pt)}{axis_note})"
    )
    if db.correlation is not None and (
        new_correlation is None
        or dict(new_correlation.pairs) != dict(db.correlation.pairs)
    ):
        operation += ", correlation=dropped"
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        correlation=new_correlation,
        call="translate_moments",
        replay_kwargs={
            "to_point": to_point,
            "from_point": from_point,
            "axis": axis,
            "force": force,
            "moment": moment,
        },
    )


def _refuse_second_transfer(
    db: VarFrame, channels: tuple[str, ...], to_pt: _Array
) -> None:
    """Refuse a transfer stacked on an earlier one (FND-074, SEAT-UNC).

    Only when a channel actually carries uncertainty: with none declared
    there is no covariance to lose and repeated transfers are ordinary
    arithmetic on the values, which compose exactly.

    Deliberately coarse. Any earlier ``translate_moments`` in this
    frame's History arms the refusal, without checking that it moved the
    SAME group, so translating a second, unrelated moment group is
    refused too. That is the conservative direction and it is cheap to
    work around; missing a real one is neither.
    """
    if db.uncertainty is None:
        return
    carried = [
        name
        for name in channels
        if name in db.uncertainty.systematic or name in db.uncertainty.random
    ]
    if not carried:
        return
    origin = earlier_transfer(db.history)
    if origin is None:
        return
    raise UncertaintyLineageError(
        f"moment channels {list(channels)} of VarFrame with uncertainty on "
        f"{sorted(carried)}",
        "translate_moments was already applied to this frame, so its "
        "moments are correlated with its forces through M' = M + r x F, "
        "and that induced correlation is not recorded anywhere: a second "
        "transfer would treat them as independent and UNDERSTATE the "
        "result (measured 1.414 where 2.0 is correct, 29 percent low)",
        f"do it in one call from the original reference point: "
        f"db.translate_moments(to_point={[float(v) for v in to_pt]}, "
        f"from_point={[float(v) for v in origin]}), which gives the same "
        f"moments and the correct uncertainty because one Jacobian spans "
        f"the whole transfer. Carrying the induced correlation forward "
        f"instead needs lineage with sensitivities and is v0.3.0 work "
        f"(SEAT-UNC, REQ-100)",
    )


def _channel_field(
    component: dict[str, _Array], name: str, shape: tuple[int, ...]
) -> _Array:
    """Uncertainty of a channel, or zeros when it carries none (DD-18)."""
    if name in component:
        return component[name]
    return np.zeros(shape)


def _corr6(db: VarFrame, channels: tuple[str, ...]) -> _Array:
    """Build the 6x6 correlation matrix over the force and moment channels."""
    corr = np.eye(len(channels))
    if db.correlation is None:
        return corr
    for i, a in enumerate(channels):
        for j, b in enumerate(channels):
            corr[i, j] = db.correlation.get(a, b)
    return corr
