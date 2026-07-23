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

from itaca.core.errors import DataError, VectorGroupError
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild

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
    db: VarFrame, role: str, default: tuple[str, str, str]
) -> tuple[tuple[str, str, str], str]:
    """Resolve the components and source frame of the force/moment group.

    A group declared under the role name (``"force"`` / ``"moment"``)
    wins, honoring its per-group source frame (REQ-107); otherwise the
    default-named ``(FX, FY, FZ)`` / ``(MX, MY, MZ)`` variables are used
    in the body frame.
    """
    if role in db.axes.vector_groups:
        comps = db.axes.vector_groups[role]
        return comps, db.axes.group_frame(role)  # type: ignore[return-value]
    for name, comps in db.axes.vector_groups.items():
        if tuple(comps) == default:
            return default, db.axes.group_frame(name)
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
    frame: str | None = None,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Transfer declared moments to a new reference point (REQ-100).

    See ``VarFrame.translate_moments`` for the full parameter
    description.
    """
    force, force_frame = _group(db, "force", _FORCE)
    moment, moment_frame = _group(db, "moment", _MOMENT)
    if force_frame != moment_frame:
        raise DataError(
            f"force frame '{force_frame}' and moment frame '{moment_frame}'",
            "translate_moments needs the force and moment groups in the same frame",
            "rotate them into a common frame first (REQ-100)",
        )
    if frame is not None and frame != force_frame:
        raise DataError(
            f"frame='{frame}' against the group frame '{force_frame}'",
            "translate_moments takes the offset in the group's own frame; "
            "a differing offset frame is not rotated yet",
            f"pass frame='{force_frame}' or None, or rotate the data first (REQ-100)",
        )
    to_pt = _point(to_point, "to_point")
    from_pt = _point(from_point, "from_point")
    offset = from_pt - to_pt
    skew = _skew(offset)

    content = content_of(db)
    shape = db.shape
    f = np.stack([content.values[c] for c in force], axis=-1)
    m = np.stack([content.values[c] for c in moment], axis=-1)
    # M' = M + r x F, per cell.
    transferred = m + np.einsum("kj,...j->...k", skew, f)
    for i, comp in enumerate(moment):
        content.values[comp] = transferred[..., i]

    channels = (*force, *moment)
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
        for i, comp in enumerate(moment):
            component[comp] = np.sqrt(np.maximum(var[..., i], 0.0))

    frame_note = f", frame='{frame}'" if frame is not None else ""
    operation = (
        f"translate_moments(to_point={list(to_pt)}, "
        f"from_point={list(from_pt)}{frame_note})"
    )
    return rebuild(db, content, operation=operation, comment=comment, history=history)


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
