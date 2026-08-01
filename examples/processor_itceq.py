"""Processors and the .itceq equation file (REQ-45 to REQ-48).

A processor is a reusable, version-controlled analysis workflow. An
.itceq file declares one in five TOML sections and needs no Python at
all, so the recipe lives in git next to the data it processes and is
reviewed and diffed like any other source file.

The file below declares ``q_inf`` after the coefficients that consume
it. That is deliberate: it shows both halves of DD-17. In the default
file order the workflow would fail, and ``auto_sort=True`` resolves the
dependency order and reports the order it chose.

The ``[corrections]`` section shows the second thing worth learning
here. A correction chained onto a quantity it already depends on is a
product of two correlated quantities, and ``compute`` carries no
lineage between calls, so it refuses that composition rather than
omitting a covariance term and reporting an uncertainty that is wrong in
an unpredictable direction (REQ-41). The same correction written as one
expression is accepted, because within a single expression every
occurrence of a variable is the same quantity and the correlation is
carried exactly.

"Exactly" there means to the first order that the law of propagation of
uncertainty (LPU, GUM clause 5) already works to, which is the accuracy
REQ-41 promises everywhere; it is not a claim that the propagated
uncertainty of a nonlinear expression is exact in the ordinary sense.
This correction is cubic in ``CL``, so its uncertainty is a first-order
result, as it would be under any LPU treatment.

All data is synthetic (textbook curves), see examples/README.md for the
provenance statement.
"""

from pathlib import Path

import numpy as np

import itaca as itc

OUTPUT = Path(__file__).parent / "output"

ITCEQ = """\
[meta]
name        = "Balance campaign: power off"
version     = "1.0"
description = "6-component internal balance, AIAA S-071A-1999 aligned"

[constants]
S_ref = 0.1963
c_ref = 0.2526

[uncertainties]
FX  = 0.005
FZ  = 0.005
MY  = 0.0002
V   = 0.02
rho = "0.05%"

[equations]
CL    = "FZ / (q_inf * S_ref)"
CD    = "FX / (q_inf * S_ref)"
CM    = "MY / (q_inf * S_ref * c_ref)"
q_inf = "0.5 * rho * V**2"

[corrections]
# blockage is reported for the record. CL_corr does NOT multiply by it,
# and the repetition below is deliberate: blockage and CL both descend
# from the same measured channels, so `CL * blockage` is a product of
# two correlated quantities across two separate calls, and compute
# carries no lineage between calls (REQ-41). Written as ONE expression
# every occurrence of CL is the same quantity, so the correlation is
# carried rather than dropped, which is why the engine accepts this form
# and refuses the other. The result is still a first-order value under
# the law of propagation of uncertainty: the expression is cubic in CL.
blockage = "1 + 0.005 * CL**2"
CL_corr  = "CL * (1 + 0.005 * CL**2)"
"""


def _run() -> itc.VarFrame:
    """One synthetic balance run: alpha swept, six raw channels."""
    rng = np.random.default_rng(7)
    alpha = np.arange(-4.0, 12.1, 2.0)
    count = alpha.size
    columns = [
        alpha,
        40.0 + 3.2 * alpha + rng.normal(0.0, 0.05, count),  # FZ
        2.0 + 0.02 * alpha**2 + rng.normal(0.0, 0.01, count),  # FX
        -0.8 - 0.05 * alpha + rng.normal(0.0, 0.005, count),  # MY
        np.full(count, 30.0),  # V
        np.full(count, 1.225),  # rho
    ]
    names = ["alpha", "FZ", "FX", "MY", "V", "rho"]
    return itc.load(np.column_stack(columns), names=names).pivot(dims=["alpha"])


def main() -> None:
    """Build a processor from an .itceq file and apply it to a run."""
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / "balance_off.itceq"
    path.write_text(ITCEQ, encoding="utf-8")

    # Construct by path (REQ-46). Cycles are caught here, before any
    # computation; auto_sort additionally reports the resolved order.
    processor = itc.processor(path, auto_sort=True)
    processor.info()

    db = _run()
    processor.validate(db)  # every input the file needs is present
    processed = processor(db, comment="power-off sweep")

    derived = sorted(set(processed.vars) - set(db.vars))
    print(f"derived: {derived}")
    assert processed.uncertainty is not None  # propagated from [uncertainties]
    print(f"CL uncertainty at alpha=0: {processed.uncertainty.systematic['CL'][2]:.3e}")

    # Each equation is an ordinary recorded operation, so the whole
    # application lifts into a reusable pipeline (REQ-53).
    pipeline = processed.history.to_pipeline()
    print(f"application lifts into {len(pipeline)} replayable steps")

    # A second application is refused: corrections applied twice corrupt
    # the data (DD-16, REQ-47). force=True allows it and still warns.
    try:
        processor(processed)
    except itc.ITACAError as error:
        print(f"reapplication refused: {error}")

    # Configuration overrides a default declared in [constants] (REQ-46).
    rescaled = itc.processor(path, config={"S_ref": 0.25}, auto_sort=True)
    print(f"S_ref override: {rescaled.constants['S_ref']}")


if __name__ == "__main__":
    main()
