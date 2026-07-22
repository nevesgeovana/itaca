"""db.combine: explicit arithmetic combination of VarFrames (REQ-37).

Python operators on VarFrames are intentionally unsupported (DD-12,
NREQ-08): every combination declares its semantics, records itself in
History, and consults the declared correlation structure.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.arithmetic import (
    combine_components,
    operations,
    worst_case_tags,
)
from itaca.core.errors import DataError, OperatingModeMixError
from itaca.core.varframe import VarFrame


def _component_of(db: VarFrame, label: str, name: str) -> NDArray[Any] | None:
    if db.uncertainty is None:
        return None
    component: Mapping[str, NDArray[Any]] = getattr(db.uncertainty, label)
    return component.get(name)


def _validate_alignment(db: VarFrame, other: VarFrame) -> None:
    if db.mode != other.mode:
        raise OperatingModeMixError(
            f"VarFrames in modes '{db.mode}' and '{other.mode}'",
            "combine requires both inputs in the same operating mode",
            "call db.promote(...) or db.demote(...) explicitly first (REQ-12)",
        )
    if list(db.dims) != list(other.dims):
        raise DataError(
            f"dimensions {list(db.dims)} vs {list(other.dims)}",
            "combine requires identical dimensions",
            "align the inputs with select/interpolate first (REQ-37)",
        )
    for name, dim in db.dims.items():
        if not np.array_equal(dim.coords, other.dims[name].coords):
            raise DataError(
                f"dimension '{name}'",
                "combine found different coordinates in the two inputs",
                "align the grids first; combine is strictly elementwise (REQ-37)",
            )
    if set(db.vars) != set(other.vars):
        only_left = sorted(set(db.vars) - set(other.vars))
        only_right = sorted(set(other.vars) - set(db.vars))
        raise DataError(
            f"variables only in one input: {only_left + only_right}",
            "combine requires the same variable set on both sides",
            "select matching variables before combining (REQ-37)",
        )


def combine(
    db: VarFrame,
    other: VarFrame,
    *,
    op: str,
    weights: tuple[float, float] | None = None,
    cross_correlation: float = 0.0,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Combine two VarFrames elementwise under a named operation.

    See ``VarFrame.combine`` for the full parameter description.
    """
    from itaca.ops._content import content_of, rebuild

    _validate_alignment(db, other)
    table = operations(weights)
    if op == "weighted_mean" and weights is None:
        raise DataError(
            "combine(op='weighted_mean')",
            "called without weights",
            "pass weights=(w_left, w_right) (REQ-37)",
        )
    if op not in table:
        raise DataError(
            f"op {op!r}",
            "combine received an unknown operation",
            f"use one of {sorted([*operations((1.0, 1.0))])} (REQ-37)",
        )
    operation_impl = table[op]
    content = content_of(db)
    systematic: dict[str, NDArray[Any]] = {}
    random: dict[str, NDArray[Any]] = {}
    tags: dict[str, NDArray[Any]] = {}
    has_tags = db.tags is not None or other.tags is not None
    for name in content.values:
        values_a = content.values[name]
        values_b = other.vars[name].values
        content.values[name] = operation_impl.evaluate(values_a, values_b)
        for label, store in (("systematic", systematic), ("random", random)):
            combined = combine_components(
                operation_impl,
                values_a,
                values_b,
                _component_of(db, label, name),
                _component_of(other, label, name),
                cross_correlation,
            )
            if combined is not None:
                store[name] = combined
        if has_tags:
            zeros = np.zeros(db.shape, dtype=np.int8)
            tags_a = db.tags.tags.get(name, zeros) if db.tags is not None else zeros
            tags_b = (
                other.tags.tags.get(name, zeros) if other.tags is not None else zeros
            )
            tags[name] = worst_case_tags(tags_a, tags_b)
    content.systematic = systematic or None
    content.random = random or None
    content.tags = tags if has_tags else None
    operation = (
        f"combine(op='{op}', with={other.state_hash[:12]}, "
        f"cross_correlation={cross_correlation})"
    )
    return rebuild(db, content, operation=operation, comment=comment, history=history)
