"""db.compute: string equation derivation (REQ-33 to REQ-36).

Symbolic GUM propagation is automatic when any expression variable
carries uncertainty. Monte Carlo (``method="mcm"``) ships in v0.3.0
(DD-21, REQ-42) and fails loud until then.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import DataError, UncertaintyError
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable
from itaca.ops._content import content_of, rebuild
from itaca.uncertainty.expression import (
    Node,
    condition_mask,
    parse_expression,
)
from itaca.uncertainty.propagation import propagate

_EQUATION = re.compile(r"^\s*(\w+)\s*=\s*(.+?)\s*$", re.DOTALL)


def _debug_report(
    name: str,
    text: str,
    tree: Node,
    env: dict[str, NDArray[Any]],
    db: VarFrame,
    carriers: list[str],
) -> None:
    # REQ-34: structured report before applying the equation.
    lines = [f"compute debug: {name} = {text}"]
    lines.append(f"  tokens (RPN): {tree.tokens()}")
    names = sorted(tree.variables())
    lines.append(f"  variables: {names}")
    sample = tuple(0 for _ in db.shape)
    lines.append(f"  sample point (grid index {sample}):")
    for variable in names:
        lines.append(f"    {variable} = {env[variable][sample]:.6g}")
    lines.append(f"    {name} = {float(tree.evaluate(env)[sample]):.6g}")
    if carriers:
        lines.append("  partial derivatives at the sample point:")
        for variable in carriers:
            partial = float(tree.derivative(env, variable)[sample])
            lines.append(f"    d{name}/d{variable} = {partial:.6g}")
        if db.correlation is not None:
            lines.append(f"  correlation pairs: {dict(db.correlation.pairs)}")
    print("\n".join(lines))


def compute(
    db: VarFrame,
    equation: str,
    *,
    debug: bool = False,
    where: str | None = None,
    fill: float | None = np.nan,
    method: str = "symbolic",
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Derive a new variable from a string equation (REQ-33).

    See ``VarFrame.compute`` for the full parameter description.
    """
    if method == "mcm":
        raise UncertaintyError(
            "compute(method='mcm')",
            "Monte Carlo propagation is not part of M0",
            "it ships in v0.3.0 (REQ-42, DD-21); use method='symbolic'",
        )
    if method != "symbolic":
        raise DataError(
            f"method {method!r}",
            "compute received an unknown method",
            "use 'symbolic' (default) or 'mcm' from v0.3.0 (REQ-33)",
        )
    match = _EQUATION.match(equation)
    if match is None:
        raise DataError(
            f"equation '{equation}'",
            "compute expects the form 'VAR = expression'",
            'example: db.compute("CL = FZ / (q * S_ref)") (REQ-33)',
        )
    name, text = match.group(1), match.group(2)
    known = set(db.vars)
    tree = parse_expression(text, known)
    env = {var: variable.values for var, variable in db.vars.items()}
    carriers = (
        sorted(
            var
            for var in tree.variables()
            if db.uncertainty is not None
            and (var in db.uncertainty.systematic or var in db.uncertainty.random)
        )
        if db.uncertainty is not None
        else []
    )
    if debug:
        _debug_report(name, text, tree, env, db, carriers)
    values = np.broadcast_to(
        np.asarray(tree.evaluate(env), dtype=float), db.shape
    ).copy()
    unc_sys: NDArray[Any] | None = None
    unc_rand: NDArray[Any] | None = None
    if carriers:
        assert db.uncertainty is not None
        unc_sys, unc_rand = propagate(
            tree, env, db.uncertainty, db.correlation, carriers
        )
    content = content_of(db)
    tags = dict(content.tags) if content.tags is not None else {}
    new_tag = np.ones(db.shape, dtype=np.int8)
    if where is not None:
        mask = np.broadcast_to(condition_mask(where, known, env), db.shape)
        if fill is None:
            base = (
                content.values[name]
                if name in content.values
                else np.full(db.shape, np.nan)
            )
        else:
            base = np.full(db.shape, fill, dtype=float)
        values = np.where(mask, values, base)
        # REQ-35: uncertainty only for filtered-in points.
        if unc_sys is not None:
            unc_sys = np.where(mask, np.broadcast_to(unc_sys, db.shape), np.nan)
        if unc_rand is not None:
            unc_rand = np.where(mask, np.broadcast_to(unc_rand, db.shape), np.nan)
        previous_tag = (
            tags.get(name, np.zeros(db.shape, dtype=np.int8))
            if fill is None
            else np.zeros(db.shape, dtype=np.int8)
        )
        new_tag = np.where(mask, np.int8(1), previous_tag).astype(np.int8)
    content.values[name] = values
    content.meta = {
        **content.meta,
        name: Variable(name=name, values=values),
    }
    tags[name] = new_tag
    content.tags = tags
    if unc_sys is not None or unc_rand is not None:
        systematic = dict(content.systematic or {})
        random = dict(content.random or {})
        if unc_sys is not None:
            systematic[name] = np.broadcast_to(unc_sys, db.shape)
        if unc_rand is not None:
            random[name] = np.broadcast_to(unc_rand, db.shape)
        content.systematic = systematic
        content.random = random
    operation = (
        f"compute('{name} = {text}', method='{method}', where={where!r}, fill={fill!r})"
    )
    return rebuild(db, content, operation=operation, comment=comment, history=history)
