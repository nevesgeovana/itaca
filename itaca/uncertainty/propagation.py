"""GUM clause-5 LPU with covariance, two components (REQ-41, DD-14, DD-19).

The engine always evaluates the full clause-5 formula; with an all-zero
correlation matrix it reduces to the independence form, so users who
declare no correlations pay no accuracy cost. The systematic and
random components propagate separately and recombine as RSS only at
reporting time (REQ-99).

Note (REQ-98/REQ-99 draft gate): the declared correlation r(a, b)
applies identically to both components. This choice is on the Phase 4
checkpoint list for Geovana's validation before freezing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.correlation import CorrelationMatrix
from itaca.core.uncframe import UncFrame
from itaca.uncertainty.expression import Node

_Array = NDArray[Any]


def propagate(
    tree: Node,
    env: Mapping[str, _Array],
    uncertainty: UncFrame,
    correlation: CorrelationMatrix | None,
    names: Sequence[str],
) -> tuple[_Array | None, _Array | None]:
    """Propagate both uncertainty components through an expression.

    Implements the GUM clause-5 law of propagation of uncertainty with
    covariance (REQ-41): partial derivatives come from chain rule on
    the operator tree; the correlation terms use the declared matrix.

    Parameters
    ----------
    tree : Node
        Parsed expression tree.
    env : mapping of str to numpy.ndarray
        Evaluation environment (variable values).
    uncertainty : UncFrame
        The two-component uncertainty mirror of the input VarFrame.
    correlation : CorrelationMatrix or None
        Declared correlation structure; ``None`` means independence.
    names : sequence of str
        Expression variables to consider (the per-variable guard of
        REQ-36 is applied by the caller).

    Returns
    -------
    tuple of (numpy.ndarray or None, numpy.ndarray or None)
        Systematic and random components of the derived quantity;
        ``None`` when no input carries that component.
    """
    carriers = [
        name
        for name in names
        if name in uncertainty.systematic or name in uncertainty.random
    ]
    if not carriers:
        return None, None
    derivatives = {name: tree.derivative(env, name) for name in carriers}
    results: list[_Array | None] = []
    for component in (uncertainty.systematic, uncertainty.random):
        present = [name for name in carriers if name in component]
        if not present:
            results.append(None)
            continue
        variance: _Array = np.asarray(0.0)
        for name in present:
            variance = variance + np.square(derivatives[name] * component[name])
        for name_a, name_b in combinations(present, 2):
            r = correlation.get(name_a, name_b) if correlation else 0.0
            if r:
                variance = variance + (
                    2.0
                    * derivatives[name_a]
                    * derivatives[name_b]
                    * r
                    * component[name_a]
                    * component[name_b]
                )
        results.append(np.asarray(np.sqrt(np.maximum(variance, 0.0))))
    return results[0], results[1]
