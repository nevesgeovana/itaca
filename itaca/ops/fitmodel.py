"""db.fitmodel: replace a dimension by polynomial coefficients (REQ-31).

The swept dimension becomes ``<dim>_coef`` with string labels
``dim^0`` to ``dim^N`` (ascending exponents, OQ-11). The original
sweep range is recorded in the coefficient dimension's description so
that ``fitvalue`` can tag evaluations inside (+1) or beyond (-1) the
fitted range (REQ-32). The normative REQ-98 table declares no
fitmodel row, so the operation raises when uncertainty is present
rather than guessing (DD-18); the gap is queued for the author
(OQ-24).

``fitvalue`` is the forward evaluation ``sum_k c_k t^k``, linear in
the coefficients, so it propagates both UncFrame components exactly
through the evaluation weights ``t^k`` (systematic as the absolute
weighted sum, random as the root sum of squares). This forward rule
is distinct from and unaffected by the open OQ-24 question, which
concerns only the inverse least-squares coefficient covariance that
``fitmodel`` would produce; whether ``fitvalue`` should nonetheless
defer until fitmodel-produced coefficient uncertainty exists is
queued for the author.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.dimension import Dimension
from itaca.core.errors import (
    DataError,
    DimensionNotFoundError,
    NonNumericDimensionError,
    UncertaintyError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild

_Array = NDArray[Any]

FIT_RANGE_TEMPLATE = "polynomial fit coefficients over {dim}=[{lo}, {hi}]"


def fitmodel(
    db: VarFrame,
    *,
    along: str,
    deg: int,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Fit a polynomial along a dimension (REQ-31).

    See ``VarFrame.fitmodel`` for the full parameter description.
    """
    if along not in db.dims:
        raise DimensionNotFoundError(
            f"dimension '{along}'",
            "fitmodel(along=...) referenced an absent dimension",
            f"available dimensions: {list(db.dims)}",
        )
    if not db.dims[along].is_numeric:
        raise NonNumericDimensionError(
            f"dimension '{along}'",
            "fitmodel along a string-valued dimension",
            "numerical operations need numeric coordinates (SRS 4.1.3)",
        )
    n = db.dims[along].cardinality
    if deg < 0 or deg >= n:
        raise DataError(
            f"deg {deg} against {n} points",
            "fitmodel needs more points than the polynomial degree",
            "reduce deg or densify the sweep first (REQ-31)",
        )
    if db.uncertainty is not None:
        raise UncertaintyError(
            "fitmodel",
            "the REQ-98 table declares no coefficient propagation rule for fitmodel",
            "fit before assigning uncertainty (DD-18); the rule is "
            "queued for the author",
        )
    coef_name = f"{along}_coef"
    if coef_name in db.dims or coef_name in db.vars:
        raise DataError(
            f"name '{coef_name}'",
            "fitmodel would collide with an existing dimension or variable",
            "rename the holder before fitting (REQ-31)",
        )

    content = content_of(db)
    axis = list(content.dims).index(along)
    x = np.asarray(content.dims[along].coords, dtype=float)
    labels = np.array([f"{along}^{k}" for k in range(deg + 1)])
    coef_dim = Dimension(
        name=coef_name,
        coords=labels,
        is_numeric=False,
        description=FIT_RANGE_TEMPLATE.format(
            dim=along, lo=float(x.min()), hi=float(x.max())
        ),
    )

    new_tags: dict[str, _Array] = {}
    for name, values in content.values.items():
        moved = np.moveaxis(values, axis, -1)
        flat = moved.reshape(-1, n)
        coeffs = np.full((flat.shape[0], deg + 1), np.nan)
        for row in range(flat.shape[0]):
            line = flat[row]
            finite = np.isfinite(line)
            if int(finite.sum()) > deg:
                # np.polyfit returns descending powers; store ascending
                # to match the alpha^k labels (OQ-11).
                coeffs[row] = np.polyfit(x[finite], line[finite], deg)[::-1]
        out_shape = (*moved.shape[:-1], deg + 1)
        content.values[name] = np.moveaxis(coeffs.reshape(out_shape), -1, axis)
        if content.tags is not None and name in content.tags:
            # A coefficient inherits the worst case of its whole line.
            moved_t = np.moveaxis(content.tags[name], axis, -1).reshape(-1, n)
            worst = np.zeros(moved_t.shape[0], dtype=np.int8)
            worst[np.any(moved_t == 1, axis=-1)] = 1
            worst[np.any(moved_t == -1, axis=-1)] = -1
            spread = np.repeat(worst[:, None], deg + 1, axis=-1)
            new_tags[name] = np.moveaxis(spread.reshape(out_shape), -1, axis)

    dims = [
        (coef_name, coef_dim) if name == along else (name, content.dims[name])
        for name in content.dims
    ]
    content.dims = dict(dims)
    content.tags = new_tags if content.tags is not None else None
    operation = f"fitmodel(along='{along}', deg={deg})"
    return rebuild(db, content, operation=operation, comment=comment, history=history)


def _parse_fit_range(dim: Dimension) -> tuple[str, float, float] | None:
    """Recover (source dim, lo, hi) from the recorded description."""
    text = dim.description or ""
    prefix = "polynomial fit coefficients over "
    if not text.startswith(prefix):
        return None
    try:
        spec = text[len(prefix) :]
        source, bounds = spec.split("=", 1)
        lo_text, hi_text = bounds.strip("[]").split(",")
        return source.strip(), float(lo_text), float(hi_text)
    except ValueError:
        return None


def fitvalue(
    db: VarFrame,
    *,
    coef_dims: list[str],
    at: dict[str, Any],
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Evaluate fitmodel coefficients at coordinates (REQ-32).

    See ``VarFrame.fitvalue`` for the full parameter description.
    """
    from itaca.ops._reduction import reduce_random, reduce_systematic

    content = content_of(db)
    consumed_sources: set[str] = set()
    for coef_name in coef_dims:
        if coef_name not in content.dims:
            raise DimensionNotFoundError(
                f"dimension '{coef_name}'",
                "fitvalue referenced an absent coefficient dimension",
                f"available dimensions: {list(content.dims)}",
            )
        source = coef_name.removesuffix("_coef")
        if source == coef_name or source not in at:
            raise DataError(
                f"coefficient dimension '{coef_name}'",
                "fitvalue could not pair it with an evaluation grid",
                f"pass at={{'{source or coef_name}': array}} matching "
                "the fitted dimension (REQ-32)",
            )
        consumed_sources.add(source)
        targets = np.atleast_1d(np.asarray(at[source], dtype=float))
        coef_dim = content.dims[coef_name]
        n_coef = coef_dim.cardinality
        fit_range = _parse_fit_range(coef_dim)
        if fit_range is None:
            raise DataError(
                f"coefficient dimension '{coef_name}'",
                "fitvalue could not recover the fitted range from its "
                "description, so it cannot tag in-range versus "
                "out-of-range evaluations",
                "produce the coefficients with db.fitmodel, which "
                "records the range (REQ-32)",
            )
        axis = list(content.dims).index(coef_name)
        # Evaluation weights: w_k(t) = t^k, ascending like the labels.
        weights = np.power(targets[:, None], np.arange(n_coef)[None, :])

        new_tags: dict[str, _Array] = {}
        for name, values in content.values.items():
            moved = np.moveaxis(values, axis, -1)
            flat = moved.reshape(-1, n_coef)
            out = flat @ weights.T
            out_shape = (*moved.shape[:-1], targets.size)
            content.values[name] = np.moveaxis(out.reshape(out_shape), -1, axis)
            for label, rule in (
                ("systematic", reduce_systematic),
                ("random", reduce_random),
            ):
                component = getattr(content, label)
                if component is not None and name in component:
                    moved_u = np.moveaxis(component[name], axis, -1).reshape(flat.shape)
                    evaluated = np.stack(
                        [
                            rule(weights[row], moved_u, -1)
                            for row in range(targets.size)
                        ],
                        axis=-1,
                    )
                    component[name] = np.moveaxis(
                        evaluated.reshape(out_shape), -1, axis
                    )
            _, lo, hi = fit_range
            inside = (targets >= lo) & (targets <= hi)
            line_tags = np.where(inside, np.int8(1), np.int8(-1))
            spread = np.broadcast_to(line_tags, (flat.shape[0], targets.size)).copy()
            new_tags[name] = np.moveaxis(spread.reshape(out_shape), -1, axis).astype(
                np.int8
            )

        new_dim = Dimension(name=source, coords=targets)
        dims = [
            (source, new_dim) if name == coef_name else (name, content.dims[name])
            for name in content.dims
        ]
        content.dims = dict(dims)
        content.tags = new_tags

    unused = sorted(set(at) - consumed_sources)
    if unused:
        raise DataError(
            f"at keys {unused}",
            "fitvalue was given evaluation grids for dimensions it did not fit",
            f"pass at keys matching {sorted(consumed_sources)} "
            "(check for a typo) (REQ-32)",
        )
    at_detail = {name: np.atleast_1d(np.asarray(v)).tolist() for name, v in at.items()}
    operation = f"fitvalue(coef_dims={coef_dims}, at={at_detail})"
    return rebuild(db, content, operation=operation, comment=comment, history=history)
