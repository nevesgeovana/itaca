# Changelog

All notable changes to the ITACA library are documented here. The format
follows Keep a Changelog; versions follow semantic versioning. The SRS
document baseline has its own changelog in `docs/srs/` Chapter 11.

## [Unreleased]

### Added

* M1 Phase B3a, reusable pipelines. `db.history.to_pipeline(start=,
  end=)` lifts a contiguous range of History entries into a `Pipeline`
  (REQ-53), `pipeline.apply(db_new)` replays the recorded sequence onto
  another VarFrame (REQ-54), and `pipeline.save(path)` plus
  `itc.load_pipeline(path)` round trip it through a human-readable,
  version-controllable `.itc_pipe` file (REQ-55, SRS Chapter 4, schema
  `itaca-itc_pipe/1`, atomic write). The file carries the creating
  version, the source history index range, each call with its keyword
  arguments and its comment (REQ-19), and a content hash reverified on
  load, so a recipe edited after it was written raises
  `HashMismatchError` instead of replaying something unintended.
  Replay re-dispatches structured steps rather than re-parsing the
  History display strings, which are not round-trippable: each
  replayable operation records a `PipelineStep` (`call`, `kwargs`,
  `comment`) as it derives, so a pipeline reconstructs the exact calls
  and, when replayed onto the frame the range was lifted from,
  reproduces the state hash including uncertainty and correlation
  (DD-28). Replaying onto a different frame reproduces the processing,
  not the hash, which is the whole point of a reusable recipe. The
  encoding is JSON rather than the TOML the SRS first named; DD-28
  records why, and the SRS section was amended with it. `Pipeline`
  supports `len()` and iteration over its `PipelineStep` objects and
  exposes `content_hash`. A pipeline with no steps is refused at
  construction and on load rather than treated as the identity:
  `to_pipeline` already refused to produce one, because applying it
  would return the target unchanged and unrecorded. The `.itc_pipe`
  file is readable for review and diffing, not for hand editing; the
  content hash rejects any post-write change, so a step is altered by
  re-running the operation and lifting a new pipeline.
* Replayable operations are an explicit allowlist (`REPLAYABLE_CALLS`),
  validated when a `.itc_pipe` is read so a hand-edited recipe cannot
  name an arbitrary method. Alongside the transforms it covers `at`,
  `set_uncertainty`, `set_correlation`, `register_axis`, and
  `declare_vector`, so uncertainty setup and the whole axes journey
  replay instead of being dropped. Only frame construction (`load`,
  `pivot`) is skipped, and only when it leads the range; any other
  step-less operation raises `PipelineCompatibilityError`, as does a
  range that yields no step at all (a draft-mode frame recorded without
  `history=True`) rather than returning a silent no-op.
* `HistoryEntry` gains `step` (the recorded `PipelineStep`, or `None`;
  excluded from the state hash) with `replayable` and `name`
  properties, and `History.append` a matching `step=` keyword.
  `itc.Pipeline`, `itc.VarFrame`, and `itc.load_pipeline`
  join the top-level exports, and `PipelineStep`, `REPLAYABLE_CALLS`,
  and `PIPELINE_SCHEMA` are importable from `itaca.core.pipeline`.
* M1 Phase B2, axes. The `Axis` type (exported as `itc.Axis`; constant
  orthogonal matrix or parametric `angles_from` with the AIAA R-004A
  Etkin wind/stability conventions, SME-accepted), the immutable
  `AxisRegistry`, `db.register_axis` and `db.declare_vector(...,
  axis=...)` binding each vector group to its source axis system
  (REQ-107 draft; the surface standardizes on "axis" for a coordinate
  system, distinct from `select(Frame=)`), and
  `db.rotate(target_axis, vector_groups=...)` (REQ-38, REQ-101):
  each group transforms from its own source frame to the target,
  composing through the canonical body axis, with condition-dependent
  frames evaluated per grid point (angle read in the source Dimension
  or Variable unit). Uncertainty is the exact Jacobian applied to the
  within-cell component covariance (declared correlation, OQ-23), and
  angle uncertainty enters by the chain-rule `dR/dangle` term; origin
  tags are preserved. The axis registry joins the state hash and the
  `.itc` format. `scipy` is a dev-only direction-cosine oracle
  (DD-26). New error leaves `AxisNotFoundError`, `VectorGroupError`,
  `RotationMatrixError`, `AccessorRegistrationError`.
* `db.translate_moments(to_point, from_point=..., axis=..., force=...,
  moment=...)` (REQ-100): the rigid moment transfer `M' = M + r x F` on
  the declared moment group, with the exact `[skew(r) | I]` Jacobian
  and force-moment covariance when declared; `force`/`moment` select
  declared groups by name.
* `itc.register_accessor(name)` (REQ-106): the sanctioned extension
  point. A class decorator registering a `db.<name>` accessor
  namespace, instantiated with the frame and cached per instance;
  name collisions raise at registration, and an `AttributeError` from
  the accessor's `__init__` is re-raised as `RuntimeError` so real
  defects are never swallowed. The first foreseen consumer is the
  pyflightstream exporter (DD-23).

* M1 Phase B1, structural and numeric operations. `db.expand`
  (REQ-23, broadcast a new dimension), `itc.concat` (REQ-24,
  concatenate along a shared dimension), `db.interpolate` (REQ-25,
  linear/cubic/nearest/polyfit densify plus `axisTranslation` and the
  `override` flag), `db.average` (REQ-27), `db.integrate` (REQ-28,
  Cartesian and polar, `skipna`), `db.smooth` (REQ-29, savgol,
  spline, moving_avg), `db.diff` and `db.d[dim]` (REQ-30,
  moving-polynomial derivative with `nan_edges`), `db.fitmodel` and
  `db.fitvalue` (REQ-31/32, polynomial coefficients with
  in-range/out-of-range tags). Every operation is immutable, records
  History, and declares its UncFrame effect (DD-18): reductions and
  interpolation propagate both components through their weights
  (REQ-98), while `smooth`, `diff`, `fitmodel`, and `fitvalue` raise
  on uncertainty until OQ-18 and OQ-24 freeze their kernel-weight and
  coefficient-space rules. New error leaves `ConcatOverlapError`,
  `AxisTranslationError`, and the shared `FitDegreeError` (the
  too-few-points-for-degree invariant across diff, smooth,
  interpolate, and fitmodel). The REQ-105 sentinel is adopted in the
  `smooth` signature with the shared `reject_no_default` helper.

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

### Changed

* `db.fill`: the `method` argument is moving to keyword-only for
  consistency with the M1 kernel operations. Passing it positionally
  is deprecated and emits a `FutureWarning` from v0.2.0 (REQ-26).
* REQ-101 (condition-dependent axes) promoted from draft to stable at
  the M1 Phase B2 checkpoint, once condition-dependent frames were
  implemented and tested.
* `.itc` archives are now written at schema `itaca-itc/2`, which adds
  the per-entry replay step to `history.json` and a `steps_hash` digest
  to `metadata.json`, so a reopened archive can still lift its recipe
  and an edited recipe is detected. The state hash of REQ-103 keeps its
  scope: it covers the recovered data, while `steps_hash` covers the
  steps, and without the second digest an edited step passes the first
  check and then steers the next replay. This build reads schema 1 and
  2; v0.1.0 cannot open an archive written by v0.2.0, which is a
  forward-compatibility break for files already written.

### Deprecated

* `db.fill(along, method)` with `method` passed positionally; pass
  `method=` as a keyword instead.

### Fixed

* Python 3.10 typing conformance: `mypy --strict` failed on the 3.10
  legs of the CI matrix only, because the NumPy stubs resolve
  differently per interpreter, and the failures were invisible in a
  3.12 development environment. The reduction kernels now pin their
  return type through `np.asarray`, the comparison table in the
  expression parser carries an explicit `Callable` annotation instead
  of a joined `object` value type, and the `savez_compressed` call
  casts the callable rather than carrying an inline ignore that is
  unused on some interpreters and required on others. Internal typing
  only; no packaged surface changes.
* ruff is pinned to one exact version in the `[dev]` extra and the
  ruff-pre-commit `rev` is locked to the same version, so the ruff half
  of the pre-commit mirror now runs the identical linter and formatter
  as the CI lint job (REQ-80, REQ-96). The previous range spec let CI
  install a much newer ruff than the pinned hook ran, so commits passed
  locally and failed in CI. The hook id moved from the deprecated alias
  `ruff` to `ruff-check` at the same time.
  `tests/test_tooling_config.py` guards the match, that the CI job still
  runs both ruff commands, that both hooks stay declared without
  narrowing keys, that the installed ruff agrees with them, and that the
  Markdown exclusion stays in place. mypy and pytest still resolve from
  ranges and run from the local environment, so those two can still
  drift. Preventively: Markdown formatting is preview-only at the pinned
  ruff, so `[tool.ruff] extend-exclude = ["*.md"]` changes nothing
  today; it keeps the formatter's scope stable if that graduates, since
  `.md` files here are prose and illustrative samples. Internal tooling
  only; no packaged surface changes.

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
