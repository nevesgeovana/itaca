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

from itaca.core.errors import DataError, UncertaintyError, UncertaintyLineageError
from itaca.core.varframe import _UNSET, VarFrame
from itaca.core.variable import Variable
from itaca.ops._content import content_of, rebuild
from itaca.uncertainty._lineage import (
    describe_roots,
    describe_unreadable,
    shared_ancestry,
    single_expression,
    unknown_only,
)
from itaca.uncertainty.expression import (
    Node,
    condition_mask,
    is_elementwise,
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
    # FND-058, SEAT-UNC. Two carriers derived from a common root are not
    # independent, and this engine keeps no lineage between compute
    # calls, so their covariance term would be silently omitted. Refuse
    # BEFORE evaluating: a number that will not be returned should not be
    # computed, and the check must run ahead of the debug report so that
    # report never describes a derivation that is about to be refused.
    groups = db.axes.vector_groups
    origin = shared_ancestry(db.history, carriers, db.correlation, groups)
    if origin is not None:
        name_a, name_b, roots = origin
        suggestion = single_expression(db.history, name, text, groups)
        fix = (
            f"write it as one expression, which is already correct: "
            f'db.compute("{suggestion}")'
            if suggestion is not None
            else (
                "write the whole derivation as a single compute expression "
                "in terms of the original variables, which is already "
                "correct because the chain rule sees the whole tree at once"
            )
        )
        if unknown_only(roots):
            # VV-10. Saying "both were derived from" about two variables
            # that may well be independent roots is a false statement,
            # and the rewrite advice that follows it cannot be carried
            # out when there is no derivation to rewrite. This frame is
            # refused for a different reason and says so, and the way out
            # is the declaration, which IS executable.
            raise UncertaintyLineageError(
                f"variables '{name_a}' and '{name_b}' in equation '{equation}'",
                f"this frame's History records "
                f"{describe_unreadable(db.history, groups)}, whose effect on "
                f"where a variable came from compute cannot read, so it "
                f"cannot rule out that these two share an origin. They may "
                f"well be independent; what is missing is the evidence, not "
                f"the independence",
                f"if you know the pair, declare it and compute proceeds: "
                f"db.set_correlation({{('{name_a}', '{name_b}'): 0.0}}) for "
                f"independent, or the coefficient if they are correlated. "
                f"Otherwise rebuild the quantity from the original variables "
                f"in a single expression on a frame whose History compute can "
                f"read (SEAT-UNC, REQ-41)",
            )
        raise UncertaintyLineageError(
            f"variables '{name_a}' and '{name_b}' in equation '{equation}'",
            f"both were derived from {describe_roots(roots)}, so they are "
            f"correlated, and compute carries no lineage between calls: the "
            f"covariance term would be omitted and u({name}) would be wrong "
            f"in an unpredictable direction",
            f"{fix}; or declare the pair with "
            f"db.set_correlation({{('{name_a}', '{name_b}'): r}}) if you know "
            f"r. Propagating this composition instead of refusing it needs "
            f"lineage with sensitivities and is v0.3.0 work (SEAT-UNC, "
            f"REQ-41)",
        )
    if debug:
        # REQ-34's report reads the FRAME's data, so it is produced
        # before the mask substitution below and not after. Reported
        # after, it printed NaN for every variable whenever grid point
        # zero fell outside the mask, which is the ordinary case for a
        # filter, and a debug surface that hides the data at the moment
        # a user asks to see it is worse than the warning it avoids.
        # Two consequences of the ORDER, both stated rather than hidden.
        # Under `debug=True` the sample evaluation runs over the full
        # grid, so a masked-out domain violation can still warn there;
        # REQ-35 carries that as the second of its two exemptions. And a
        # malformed `where` string now raises AFTER the report has
        # printed, because `condition_mask` runs below: the report
        # describes the equation, which was already parsed, so it is not
        # describing work that never happened.
        _debug_report(name, text, tree, env, db, carriers)
    mask: NDArray[Any] | None = None
    if where is not None:
        # FND-073. The mask is resolved HERE, on the untouched
        # environment, and then applied to the environment itself.
        # `where=` used to mask only the RESULT: values and derivatives
        # were evaluated over the whole grid and the mask applied to
        # what came out, so a cell the caller excluded still went
        # through the arithmetic. Measured on `sqrt` over a masked-out
        # negative: two RuntimeWarnings with an uncertainty carrier,
        # from expression.py (the value) and operators.py (the
        # derivative), one without, none on all-positive data.
        #
        # NaN is what excludes a cell, rather than a sentinel or a
        # gather-and-scatter, because NaN is already the library's
        # absent value and because NumPy propagates it through every
        # ELEMENTWISE operator WITHOUT warning: `sqrt(nan)` is `nan` in
        # silence where `sqrt(-1)` is not.
        #
        # `is_elementwise` is the precondition and not a precaution.
        # REQ-36 lets any `np.*` function into an expression carrying no
        # uncertainty, and a reduction reads cells other than its own,
        # so the sentinel would reach the cells the mask was protecting:
        # measured, `y = np.max(v)` over `v = [-1, 1, 3]` with
        # `where='v >= 0'` returned `nan` IN the mask where it had
        # returned 3.0. Those trees keep the whole-grid evaluation and
        # therefore keep the warning; the limit is documented on the
        # public method rather than silently accepted.
        mask = np.broadcast_to(condition_mask(where, known, env), db.shape)
        if is_elementwise(tree):
            env = {
                var: np.where(mask, np.asarray(values, dtype=float), np.nan)
                for var, values in env.items()
            }
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
    if mask is not None:
        if fill is None:
            base = (
                content.values[name]
                if name in content.values
                else np.full(db.shape, np.nan)
            )
        else:
            base = np.full(db.shape, fill, dtype=float)
        values = np.where(mask, values, base)

        # REQ-35: uncertainty only for filtered-in points, and FND-090:
        # under `fill=None` the out-of-mask cell is not a filtered-out
        # point, it is a point this compute did not touch. It kept its
        # prior VALUE through `base` above and lost its prior
        # UNCERTAINTY here, so a surviving number came back paired with
        # `u = NaN`. Measured: x = [100., 2.] with u(x) = [nan, 0.2]
        # where the prior was [10., 0.4].
        #
        # An explicit `fill` is the other case and stays as it was: it
        # WRITES a value the expression did not produce, so carrying the
        # uncertainty of the value it replaced would pair a number with
        # an uncertainty belonging to a different one.
        priors = (content.systematic or {}, content.random or {})

        def _masked(
            propagated: NDArray[Any] | None, prior: NDArray[Any] | None
        ) -> NDArray[Any] | None:
            keep = prior if fill is None else None
            if propagated is None and keep is None:
                return None
            inside = (
                np.broadcast_to(propagated, db.shape)
                if propagated is not None
                else np.full(db.shape, np.nan)
            )
            outside = (
                np.broadcast_to(keep, db.shape)
                if keep is not None
                else np.full(db.shape, np.nan)
            )
            return np.asarray(np.where(mask, inside, outside))

        unc_sys = _masked(unc_sys, priors[0].get(name))
        unc_rand = _masked(unc_rand, priors[1].get(name))
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
    # REQ-91 and ITACA-024: the target's uncertainty is exactly what this
    # expression implies. Clearing first and writing only what
    # propagation returned means nothing survives from the assignment
    # being replaced, and a component with no carrier is DELETED rather
    # than written as a fabricated zero, so absence keeps meaning "not
    # assigned" rather than "assigned to be exact".
    if content.systematic is not None or content.random is not None:
        systematic = dict(content.systematic or {})
        random = dict(content.random or {})
        systematic.pop(name, None)
        random.pop(name, None)
        if unc_sys is not None:
            systematic[name] = np.broadcast_to(unc_sys, db.shape)
        if unc_rand is not None:
            random[name] = np.broadcast_to(unc_rand, db.shape)
        # Back to None, not to an empty UncFrame, when the target was the
        # only carrier: rebuild keys on `is not None`.
        content.systematic = systematic or None
        content.random = random or None
    elif unc_sys is not None or unc_rand is not None:
        content.systematic = (
            {name: np.broadcast_to(unc_sys, db.shape)} if unc_sys is not None else None
        )
        content.random = (
            {name: np.broadcast_to(unc_rand, db.shape)}
            if unc_rand is not None
            else None
        )
    # A pair naming an OVERWRITTEN target described the values that were
    # replaced. A brand-new target has no pairs to drop, so unrelated
    # declarations survive.
    overwritten = name in db.vars and db.correlation is not None
    new_correlation: object = (
        db.correlation.without({name}) if overwritten else _UNSET  # type: ignore[union-attr]
    )
    operation = (
        f"compute('{name} = {text}', method='{method}', where={where!r}, fill={fill!r})"
    )
    if overwritten:
        operation += ", correlation=dropped"
    replay: dict[str, Any] = {"equation": equation}
    if method != "symbolic":
        replay["method"] = method
    if where is not None:
        replay["where"] = where
    if not (isinstance(fill, float) and fill != fill):
        # Omit the default NaN fill: it is not JSON-safe and replay
        # restores it from the method default anyway.
        replay["fill"] = fill
    return rebuild(
        db,
        content,
        operation=operation,
        comment=comment,
        history=history,
        correlation=new_correlation,
        call="compute",
        replay_kwargs=replay,
    )
