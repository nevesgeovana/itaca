# ITACA

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
uncertainty propagation including covariance, origin tags for every value,
and publication-quality plotting.

## Status

Pre-release. The milestone M0 foundation (release v0.1.0) is
implemented and test-covered: loading in all modes, inspection and
diagnostics, structural operations, two-component GUM uncertainty
propagation with covariance, string-equation derivation, explicit
combination, exports, and the `.itc` native format with state-hash
revalidation. The SRS (document 0.1.1) is versioned in `docs/srs/`.
Releases follow the incremental roadmap in the SRS Chapter 10: each
milestone ships on PyPI with a Zenodo DOI. See `examples/` for a
complete synthetic walkthrough.

## Design record

* `docs/srs/`: the SRS LaTeX sources, the authoritative reference for
  what ITACA must do and how it is built. First workspace-tracked
  version: document 0.1.0, 2026-07-21.
* `docs/DECISIONS.md`: architectural decisions DD-01 to DD-22 with
  long-form rationale.
* `docs/OPEN_QUESTIONS.md`: design questions OQ-01 to OQ-18 with
  resolutions.

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

MIT License (see `LICENSE`). Citation metadata lives in `CITATION.cff`;
tagged releases will be mirrored on Zenodo with a DOI. A software paper
(JOSS or SoftwareX) is planned after the API stabilizes.

## Author

Geovana Neves, aerospace engineer (aeropropulsive integration and wind
tunnel testing), ITA / TU Delft.
