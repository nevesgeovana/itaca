# Changelog

All notable changes to the ITACA library are documented here. The format
follows Keep a Changelog; versions follow semantic versioning. The SRS
document baseline has its own changelog in `docs/srs/` Chapter 11.

## [Unreleased]

### Added

* M1 Phase B3b, processors and the `.itceq` equation file (REQ-45 to
  REQ-48, DD-16, DD-17). `itc.processor(name_or_path, config=None, *, auto_sort=False)` builds a
  processor from a registered name or from a
  path to an `.itceq` file, whose `[constants]` defaults the `config`
  mapping overrides (REQ-46). A processor satisfies the `Processor`
  typing protocol (`name`, `version`, `info()`, `validate(db)`, and the
  call itself, REQ-45); `itaca.pproc` also exports `EquationProcessor`,
  `parse_itceq`, `ItceqSpec`, `Equation` (one `target = expression`
  line), `register_processor`, and `registered_processors`. The parser reads the five sections of SRS
  Section 4.6 with the standard-library `tomllib` (REQ-83, DD-32),
  enforces every section rule, and refuses a cyclic dependency at parse
  time before any computation, in both ordering modes (REQ-48, OQ-04).
  Equations run in file order by default; `auto_sort=True` resolves the
  dependency order and reports it. The resolved order is the stable
  topological order, at each step the equation earliest in file order
  whose dependencies are met: deterministic and independent of parser
  internals, which is what DD-17 asks for, and explicitly not an
  edit-distance-minimal reordering. `[corrections]` run after
  `[equations]` and may replace an existing variable, whether
  `[equations]` produced it or the VarFrame supplies it, so
  `CL = "CL * blockage"` is a replacement there and a cycle inside
  `[equations]`; a variable a correction replaces but the file does not
  produce is a required input. A forward reference in file order is
  refused when the file is read.
* Reapplication is recognized from the data *and* the History: a
  processor refuses a second run only when the frame carries every
  variable it produces and the History records this processor. Matching
  names alone warn and then apply, so a CSV that arrives carrying `CL`
  and `q_inf` beside the raw forces is processed rather than refused on
  its first application. Detection by names alone taught the caller to
  write `force=True` by reflex, which is the habit DD-16 exists to
  prevent (REQ-47 amended, DD-35). "Records this processor" is an exact
  match on the shapes the processor itself writes, the signature alone
  or `"<signature>: <user comment>"`, and never a substring search: a
  user comment quoting the signature, which REQ-19 invites, must not
  sign a frame the processor never touched, and one version must not
  read another version's History as its own. The evidence survives a
  save and reopen, since History is persisted in the `.itc` archive;
  where History does not travel with the data, a frame rebuilt from a
  CSV or JSON export, only the warning remains.
* Idempotence is declarable in the file: `[meta] idempotent = true`
  (REQ-47 amended, DD-36). It is the one typed field in a strings-only
  section, and a quoted `"True"` is refused rather than accepted and
  silently ignored, which is what the old rule did. Without it, the only
  way to declare idempotence for a file-defined processor was to
  subclass `EquationProcessor` and bypass `itc.processor`.
* A name declared in `[constants]` may no longer also be an equation or
  correction target (DD-37). A constant is substituted into every read,
  so such an equation ran with its result unreachable: measured,
  `k = 2.0` with `k = "rho * 100.0"` made `x = "k + 1"` evaluate to
  `3.0` and History record `x = 2.0 + 1`. Replacement inside the
  equation sections is unaffected and stays legal.
* Applying a processor assigns the declared `[uncertainties]` as the
  systematic component (SRS Chapter 8, REQ-99) and evaluates each
  equation through the ordinary `db.compute` path, so uncertainty
  propagates automatically (REQ-41), every step is recorded, and a
  whole application lifts into a `Pipeline` (REQ-53). Declared
  constants are substituted into the expressions before they run, so
  History records the numbers the workflow actually used. Every entry
  the application writes carries the processor name and version in its
  comment alongside the user's own (REQ-19).
* Reapplying a processor is refused rather than silently repeated
  (REQ-47, DD-16): `ProcessorIdempotenceWarning` is raised when the
  frame already carries every variable the workflow produces, and
  `force=True` permits the re-run while still warning and recording a
  distinct History entry. A processor that declares `idempotent = True`,
  in Python or in the file, re-runs without being refused and still
  warns. How a reapplication is recognized is the bullet above.
* The exception hierarchy gains the `ProcessorError` leaves the SRS
  specified at the 0.1.0 baseline: `ProcessorNotFoundError` (with the
  registered alternatives in the message), `ProcessorValidationError`,
  `ItceqParseError`, `ItceqCycleError`, and
  `ProcessorIdempotenceWarning`, which is both an `ITACAError` and a
  `Warning` because REQ-47 gives it both roles.
  `examples/processor_itceq.py` is the walkthrough. `report=` is accepted by the
  call signature and raises until REQ-51 ships in v0.3.0, rather than
  being silently ignored.
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

* **The minimum supported Python is now 3.11** (was 3.10). This is a
  breaking change for anyone on 3.10: `pip install itaca` there will
  resolve to v0.1.0 rather than upgrading. The reason is `.itceq`,
  which the SRS specifies as a TOML-structured file (REQ-48) and which
  M1 Phase B3b implements: only from 3.11 does the standard library
  ship a TOML reader, so the parser uses `tomllib` and the format needs
  no dependency, no vendored reader, and no parser of ours. This
  resolves OQ-28 by taking none of the three options it put forward,
  and it amends REQ-83, a stable requirement, through the SRS process;
  DD-32 records why, including why the JSON `.itc_pipe` encoding of
  DD-28 is unaffected (`tomllib` reads and does not write). The CI test
  matrix, the PyPI classifiers, and the `ruff` target version moved
  with the floor, and `tests/test_python_floor.py` now pins all of them
  to the single `requires-python` declaration, and pins the floor
  against the standard-library modules the library imports.
* `db.fill`: the `method` argument is moving to keyword-only for
  consistency with the M1 kernel operations. Passing it positionally
  is deprecated and emits a `FutureWarning` from v0.2.0 (REQ-26).
* `db.save` refuses an archive whose recorded replay argument has no
  JSON representation, for example `compute(fill=float("inf"))`, which
  REQ-35 admits as a value. The refusal is a `DataError` naming the
  step and the argument; a NaN fill is not recorded as a replay
  argument, so it is unaffected. A `.itc` archive must stay readable by
  any JSON tool
  (REQ-70), and `Pipeline.save` has refused the same values since B3a.
* REQ-101 (condition-dependent axes) promoted from draft to stable at
  the M1 Phase B2 checkpoint, once condition-dependent frames were
  implemented and tested.
* `.itc` archives are now written at schema `itaca-itc/2`, which adds
  the per-entry replay step to `history.json` and a `steps_hash` digest
  to `metadata.json`, so a reopened archive can still lift its recipe
  and an edited recipe is detected. REQ-103 keeps its scope; the
  boundary between the two digests is specified in the archive section
  of SRS Chapter 4 and recorded in DD-30. The digest requirement
  follows what an archive carries, not what its schema string declares,
  so downgrading that string does not skip the check. This build reads
  schema 1 and 2, so archives written by v0.1.0 still open; a v0.1.0
  install cannot open an archive written by v0.2.0.

### Deprecated

* `db.fill(along, method)` with `method` passed positionally; pass
  `method=` as a keyword instead.

### Fixed

* **Precise public return types, and keyword-only options with a
  deprecation window** (`ITACA-032`, REQ-78, REQ-85). Eight public
  `VarFrame` methods were annotated `-> object`, so a caller under
  `mypy --strict` got nothing back they could use; they now declare
  what they return. `expand`'s `axis` and `interpolate`'s `method`,
  `deg` and `override` become keyword-only behind the window `fill`
  established: a positional call still works, emits a `FutureWarning`
  naming the parameter, and the shim is removed in v0.3.0. Breaking it
  outright would have been worse than the finding, since `axis` is an
  int and a positional call would have landed it in a different
  parameter silently.

  This finding was CLAIMED CLOSED in the lane's plan entry while it was
  untouched, and the role review caught it. The claim is corrected
  where it was made: a false closure is worse than an open finding,
  because it makes the finding invisible to the next reviewer.

* **`db.set_metadata({name: {field: value}})`** (new public method).
  `rotate` refuses a condition-dependent rotation with "set the
  Dimension or Variable unit", and there was no way to do it: no
  `set_unit`, no `units=` on `itc.load` or `db.pivot`, and neither
  `Dimension` nor `Variable` exported. The only route was
  `dataclasses.replace` on a frozen object through a private module
  path, which this library's own `rotate` docstring taught, and which
  bypasses `_derive`: no History entry, no re-derived state hash. Since
  DD-40 the unit is part of the hash and REQ-101 makes it decide
  physics, so it was the one field that most needed a traceable setter
  and had none. The `rotate` docstring now teaches this instead.

* **`db.drop_correlation(names=None)`** (new public method).
  `set_correlation` merges and can therefore only add or overwrite a
  pair, so a declaration could not be withdrawn at all. Three `rotate`
  refusals prescribed "drop the declaration before rotating" as their
  fix, naming an action with no implementation. This lane had added the
  capability internally and left it unreachable from a frame. It
  records itself in History and is replayable like any other operation.

* **A pre-1.0 carve-out in REQ-92** (SemVer clause 4). The requirement
  said flatly that a breaking change increments MAJOR, with no clause
  for major version zero, so this release with its three documented
  breaks was non-conforming against its own specification. The
  requirement was what was wrong, not the release. Every breaking
  change is still marked BREAKING here with its migration, which is the
  obligation that replaces the version bump while the major version is
  zero.

* **REQ-105 and REQ-106 surfaces are marked PROVISIONAL**
  (`itc.no_default`, `itc.register_accessor`). Both ship in 0.2.0
  because the M1 operations needed them, while their requirements are
  still `draft` and unvalidated by the author. Publishing a release is
  normally what freezes a public API; these are published with their
  provisional status stated in the module instead, so the freeze is a
  decision rather than an accident. Promotion to stable needs the
  author's recorded validation.

* **The README has an installation section and a runnable quickstart**
  (`ITACA-018`). It had neither, and no `pip install` line anywhere. The
  quickstart is executed by hand against the library and prints the
  values shown.

* **Public documentation no longer advertises unreleased capability**
  (`ITACA-018`). The README and `CITATION.cff` presented
  publication-quality plotting in the present tense while `itaca/plot`
  does not exist, and the citation record for v0.1.0 also advertised
  reusable processors, which are M1. The README stops hard-coding the
  SRS document version, which had drifted to naming 0.1.1 while the
  document was 0.2.0. The SRS itself said "RPN expression tree" in 15
  places across 7 chapters against the canonical stdlib `ast`; the
  acronym entry went with them.

* **A normative document no longer claims an absent capability**
  (`ITACA-012`). `08_standards_alignment.tex` stated that v0.1.0
  supports PROV-N and PROV-JSON via `db.export_provenance`. No such
  symbol exists, the M0 plan says v0.3.0 and the roadmap places it in
  M2, so a normative document made a false claim about a PUBLISHED
  release. It is now marked as the M2 deliverable it is, and
  `tests/test_requirement_trace.py` pins that the claim and the symbol
  cannot drift apart again in either direction.

* **REQ-79 is enforced where it is claimed** (`ITACA-016`). The same
  chapter said linting enforced the NumPy docstring sections. It does
  not: ruff checks presence and style, never section completeness.
  Measured with a loose reading of public, 162 of 223 surfaces had no
  Examples and 137 had no Parameters, and the suite was green. A
  section checker now runs over the DECLARED public surface, the
  normative text says exactly that, and the six real gaps it found on
  that surface are filled.

* **A REQ to code to test trace runs in CI** (`ITACA-007`, partial). No
  matrix existed. The trace is discovered rather than enumerated, a
  requirement the library cites must be cited by a test, and the run
  NAMES the requirements nothing reaches instead of being silent about
  them. Separating `spec_status` from `implementation_status` in the
  reqbox macro is registered, not done here.

* **The documented install command actually collects the suite**
  (`ITACA-015`). The contributing guide documents `pip install -e
  ".[dev]"` and says the extra installs everything the tests need; a
  test imports pandas at module scope, so the documented command failed
  at collection while CI hid it by installing `.[dev,pandas]`. pandas
  joins the dev extra and both workflow callers now use the documented
  command. The two pre-commit gates gain `always_run`, because
  `types: [python]` made pre-commit skip them on a documentation-only or
  configuration-only commit, which is the commit most likely to change
  what the gates check.

* **The decision log states when an entry becomes frozen**
  (`ITACA-017`). The append-only rule read as absolute while DD-30
  records an in-place edit of DD-28 after publication. Frozen now means
  frozen from publication, with supersession as the only instrument
  after it.

* **The state hash covers every field that decides behavior**
  (`ITACA-003`, DD-40, REQ-103 rewritten, REQ-107 stabilized). A frame
  whose angle dimension was labeled `deg` and one labeled `rad`, with
  identical arrays, produced the SAME `state_hash` while `rotate` read
  the unit and computed `FZ = -1.0` against `-0.894`. Two states with
  the same identity produced different physics.

  REQ-103 now states a guarantee rather than a field list: two VarFrames
  in the same semantic state have the same hash. The hash covers
  dimension and variable metadata (unit, description, long name) and the
  axis registry, which the code already hashed while the requirement
  omitted it. Same semantic state is defined representationally, with
  memory layout and byte order normalized because neither is observable,
  and with signed zeros, one-ULP differences, dtypes and NaN payloads
  deliberately left distinct. Hash equality implies semantic identity;
  hash inequality proves nothing about semantic difference.

  **Breaking for existing `.itc` archives.** An archive written before
  0.2.0 whose dims or variables carry a unit, description or long name
  now fails `itc.open` with `HashMismatchError`, because the recorded
  digest predates the scope. The archive is intact; the remedy is to
  re-export from the source data, or to open it with 0.1.x and re-export.
  The error message says so and cites DD-40. An archive with no metadata
  at all is unaffected, because an absent field contributes no token:
  verified against the shipped example, whose digest does not move.

* **A `.itceq` constant may not shadow a measured channel** (`ITACA-002`,
  DD-39, OQ-31 resolved). A `[constants]` entry is substituted into
  every read before an expression evaluates, so a file declaring
  `rho = 1.225` applied to a campaign flown at `rho = 0.9` computed
  `q_inf` 36 percent high, with no error, no warning, and no record of
  the substitution: History showed
  `compute('q_inf = 0.5 * 1.225 * V ** 2', ...)`, so not even the
  provenance revealed that a measurement had been discarded.
  `validate` now refuses the collision, naming the colliding names and
  the declared value, and the call runs `validate` first so both entry
  points are closed.

  This is symmetric with DD-37, which already refused the HARMLESS
  sibling, a constant colliding with an equation target, where the
  equation's result is merely unreachable. The fix had landed on the
  safe instance and left the dangerous one.

  **Breaking, and deliberately so.** Anyone using a constant to
  override a bad channel loses that path. The replacement is to correct
  the channel in the frame, which is what `[corrections]` and
  `db.compute` are for; a value that is measured belongs in the
  VarFrame, and a value that is declared belongs in `[constants]`. The
  refusal is scoped to `db.vars`, so a constant sharing a DIMENSION's
  name is unaffected: expressions read variables only.

* **NumPy keyword arguments are refused instead of silently dropped**
  (`ITACA-023`, REQ-44, OQ-37). `np.round(x, decimals=2)` on
  `[1.234, 2.345]` returned `[1., 2.]` rather than `[1.23, 2.35]`: the
  parser read only `node.args`, and `node.keywords` was neither
  represented nor refused. History recorded the expression WITH the
  keyword, so the provenance showed an intent the execution did not
  honor. Any keyword now raises `DataError` naming the function and the
  keyword. `np.clip(x, a_min=..., a_max=...)`, which escaped as a bare
  `TypeError`, is covered by the same check, and `np.pi(x)` now raises
  `DataError` rather than a bare `TypeError`, because the admission gate
  tests `callable` where it used to test `hasattr`.

* **A dead expression branch no longer poisons a derivative**
  (`ITACA-022`). `u(x**2)` was `NaN` for a negative base and for zero,
  because `d(a**b)/db = a**b * log(a)` is `NaN` or `-inf` there and was
  multiplied by the exactly zero derivative of the exponent; `0 * NaN`
  is `NaN`, not `0`. Both derivative walks now skip a branch that does
  not reference the differentiation variable. The predicate is
  variable-set membership rather than is-a-constant, because an exponent
  stored as a VARIABLE poisoned the sum identically.

  Two consequences. When the exponent IS live and the base is
  non-positive anywhere, that is a genuine domain violation and now
  raises `UncertaintyCompatibilityError` naming how many grid points
  offend, rather than writing `NaN` into a plausible-looking result. And
  REQ-36's guard becomes per-subtree rather than per-expression, so
  `y = x + np.sum(z)` with uncertainty on `x` alone now succeeds where
  it used to raise. That widening is exact rather than an approximation:
  the branch cannot affect the result by any amount.

* **Repeated names are refused at every ingestion boundary**
  (`ITACA-026`, new `DuplicateNameError`). `itc.load(array,
  names=["a","b","a"])` was accepted and produced two variables, the
  third column having overwritten the first, so data was lost at step
  one of the chain and Provenance then documented a dataset that no
  longer matched the input. Five boundaries now share one rule: the
  `names=` list, DataFrame columns, a CSV header, a `dims=` list, and a
  dict-mode coordinate that would shadow the file's own column. The CSV
  and `dims=` cases did not lose data but reported a shape mismatch that
  named neither the file nor the repeated name.

* **A negative polynomial degree is refused** (`ITACA-033`).
  `interpolate({"x": [...]}, "polyfit", -1)` returned zeros over data
  that was a straight line, because the validation checked `deg >= n`
  and never `deg >= 0`. Every public degree parameter now shares one
  check: `interpolate`, `fill` (both the moving-window path and the
  `global_fit` path, the second of which was a silent no-op that
  recorded `deg=-1` in History), `diff`, `smooth` and `fitmodel`.

* **The version is derived from the repository instead of written in a
  file** (`ITACA-004`, DD-38, REQ-92). `itaca/core/version.py` held
  `__version__ = "0.1.0"` and every M1 commit inherited it, so an sdist
  built from the seam was named `itaca-0.1.0.tar.gz` while containing
  `Pipeline`, `core/sentinels.py`, `ops/rotate.py` and the whole `pproc`
  package, and Provenance and `.itc` recorded a false statement about
  which implementation produced a result. `setuptools-scm` now computes
  it at build time: a tagged commit builds as exactly `X.Y.Z`, and every
  other commit as `X.Y.Z.devN` naming the release being worked toward,
  with `N` the commits since the last release tag.

  **Breaking for source checkouts.** `import itaca` itself now raises
  `VersionResolutionError` on a tree that was never installed. The
  version is resolved at import time, and a guess would be stamped into
  Provenance and into `.itc` archives as though it were a fact, so
  nothing is importable rather than only `__version__` being wrong. Run
  `pip install -e .` first. Also, `itaca/core/_version.py` is generated
  at build time and gitignored.

  A hand-maintained literal was also unbumpable without a window in
  which the tree is wrong: the version-bump commit must be pushed before
  its tag, and a final version on an untagged commit is refused, so the
  branch would go red between the two pushes. Derivation removes that
  window structurally rather than detecting it afterwards.

* **`py.typed` is shipped, so the PEP 561 promise survives installation**
  (`ITACA-014`). `pyproject.toml` declared the `Typing :: Typed`
  classifier while `itaca/py.typed` did not exist, so it was in neither
  the published wheel nor an sdist. A consumer type-checking against the
  installed package got nothing from a promise this repository's own
  `mypy --strict` gate satisfied against the source tree.

* **Publication cannot happen without the gates** (`ITACA-006`,
  REQ-95). `release.yml` triggered on a `v*` tag and ran build,
  `twine check` and a tag-versus-version comparison, then published,
  with no pytest, no coverage, no ruff, no mypy, and no dependency on
  CI's verdict for that SHA; CI's triggers are disjoint from the tag, so
  the two ran in parallel and publish could finish first. Both `ci.yml`
  and `release.yml` now call one vendored reusable release gate, and the
  old publishing body was deleted rather than kept beside it, because a
  second publishing path makes the gate advisory.

* The processor factory is `itc.processor`, not `itc.pproc`. Binding it
  under the package's own name shadowed the `itaca.pproc` attribute the
  import machinery sets, so `itc.pproc.parse_itceq` did not resolve and
  `import itaca.pproc as pp` returned a function without saying so.
  REQ-49 to REQ-51 are specified as `pproc.statistics`, `pproc.compare`
  and `pproc.report`, which that shadow would have made unreachable.
  Renaming the factory rather than the package leaves every module path
  and both requirement texts true as written; `\stable` REQ-46 was
  amended through the SRS process, OQ-29 records the measurement behind
  the choice, and DD-34 the reasoning. Nothing shipped under the old
  name: the factory is new in this release.
* REQ-82 now states the NumPy-only scope as every package except `io/`
  and `utils/`, instead of naming `core/`, `ops/` and `uncertainty/`.
  No behavior changed, because the ruff ban was already repository-wide
  with per-file exemptions; the requirement text had not kept up, and
  `pproc/` arrived in this release already covered by a rule that did
  not mention it. Stated as an exception list, a package added later is
  restricted by default. DD-33 records why; CLAUDE.md, the `pyproject`
  ban messages, and the Chapter 9 contributor checklist moved with it.
* Three guards that enumerated names now discover them, after the
  role-review passes found the same defect class DD-33 names in two
  more files. `tests/test_errors.py` walked a hand-written leaf-to-family
  map, so the five new `ProcessorError` leaves were checked by nothing
  and a public error outside the `ITACAError` hierarchy would have
  shipped; it now discovers every leaf and additionally refuses one that
  belongs to no family. That walk immediately found a real omission:
  `PipelineCompatibilityError` was never added to `errors.__all__` and
  is now exported. `tests/test_package.py` imported five named
  subpackages and never `itaca.pproc`. `tests/test_import_policy.py`
  composed paths from a package list, so modules directly under
  `itaca/`, today `itaca/__init__.py`, were walked by neither half while
  the repository-wide ruff ban covered them; the root is now walked as
  its own unit. All three were proven by mutation.
* `tests/test_python_floor.py` reads stdlib *symbols*, not only modules.
  `from datetime import UTC` is 3.11 while `datetime` is not, so a
  module-granular check reported the library as 3.10-safe when it would
  have failed at import. Lowering the floor now names `datetime.UTC`
  alongside `tomllib`.
* The NumPy-only AST guard no longer enumerates package names.
  `tests/test_import_policy.py` listed `("core", "ops", "uncertainty")`
  and `("core", "ops", "uncertainty", "io", "utils")` in two literal
  tuples, so a package added later was named in neither and the guard
  silently stopped covering the newest part of the library, in exactly
  the case its own docstring says it exists for. The ruff half held,
  since that ban is repository-wide with per-file exemptions, so the
  belt held and the braces did not. Packages are now discovered by
  walking `itaca/` for subdirectories carrying an `__init__.py`, and
  the exemption set is checked against the `per-file-ignores` keys in
  `pyproject.toml` by parsing rather than retyping, comparing library
  package keys only, since `tests/**` is exempt in ruff and is not a
  package the AST guard walks. A third check refuses an exemption
  naming a package that does not exist, and a fourth refuses a
  discovery that comes back empty, which would otherwise pass every
  check vacuously. Both failure modes were reproduced by mutation
  before the fix was accepted.
* The three NumPy-only ban messages in `pyproject.toml` said an import
  was "barred from core/, ops/, and uncertainty/" while the ban's real
  scope is every itaca package except `io/` and `utils/`. A developer
  hitting it inside any other package got an error naming three
  packages that did not include theirs. The messages now state the
  scope REQ-82 requires, which after the amendment above is the same
  scope, so the requirement and its enforcement no longer differ.
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
