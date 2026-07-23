# Changelog

All notable changes to the ITACA library are documented here. The format
follows Keep a Changelog; versions follow semantic versioning. The SRS
document baseline has its own changelog in `docs/srs/` Chapter 11.

## [Unreleased]

### Added

* `itc.no_default` (REQ-105): typed no-default sentinel in
  `core/sentinels.py`, an enum singleton whose type is expressible in
  annotations, distinguishing an argument that was not passed from an
  explicit `None`. Adopted by the M1 operation signatures as they
  land.
* Release workflow `.github/workflows/release.yml`: build, a
  tag-to-version consistency check, and PyPI publish through trusted
  publishing (OIDC, no stored token), triggered by `v*` tags (M1
  plan Phase B0).
* `docs/M1_EXECUTION_PLAN.md`: the approved M1 plan (v0.2.0
  computation scope and stretch split, re-baseline of 2026-07-23);
  the accompanying SRS document 0.2.0 changes are recorded in
  `docs/srs/` Chapter 11 and the revision history.
* `docs/SISTER_PYFLIGHTSTREAM.md`: the sister library page for the
  pyflightstream co-development (DD-22, DD-23), linked from the
  README design record.

## [0.1.0] - 2026-07-22

Milestone M0, the foundation release (SRS Chapter 10, DD-21).

### Added

* M0 Phase 6, release hardening: REQ-76 edge-case sweep closed for M0
  (empty VarFrame load, cross-directory hash reproducibility,
  auto-detect feedback, symbolic-vs-mcm on one expression); synthetic
  walkthrough example `examples/wt_campaign.py` with the provenance
  statement in `examples/README.md` (dict-mode load, two-component
  uncertainty, correlated pair, GUM propagation, `.itc` round trip);
  Examples sections on the main VarFrame methods (REQ-79); wheel and
  sdist build verified; README status updated to the implemented M0.

* M0 Phase 5, export and persistence: `to_csv` with provenance header
  comments and `split_by=` (REQ-70 to REQ-72); `to_json` with
  top-level provenance and history keys and optional uncertainty;
  `to_pandas` (lazy, MissingDependencyError when absent, REQ-84);
  `to_numpy` returning read-only views by default (REQ-102); the
  `.itc` native ZIP archive with atomic writes, a versioned schema
  string, and `db.save`/`itc.open` revalidating the state hash on
  read (`HashMismatchError` on drift, REQ-103); the draft-mode export
  guard with `allow_draft=True` embedding a prominent warning
  (REQ-11, OQ-22); `utils.units.convert` with the hand-curated SI and
  aerospace table, every entry unit-tested (REQ-73, DD-13).

### Changed

* SRS document 0.1.1: REQ-98 and REQ-99 promoted to stable at the M0
  Phase 4 checkpoint; OQ-19 to OQ-23 folded into the text.

* M0 Phase 4, uncertainty and compute engine: expression operators
  with analytical partials, each Hypothesis-verified against finite
  differences (REQ-44, REQ-77, DD-20); ast-based parser with precise
  syntax errors, np.* normalization, and the per-variable
  non-differentiable guard (REQ-36); `db.set_uncertainty` with
  absolute and percent values and the two REQ-99 components (REQ-39);
  `db.set_correlation` with merge-and-override semantics (REQ-40);
  GUM clause-5 LPU with covariance, components propagated separately
  (REQ-41, DD-14, DD-19); `db.compute` with `debug=`, `where=`/`fill=`
  semantics, and `+1` origin tags (REQ-33 to REQ-35); `db.combine`
  with exact Jacobians, `cross_correlation=`, strict mode mixing, and
  worst-case tag reduction (REQ-37, REQ-12, OQ-10). Monte Carlo
  (`method="mcm"`) fails loud until v0.3.0 (REQ-42, DD-21).

* M0 Phase 3, structural operations: `db.select` with operator-suffixed
  keys, `Frame=` targeting (values, uncertainty, origin tags), masking
  semantics with fully-masked coordinate slices dropped and the masked
  count recorded in History (REQ-20); `db.at` recorded as a single
  entry (REQ-21); `db.squeeze` including the fully-squeezed datapoint
  holder (REQ-22); `db.fill` with linear, nearest, and moving or
  global polyfit, filled values tagged `+1`, and two-component
  uncertainty propagation through the interpolation weights per
  REQ-98 (systematic through the weight sum, random through the RSS;
  polyfit with uncertainty raises pending the REQ-98 freeze, DD-18).
  All operations honor draft-mode opt-in recording (REQ-10) and
  `comment=` (REQ-19).

* M0 Phase 2, loading and inspection: `itc.load` with folder, single
  file, coordinate dictionary, NumPy, and pandas sources, datapoint
  mode, filename patterns, NaN fill for sparse matrices, and
  provenance plus history at load time (REQ-01 to REQ-07); `db.pivot`
  with auto-detection and loud duplicate rejection (REQ-14);
  `db.inspect` (REQ-13); `db.summary` with RAM footprint (REQ-16,
  REQ-89); `db.diagnostics` returning a `DiagnosticsReport` with
  `log=` support (REQ-17); `db.manifest` in CSV and JSON with the `*`
  swept-here convention backed by per-file coordinates recorded in
  Provenance (REQ-15).

* M0 Phase 1, core data model: frozen `Dimension`, `Variable`, and
  `VarFrame` with construction-time shape and naming validation (SRS
  4.1, DD-03) and read-only arrays throughout (REQ-102); `Provenance`
  with operating modes, `itc.set_user`, `itc.set_mode`, and explicit
  `promote`/`demote` recorded in History (REQ-07 to REQ-12);
  append-only `History` with contiguous-index enforcement and the
  canonical SHA-256 state hash excluding volatile fields (REQ-103,
  SRS 4.4); two-component `UncFrame` with RSS combination (DD-19,
  REQ-99 storage layer); `HistoryFrame` origin tags (SRS 4.3, DD-06);
  `CorrelationMatrix` storage with symmetry and bounds validation
  (REQ-40 storage layer); `Cartesian` and `Polar` tags. Property-based
  tests (Hypothesis) cover the state-hash contract; a house-style
  guard test enforces the no em/en dash rule repository-wide.
* Recording, registry, and logging conventions adopted from
  pyflightstream, documented in `docs/PYFLIGHTSTREAM_ADOPTIONS.md`
  with SRS conflicts resolved in the SRS's favor.

* M0 Phase 0, project infrastructure: package skeleton (`core/`, `io/`,
  `ops/`, `uncertainty/`, `utils/`) importable as `import itaca as itc`
  with `__version__` single-sourced in `core/version.py` (REQ-92); the
  `ITACAError` hierarchy with all six families and the M0 leaf classes,
  every message carrying object, operation, and suggested fix (DD-10,
  REQ-81); the shared message formatter re-exported by
  `utils/validation.py`; tooling per SRS Chapter 7: ruff lint and
  format with the NumPy-only import ban (REQ-80, REQ-82), `mypy
  --strict` (REQ-78), pytest with the 90 percent coverage gate
  (REQ-75), Hypothesis available, pre-commit mirror (REQ-96), GitHub
  Actions CI testing minimum and latest dependency versions (REQ-83,
  REQ-95), and an AST guard test backing the import policy (DD-02).
* M0 execution plan consolidated in `docs/M0_EXECUTION_PLAN.md` from
  SRS Chapter 10, approved by Geovana 2026-07-21.
* Repository established 2026-07-21 with the design baseline: SRS
  document 0.1.0 (first workspace-tracked version), DECISIONS DD-01 to
  DD-22, OPEN_QUESTIONS OQ-01 to OQ-18, MIT license, citation metadata.
