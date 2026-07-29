# ITACA

[![PyPI](https://img.shields.io/pypi/v/itaca)](https://pypi.org/project/itaca/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21482648.svg)](https://doi.org/10.5281/zenodo.21482648)
[![CI](https://github.com/nevesgeovana/itaca/actions/workflows/ci.yml/badge.svg)](https://github.com/nevesgeovana/itaca/actions/workflows/ci.yml)

**Integrated Toolkit for Aerospace Computation and Analysis**

*From data to wisdom.*

```python
import itaca as itc
```

ITACA is a Python library for rigorous engineering data management,
analysis, and computation, with a primary focus on aerospace applications.
It manages multidimensional experimental and numerical datasets (wind
tunnel campaigns, CFD post-processing, flight-test data, engineering
computations) with mandatory provenance, automatic GUM-compliant
uncertainty propagation including covariance, and origin tags for every
value. Publication-quality plotting is roadmapped for v0.3.0 and is not
in the library today.

## Installation

```bash
pip install itaca
```

ITACA needs Python 3.11 or newer and depends only on NumPy. The pandas
bridge (`itc.load(df)`, `db.to_pandas()`) is optional:

```bash
pip install "itaca[pandas]"
```

## Quickstart

```python
import numpy as np
import itaca as itc

# Load, then declare which column is the sweep dimension.
rows = np.column_stack([[0.0, 2.0, 4.0], [10.0, 12.0, 14.0]])
db = itc.load(rows, names=["alpha", "FZ"]).pivot(dims=["alpha"])

# Assign an uncertainty; it propagates by the GUM rules, automatically.
db = db.set_uncertainty({"FZ": 0.05})
db = db.compute("CZ = FZ / 100.0")

print(db.vars["CZ"].values)             # [0.1  0.12 0.14]
print(db.uncertainty.systematic["CZ"])  # [0.0005 0.0005 0.0005]
print(db.history)                       # every step, in order
```

Every operation returns a **new** frame and records itself in History,
so nothing above mutates `db`. See `examples/` for a complete synthetic
wind tunnel walkthrough.

## Status

Pre-release. The milestone M0 foundation (release v0.1.0) is
implemented and test-covered: loading in all modes, inspection and
diagnostics, structural operations, two-component GUM uncertainty
propagation with covariance, string-equation derivation, explicit
combination, exports, and the `.itc` native format with state-hash
revalidation. The SRS is versioned in `docs/srs/`; its document version is stated in
one place, the top row of `docs/srs/frontmatter/revision_history.tex`.
Releases follow the incremental roadmap in the SRS Chapter 10: each
milestone ships on PyPI with a Zenodo DOI. See `examples/` for a
complete synthetic walkthrough.

## Design record

* `docs/srs/`: the SRS LaTeX sources, the authoritative reference for
  what ITACA must do and how it is built. First workspace-tracked
  version: document 0.1.0, 2026-07-21.
* `docs/DECISIONS.md`: the architectural decisions with long-form
  rationale (the file's own header carries the current range).
* `docs/OPEN_QUESTIONS.md`: the design questions with resolutions.
* `docs/SISTER_PYFLIGHTSTREAM.md`: the co-developed sister library
  (DD-22, DD-23): division of labor, the cross-requirement
  convention, and the shared review process.

## Core convictions

1. Data management before analysis: a result is only as trustworthy as
   the pipeline that produced it.
2. Provenance is mandatory: every dataset knows where it came from, what
   was done to it, by whom, and when.
3. Fail fast and loud: ambiguity is an error, silent fallbacks are
   defects.
4. Uncertainty is native: two-component GUM propagation with covariance,
   not an afterthought.
5. Test-driven, coverage at or above 90 percent, minimal API surface,
   NumPy-only core.

## License and citation

MIT License (see `LICENSE`). Citation metadata lives in `CITATION.cff`.
Tagged releases are mirrored on Zenodo: cite the concept DOI
[10.5281/zenodo.21482648](https://doi.org/10.5281/zenodo.21482648) for
the latest version, or the per-release DOI (v0.1.0:
[10.5281/zenodo.21482649](https://doi.org/10.5281/zenodo.21482649)). A
software paper (JOSS or SoftwareX) is planned after the API
stabilizes.

## Author

Geovana Neves, aerospace engineer (aeropropulsive integration and wind
tunnel testing), ITA / TU Delft.
