"""db.set_uncertainty and db.set_correlation (REQ-39, REQ-40, REQ-99)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.correlation import CorrelationMatrix
from itaca.core.errors import (
    CorrelationKeyError,
    DataError,
    UncertaintyError,
    UncertaintyKeyError,
)
from itaca.core.pipeline import PipelineStep, _to_jsonable
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame

_COMPONENTS = ("systematic", "random")


def _scalar(name: str, value: object, origin: str, display: object) -> float:
    """Parse the declared magnitude, refusing anything that is not one.

    ``float()`` was called unguarded on both branches, so a typo in a
    percentage escaped as ``ValueError`` and a wrong type as
    ``TypeError``, neither inside the hierarchy REQ-81 promises
    (``ITACA-031``).

    Finiteness is checked here, on the DECLARED magnitude, and that is
    known to be the proximate cause rather than the structural one. The
    structural home is :class:`~itaca.core.uncframe.UncFrame`, beside the
    negativity rule and on the assembled array, because a relative spec
    resolves against the data and a valid ``"5%"`` against a variable
    carrying NaN still produces a non-finite standard uncertainty without
    passing through this function. That fix was attempted and reverted:
    the array legitimately carries NaN for cells ``compute(where=)`` and
    ``fill`` did not touch, so NaN means BOTH missing and invalid there
    and separating the two is a numerical-analyst decision. Registered as
    OQ-40 with the measurement; the remaining hole is pinned by an xfail
    ratchet rather than left in prose (``R3-ITA-007``).

    ``display`` is what the caller actually passed, so the first part of
    the message names an object they can find in their own code; the
    percentage branch parses a stripped copy the caller never typed.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise UncertaintyError(
            f"uncertainty {display!r} for '{name}'",
            f"{origin} is not a number",
            'use a float (absolute) or e.g. "0.05%" (relative, REQ-39)',
        ) from error
    if not np.isfinite(number):
        raise UncertaintyError(
            f"uncertainty {display!r} for '{name}'",
            f"{origin} is not finite, and a non-finite standard uncertainty "
            f"would propagate into every quantity derived from '{name}'",
            "declare a finite, non-negative standard uncertainty; a "
            "standard uncertainty is a standard deviation, and the "
            "combined form sums finite terms (GUM clauses 2.3.1 and "
            "5.1.2, REQ-39)",
        )
    return number


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
        fraction = _scalar(name, value[:-1], "the percentage", value) / 100.0
        return np.asarray(fraction * np.abs(reference))
    return np.full(reference.shape, _scalar(name, value, "the value", value))


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
                "spec": {name: _to_jsonable(value) for name, value in spec.items()},
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
    # Delegate canonicalization to CorrelationMatrix rather than
    # repeating it here. Canonicalizing first made the conflict detector
    # unreachable from this entry point: {('a','b'): 0.1, ('b','a'): 0.9}
    # collapsed to one key and the later value won by dictionary order.
    # Validating what the caller actually passed catches it, and
    # validating the MERGED store applies the positive-semidefinite check
    # to the accumulated declaration, which no single call can see.
    declared = CorrelationMatrix(pairs=spec)
    merged = (
        {**dict(db.correlation.pairs), **dict(declared.pairs)}
        if db.correlation is not None
        else dict(declared.pairs)
    )
    operation = f"set_correlation(pairs={sorted(declared.pairs)})"
    return db._derive(
        operation=operation,
        comment=comment,
        history=history,
        correlation=CorrelationMatrix(pairs=merged),
        # JSON object keys cannot be tuples, so the declared pairs are
        # recorded as [a, b, r] triples and rebuilt on replay.
        step=PipelineStep(
            call="set_correlation",
            kwargs={"spec": [[a, b, r] for (a, b), r in declared.pairs.items()]},
            comment=comment,
        ),
    )


def drop_correlation(
    db: VarFrame,
    names: Sequence[str] | None = None,
    *,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Remove declared correlation pairs (REQ-40).

    See ``VarFrame.drop_correlation`` for the parameter description.
    """
    if db.correlation is None:
        return db
    if names is None:
        remaining = None
        detail = "all"
    else:
        missing = sorted(set(names) - set(db.vars))
        if missing:
            raise CorrelationKeyError(
                f"variable(s) {missing}",
                "drop_correlation references variables that are absent",
                f"available variables: {list(db.vars)}",
            )
        remaining = db.correlation.without(set(names))
        detail = f"names={sorted(names)}"
    return db._derive(
        operation=f"drop_correlation({detail})",
        comment=comment,
        history=history,
        correlation=remaining,
        step=PipelineStep(
            call="drop_correlation",
            kwargs={"names": (None if names is None else sorted(names))},
            comment=comment,
        ),
    )


def set_metadata(
    db: VarFrame,
    spec: Mapping[str, Mapping[str, str | None]],
    *,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Set unit, description or long name on dimensions and variables.

    See ``VarFrame.set_metadata`` for the parameter description.
    """
    dim_fields = {"unit", "description"}
    var_fields = {"unit", "description", "long_name"}
    new_dims = dict(db.dims)
    new_vars = dict(db.vars)
    for name, fields in spec.items():
        in_dims, in_vars = name in db.dims, name in db.vars
        if not in_dims and not in_vars:
            raise DataError(
                f"name '{name}'",
                "set_metadata references neither a dimension nor a variable",
                f"available dimensions {list(db.dims)}, variables {list(db.vars)}",
            )
        allowed = dim_fields if in_dims else var_fields
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise DataError(
                f"metadata field(s) {unknown} for '{name}'",
                "set_metadata received a field the target does not carry",
                f"a {'dimension' if in_dims else 'variable'} carries "
                f"{sorted(allowed)} (REQ-101, REQ-103)",
            )
        # replace() is typed against each field's own annotation, so a
        # str-valued mapping cannot be splatted under --strict; the
        # allowed-field check above is what makes this sound.
        if in_dims:
            new_dims[name] = replace(new_dims[name], **dict(fields))  # type: ignore[arg-type]
        else:
            new_vars[name] = replace(new_vars[name], **dict(fields))  # type: ignore[arg-type]
    detail = {name: dict(fields) for name, fields in sorted(spec.items())}
    return db._derive(
        operation=f"set_metadata({detail})",
        comment=comment,
        history=history,
        dims=new_dims,
        variables=new_vars,
        step=PipelineStep(
            call="set_metadata",
            kwargs={"spec": {n: dict(f) for n, f in spec.items()}},
            comment=comment,
        ),
    )
