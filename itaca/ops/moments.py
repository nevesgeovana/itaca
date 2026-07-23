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
    db: VarFrame, default: tuple[str, str, str], role: str
) -> tuple[str, str, str]:
    for comps in db.axes.vector_groups.values():
        if tuple(comps) == default:
            return default
    if all(c in db.vars for c in default):
        return default
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
    force = _group(db, _FORCE, "force")
    moment = _group(db, _MOMENT, "moment")
    to_pt = _point(to_point, "to_point")
    from_pt = _point(from_point, "from_point")
    offset = from_pt - to_pt
    skew = _skew(offset)

    content = content_of(db)
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
        if component is None or not all(c in component for c in channels):
            continue
        u = np.stack([component[c] for c in channels], axis=-1)
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


def _corr6(db: VarFrame, channels: tuple[str, ...]) -> _Array:
    """Build the 6x6 correlation matrix over the force and moment channels."""
    corr = np.eye(len(channels))
    if db.correlation is None:
        return corr
    for i, a in enumerate(channels):
        for j, b in enumerate(channels):
            corr[i, j] = db.correlation.get(a, b)
    return corr
