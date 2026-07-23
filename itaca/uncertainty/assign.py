"""db.set_uncertainty and db.set_correlation (REQ-39, REQ-40, REQ-99)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.correlation import CorrelationMatrix
from itaca.core.errors import (
    CorrelationKeyError,
    UncertaintyError,
    UncertaintyKeyError,
)
from itaca.core.pipeline import PipelineStep, to_jsonable
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame

_COMPONENTS = ("systematic", "random")


def _resolve_value(
    name: str, value: float | str, reference: NDArray[Any]
) -> NDArray[Any]:
    if isinstance(value, str):
        if not value.endswith("%"):
            raise UncertaintyError(
                f"uncertainty {value!r} for '{name}'",
                "string values must be relative percentages",
                'use a float (absolute) or e.g. "0.05%" (relative, REQ-39)',
            )
        fraction = float(value[:-1]) / 100.0
        return np.asarray(fraction * np.abs(reference))
    return np.full(reference.shape, float(value))


def set_uncertainty(
    db: VarFrame,
    spec: Mapping[str, float | str],
    *,
    component: str = "systematic",
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Assign standard uncertainties to variables (REQ-39, REQ-99).

    See ``VarFrame.set_uncertainty`` for the parameter description.
    """
    if component not in _COMPONENTS:
        raise UncertaintyError(
            f"component {component!r}",
            "set_uncertainty accepts only the two REQ-99 components",
            "use component='systematic' (default) or component='random'",
        )
    for name in spec:
        if name not in db.vars:
            raise UncertaintyKeyError(
                f"variable '{name}'",
                "set_uncertainty key does not match any variable",
                f"available variables: {list(db.vars)}",
            )
    systematic = dict(db.uncertainty.systematic) if db.uncertainty else {}
    random = dict(db.uncertainty.random) if db.uncertainty else {}
    target = systematic if component == "systematic" else random
    for name, value in spec.items():
        target[name] = _resolve_value(name, value, db.vars[name].values)
    operation = f"set_uncertainty(vars={sorted(spec)}, component='{component}')"
    return db._derive(
        operation=operation,
        comment=comment,
        history=history,
        uncertainty=UncFrame(systematic=systematic, random=random),
        step=PipelineStep(
            call="set_uncertainty",
            kwargs={
                "spec": {name: to_jsonable(value) for name, value in spec.items()},
                "component": component,
            },
            comment=comment,
        ),
    )


def set_correlation(
    db: VarFrame,
    spec: Mapping[tuple[str, str], float],
    *,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Declare correlation coefficients between variables (REQ-40).

    See ``VarFrame.set_correlation`` for the parameter description.
    """
    for name_a, name_b in spec:
        for name in (name_a, name_b):
            if name not in db.vars:
                raise CorrelationKeyError(
                    f"variable '{name}'",
                    "set_correlation references a variable that is absent",
                    f"available variables: {list(db.vars)}",
                )
    canonical_new = {
        (a, b) if a < b else (b, a): float(r) for (a, b), r in spec.items()
    }
    merged = (
        {**dict(db.correlation.pairs), **canonical_new}
        if db.correlation is not None
        else canonical_new
    )
    operation = f"set_correlation(pairs={sorted(canonical_new)})"
    return db._derive(
        operation=operation,
        comment=comment,
        history=history,
        correlation=CorrelationMatrix(pairs=merged),
        # JSON object keys cannot be tuples, so the declared pairs are
        # recorded as [a, b, r] triples and rebuilt on replay.
        step=PipelineStep(
            call="set_correlation",
            kwargs={"spec": [[a, b, r] for (a, b), r in canonical_new.items()]},
            comment=comment,
        ),
    )
