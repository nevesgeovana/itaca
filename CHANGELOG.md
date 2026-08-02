# Changelog

All notable changes to the ITACA library are documented here. The format
follows Keep a Changelog; versions follow semantic versioning. The SRS
document baseline has its own changelog in `docs/srs/` Chapter 11.

## [Unreleased]

Nothing yet.

## [0.2.1] - 2026-08-02

**Read this before upgrading: this is a PATCH release and it breaks the
reading of files written by 0.2.0.** The version number does not say so,
which is why this paragraph is first. The `.itc` format moves to schema
`itaca-itc/3`, and archives at `itaca-itc/1` and `itaca-itc/2` are
REFUSED by name rather than reinterpreted, because neither records the
spatial coordinate system and reading one back would return a polar frame
as Cartesian. Separately, every state hash changes, once.
**What to do:** re-export any `.itc` you need from the source data before
upgrading, and expect new state hashes for frames you rebuild. The
refusal names the migration and tells you to re-export; nothing is
silently reinterpreted.

New public surface is listed under Added below, and the observable
behavior changes are the bullets under Changed and Fixed, rather than a
count restated here. The count has now been wrong three times: seven
when the entries had grown past seven, eight when a restructure made it
ten, and "one new public exception" when a later lane added two modules
and several callables. A number that has to be maintained by hand beside
a list it describes is a second copy of that list. Also release infrastructure, recorded because it changes how a
release reaches PyPI and the next tag runs on it.

**How v0.2.0 was published, stated plainly.** The v0.2.0 files on PyPI
were uploaded by hand, over the artifact the release gate had built. The
automated path could not publish, for the reason under Changed below.
Those files therefore carry no PEP 740 provenance attestation. Releases
from this one onward are published by the workflow and do carry one,
so a reader comparing the two will find that asymmetry and this is what
explains it.

**Publishing configuration.** The PyPI trusted publisher for `itaca`
names `release.yml` with environment `pypi`. A publisher naming
`release_gate.yml` cannot work and is not a fallback.

### Known open

**This release ships with known limitations, deliberately and on the
record.** v0.2.0 disclosed its known defects here and pinned each one with
a strict-xfail test; that ledger,
`tests/test_chk1_open_defects.py`, now marks exactly TWO defects
`xfail(strict=True)` and passes everything else, so all but two of them
are closed. What follows is those two, plus the classes
the independent review and this cycle's own review rounds found and no
lane has closed. Disclosure is the half that makes shipping with a known
gap legitimate, and a section stating it is now REQUIRED before a version
tag can pass the release gate.

These are stated as **classes of thing you can observe**, not as internal
defect ids, because an id tells you what a fix would be and a class tells
you what happens to you. Every one of them was reproduced against the
code this release ships; the numbers below came from running it.

The two classes that produce a **wrong number with no signal** are first,
because they are the ones to read.

**1. A shared origin that `concat` discarded is not seen, and the result
is silently overstated.** `compute` refuses when it can see that two
quantities came from a common root (see class 3), and that net has a hole
at `concat`: the joined frame carries the History of its FIRST input
alone, so a derivation recorded in any other input is gone, and the
refusal has nothing left to fire on.

Measured, with `p` and `q` plain roots carrying `u(p) = 0.3` and
`u(q) = 0.2` in the first input and both derived from a shared `x` with
`u(x) = 0.1` in the second: `compute("r = p - q")` on the joined frame
returns `u(r) = 0.36055513`, where `0.1` is correct on the second input's
rows.

**This defeats all four of the refusals in class 3, and the rule is one
mechanism rather than four.** Every one of them reads ancestry out of
History, and `concat` keeps only the FIRST input's, so a refusal whose
evidence sits in any other input is defeated. Measured, each with the
evidence in a later input: an unreadable record returns `u = 0.2236`
where the input alone raises; a prior `translate_moments` lets a second
transfer through at `u(MY) = 1.41421356` where `2.0` is correct; an
earlier `interpolate` lets a random-component reduction through at
`u = 0.45069391`. The same evidence in the FIRST input survives the join.

**A third direction is a wrong workaround rather than a wrong number.**
When the derivation is in the first input and another input carries that
name as a plain root, the record is OVER-asserted rather than discarded.
The refusal fires, which looks right, and the expression it suggests is
wrong for the rows that were not derived: measured `z = (2*x) - 2*x`
returning `[0, 0]` where the truth is `[0, 97]`. If you follow a refusal's
suggestion on a concatenated frame, check it against those rows.

**What to do now**, and both routes were run as written. Concatenate the
INPUTS of a derivation and derive once on the joined frame, rather than
joining frames that are already derived. That derivation is then refused
by class 3, which is the correct outcome and not a second problem:
`set_correlation` **on the joined frame** settles it, measured
`u(r) = 0.1`. The frame matters, because `concat` refuses inputs whose
declared correlation stores differ, so declaring on one input and then
joining raises instead. Deriving each input identically needs no extra
step and is the ordinary workflow of processing several runs the same
way.

**Why there is no partial guard, stated because one was here and is gone.**
This release removed a `concat`-time refusal that covered only the case
where uncertainty was already present when the frames were joined.
Declaring on the JOINED frame instead reached the measurement above with
the mechanism in place, so its real effect was to teach readers that the
class was covered. Refusing every `concat` that discards a derivation,
regardless of uncertainty, would refuse ordinary data concatenation. The
trade between those is an open author decision, and until it is taken the
gap is declared here rather than half-covered in code.

**2. A relative uncertainty spec resolved against a non-finite value
yields a non-finite uncertainty.** `set_uncertainty` refuses a DECLARED
magnitude that is not finite, but `"5%"` is resolved against the data, so
on a variable carrying `NaN` it produces `NaN`. Measured: `y = [nan, 2.0]`
with `"5%"` gives `u(y) = [nan 0.1]`, and that `NaN` then propagates into
everything derived from `y`. The structural fix belongs in `UncFrame` and
is blocked on `OQ-40`, because that array carries `NaN` deliberately for
cells `compute(where=)` and `fill` did not touch, so the two meanings have
to be separated first. Pinned by a strict-xfail test.
**What to do now:** declare an absolute magnitude on any variable that
carries `NaN`, or fill before declaring.

**3. Five operations refuse uncertainty, and a sixth family refuses a
shared origin.** Both are deliberate and both raise rather than returning
a number. The first group is unchanged in force from v0.2.0; the second is
new in this release.
`db.smooth`, `db.diff` (and `db.d[dim]`), `db.fitmodel`, `db.fitvalue` and
`db.fill(method="polyfit")` raise when the frame carries an UncFrame,
because their uncertainty rule is not frozen (`REQ-98`; `OQ-18`, `OQ-24`
and `OQ-42` are what would lift them). Separately,
`compute` on quantities of common origin, `translate_moments`
stacked on an earlier transfer, and a random-component reduction over a
dimension an earlier `interpolate` produced all raise
`UncertaintyLineageError` rather than returning a number computed from a
false independence assumption; the message names the single expression
that is already correct. A fourth case joins them: a History entry the
engine cannot interpret leaves every origin unknown, so a multi-carrier
`compute` is refused even for quantities that were never derived.
**All four are defeated by `concat`**, which is class 1 and not a
separate limitation: the joined frame carries only the first input's
History, so a refusal whose evidence sits in another input has nothing
left to read. Class 1 carries the measurements.
**What to do now:** run the five before assigning uncertainty, or use
`fill(method="linear")` or `fill(method="nearest")`; for the refusals,
the escape differs per case, so follow the message you actually got.
The two `compute` refusals, shared ancestry and absent evidence, are
settled EITHER by the single expression the message names OR by
`set_correlation`, including a declared zero. Measured: with `p = 3*x`,
`q = 2*x` and `u(x) = 0.1`, `compute("r = p - q")` raises, and after
`set_correlation({("p","q"): 1.0})` it returns `u(r) = 0.1`, correct.
The other two do NOT consult correlation and cannot be escaped that way:
a stacked `translate_moments` wants ONE transfer done on the frame before
the first one, and a random-component reduction over an interpolated
dimension wants the reduction done before the `interpolate`. Declaring a
pair against either of those re-raises the same error.
**The limit of that advice:** there is still no `drop_uncertainty`
(`OQ-46`), so once a frame carries an UncFrame the only way back is to
re-run from `itc.load`, and applying a processor assigns its
`[uncertainties]` section itself.

**4. Units are labels, not contracts.** Nothing converts and nothing
refuses a mismatch, in three places, and in each the result carries a unit
string that is not what its number means.
`db.combine` sums a variable in `N` with one in `lbf` and labels the
result `N` (pinned by a strict-xfail test). `itc.concat` joins a frame
whose `along` dimension is in `deg` to one in `rad`, and a variable in `N`
to one in `lbf`, taking both labels from the first input; note that
`concat` DOES refuse a mismatch on the other, non-`along` dimensions, so
the coverage is partial in a way the requirement's wording does not
signal. `db.fitmodel` followed by `db.fitvalue` drops the source
dimension's unit entirely: measured `deg` in, `None` on the coefficient
dimension and `None` again on the dimension `fitvalue` restores.
**What to do now:** convert before you combine or concatenate, and note
where the conversion has to happen. `from itaca.utils.units import
convert` is the import that works, since `itc.utils` is not exported. It
CONVERTS VALUES and is not a factor you can fold into an expression: the
temperature units are affine, so `convert(1.0, "C", "K")` is `274.15`. For a VARIABLE, convert with `compute` and re-label
with `set_metadata`. For a DIMENSION there is no route on the frame you
have, so convert the coordinate array before `itc.load`. After a
`fitmodel`/`fitvalue` round trip, re-apply the unit with `set_metadata`.

**5. Structure can survive an operation that invalidated it.** Three
shapes, all reproduced.
After `integrate` consumes a component, the AxisRegistry still declares
the vector group over the components that are gone: measured
`vars = ['FX']` with `force = ('FX','FY','FZ')` still registered, and a
later `db.rotate` on that frame is ACCEPTED rather than refused.
**There is no way out of this one on the frame you have**, which is why
it is stated in full: `declare_vector` refuses a second declaration of an
existing name (`VectorGroupError`, "a group of that name is already
declared"), it refuses a group that is not a triplet, and there is no
public `drop_vector`. All three were measured.
`concat` accepts two inputs that define the SAME axis name with different
rotation matrices and keeps the first input's, so reversing the input
order changes the surviving matrix; both orders were accepted and the
matrices measured differ.
`Dimension` accepts coordinate arrays that cannot describe a grid: empty,
duplicated (`[1, 1]`), and non-finite (`[0, inf]`) were all constructed
without complaint.
**What to do now:** declare vector groups AFTER the reductions that
consume components rather than before, since the declaration cannot be
withdrawn or amended afterward; bring inputs into one axis definition
before concatenating; and check coordinate arrays at ingestion.

**6. Two filters on one dimension: the later replaces the earlier.**
`db.select({"x>": 0, "x<": 3})` over coordinates `[-1, 1, 4]` returns
`[-1, 1]`, which is the second filter alone, where the intersection is
`[1]`. `REQ-20` defines the filter key form and says nothing about two
keys naming one dimension, so this is unspecified rather than contradicted
and it is stated here rather than left to be discovered.
**What to do now:** chain the calls, `db.select({"x>": 0}).select({"x<": 3})`.

**7. A name you can load may be a name you cannot reference.** Ingestion
accepts identifiers the expression parser cannot use, and there is no
public `rename` to get out. Measured: `itc.load(names=["alpha", "force-x"])`
is accepted, and `compute("y = force-x * 2.0")` then raises
`VariableNotFoundError` for `'force'`, because the parser reads the hyphen
as subtraction.
**What to do now:** rename the columns in the source, or pass `names=`
with parser-legal identifiers at load time.

**8. The read-only array guarantee is about the array, not the object
graph.** `REQ-102` promises that no owner reachable FROM a stored array
can restore the write flag, and that holds. It does not cover
reconstruction: `pickle` and `copy.deepcopy` rebuild a frozen dataclass
from its `__dict__` without re-running the constructor, so a `Variable` or
`Dimension` cloned that way holds a WRITEABLE array. Measured, mutated to
`[99. 42.]` by both routes.
**The bound, which is why this is a limitation and not a hole:** a whole
`VarFrame` does not pickle at all today (`TypeError: cannot pickle
'mappingproxy' object`), so no frame produced by this library's own APIs
is reachable this way, and whoever performs the reconstruction is also the
one holding the result.
**What to do now:** treat `save`/`itc.open` as the supported way to move a
frame between processes; it is also the only one that carries Provenance.

**9. One requirement asserted with nothing measuring it, and two the
release does not implement.** All three are `stable` in the SRS and
ungated, which means the document promises them without qualification.
`REQ-88` (all operations vectorized, no Python element loops in hot
paths) is ASSERTED and satisfied as far as anyone can tell, and there is
no benchmark behind it, so nothing would notice if a hot path stopped
being vectorized.
`REQ-89` ships HALF: `db.summary()` does report the in-memory footprint,
and no operation warns when a projected allocation exceeds 1 GB, so an
`expand` onto a high-cardinality dimension is silent until memory runs
out.
`REQ-90` (sparse-aware variants of `compute`, `interpolate` and
`integrate`) is absent entirely; measured, `db.use_sparse` does not
exist.
Whether to implement or descope is an open author decision.

**The `.itceq` uncertainty moment stays open.** The three limitations
declared under `[0.2.0]` about when a declared uncertainty is applied
relative to `[equations]` and `[corrections]` (`OQ-43`, `OQ-44`, `OQ-45`)
are unchanged: a name written more than once takes its declaration after
the FIRST write, a relative declaration on a name that is both carried and
written resolves twice, and a declaration speaks for the systematic
component only.

**The wider population, and what this section does not cover.** An
independent verification compilation reviewed this library and its
findings are what most of the classes above are drawn from; its own
records live outside this repository, so this section states no count
from it. The classes above are those a user can recognize from their own
usage; the remainder
are process, CI topology and documentation currency, which are real and
tracked in the project's working ledger outside this repository. Two of
the classes above are pinned by strict-xfail tests in
`tests/test_chk1_open_defects.py`, so they cannot be forgotten silently;
the rest are held by this section alone, and that asymmetry is stated
rather than smoothed over. Open design questions live in
`docs/OPEN_QUESTIONS.md`, which ships in the source distribution.

**What is NOT in this list.** No limitation above is a case where this
release is worse than v0.2.0. Classes 1 and 3 describe machinery that is
new in this release and that refuses in cases v0.2.0 answered with a wrong
number.

**How to report one.** Open an issue on the repository. A finding that
comes with the `.itceq` or the array that produces it, and what you
expected instead, is one that can be reproduced and therefore fixed.

### Added

* `UncertaintyLineageError`, a new `UncertaintyError` leaf, raised when
  an operation would combine quantities whose shared origin the engine
  cannot see (SRS document 0.2.8, REQ-41; author decision SEAT-UNC).
  Exported from `itaca.core.errors`.
* A dev-only GUM oracle under `tests/oracle/`, cross-validating the
  propagation engine against the `uncertainties` package, and
  metamorphic invariants for the engine under `tests/uncertainty/`.
  DD-25 approved this oracle in M0 and no dependency group ever listed
  the package, so the ruff rule barring it from library code named an
  import nobody could make and the oracle was never written. It is now
  in the `dev` extra. Reinstall with `pip install -e ".[dev]"`.
* `itaca.core.canonical`, the single owner of the length-prefixed
  framing every ITACA digest reads. One encoding, because the state hash
  and the source hash must agree about it (REQ-103, DD-47).
* `itaca.core.immutable.readonly`, which backs an array with an
  immutable buffer so neither it nor any owner reachable from its `base`
  can restore the write flag (REQ-102).
* `itaca.core.coords.coord_system` and `COORD_SYSTEMS`, name-to-tag
  resolution for the coordinate system a `.itc` now persists. An unknown
  name is refused, never defaulted (REQ-70).
* `itaca.uncertainty.expression.validate_expression_syntax`, which
  checks an expression against the REQ-44 operator and function set
  without a VarFrame, so the `.itceq` parser can refuse at parse time
  using the same converter `compute` uses (REQ-48).

### Changed

* **License metadata is a PEP 639 SPDX expression.** `pyproject.toml`
  declared the license in the legacy setuptools table form
  (`license = { text = "MIT" }`), so a built artifact carried a
  free-text `License: MIT` field and the deprecated
  `License :: OSI Approved :: MIT License` classifier, and no
  `License-Expression` at all. The license is unchanged and still MIT;
  what changes is that it is now machine-readable, which is the reason
  PEP 639 exists, since a downstream redistributor has to answer the
  license question programmatically. `license-files` is declared so the
  license TEXT ships and not only its name. **The build requirement for
  `setuptools` rises from `>=68` to `>=77`**, which is where PEP 639
  support begins; a lower floor would let a conforming build environment
  emit the legacy metadata again. Nothing changes for an installing
  consumer.

* **The `dev` extra requires `pytest>=9.0.3` and `pytest-cov>=7.0`.**
  CVE-2025-71176 is pytest's insecure temporary-directory handling on
  UNIX: `/tmp/pytest-of-{user}` is predictable, so a local attacker can
  pre-create it or symlink it ahead of pytest, for information
  disclosure, altered permissions or denial of service. Verified against
  the advisory rather than assumed: the affected range is `< 9.0.3` and
  the patched range is `9.0.3` alone, with no backport to 8.x. So the
  previous `>=8.0,<9.0` did not merely exclude the fix, it pinned this
  project to a vulnerable pytest with no remedy inside its own range.
  Moderate, CVSS 6.8, and a development dependency only, so no released
  artifact is affected. `pytest-cov` moves with it because 5.x predates
  pytest 9. Measured before shipping, in a clean environment: the suite
  passes unchanged on pytest 9.1.1 with pytest-cov 7.1.0, needing no
  source change. **Reinstall with `pip install -e ".[dev]"`.**

* The REQ-83 dependency table in the SRS is now checked against
  `pyproject.toml` in both directions, by
  `tests/test_packaging_metadata.py`, rather than maintained beside it.
  It had drifted both ways: six declared dependencies missing, a range
  for `ruff` where the file carries the exact pin, and five rows for
  packages declared in no extra at all. SRS document 0.2.10.

* **BREAKING: the `.itc` format moves to schema `itaca-itc/3`, and
  archives written by an earlier version no longer open.** They are
  refused by name, with a message saying what the archive lacks and to
  re-export it from the source data. They are NOT read and
  reinterpreted, and the reason is the point of the change: schema 1 and
  2 record no coordinate system, so a frame saved in polar coordinates
  would come back cartesian and integrate against the wrong area
  element. That is one of the defects this schema closes, and a defect
  must not be the remedy for a defect (DD-47, REQ-70).

* **BREAKING: every state hash changes, once.** Three things enter the
  REQ-103 digest in one migration rather than three: canonical
  length-prefixed framing, the spatial coordinate system, and the
  operating mode. A recorded hash from an earlier version will not
  reproduce, which is what the schema refusal above exists to explain
  rather than leave a user to discover as an unexplained mismatch.

* **A `.itc` now carries a member manifest**, the SHA-256 of every
  OTHER member as written, so an edit to any of those is refused rather
  than only an edit that happens to move the recomputed state.

  Stated plainly, because the opposite would be easy to imply: this is
  tamper EVIDENCE, not tamper proofing. A `.itc` carries no secret, so
  an editor who rewrites a member and also recomputes `metadata.json`
  still produces an archive that opens. What ends is the case where a
  one-field edit needed nothing else at all.

  The manifest cannot cover `metadata.json`, since that is where it
  lives, so an edit to a field of that member which no other check reads
  is not refused. The fields that matter carry their own checks: the
  schema string, `state_hash` and `steps_hash`.

* **A JSON export now distinguishes NaN from the infinities.** All three
  used to become `null`, so a point that was never measured stopped
  arriving distinguishable from a computation that diverged, and the two
  call for opposite responses. NaN stays `null`; `+inf` and `-inf`
  export as the strings `"Infinity"` and `"-Infinity"`. The file remains
  strict RFC 8259 JSON: the tokens are quoted, never bare.

* **A JSON export carrying uncertainty now carries the combined value**
  beside its components, under `uncertainty.combined`, with an
  `uncertainty.combination` sentence naming the rule that produced it.
  A consumer given only the components reimplements the composition, and
  the plausible wrong guess is the one that ignores declared
  correlation.

* `to_csv(split_by=...)` refuses a split whose filenames would not tell
  two slices apart, instead of letting one overwrite the other. The
  check runs over every slice before anything is written, so a refused
  export leaves no partial directory. Filenames that do not collide are
  unchanged.

* `compute_state_hash` takes `coords` and `mode` as required keyword
  arguments. Both were state that decided behavior from outside the
  digest, and an optional argument is one a call site can omit, which is
  how they came to be outside it.

* `drop_correlation` on a frame carrying no correlation now returns a
  new frame with a History entry, instead of returning the same object
  and recording nothing. The same call naming variables that removed
  nothing was already recorded, so History told two no-ops apart by
  which branch reached the recorder.

* `translate_moments` records the axis it RESOLVED, always, including
  when the caller passed `axis=None`. Two frames whose groups resolve to
  different axis systems previously recorded byte-identical text.

* **The uncertainty engine now refuses compositions it cannot propagate
  correctly, instead of returning a wrong number.** It is exact WITHIN
  one expression, where the chain rule sees the whole tree, to the same
  first order it always worked to, and carries no lineage BETWEEN
  operations. Measured before this change: `p = 3*x`,
  `q = 2*x`, `r = p - q` gave `u(r) = 0.3606` where `0.1` is correct, a
  3.6x overstatement; `y = 2*x` then `z = y - 2*x` gave `0.2828` where
  zero is exact; two sequential `translate_moments` understated by 29
  percent; `interpolate` then `average` understated the random component
  by 21 percent.

  Four situations are affected, and each refusal names a way forward:

  * `db.compute` when two uncertainty carriers in the equation share an
    origin. The message carries the equivalent SINGLE expression, built
    from the recorded equations, which is already correct.
  * `db.translate_moments` applied to a frame an earlier transfer
    already moved. The message names the one-call transfer from the
    original reference point.
  * `db.average` and `db.integrate` reducing the RANDOM component along
    a dimension an earlier `interpolate` produced. The systematic
    component is unaffected: its rule already assumes full correlation.

  * Any `db.compute` with two carriers on a frame whose History this
    engine cannot interpret, which means a `combine` or a schema-1
    archive restored without its replay steps. Here the refusal is about
    absent EVIDENCE rather than a known shared origin, and it says so;
    the variables may well be independent. `db.set_correlation` settles
    it, including with a declared zero.

  A pair declared with `db.set_correlation` is propagated rather than
  refused, since the coefficient is then a statement the engine uses.
  Independent derivations with a readable History are untouched, so the
  documented `q = 0.5*rho*V**2` then `CL = FZ/(q*S)` workflow still
  propagates.

* **`itc.concat` does NOT refuse a derivation record it cannot keep, and
  the gap is declared instead.** A refusal for this case was written
  during this release cycle and WITHDRAWN before the release, by the
  author's decision of 2026-08-02, so no published version ever carried
  it and there is nothing to migrate. It refused only where uncertainty
  was already present when the frames were joined; the sequence derive,
  concat, then declare reached `u = 0.36055513` where `0.1` is correct
  with the mechanism in place, because what `concat` discards is the
  RECORD a later declaration needs. A guard covering one ordering of
  three acts teaches that the class is handled, which is worse than a
  stated gap. The class is now class 1 under Known open above, and in
  REQ-41.

  Lineage with sensitivities, which would propagate these compositions
  rather than refuse or lose them, is v0.3.0 work.
* **An `.itceq` processor whose corrections read what they correct now
  refuses** rather than returning an understated uncertainty, since it
  is an ordinary sequence of `compute` calls and inherits the same
  limit. Measured 0.1 to 0.9 percent low on the reference blockage
  workflow, growing with the coefficient. A processor whose equations
  read only root variables is unaffected. Whether the processor should
  instead expand its equations against the roots, which would be correct
  and silent, is OQ-50.

* The publish job moved out of the shared reusable gate and into
  `release.yml`, which is now the publisher (DD-45). PyPI Trusted
  Publishing matches the file containing the publishing job, while the
  attestation the same action uploads names the entry point, so with a
  reusable workflow no configured publisher value satisfies both claims.
  Both halves were measured on v0.2.0's tag.
* The tag path now runs the full CI matrix on the commit being released,
  where it previously ran Python 3.12 alone, an interpreter CI's matrix
  does not contain. The artifact that ships is built in a separate
  non-matrix gate call, still on Python 3.12, now beside the full matrix
  rather than instead of it.
* `id-token: write` is held by the publishing job alone; the build and
  gate jobs no longer hold a credential able to publish.
* The packaging frontend is pinned exactly
  (`pip==26.2 build==1.5.0 twine==7.0.0`) instead of being upgraded from
  the index at build time. The build backend is not yet pinned; DD-45
  records that as the open half.

### Fixed

* **`itaca.__version__` depended on the current working directory, and
  could be `None`.** `importlib.metadata` finds a distribution by
  scanning `sys.path` for `*.egg-info` and `*.dist-info` directories,
  and the working directory is on `sys.path`, so any stray
  `itaca.egg-info/` shadowed the real install. Measured: the same
  interpreter at the same commit reported `9.9.9.dev99` from one
  directory and `0.3.0.dev24` from another, and that value is stamped
  into `Provenance.itaca_version` and into every `.itc` archive.
  Separately, `version()` returns `None` for metadata that parses with
  no `Version:` field, which the resolver did not guard, so `None`
  reached a field typed `str` with nothing raised; `mypy --strict`
  cannot see this because typeshed declares `version() -> str`. The
  generated `itaca/core/_version.py` is now read first, which is found
  by import rather than by a path scan, and a resolution that yields
  nothing raises `VersionResolutionError` (DD-48 and DD-49, which
  together supersede two sentences of DD-38). A corrupt or unparsable
  version file degrades to the metadata with a `RuntimeWarning` rather
  than making `import itaca` fail.

  **Two cases this does not fix.** If your tree has never been built (a
  fresh clone, a git worktree, or CI before its install step) there is
  no generated version file, so the version still comes from
  `importlib.metadata` and a stray `itaca.egg-info/` on `sys.path` can
  still shadow it. **Run `pip install -e .` before relying on
  `itaca.__version__` or on `Provenance.itaca_version`.** Second, in an
  editable checkout the version is as old as the last build of that
  checkout, so reinstall after moving between branches if the recorded
  version matters. DD-49 records why neither is closed.

* **A CSV written by `to_csv` could not be read back by `itc.load`.**
  The loader took the first non-empty line as the header, so the
  provenance preamble REQ-71 requires became it and the file ITACA had
  just exported was refused by ITACA: `DataError: row 3 ... it has 2
  fields against a header of 1`. Leading comment lines are now skipped.

* The CSV parser split the text on lines before the reader could see the
  quoting, so a value containing a newline was silently joined:
  `"front\nrear"` came back as `frontrear`. It now parses the stream.
  String cells also keep their whitespace, so a deliberate
  `" padded label "` survives. The stdlib reader does not report whether
  a cell was quoted, so this applies to every string cell and not only
  quoted ones; numeric cells are unaffected, because `float` tolerates
  surrounding spaces.

* `db.manifest(path)` built its CSV with a plain comma join, so a source
  path containing a comma added a field to its own row and the manifest
  parsed as a different table than the one written. It is written to RFC
  4180 now, as `to_csv` already was (REQ-15).

* `itc.open` leaked `json.JSONDecodeError` on a malformed JSON member and
  `ValueError` on a malformed NPZ, and `itc.processor` leaked
  `AttributeError` when a registered constructor returned something that
  is not a Processor. All three now raise inside the `ITACAError`
  hierarchy, and the processor case names the plugin and the protocol
  members it is missing (REQ-45, REQ-46, REQ-81).

* An `.itceq` `[constants]` value of `nan` or `inf` passed validation and
  made every equation reading it non-finite. Non-finite constants are
  refused at parse time (REQ-48).

* An `.itceq` expression using a disallowed operator, such as `x // 2`,
  parsed cleanly and was refused only when the processor was applied,
  after a load, a construction and an explicit `validate()` had all
  reported the file as fine. Expressions are checked at parse time, by
  the same converter `compute` uses, so the two answers cannot drift
  apart. Names are deliberately still resolved at application time: an
  equation may reference a variable an earlier one produces.

* **Editing `provenance.json` inside a `.itc` turned a draft file into
  production, and it reopened with a valid state hash.** `Provenance.mode`
  was outside the authenticated state, so one edited JSON string was
  enough: measured, the same file whose `to_json` had raised
  `DraftModeExportError` exported without `allow_draft` after the edit,
  with the state hash unchanged. `mode` is now inside the digest
  (REQ-08, REQ-11, REQ-103).

* A frame's spatial coordinate system was in neither the state hash nor
  the archive, so a Cartesian and a Polar frame shared a digest and a
  Polar frame reopened Cartesian, silently changing the area element
  `integrate` selects. It is now hashed and persisted, and an unknown
  tag is refused rather than defaulted.

* An individual `HistoryEntry.state_hash` inside a saved archive could
  be forged to 64 zeros and the archive still opened, because only the
  final state hash and the replay-steps digest were authenticated. The
  member manifest covers it.

* Coordinates were serialized without their dtype and rebuilt as
  float64, so an INTACT archive holding float32 or int32 coordinates
  raised `HashMismatchError` on reopen. The dtype is now recorded and
  restored exactly.

* The state-hash framing collided a missing comment with an empty one,
  and let content carrying the separator byte cross field boundaries:
  `("op1\x1fx", "y")` and `("op1", "x\x1fy")` produced one digest. The
  framing is length-prefixed, and absent is a different token from
  empty.

* `set_metadata` sorted the outer mapping but embedded the inner one in
  insertion order, so writing `unit` before `description` and the other
  way round gave one semantic state two hashes.

* `source_hash` for in-memory loads joined variable names with a comma
  and no framing, so `names=['a,b','c']` and `['a','b,c']` collided; and
  it read the caller's raw array bytes, so an integer source and a float
  source that load to the IDENTICAL frame produced different digests. It
  now frames the names and hashes the columns actually loaded.

* `Pipeline(steps=<list>)`, `Provenance(source_files=<list>)` and
  `Provenance(source_coords=...)` stayed bound to the caller's
  containers, so an external `append` changed a frozen object, and its
  content hash, with nothing recorded. All three take ownership at the
  boundary, as `PipelineStep.kwargs` already did; `source_coords` nested
  lists become nested tuples.

* A public array could be made writeable again with
  `setflags(write=True)` and then written, mutating recorded state with
  a changed state hash and no History entry. Arrays are now backed by an
  immutable buffer, so neither the array nor any owner reachable from
  its `base` can restore the flag. Applies to variable values, dimension
  coordinates, uncertainty components, origin tags and rotation matrices
  (REQ-102).

  Two rounds were needed for this one and the CHANGELOG says so, because
  the first fix looked complete. Handing out a read-only VIEW of a
  read-only owner stops `values.setflags(write=True)`, and the review
  measured that `values.base.setflags(write=True)` then restored write
  access and mutated the frame. An owning array may always re-enable its
  own flag; only a buffer that cannot be written at all ends the chain.

* `abs` at zero returned `u = 0` with an uncertainty-carrying input,
  asserting exact certainty at a point where the derivative does not
  exist (`np.sign(0)` is `0`). It now raises
  `UncertaintyCompatibilityError` naming the operator, the offending
  operand value and how many points hit it. `abs` away from zero is unchanged, and an expression
  carrying no uncertainty still evaluates `abs(0)` normally.

* `db.compute(..., where=...)` now EVALUATES only inside its mask. The
  mask was applied to the result, while values and derivatives were
  computed over the whole grid first, so a domain violation in a cell
  the caller excluded still ran: `compute("y = sqrt(v)", where="v >= 0")`
  over `v = [-1, 1]` emitted `invalid value encountered in sqrt` twice
  with an uncertainty carrier and once without, for a cell that never
  reached the output. Excluded cells are now NaN in the evaluation
  environment, which NumPy carries through every ELEMENTWISE operator
  without warning. In-mask results are unchanged, and that holds because
  the substitution is applied only to expressions with no `np.*` call: a
  reduction such as `np.max` reads cells other than its own, so those
  expressions keep the whole-grid evaluation and keep the warning. Under
  `debug=True` the REQ-34 sample evaluation also stays on the whole
  grid, so the report shows the frame's data instead of the mask.
* `db.compute(..., where=..., fill=None)` now keeps the masked-out
  cell's prior UNCERTAINTY as well as its prior value. It kept the
  value and wrote `u = NaN`, so a surviving number came back paired
  with an uncertainty that is not a number: from `x = [100., 4.]` with
  `u(x) = [10., 0.4]`, `compute("x = x / 2", where="i > 0", fill=None)`
  gave `u(x) = [nan, 0.2]`. `fill=<value>` and the default `fill=nan`
  are unchanged: those WRITE the cell, so the uncertainty of the value
  they replaced is still dropped. Both rules are now stated in REQ-35
  (SRS document 0.2.7), which was silent on them. REQ-35, REQ-91,
  FND-073, FND-090.
* `db.average(along=...)` no longer drops an infinity as if the cell
  were empty. Its presence mask was `np.isfinite`, while REQ-27 says
  "arithmetic mean of non-NaN values": the mean of `[1.0, +inf]` came
  back as `1.0`, finite, over a set containing an infinity. The mask is
  now `~np.isnan` and feeds the value, the populated count and the
  REQ-98 reduction weights alike, so a mean over data containing an
  infinity is now infinite. REQ-27, OQ-49, FND-045.
* `db.diagnostics()` now warns when a variable carries infinite values.
  It already counted them into `.non_finite` and said nothing, so an
  all-infinity variable reported `coverage = 1.0` with an empty
  `.warnings`, where an all-NaN variable warned twice. `.coverage`,
  `.missing` and `.non_finite` are unchanged: whether an infinity should
  count as populated is OQ-49 and belongs to the numerical-analyst seat.
  REQ-17, REQ-90, OQ-49, FND-083.
* `db.interpolate(..., method="linear")` and `method="cubic"` now raise
  `DataError` when the source dimension carries fewer than two points,
  instead of dividing by zero and returning `inf` under a bare
  `RuntimeWarning`. Both methods interpolate BETWEEN samples, and the
  segment lookup collapsed to a zero-width segment at one point. The
  refusal is a preflight, so nothing is computed and no warning is
  emitted before it. `method="nearest"` and `method="polyfit"` with
  `deg=0` are defined at one point and are unchanged. The rule is now
  stated in REQ-25 (SRS document 0.2.7), which was silent on source
  cardinality. REQ-25, FND-044.
* `db.combine(op='mean')` and `db.combine(op='weighted_mean')` no longer
  collapse the propagated uncertainty to zero on integer-valued frames.
  The constant partials were built with `np.full_like`, which inherits
  the operand's dtype, so the 0.5 of `mean` truncated to 0: measured
  `u = [0, 0]` where the same values as float64 gave `[2.5, 2.5]`. Only
  frames whose arrays were retyped after `itc.load` could reach it, since
  `itc.load` casts to float64, so this was latent rather than absent.
  REQ-37, FND-035.
* `db.pivot(auto_detect=True)` no longer writes to stdout. It announced
  the dimension list it resolved on every call, with no argument a caller
  could pass to stop it, which corrupts the output of any program using
  itaca as a component. Nothing chartered that output: REQ-14 specifies
  the detection and says nothing about announcing it. The message is
  unchanged and now goes to `logging` at INFO on the `itaca.io.pivot`
  logger, the convention `core/provenance.py` and `io/loader.py` already
  use. A script reading those lines off stdout will now find them absent;
  `logging.basicConfig(level=logging.INFO)` puts them back, on stderr.
  REQ-14, REQ-76, P-08.
* `parse_itceq(..., auto_sort=True)` **still prints** its resolved order,
  deliberately: DD-17 charters that report as feedback to the user, and a
  log record at INFO is silent under the default configuration, so moving
  it would retire a decided behavior in passing. OQ-48 asks whether it
  should move and what would replace DD-17's auditability if it does.

## [0.2.0] - 2026-07-30

Milestone M1, "Analysis Core, computation complete". Read the two blocks
below before the feature list: the first is a deliberate design position
you will hit immediately, and the second is what is known BROKEN in this
release.

**Read this first: five operations refuse uncertainty on purpose.**
This is a deliberate design position, not a defect, and it is stated at
the top of these notes because it is the first thing a user propagating
uncertainty through this release will hit. These five are a different
set from the CHK-1 input refusals listed under Changed below, and the
two sets are unrelated.

Five operations **raise** when the VarFrame carries an UncFrame, rather
than returning a number:

* `db.smooth` (any method)
* `db.diff`, and the `db.d[dim]` sugar
* `db.fitmodel`
* `db.fitvalue`
* `db.fill(method="polyfit")`

Each refuses because its uncertainty rule is **not yet frozen**, and
returning a value would mean guessing one. The first four have no frozen
kernel-weight or coefficient-space rule; `fill(method="polyfit")` has no
weight path at all, since that method evaluates the fitted polynomial
directly and emits no weights for the propagation to consume. REQ-98
carries all five as its provisional rows and is normative.

**What lifts this:** OQ-18 (kernel and moving-fit weights) for `smooth`
and `diff`, OQ-24 (coefficient space) for `fitmodel` and `fitvalue`, and
OQ-42 for `fill(method="polyfit")`, which asks whether the polynomial
weight matrix `interpolate` already propagates through applies to a
support that fill picks per gap from the cells that are not NaN. All
three are open and all three are numerical-analyst decisions. Until they
are answered, the refusal stands.

**What to do now:** run these operations *before* assigning uncertainty,
or use a method that does propagate (`fill(method="linear")` or
`fill(method="nearest")`). Every other operation in this release either
carries its components unchanged, propagates through its weights, or
propagates through its Jacobian; none silently drops or silently carries
an UncFrame.

**Two limits of that advice, stated because you will otherwise find them
the hard way.** There is no `drop_uncertainty`, so once a frame carries
an UncFrame the only way back is to re-run from `itc.load`; and applying
a processor assigns its `[uncertainties]` section itself, so
`proc(db).smooth(...)` refuses even though you never called
`set_uncertainty`. Whether a recorded `db.drop_uncertainty` should exist,
as the symmetric partner of `db.drop_correlation`, is OQ-46 and belongs
to the author. Note that this release introduced TWO withdrawal idioms
that disagree: `set_metadata` is undone by passing `None`, and
`set_correlation` by a separate `drop_correlation`. OQ-46 is where that
is settled.

### Known open

**This release ships WITH known defects, deliberately and on the record.**
The alternative was holding the analysis core behind a long tail of
findings from an independent review, and the decision was to ship and
disclose. Disclosure is the half that makes that legitimate, so it is
here rather than in an issue tracker.

Every item below is pinned by a strict-xfail test in
`tests/test_chk1_open_defects.py`, so it cannot be silently forgotten: the
moment one is fixed, that test passes, strict xfail turns the pass into a
failure, and whoever fixed it has to come and remove the marker.

**Wrong numbers, produced silently.** These are the ones to read.

* **`combine` truncates its Jacobians on an integer dtype** (`R3-ITA-002`).
  A mean of two integer-valued variables takes Jacobian 0.5 and stores it
  as 0, so the propagated uncertainty is zero rather than half. Load or
  cast to float before combining.
* **`average` treats an infinity as missing data** (`R3-ITA-014`), so a
  column containing `inf` reports a finite mean rather than refusing or
  returning `inf`.
* **`interpolate` from a single support point returns `inf`** behind a bare
  `RuntimeWarning` rather than raising (`R3-ITA-013`, linear and cubic).
* **`combine` sums incompatible units silently** (`ITACA-030`): newtons
  plus pounds-force is accepted and the result carries one of the two unit
  strings.

**Provenance and archive integrity.**

* **`db.coords` is outside the state hash AND is lost on an `.itc` round
  trip** (`R3-ITA-004`). A frame saved in polar coordinates reopens as
  Cartesian, and the state hash does not notice. If you use coordinate
  systems, do not rely on `.itc` to carry them in this release.
* **A forged `HistoryEntry.state_hash` inside an `.itc` is not detected**
  (`R3-ITA-005`). The archive-level check catches a tampered final hash;
  a per-entry one does not exist. Treat `.itc` provenance as
  tamper-evident against accident, not against an adversary.
* **`comment=None` and `comment=""` hash identically** (`R3-ITA-003`), and
  **metadata field order changes the state hash** (`R3-ITA-019`), so two
  frames that are semantically identical can hash differently and two that
  differ in one field can hash the same.

**Loud but wrong-shaped.**

* **A malformed `.itc` member leaks `json.JSONDecodeError`** rather than an
  `ITACAError` (`R3-ITA-015`), so `except itc.ITACAError` does not catch a
  corrupt archive.
* **A broken processor constructor leaks its own exception**
  (`ITACA-031` residual).
* **A relative uncertainty spec can still inherit a non-finite value**
  (`R3-ITA-007` structural half). `set_uncertainty` refuses a declared
  NaN; `"5%"` resolved against a column containing NaN is not refused,
  because that array carries NaN deliberately for cells `compute(where=)`
  and `fill` did not touch. Separating the two meanings is `OQ-40`.

**The wider population.** The independent review REV-004 (2026-07-29)
returned 26 findings, all 26 reproduced. Its two blockers and the release
blockers found since are fixed and are described under Fixed below. What
remains is roughly 71 items at P1 and 42 at P2, tracked in the project's
working ledger outside this repository, together with the open design
questions recorded in `docs/OPEN_QUESTIONS.md`, which ships in the
source distribution and is the single home of that list. Among them,
`OQ-18`, `OQ-24` and `OQ-42` are what would lift the five uncertainty
refusals above. None of them is a wrong number produced silently; that
class is enumerated in full at the top of this block.

**How to report one.** Open an issue on the repository. A finding that
comes with the `.itceq` or the array that produces it, and what you
expected instead, is one that can be reproduced and therefore fixed.

### Added

* M1 Phase B3b, processors and the `.itceq` equation file (REQ-45 to
  REQ-48, DD-16, DD-17).
  `itc.processor(name_or_path, *, config=None, auto_sort=False)` builds a
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
  (REQ-107, promoted to stable in SRS 0.2.1; the surface standardizes
  on "axis" for a coordinate
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
  (REQ-98), while the five provisional operations named at the top of
  these notes raise on uncertainty until OQ-18 and OQ-24 freeze their
  kernel-weight and coefficient-space rules. New error leaves `ConcatOverlapError`,
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

The CHK-1 release checkpoint turned five previously accepted inputs into
refusals. Each is listed with the number that used to come out wrong,
because that is the part a reader needs in order to tell whether their
own data was affected.

* **BREAKING. A built-in expression constant may not shadow a measured
  channel** (`CHK1-001`, DD-42). `pi` and `e` were tested before the
  frame's own names, so a frame carrying a variable named `e` read
  Euler's number instead: `CDi = CL**2 / (pi * AR * e)` on `e = 0.5`
  returned `0.01463746` against the correct `0.07957747`, and neither
  the result nor History said so. `e` is the Oswald span efficiency
  factor, so this is the most likely collision in the library's own
  domain. `db.compute` and `EquationProcessor.validate` now refuse it,
  naming the name. Symmetric with DD-39, which already refuses the
  `[constants]` form of the same defect. **Migration:** give the channel
  another name on the way in, with `itc.load(..., names=[...])` for an
  array source or by correcting the header for a file source. A recorded
  rename operation does not exist yet and is OQ-41.
* **BREAKING. `itc.load` refuses a CSV row wider than its header**
  (`R3-ITA-009`). Rows were read by header position, so every cell past
  that width was dropped with no signal while Provenance went on hashing
  the complete file bytes: the source hash certified content the frame
  did not represent. A row that wide is a malformed file, either a
  truncated header or a delimiter inside an unquoted field.
  **Migration:** correct the header, or quote the offending field. A row
  NARROWER than the header is still filled with NaN, unchanged.
* **BREAKING. A VarFrame may not carry one name as both a dimension and
  a variable** (`R3-ITA-008`). Datapoint mode always creates the
  synthetic `datapoint` dimension and also accepted a column of that
  name, so one frame carried both: `select` resolved the dimension and
  never the variable, `to_csv` emitted a duplicate header the loader
  then refused to read back, and `to_pandas` lost one of the two columns
  to a dict-key overwrite. Enforced on the constructor, beside the
  correlation invariant, so no operation can build one either.
  **Migration:** as above.
* **BREAKING. `itc.concat` refuses inputs whose vector groups sit in
  different axis systems** (`CHK1-003`). `concat` rebuilds on the first
  input, so its AxisRegistry stood for every row: a body-axis frame
  joined to an already-rotated wind-axis frame came out claiming one
  axis for all of them, and the next `rotate` transformed the rotated
  rows a second time. REQ-107 makes the recorded source axis the thing
  that keeps a repeated rotation an identity. An input that never
  declared the group counts as the canonical body axis, so the check
  covers the common shape where nobody called `declare_vector`.
  **Migration:** rotate every input to a common target first.
* **BREAKING for a non-finite value. `db.set_uncertainty` refuses a
  declared magnitude that is not a finite number** (`R3-ITA-007`), and a
  malformed one now raises `UncertaintyError` rather than a bare
  `ValueError` or `TypeError` (`ITACA-031`). A NaN standard uncertainty
  propagated into every quantity derived from the variable.
  **Known limitation, stated rather than implied:** only the DECLARED
  magnitude is validated. A relative spec resolves against the data, so
  `"5%"` on a variable carrying NaN still yields a non-finite standard
  uncertainty. The structural fix belongs in `UncFrame` and is blocked
  on OQ-40, because that array carries NaN deliberately for cells
  `compute(where=)` and `fill` did not touch.

* **The SRS now describes the refusals this release ships** (SRS
  documents 0.2.2 and 0.2.3, `ITC-20260729-1450` and
  `ITC-20260729-2255`, which blocked the tag). All five refusals above
  landed against requirement text that contradicted them or passed over
  them in silence: REQ-01 said every column becomes a variable and
  described no row-width refusal at all, REQ-24 and REQ-107 described no
  `AxesError`, REQ-39 said a value may be any float, REQ-44 named `pi`
  and `e` as constants without saying what happens when the frame carries
  one, and REQ-45 said `validate` refuses two things where it now refuses
  three. Six stable requirements are amended, plus REQ-92 and
  REQ-98/REQ-26 as separate items below.

  **Why five bullets amend six requirements, and why the SRS counts six
  refusals where this list counts five.** The mapping is not one to one in
  either direction, and the two effects are separate. Upward: the concat
  refusal is written into REQ-24 **and** REQ-107, and the
  constant-shadowing refusal into REQ-44 **and** REQ-45, so two bullets
  need two requirements each. Downward: REQ-01 is amended for **two** of
  the five, the `datapoint` collision and the row-width refusal. Those net
  out at six requirements for five bullets.
  The SRS counts *refusals* rather than bullets, and it counts six because
  it states `validate`'s third refusal as its own amendment (REQ-45)
  rather than folding it into the constant-shadowing bullet as these notes
  do. The five here are the five rules a caller can hit. Nothing is
  missing from either document: SRS 0.2.2 closed five of the six and SRS
  0.2.3 closed the last one, the row-width refusal, which was missed when
  this list was first written and was found by the independent review
  REV-004 (`ITC-20260729-2255`).

* **The SRS is now built by CI, and it did not build before** (`REQ-95`,
  `ITC-20260729-2300`, `ITC-20260729-2350`, `ITC-20260730-0010`). Nothing
  compiled `docs/srs/` at any point in this release, so a specification
  that could not be built was indistinguishable from one that could.
  `pdflatex` exited non-zero with seven errors: four from a chapter whose
  every content line carried a blank after it, making each source line its
  own paragraph and splitting a `\caption`, and three from a single
  unescaped underscore that put another chapter into math mode which then
  leaked into the chapter after it. Both are fixed, both are guarded, and
  the document now compiles with no errors and no undefined references.
  This is listed for the same reason the requirement amendments above are:
  the authority chain opens by calling `docs/srs/` authoritative, and for
  two document versions it asserted a state nobody had observed. Nothing in the library
  changed: the code was correct and the specification was wrong, which
  is the direction the SRS's own note says is not supposed to happen and
  the reason this was a tag blocker.

* **The source distribution now contains the repository**, not
  only the package: `pip download itaca --no-binary :all:` delivers
  `tests/`, `docs/`, `examples/` and the workspace configuration
  alongside `itaca/`. This follows from deriving the version with
  `setuptools-scm` (DD-38), whose file finder replaces the default
  selection; the wheel is unchanged and still ships `itaca/` alone.
* **BREAKING. The minimum supported Python is now 3.11** (was 3.10).
  This breaks anyone on 3.10: `pip install itaca` there will
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

* **`interpolate` recorded a polynomial degree it never used**
  (`REQ-105`). `interpolate({...}, method="linear", deg=3)` was accepted,
  `deg` was ignored by every method except `"polyfit"`, and it was then
  written into the History string and into the replay kwargs anyway, so the
  provenance record asserted an intent the computation did not honor. That
  is `ITACA-023`, fixed earlier in this same release for NumPy keywords and
  missed for the library's own. `deg` now raises when passed to a method
  that does not consume it, and is recorded only when it was. **Never
  shipped:** `interpolate` is new in this release. `db.fill` has the
  identical hole for `deg`, `window` and `global_fit`, and that signature
  DID ship in v0.1.0, so it needs a deprecation window and is registered
  rather than changed here.
* **`Axis` becomes keyword-only.** It was a six-field positional dataclass,
  one of whose fields (`parent`) exists only to raise until chained
  transforms land, so it occupied a permanent positional slot that could
  never be removed. `Pipeline`, added in the same release, was already
  `kw_only`. Every documented use passes keywords, so nothing breaks.
* **The SRS no longer promises a method that does not exist**
  (`ITACA-012`, the chapter-6 residual). REQ-70 listed
  `db.export_provenance` among the export formats with no qualifier while
  the symbol exists nowhere; it is now marked an M2 deliverable and NOT
  IMPLEMENTED. Chapter 8 had been corrected when the finding was first
  closed and this had not, because the guard written for it read chapter 8
  alone. The guard now walks every chapter.
* **Chapter 8 no longer overclaims what the docstring checker enforces.**
  It said SECTION COMPLETENESS is enforced; the checker pins `Parameters`
  and `Returns`, and REQ-79 names four sections, so `Raises` and
  `Examples` completeness is machine-checked by nothing. Stated as it is.
* **The fourth `rotate` refusal now names `db.drop_correlation`.** Three
  were updated when the method was added, for the reason recorded
  below; this one still said "drop the declaration", which is the state
  the method was introduced to end. All four name the call now.
* **Two refusals stopped promising a fix in the version that ships them.**
  `smooth` and `diff` said "the rule freezes during v0.2.0", in v0.2.0.
  Both now cite OQ-18, which is what actually lifts them, as their three
  siblings already did.
* **`fitmodel` stopped misstating the specification on its public
  surface.** `help(db.fitmodel)` said "the REQ-98 table declares no
  fitmodel row"; the table carries `fitmodel` and `fitvalue` as a
  provisional row. The module docstring had been corrected and the method
  docstring, which is what a user reads, had not.
* **The published sdist no longer carries `.claude/`.** setuptools-scm
  ships every tracked file, which is deliberate for `tests/`, `docs/` and
  `examples/` and wrong for the agent charters, the skills, the vendored
  process kit and the push-gate hooks. `MANIFEST.in` prunes it and
  `tests/test_release_integrity.py` reads a real built sdist to check.

* **A declared `[uncertainties]` value could be replaced by a different
  one, silently** (`R3-ITA-006`, reopened as `R4-ITA-003`; SRS documents
  0.2.4 and 0.2.5). A processor decided
  when to apply each declaration from a single question, whether the
  incoming VarFrame already carried the name. A name the file *writes* and
  the frame happened to carry was therefore assigned before the equations
  ran and then overwritten by its own equation's propagation. With
  `[uncertainties] x = 1.0, y = 5.0` and `[equations] y = "2*x"`, the
  frame shipped `u(y) = 2.0`, which is what `u(x)` propagates to, where
  the file declares `5.0`. With `y = 5.0` declared alone, or declared
  relatively as `"10%"`, the frame shipped no uncertainty at all.
  **Never shipped:** `itc.processor` is new in this release, so no
  published build produced these numbers; if you are running a development
  build, re-apply the processor and re-derive anything downstream of the
  affected target.
  The rule is now two independent questions, and a name may answer yes to
  both: applied before the first line when the frame carries the name, so
  every line reading it propagates from the declared value, and applied
  again after the first line that writes it, so a declaration is not
  shipped as the propagation of itself. The moment was unspecified in the
  SRS, which is why the fix amends Section 4.6 rather than only the code.
  **Three known limitations, all of them reachable through legal files and
  none of them decided:**
  * a name written *more than once*, by an equation and then by a
    correction, takes the declaration after the FIRST write, so the
    correction propagates over it. With `CL = 0.01` declared,
    `[equations] CL = "2*x"` and `[corrections] CL = "CL * 2"`, the frame
    ships `u(CL) = 0.02` (OQ-43);
  * a *relative* declaration on a name that is both carried and written is
    resolved twice, against the values it holds at each moment, so one
    declaration yields two numbers. With `CL = "10%"`,
    `[equations] CD = "CL * 2"` and `[corrections] CL = "CL + 90"` against
    `CL = [10, 10]`, the frame ships `u(CL) = 10.0` beside `u(CD) = 2.0`
    (OQ-44);
  * a declaration speaks for the **systematic** component only, so a random
    component your frame already carries is kept and propagates untouched.
    An `.itceq` file cannot currently specify the whole uncertainty of a
    name it declares (OQ-45).

  All three are numerical-analyst decisions and all three are pinned by
  tests, so the answers cannot change without saying so.
* A negative `.itceq` `[constants]` value kept its sign under a power
  (`CHK1-002`). Substitution round-tripped through `ast.unparse`, which
  writes a negative float as the bare token `-0.25`; re-parsed in the
  base of a power it bound as `-(0.25 ** 2)`, so `x_ref ** 2` with
  `x_ref = -0.25` returned `-0.125` where `+0.125` is correct. Worse,
  History recorded `Cm = -0.25 ** 2 * CN`, an expression that is not
  equivalent to the file's, so the provenance record was
  self-consistent and wrong. Negative reference stations are ordinary in
  this domain.
* The release workflow could not check out (`R3-ITA-001`).
  `release.yml` declared `id-token: write` and nothing else, while the
  gate it calls runs `actions/checkout` three times; declaring any
  permission sets every undeclared one to `none`, and a reusable
  workflow cannot exceed its caller. The green runs came from `ci.yml`,
  a different caller that does grant `contents: read`, and the publish
  jobs it skips were the ones that would have exercised this path.
  `tests/test_release_integrity.py` now asserts every checkout-bearing
  caller grants it.
* The requirement traceability matrix counted its own gap inventory as
  evidence (`R3-ITA-010`). `build_trace` walked the whole suite
  including the module declaring `_UNREACHED_AT_LANE_CLOSE`, so every id
  in that inventory registered as a test citation of the requirement it
  records as unreached, and the gate reported zero unreached where the
  honest figure is 26. The walk now skips its own file, and the ratchet
  asserts both directions, so a stale entry can no longer hide.

* **No personal or institutional identifier appears outside the files
  where authorship is deliberate** (DD-41), and none at all inside the
  importable package. Four occurrences in shipped docstrings stated
  their fact by naming a person or an institution, one of them the
  `set_user` Examples section, which bound a given name to an
  institutional domain and traveled inside every wheel. They now state
  the fact and cite the record instead. Authorship in `LICENSE`,
  `CITATION.cff`, `README.md`, `CHANGELOG.md`, `pyproject.toml` and the
  packaging metadata derived from them is intentional and unchanged.
  DD-41 records the rule, both guards that hold it, and its limits.
* **`fitmodel` no longer misstates the specification it cites.** Its
  module docstring said the normative REQ-98 table declares no
  `fitmodel` row; the table carries `fitmodel` and `fitvalue` as a
  provisional row whose coefficient-space rule is not frozen (OQ-24).
  The behavior was always correct and is unchanged; the description of
  why was not. `propagation.py` likewise called REQ-98 and REQ-99 a
  draft gate awaiting validation, when both were promoted to stable in
  SRS document 0.1.1, and it now names every provisional row rather
  than two. Four `SRS 4.6` citations that pointed at the `.itceq`
  section now point at Axes (4.5) and the HistoryFrame (4.3), and one
  `SRS 4.4` in `_degree.py` now cites REQ-30.
* **`itc.set_user` documents what the identity becomes.** The value is
  captured at VarFrame creation and copied verbatim into every `.itc`
  archive, which is shareable, so the docstring now says to use an
  identifier you would publish rather than a personal email address.
* **Precise public return types, and keyword-only options with a
  deprecation window** (`ITACA-032`, REQ-78, REQ-85). Eight public
  `VarFrame` methods were annotated `-> object`, so a caller under
  `mypy --strict` got nothing back they could use; they now declare
  what they return. `expand`'s `axis` and `interpolate`'s `method`,
  `deg` and `override` become keyword-only OUTRIGHT, with no
  deprecation window. A window was added first, on the reasoning that
  breaking a positional call would be worse than the finding, and the
  release review measured that reasoning against the shipped surface:
  NEITHER method existed in v0.1.0, so there were no released callers
  to protect, and with `axis` keyword-only a positional call raises
  `TypeError` naming the arity, which is loud. The window would have
  let v0.2.0 users write a positional call legally and broken them in
  v0.3.0: it manufactured the compatibility obligation it was added to
  avoid. `db.fill(along, method)` keeps ITS window, because that
  signature genuinely shipped in v0.1.0.

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
  for major version zero, so this release with its documented breaks
  was non-conforming against its own specification. The requirement was
  what was wrong, not the release. Every breaking change is still
  marked BREAKING here with its migration, which is the obligation that
  replaces the version bump while the major version is zero.

  REQ-92 used to enumerate the breaks itself, and named three. That
  count was false by the time the release closed, and it was never quite
  right: the version-resolution break was omitted when the list was
  written, and the CHK-1 checkpoint then added more refusals on top. The
  enumeration has been REMOVED from REQ-92 rather than corrected, and
  no replacement count was put in its place: a bare count is the same
  stale artifact with its evidence removed. This file is where the
  requirement already mandates the list, and a duplicate inventory in a
  normative document goes stale independently of the one it duplicates.
  Four entries here declared a break in prose or in mixed case rather
  than with the marker the requirement names; all of them now carry
  `BREAKING`, so the obligation REQ-92 now rests on is actually true of
  this file. `tests/test_srs_refusals.py` holds it. SRS document 0.2.2
  records the amendment.

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

  **BREAKING for existing `.itc` archives.** An archive written before
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

  **BREAKING, and deliberately so.** Anyone using a constant to
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
  **Shipped in v0.1.0.** If you passed a keyword to a function inside
  `db.compute`, the keyword was ignored and History recorded it as used;
  re-derive those variables.

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
  **Shipped in v0.1.0.** `u(x**2)` came out `NaN` wherever `x` was zero or
  negative, so any uncertainty derived through a power over such data was
  lost rather than wrong; re-derive it.

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
  **Shipped in v0.1.0.** A repeated name in `names=` silently dropped a
  column at load, so anything derived from that frame is suspect;
  re-load and re-derive.

* **A negative polynomial degree is refused** (`ITACA-033`).
  `interpolate({"x": [...]}, "polyfit", -1)` returned zeros over data
  that was a straight line, because the validation checked `deg >= n`
  and never `deg >= 0`. Every public degree parameter now shares one
  check: `interpolate`, `fill` (both the moving-window path and the
  `global_fit` path, the second of which was a silent no-op that
  recorded `deg=-1` in History), `diff`, `smooth` and `fitmodel`.
  **Shipped in v0.1.0, the `fill` half only.**
  `fill(..., deg=-1, global_fit=True)` was a no-op that recorded
  `deg=-1` in History, a wrong number with a provenance record that
  looks correct; re-derive anything filled that way. The `interpolate`,
  `diff`, `smooth` and `fitmodel` degree checks are new in this release
  and never shipped.

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

  **BREAKING for source checkouts.** `import itaca` itself now raises
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
