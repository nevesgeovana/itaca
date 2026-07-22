"""db.inspect: dimension-vs-variable candidacy analysis (REQ-13).

Inspection is read-only: it prints, returns ``None``, and records
nothing in History.
"""

from __future__ import annotations

import numpy as np

from itaca.core.varframe import VarFrame
from itaca.io.pivot import is_datapoint


def inspect(db: VarFrame, threshold: int = 20) -> None:
    """Analyze a datapoint-mode VarFrame and print a candidacy report.

    A column is a dimension candidate when it has at most
    ``threshold`` unique values and its values repeat across rows; a
    column that never repeats is a variable; anything else is
    ambiguous. A no-op (with a notice) on structured VarFrames.

    Parameters
    ----------
    db : VarFrame
        The VarFrame to analyze.
    threshold : int, optional
        Unique-value bound for dimension candidacy, 20 by default.

    Examples
    --------
    >>> import numpy as np
    >>> from itaca.io.loader import load
    >>> load(np.array([[0.1, 1.0]]), names=["mach", "CT"]).inspect()
    ... # doctest: +SKIP
    """
    if not is_datapoint(db):
        print(
            "inspect: VarFrame is already structured "
            f"(dims: {list(db.dims)}); nothing to analyze (REQ-13)"
        )
        return
    n_rows = db.dims["datapoint"].cardinality
    candidates: list[str] = []
    print(f"inspect: {n_rows} datapoint(s), {len(db.vars)} column(s)")
    for name, variable in db.vars.items():
        finite = variable.values[np.isfinite(variable.values)]
        n_unique = int(np.unique(finite).size)
        if n_unique <= threshold and n_unique < finite.size:
            verdict = "dimension candidate"
            candidates.append(name)
        elif n_unique == finite.size:
            verdict = "variable"
        else:
            verdict = "ambiguous"
        print(f"  {name}: {n_unique} unique value(s) -> {verdict}")
    if candidates:
        grid_size = int(
            np.prod(
                [
                    np.unique(
                        db.vars[name].values[np.isfinite(db.vars[name].values)]
                    ).size
                    for name in candidates
                ]
            )
        )
        coverage = 100.0 * n_rows / grid_size if grid_size else 0.0
        print(f"  grid coverage estimate over {candidates}: {coverage:.1f} percent")
