# M0 Execution Plan (release v0.1.0)

Status: proposed 2026-07-21, pending Geovana's approval.
Authority: SRS 0.1.0 (`docs/srs/`, Chapter 10 scope, Chapters 6 and 7
requirements), DD-01 to DD-22, OQ-01 to OQ-18. Where this plan and the
SRS disagree, the SRS wins and the discrepancy is reported, not patched.

## 1. Objective

Ship M0 as public release v0.1.0 on PyPI with a Zenodo DOI: a working,
tested core that can load, inspect, compute, propagate two-component
uncertainty with covariance, and export. No processors, no plots, no
axis machinery (moved to v0.2.0); no Monte Carlo, no PROV export
(moved to v0.3.0). See DD-21.

## 2. Scope

In scope (SRS Table "M0 deliverables"):

| Area | Requirements | Modules |
|---|---|---|
| Loading, all modes, datapoint mode, provenance at load | REQ-01 to REQ-07 | `io/loader.py` |
| Inspect, pivot | REQ-13, REQ-14 | `io/inspector.py`, `io/pivot.py` |
| Manifest, diagnostics, summary | REQ-15, REQ-16, REQ-17 | `io/manifest.py`, `io/diagnostics.py`, `io/summary.py` |
| Operating modes, draft save guard, strict mixing | REQ-08 to REQ-12 | `core/provenance.py` |
| select, at, squeeze | REQ-20, REQ-21, REQ-22 | `ops/` |
| fill | REQ-26 | `ops/fill.py` |
| combine | REQ-37 | `core/combine.py`, `core/arithmetic.py` |
| Uncertainty: set_uncertainty, set_correlation, UncFrame, ast expression engine, GUM LPU with covariance | REQ-39, REQ-40, REQ-41, REQ-43, REQ-44 | `uncertainty/` |
| Two-component uncertainty and per-operation semantics | REQ-98, REQ-99 (draft, gated) | `uncertainty/`, `ops/` |
| compute with debug, where/fill, NumPy guard | REQ-33 to REQ-36 | `ops/compute.py` |
| Exports, .itc format, itc.open, split_by | REQ-70, REQ-71, REQ-72 | `io/export.py`, `io/formats/` |
| Unit conversion table | REQ-73 | `utils/units.py` |
| Immutability and hash invariants | REQ-18, REQ-19, REQ-102, REQ-103 | `core/` |
| set_user, set_mode, version tagging, test suite, CI, pre-commit | n/a | `core/` |

Out of scope for M0 (do not absorb silently): expand, concat,
interpolate, average, integrate, smooth, diff, fitmodel, fitvalue,
Axis and rotate, translate_moments, pipelines, processors and .itceq
execution, statistics, compare, report, all plotting, surrogates,
Monte Carlo (REQ-42), PROV export, itc.aerospace. REQ-70's
`export_provenance` ships in v0.3.0 with the PROV formats.

## 3. Gate on draft requirements

REQ-98 and REQ-99 are tagged draft. Their M0 implementations proceed
behind tests but are not frozen: before v0.1.0 is tagged, Geovana
validates the normative table of REQ-98 (restricted to the M0
operations: select, at, squeeze, pivot subset rules; fill through fit
weights; combine and compute via exact Jacobian) and the REQ-99
component semantics. OQ-18 (smooth and diff kernels) does not block
M0 because both operations are v0.2.0 scope. REQ-101 is v0.2.0 scope
and is untouched here.

## 4. Phases

Each phase follows TDD: usage example first, failing tests, minimal
implementation, refactor. A phase is done when its tests pass, coverage
of its modules is at or above 90 percent, `ruff check`, `ruff format
--check`, and `mypy --strict` (public API) are green, and the CHANGELOG
is updated for any public API addition.

### Phase 0: Project infrastructure

* `pyproject.toml`: package metadata, `numpy>=1.26,<3.0`,
  `python>=3.10,<3.14`, optional extras (`pandas`), dev group per SRS
  Table "Dependency version policy".
* Package skeleton `itaca/` with `core/`, `io/`, `ops/`,
  `uncertainty/`, `utils/`; `import itaca as itc` works and exposes
  `__version__`.
* `core/errors.py`: full ITACAError hierarchy from SRS Table "The
  ITACAError hierarchy" (families now, M0-relevant leaves now; leaves
  belonging to later milestones are added with their features).
  Three-part message convention (object, operation, suggested fix)
  enforced by a shared formatter in `utils/validation.py`.
* Tooling: ruff (lint plus format, import-policy rule banning xarray,
  dask, pandas in `core/`, `ops/`, `uncertainty/`), mypy strict config,
  pytest plus pytest-cov (90 percent hard gate), Hypothesis,
  `.pre-commit-config.yaml` mirroring CI (REQ-96), GitHub Actions
  workflow (REQ-95) testing minimum and latest dependency versions.
* Guard test asserting the import policy (complements the ruff rule).

### Phase 1: Core data model

* `core/dimension.py`, `core/variable.py`: frozen dataclasses per SRS
  Sections 4.1.3 and 4.1.4.
* `core/varframe.py`: frozen VarFrame with `dims`, `vars`,
  `uncertainty`, `tags`, `provenance`, `history`, `coords`,
  `correlation` (AxisRegistry deferred to v0.2.0; the attribute slot
  exists so the .itc format is stable, but no Axis machinery ships).
* Array-level immutability (REQ-102): `writeable=False` at
  construction everywhere, read-only views from `to_numpy` by default.
* `core/uncframe.py`, `core/historyframe.py`: structural mirrors
  (DD-05, DD-06), lazy materialization (REQ-91). UncFrame holds the
  systematic and random components (DD-19).
* `core/provenance.py`: Provenance record, operating modes REQ-08 to
  REQ-12, `promote`/`demote`, `itc.set_user`, `itc.set_mode`.
* `core/history.py`: append-only indexed History, `comment=` plumbing
  (REQ-19), state hash with the exact scope of REQ-103 and its
  reproducibility test.
* `core/coords.py`: Cartesian and Polar tags (storage only in M0).

### Phase 2: Loading and inspection

* `io/loader.py`: all five source forms of REQ-01, folder `pattern=`
  (REQ-02), dict mode with `LoadCoordinateError` (REQ-03), NumPy mode
  (REQ-04), lazy pandas mode (REQ-05), NaN fill for sparse matrices
  (REQ-06), provenance and history at load time (REQ-07, load is
  History index 1).
* `io/inspector.py` (REQ-13), `io/pivot.py` (REQ-14 including
  `PivotDuplicateError`), `io/manifest.py` (REQ-15 with the `*`
  swept-here convention), `io/summary.py` (REQ-16 including RAM
  footprint, REQ-89), `io/diagnostics.py` (REQ-17 with
  DiagnosticsReport and `log=`).

### Phase 3: Structural operations

* `ops/select.py` (REQ-20: operator-suffixed keys, `Frame=` targeting,
  masking semantics for variable-keyed filters), `db.at` (REQ-21),
  `ops/squeeze.py` (REQ-22).
* `ops/fill.py` (REQ-26: linear, nearest, windowed and global polyfit,
  `+1` tags).
* Every operation: new object, History entry, declared UncFrame and
  HistoryFrame effect (subset rules of REQ-98 for these operations),
  `comment=` support.

### Phase 4: Uncertainty and compute engine

* `uncertainty/operators.py`: operator objects with `evaluate`,
  `d_da`, `d_db` (REQ-44 coverage list), each independently tested
  plus Hypothesis property tests for the derivative identities
  (REQ-77).
* `uncertainty/expression.py`: ast-based parser to the operator tree
  (DD-20), precise syntax errors, undefined-variable detection.
* `db.set_uncertainty` (REQ-39, absolute and percent forms;
  `component=` per REQ-99), `db.set_correlation` (REQ-40 with
  validation), `core/correlation.py`.
* `uncertainty/propagation.py`: full GUM clause 5 LPU with covariance
  (REQ-41, DD-14), two components propagated separately and recombined
  as RSS at reporting (REQ-99). Hypothesis tests: variance additivity
  under independence, known correlated cases, dimensional consistency.
* `ops/compute.py`: REQ-33 (symbolic default), REQ-34 (debug report),
  REQ-35 (`where`/`fill` semantics), REQ-36 (NumPy guard,
  per-variable). `method="mcm"` raises a clear not-yet-available error
  pointing to v0.3.0.
* `core/arithmetic.py` and `core/combine.py`: REQ-37 with
  `cross_correlation=`, strict mode mixing (REQ-12), no operator
  overloading (DD-12).
* Checkpoint with Geovana: validate REQ-98 (M0 rows) and REQ-99
  before freezing this phase.

### Phase 5: Export, units, native format

* `utils/units.py` (REQ-73): hand-curated table, SI plus deg, rpm,
  knot, ft, lb, slug; every entry unit-tested (DD-13).
* `io/export.py` and `io/formats/`: `to_csv` (header provenance
  comments, `split_by=`, REQ-71, REQ-72), `to_json` (provenance and
  history keys), `to_pandas` (lazy), `to_numpy(return_dims=True)`
  read-only by default.
* `io/formats/itc.py`: `.itc` ZIP archive exactly per SRS Table
  "Layout of a .itc archive"; `db.save` with the draft-mode guard
  (REQ-11), `itc.open` with `HashMismatchError` on source-hash drift;
  round-trip tests including comments, uncertainty components,
  correlation, tags.

### Phase 6: Release hardening and gates

* Sweep the REQ-76 edge-case table rows applicable to M0 (Load, Pivot,
  Diagnostics, Compute, Immutability, Reproducibility, History
  round-trip, Modes, Uncertainty) and close gaps.
* Docstring and typing audit: NumPy format with Examples everywhere
  public (REQ-79), `mypy --strict` clean (REQ-78).
* Example dataset: synthetic, provenance stated (provenance scrub
  gate); `itc.load` dict mode in the production example.
* Release gates before tagging: green CI; coverage at or above 90
  percent; LICENSE and CITATION.cff present (already in repo);
  example-data provenance scrub; PyPI name `itaca` registered
  (verified free 2026-07-21); Zenodo webhook enabled; CHANGELOG for
  0.1.0; draft-requirement gate of Section 3 cleared.

## 5. Sequencing rationale

Phases are ordered by the dependency layering of SRS Chapter 5: `core`
has no intra-project dependencies, `ops` and `io` build on `core`,
`compute` needs the expression engine, `combine` needs the covariance
arithmetic, exports serialize everything and therefore come last
before hardening. select/at/squeeze/fill precede the uncertainty
engine because their UncFrame effects are pure subsetting or weight
propagation and they exercise the mirror-frame plumbing early.

## 6. Standing rules restated

TDD without exception; 90 percent coverage as hard CI gate; NumPy-only
in `core/`, `ops/`, `uncertainty/`; every operation immutable,
history-recording, and UncFrame-declaring; Conventional Commits citing
REQ, DD, and OQ ids; English (American, with Z) in all artifacts; no
em or en dashes anywhere; synthetic or publicly licensed example data
only.
