# ITACA Architectural Decisions Log

This file captures the **architectural decisions** that shaped ITACA v0.1.0.
It is the long-form companion to the design-decision boxes (DD-01 to DD-22)
in the SRS; later entries (DD-23 onward) are recorded here first and enter
the SRS at its next baseline. The SRS states the decision; this file
records why.
A snapshot of this file was carried in the research workspace thread
(`threads/itaca/`, DLV-008) from 2026-07-21, and the SRS carries that
same baseline; this repository is its living home.

Every entry is a frozen record. New decisions are appended; old decisions
are never edited in place. If a decision is overturned, a new entry
supersedes it and references the old one.

**When an entry becomes frozen, stated because the rule above read as
absolute and DD-30 records an exception to it.** An entry is frozen from
PUBLICATION, meaning the commit that ships it. Correcting an entry
before that commit is ordinary drafting and needs no ceremony. After it,
the only instrument is a superseding entry, and an in-place edit is a
defect regardless of how small it looks: DD-30 records that DD-28 was
edited in place after publication, which is what made the unqualified
wording above misleading rather than merely terse (`ITACA-017`).

---

## DD-01: Split Provenance from History

**Date:** v0.1.0 baseline
**Status:** confirmed

Provenance and History were originally a single combined object. The split
aligns ITACA with the W3C PROV-DM model (Entity / Activity / Agent) and
enables provenance-graph serialization across multiple VarFrames, which arise
naturally in `pproc.compare` and in `itc.aerospace` analyses that consume
multiple inputs.

**Rejected alternative:** keep a single combined object. Rejected because it
conflates origin (immutable, set once) with the operation log (append-only),
and because it would force every export format to flatten two semantically
distinct concepts.

---

## DD-02: NumPy-only core

**Date:** v0.1.0 baseline
**Status:** confirmed

`core/`, `ops/`, and `uncertainty/` import only NumPy and the standard
library. xarray, dask, and pandas are barred from these packages.

**Why:** these are the modules that define ITACA's correctness contracts.
Adding optional heavy dependencies to them would couple correctness to the
state of those projects and would make memory profiles unpredictable. NumPy
alone is sufficient for the operations defined in the SRS.

**Enforcement:** a `ruff` import-policy rule blocks non-conforming imports in
these packages.

---

## DD-03: VarFrame structural immutability

**Date:** v0.1.0 baseline
**Status:** confirmed

VarFrame is a frozen dataclass. All operations return new objects. In-place
mutation is structurally impossible.

**Why:** safe chaining; provenance/history consistency by construction;
elimination of an entire class of aliasing bugs. The cost is one extra
allocation per operation, which is small relative to the array sizes ITACA
typically handles.

---

## DD-04: Processors as a Protocol

**Date:** v0.1.0 baseline
**Status:** confirmed

`Processor` is a `typing.Protocol`. Built-in processors implement the
protocol without subclassing a common base.

**Why:** keeps data structure (VarFrame) and analysis logic (Processor)
decoupled. Any object satisfying the protocol: including user-defined
classes living entirely outside the ITACA tree: is a valid processor.
Subclassing `Processor` is a convenience for the built-ins, not a
requirement.

---

## DD-05: UncFrame as structural mirror

**Date:** v0.1.0 baseline
**Status:** confirmed

Uncertainty is stored in a separate UncFrame, not as extra columns inside
VarFrame.

**Why:** uncertainty presence is explicit (`db.uncertainty is None` when
absent); primary data arrays remain clean; downstream code can branch on
presence rather than testing for sentinel values.

---

## DD-06: HistoryFrame as separate mirror

**Date:** v0.1.0 baseline
**Status:** confirmed

Origin tags `{0, +1, âˆ’1}` are stored in a separate HistoryFrame, not as extra
columns or as sentinel values within the main arrays.

**Why:** the numerical arrays remain pure NumPy; operations can manipulate
values and tags in parallel without coupling; the tag space is small enough
(int8) that the memory cost is negligible.

---

## DD-07: Operating modes as metadata, not API branch

**Date:** v0.1.0 baseline
**Status:** confirmed

`draft` vs `production` is a VarFrame attribute, not a different class. The
same API applies in both modes; only history-recording behavior and export
guards differ. Mixing modes is **strict**: `db.promote(...)` or
`db.demote(...)` must be called explicitly before any binary operation.

**Rejected alternative:** permissive mode mixing (the result inherits the
weakest mode automatically). Rejected because silent demotion to `draft` is
exactly the failure mode draft mode is meant to prevent: analysts running a
production pipeline would find out about the demotion only when the export
guard fired, often hours later.

---

## DD-08: Aerospace generates, pproc processes

**Date:** v0.1.0 baseline
**Status:** confirmed

`itc.aerospace` modules **generate** VarFrame data from physical models.
`pproc` modules **process** existing VarFrame data.

**Why:** keeps the dependency graph clean (aerospace builds on pproc, never
the other way around) and ensures that the same plotting, comparison, and
uncertainty machinery applies to both measured and computed data without
special cases.

---

## DD-09: Sensitivity analysis as native capability

**Date:** v0.1.0 baseline
**Status:** confirmed

Sensitivity analysis is the direct output of combining `set_uncertainty` and
`set_correlation` on input variables with `compute` or `itc.aerospace`
computations. The propagated uncertainty on the output **is** the
sensitivity measure.

**Why:** a separate sensitivity module would duplicate the propagation
engine. Treating sensitivity as the natural output of the existing engine
keeps the API minimal and ensures every sensitivity result is also a fully
provenanced VarFrame.

---

## DD-10: Errors as a typed hierarchy

**Date:** v0.1.0 baseline
**Status:** confirmed

All ITACA-specific exceptions inherit from `ITACAError`, organized into
families: `DataError`, `ProcessorError`, `ProvenanceError`,
`UncertaintyError`, `DependencyError`, `AxesError`. The complete enumeration
is in the SRS, Table "The ITACAError hierarchy."

**Why:** users can catch family-level exceptions when appropriate; specific
subclasses provide actionable error messages. Exception types are part of
the public API and follow the same versioning rules as functions.

---

## DD-11: Custom axes are core, not aerospace

**Date:** v0.1.0 baseline
**Status:** confirmed

`Axis` and the rotation operations live in `core/axes.py`, not in
`itc.aerospace`.

**Why:** axis transformations are common across experimental, CFD, and
engineering workflows. WT bookkeeping routinely moves data between rig,
tunnel, body, stability, and wind axes; the machinery must remain available
outside the aerospace subpackage. The rotation operation also interacts
directly with the uncertainty propagation engine and therefore lives next to
`core/correlation.py`.

**Rejected alternative:** put axes in `itc.aerospace`. Rejected because it
would force the uncertainty propagation engine to depend on a higher-level
package, breaking the strict layering of the architecture.

---

## DD-12: Combine over operator overloading

**Date:** v0.1.0 baseline
**Status:** confirmed

Arithmetic combinations of VarFrames go through `db.combine(other, op=...)`,
not Python operators (`+`, `-`, `*`, `/`).

**Why:** every numerical combination must record its semantics in History
and consult the declared correlation structure. Overloaded operators hide
both. Convenience that hides numerical assumptions is not convenience; it is
a defect.

**Rejected alternative:** support both: `db.combine` plus overloaded
operators. Rejected because it splits the correctness contract: `db1 + db2`
and `db1.combine(db2, op="sum")` would behave subtly differently with
respect to History granularity, encouraging users to take the silent path.

---

## DD-13: Custom unit conversion, no external dependency

**Date:** v0.1.0 baseline
**Status:** confirmed

Unit metadata on `Dimension` and `Variable` is optional and opt-in.
Conversion is implemented in `utils/units.py` with a hand-curated table
covering SI base units plus common aerospace units (deg, rpm, knot, ft, lb,
slug, etc.).

**Rejected alternative:** depend on `pint` or `astropy.units`. Rejected to
keep the dependency surface minimal, the conversion table fully auditable,
and to avoid the dtype interactions that those libraries introduce
(particularly with NumPy ufuncs and SMT).

**Cost:** the conversion table is small but must be maintained. Adding a
unit is a `feat:` PR with a single-line table addition plus tests.

---

## DD-14: Covariance support from v0.1.0

**Date:** v0.1.0 baseline
**Status:** confirmed

Cross-correlation handling is in scope for v0.1.0, not deferred. The
propagation engine always evaluates the full GUM clause-5 formula, which
reduces to the independent form when the correlation matrix is zero.

**Why:** wind tunnel data routinely involves multi-channel calibrations that
produce correlated uncertainties. Deferring covariance to a later release
would mean shipping a propagation engine that systematically underestimates
combined uncertainty for the dominant ITACA use case.

**Cost:** the correlation matrix is materialized lazily; users who do not
declare correlations pay no runtime or memory cost.

---

## DD-15: Monte Carlo restricted to discrete-branch models

**Date:** v0.1.0 baseline
**Status:** confirmed

`db.compute(..., method="mcm")` is available specifically for expressions
containing discrete branches (conditional logic that selects different
equations based on input values). It is **not** the default and not
recommended for continuous nonlinearities.

**Why:** symbolic propagation via chain rule on the RPN tree handles
arbitrary continuous nonlinearities correctly, exactly per the GUM linear
model. Switching to Monte Carlo for those cases would be slower without
being more accurate. Discrete branches genuinely break the symbolic model;
those are the cases where MCM is necessary.

---

## DD-16: Idempotence opt-in, with explicit override

**Date:** v0.1.0 baseline
**Status:** confirmed

Processors declare `idempotent: bool` as a class attribute. Default is
`False`: applying a processor twice raises `ProcessorIdempotenceWarning` and
refuses to re-run unless the caller passes `force=True`. Reapplication, when
allowed, always emits the warning and records the second application in
History as a distinct entry. There is no silent no-op.

**Why:** silent no-ops hide bugs (the user thinks the processor ran;
nothing happened). Silent re-running corrupts data (corrections applied
twice). The middle path: warn, refuse, require explicit `force=True`: is
the only one that protects both failure modes.

---

## DD-17: `.itceq` topological sort opt-in with feedback

**Date:** v0.1.0 baseline
**Status:** confirmed

Equations in `.itceq` files evaluate in file order by default. Topological
sorting is available via `auto_sort=True`, in which case the parser reports
the resolved order to the user as feedback.

**Why:** explicit ordering keeps `.itceq` files reproducible across parser
versions. Topological sort is convenient when authoring, and the feedback
makes the resolved order auditable. Forcing topological sort by default
would make the file's behavior depend on the parser's tiebreaking rules,
which is a portability risk.

---

## DD-18: Uncertainty semantics are defined per operation

**Date:** 2026-07-21 (workspace baseline, specification review)
**Status:** confirmed

Every operation declares its effect on the UncFrame; REQ-98 carries the
normative table. All v0.x operations are linear in the variable values, so
propagation through the operation weights is exact. An operation with no
sound propagation rule must raise or warn.

**Rejected alternative:** propagation defined only in `compute` (the
founding draft's implicit position). Rejected because it left every other
operation free to silently drop or silently corrupt the uncertainty record,
violating the fail-fast principle exactly where users are least likely to
notice.

---

## DD-19: Two-component uncertainty

**Date:** 2026-07-21 (workspace baseline, specification review)
**Status:** confirmed

The UncFrame separates a systematic component (fully correlated across the
points of a variable) from a random component (independent between points).
Reductions apply their weights to both, which yields the 1/sqrt(N) gain for
the random component only. Reporting combines them as RSS. This is the
native representation of AIAA S-071A-1999 bias and precision bookkeeping.

**Rejected alternative:** a single per-variable uncertainty array. Rejected
because repeat averaging would then shrink calibration bias by 1/sqrt(N),
silently understating the combined uncertainty of every averaged result,
which is the exact failure mode the standard exists to prevent.

---

## DD-20: Expression parsing built on the Python ast module

**Date:** 2026-07-21 (workspace baseline, specification review)
**Status:** confirmed

`db.compute` expressions are parsed with the standard-library `ast` module
and compiled to the ITACA operator tree; symbolic differentiation walks that
tree. Operator objects keep `evaluate`, `d_da`, and `d_db` and remain
independently testable, so the property-based test obligations (REQ-77) are
unchanged.

**Rejected alternative:** a hand-written tokenizer and infix parser.
Rejected as the most defect-prone component of the foundation release; the
stdlib parser is battle-tested, keeps the NumPy-only rule intact, and gives
precise syntax errors for free.

---

## DD-21: Incremental public releases

**Date:** 2026-07-21 (workspace baseline, specification review)
**Status:** confirmed; supersedes the single-release plan of the v0.1.0b
roadmap chapter

Each milestone ships as a public release on PyPI with a Zenodo DOI: M0 as
v0.1.0, M1 as v0.2.0, M2 as v0.3.0, M3 as v0.4.0. M0 is additionally
slimmed: axis machinery moves to v0.2.0; Monte Carlo propagation and PROV
export move to v0.3.0.

**Rejected alternative:** one public release only after every milestone is
complete (the v0.1.0b position, itself an unrecorded reversal of the
founding incremental plan). Rejected because it maximizes time to first
external feedback and concentrates risk for a solo maintainer; the sibling
package precedent showed the incremental model working in practice.

---

## DD-22: Solver drivers stay outside ITACA

**Date:** 2026-07-21 (workspace baseline, specification review)
**Status:** confirmed

ITACA is solver-agnostic (NREQ-10): it does not launch, script, or automate
any solver, and embeds no solver-specific command emitters. Dedicated driver
packages own solver automation and version-compatibility knowledge; they
interoperate with ITACA through `itc.load` and the export formats. In
Geovana's ecosystem, pyflightstream is such a driver: it automates
FlightStream and may emit ITACA-compatible datasets, while ITACA remains the
generic data-management and uncertainty layer. This resolves the mission
overlap between the two packages recorded in OQ-16.

**Rejected alternative:** embedding solver automation in ITACA, or growing
the driver's post-processing layer into a second general framework. Rejected
to avoid two competing frameworks by the same author and to keep each
package's correctness surface small.

---

## DD-23: Co-development with pyflightstream

**Date:** 2026-07-23
**Status:** confirmed

ITACA and pyflightstream are developed as consciously integrated
sister libraries: each may generate requirements for the other, and
each documents awareness of the other's architecture. This refines
DD-22: the adapter that emits ITACA-compatible datasets lives in
pyflightstream behind an optional extra; ITACA never imports
pyflightstream and gains no solver-specific loader. Needs that
pyflightstream's exporter cannot satisfy with the existing ITACA
surface enter this repository as candidate requirements carrying a
pyflightstream origin; ITACA requirements may cite pyflightstream as
a consumer. Both repositories adopt the same role-based review
process (reviewer charters in `.claude/agents/`, the `role-review`
skill, the author holding the non-delegable seats), so a work item
in either repository is reviewed by the same set of expertises.

**Rejected alternative:** independent evolution with integration
deferred until both libraries stabilize. Rejected because deferred
integration lets each library ossify around the other's absence;
requirement flow is cheapest while both APIs are young, and the
version-aware driver produces exactly the provenance-rich run data
the data layer is designed to receive.

---

## DD-24: Options registry with exact keys (library-review adoption D1)

**Date:** 2026-07-23
**Status:** confirmed

ITACA adopts a central options registry (REQ-104) modeled on the pandas
`register_option` mechanism combined with the OpenMDAO options message
contract: every option is registered with a type, a validator, and a
default; a validator rejection names the offered value, the accepted
domain, and the bounds. Keys are exact, dot-namespaced strings. Partial
or abbreviated key matching is rejected outright: ambiguity is an
error, consistent with the fail-fast posture of the DD-04 family. The
registry supports snapshot and restore so the test suite can reset it
through an autouse fixture. The first consumer is the plot core's
AIAATheme, expressed as a validated configuration tree with a frozen
testing theme (the pyvista pattern), which places the implementation in
the stretch window of M1 (`utils/options.py`; the NumPy-only rule of
`core/`, `ops/`, and `uncertainty/` is untouched).

**Rejected alternative:** pandas-style partial key matching for
convenience. Rejected because silent prefix resolution can bind a
setting to the wrong option as the registry grows, which is exactly the
class of quiet misconfiguration the error-message contract exists to
prevent.

---

## DD-25: uncertainties as a dev-only test oracle (library-review adoption D5)

**Date:** 2026-07-23
**Status:** confirmed

The `uncertainties` package (BSD license) enters the dev dependency
group as a test oracle for the GUM linear-propagation mathematics: an
oracle test tier (`tests/oracle/`) cross-validates the random-component
propagation on small analytic cases against an independent
implementation. It is never a runtime dependency, is never imported by
library code, and its absence never affects any public behavior; the
oracle tier exists purely to catch defects in ITACA's own LPU
implementation. No requirement accompanies this decision because it
adds no public surface.

**Rejected alternative:** adopting `uncertainties` as the runtime
propagation engine. Rejected because ITACA's two-component model,
covariance handling, and provenance recording require an implementation
that the library owns, and because the NumPy-only rule bars third-party
runtime dependencies in `uncertainty/`.

---

## DD-26: scipy as a dev-only geometry test oracle (M1 axes)

**Date:** 2026-07-23
**Status:** confirmed

The rotation machinery (REQ-38, REQ-101) builds direction-cosine
matrices from the general formulation, composing elementary rotations
in pure NumPy so that `core/` stays within the NumPy-only rule (DD-02,
REQ-82) and ITACA owns the analytical sensitivities `dR/dangle` that
the REQ-101 chain-rule uncertainty propagation requires. The `scipy`
package (BSD license) enters the dev dependency group as an
independent oracle: an oracle test tier cross-validates ITACA's
direction-cosine matrices against `scipy.spatial.transform.Rotation`
on random angles. It is never a runtime dependency, is never imported
by library code, and its absence never affects any public behavior;
the oracle exists only to catch defects in ITACA's own geometry. This
mirrors DD-25 (`uncertainties` as a GUM oracle).

**Rejected alternative:** adopting `scipy` as the runtime rotation
engine. Rejected because it would breach the NumPy-only rule for a
data-management core, pull in a heavy runtime dependency, and still
not provide the analytical derivative terms that condition-dependent
frames need; a hand-composed general formulation is textbook, small,
and fully differentiable.

---

## DD-27: The accessor per-instance cache is the one permitted frozen-instance write

**Date:** 2026-07-23
**Status:** confirmed

DD-03 makes in-place mutation of a VarFrame structurally impossible.
The accessor registration mechanism (REQ-106) introduces one sanctioned
exception: the `_CachedAccessor` descriptor writes a per-instance cache
dict onto the frozen VarFrame via `object.__setattr__` on first access,
so `db.<name>` instantiates the accessor once and reuses it (the xarray
pattern). This does not weaken DD-03: the cache attribute is not a
dataclass field, so it never enters the state hash, equality (VarFrame
is `eq=False`), `dataclasses.replace`, or any export; and the
class-level attribute set by `register_accessor` is registration, not
instance state. This entry records that the single `object.__setattr__`
on a frozen VarFrame instance found under `core/accessors.py` is
intentional and bounded, so a future reviewer grepping for it does not
read it as a DD-03 breach.

**Rejected alternative:** an external `WeakKeyDictionary` cache keyed by
frame identity. Rejected because it duplicates the instance lifetime
management the interpreter already provides through the instance
`__dict__`, and the cache is conceptually per-frame state anyway.

---

## DD-28: Pipelines replay structured steps, and .itc_pipe is JSON

**Date:** 2026-07-23
**Status:** confirmed

**Edited in place after first writing; DD-30 records what changed and
the open question it raises.**

A Pipeline (REQ-53 to REQ-55) replays by re-dispatching structured
steps, not by re-parsing the History display strings. Every replayable
operation records a `PipelineStep` (the VarFrame method to call, its
keyword arguments, and the History comment) through the single
`VarFrame._derive` choke point, so a pipeline reconstructs the exact
calls and reproduces the state hash.

**Rejected alternative:** parsing the History `operation` text back into
a call. Those strings are built for humans and for the state hash, and
they are not round-trippable: `concat(along='x', with=[...])` names
frames that no longer exist at replay time, `select` embeds a `repr`,
and any change to display formatting would silently change replay.

Two consequences are recorded here because they are load-bearing. First,
which operations are replayable is an explicit allowlist
(`REPLAYABLE_CALLS`), and `to_pipeline` skips only the frame
construction prefix (`load`, `pivot`). An entry that records no step
anywhere else raises, and a range that yields no step at all raises
rather than returning a pipeline that would apply as a silent no-op.
Keying the skip on "records no step" instead would also swallow a
transform that was merely not wired, silently changing the result.
Second, the step is stored on `HistoryEntry` and excluded from the state
hash, because it is replay metadata rather than frame state; it is
persisted in the `.itc` archive (schema `itaca-itc/2`) so a reopened
archive can still lift its recipe.

The `.itc_pipe` encoding is JSON, superseding the TOML named in the
original text of the .itc_pipe section of SRS Chapter 4. Three reasons:
no Python version ships a standard
library TOML writer (`tomllib` is read-only and 3.11+), so TOML would
force a third-party runtime dependency into a core feature; TOML has no
null type, and `compute(fill=None)` is meaningful and differs from the
default `fill=nan`, so a TOML encoding would either lose it or need a
side-channel that a reader can misread; and replay arguments nest
(`filters`, `at`, `axisTranslation`), which TOML expresses as
non-adjacent sub-tables that scatter one call's arguments. JSON keeps
every content item that section requires (creating version, source
index range, each call with its arguments and comment, and a content
hash) with no dependency, and it matches the `.itc` metadata
discipline. Encoding is not lossless in general: `_freeze` stores
nested lists as tuples and nested mappings as read-only views, and a
non-finite float has no JSON form and is refused at write time rather
than silently reshaped. That section was amended in the same change.

**Rejected alternative:** a hand-rolled stdlib TOML emitter. Rejected
because the nesting, ordering, and null rules above make it real format
code of ours to maintain and test, for a file whose only job is faithful
reproduction.

---

## DD-29: The linter is pinned exactly and bumped deliberately

**Date:** 2026-07-23
**Status:** confirmed

`ruff` is pinned to one exact version in the `[dev]` extra, and the
`ruff-pre-commit` `rev` in `.pre-commit-config.yaml` is locked to that
same version. Bumping it is a deliberate, reviewed change that moves
both together, never an incidental floating upgrade.

The reason is that ruff is not a library ITACA calls, it is a tool whose
*output* is a gate. REQ-96 claims the pre-commit configuration is a
local mirror of the CI lint job, and that claim is only true when both
sides run the identical linter and formatter. A range spec broke it in
practice: CI installed a ruff a year newer than the pinned hook, so
commits passed locally and failed in CI, and a real lint failure stayed
invisible on the author's machine. A version range expresses "any of
these will do", which is the right contract for a library dependency
and the wrong one for a formatter whose rule set changes between
minor releases.

This follows the precedent of DD-25 and DD-26 for dev-only tooling
decisions, and the discipline is adopted from pyflightstream, which hit
the same drift first (recorded in `PYFLIGHTSTREAM_ADOPTIONS.md`).
`tests/test_tooling_config.py` enforces the pin and the hook rev
against each other so they cannot silently diverge again.

**Rejected alternative:** pinning only the pre-commit hook rev and
leaving `[dev]` as a range. Rejected because the drift then simply
moves to the CI side, which is the side the author does not run.

**Open, deferred to the author:** REQ-83 is stable and states that
ITACA declares explicit version *ranges* for every dependency, listing a
minimum tested version and an upper bound; an exact pin is neither, and
its ruff row still reads `>=0.5,<1.0`. By the authority chain the SRS
wins over the code, so this decision is not final until REQ-83 is
either amended to admit exact pins for output-defining tools or the pin
is reverted. Recorded here so the contradiction is visible rather than
silent; the details are staged for a dedicated session.

---

## DD-30: The archive carries a second digest for the replay recipe

**Date:** 2026-07-23
**Status:** confirmed

The `.itc` archive at schema `itaca-itc/2` carries `steps_hash` in
`metadata.json`, a SHA-256 over the recorded replay steps, alongside the
REQ-103 state hash.

REQ-103's state hash covers the recovered state: the data together with
the ordered operation sequence and its comments. It deliberately
excludes the structured replay arguments, because those are provenance
metadata rather than frame state, and widening REQ-103 to swallow them
would change what a state hash means for every frame, including frames
that carry no recipe at all.

Schema 2 makes the archive recipe-bearing, and that exclusion becomes a
gap: an edited replay argument leaves the operation text and the stored
data matching themselves, so the state check passes, and the edited
recipe then steers the next `to_pipeline().apply(...)`. The second
digest closes the gap without moving the REQ-103 boundary.

The requirement follows what an archive **carries**, never what it
**declares**. The schema string is ordinary metadata that no digest
covers, so it cannot gate an integrity check: any archive carrying a
replay step is refused unless `steps_hash` is present and matches,
whichever schema it names. The first implementation gated the check on
`schema != "itaca-itc/1"`, which meant rewriting one string and dropping
the digest skipped verification entirely while the state hash still
validated. Three independent review passes found that hole in the same
sitting, which is what a version field looks like when it is asked to
carry integrity.

**Rejected alternative:** widening REQ-103 to include the replay steps.
Rejected because it changes a published guarantee for every frame in
order to protect a property only recipe-bearing archives have, and it
would make two frames with identical data and identical operations hash
differently on an argument the state does not depend on.

**Rejected alternative:** trusting the schema field and refusing to read
schema 1 archives at all. Rejected because the compatibility promise to
v0.1.0 files is worth keeping, and because it would still rest the
integrity decision on an unauthenticated field.

**Note on DD-28.** DD-28 entered in commit `23001b4`, which was still
unpushed, and its encoding claim was corrected in place in commit
`2047c6b` to say what the JSON encoding actually does with nested
containers and non-finite floats rather than claiming no lossy
encoding. The file itself has been published many times; that
particular entry never had been.

DD-28 has been edited in place after the file was published: its
encoding claim in `2047c6b`, and the marker under its status, added in
`5110f62` and reworded afterward. Further edits to DD-28, and edits to
this note, fall under the same question. A running count is not kept on
purpose: a note that enumerates edits to an entry, written by a commit
that edits that entry, is stale the moment it is written, and this note
carried exactly that defect before a review pass caught it.

The preamble states the append-only rule without a qualifier, so on its
face both edits are violations, and whether "frozen" begins at
authoring or at the first push is a question for the author. It is
registered in the working plan ledger as
`when-does-a-decision-entry-become-frozen`, not settled here, and until
it is settled the strict reading applies.

---

## DD-31: The session documents live under a configured management root

**Date:** 2026-07-27
**Status:** confirmed

The session documents (inbox, handoffs, `NEXT_SESSION.md`, the working
plan ledger, `progress/`, working decision notes) live outside this
repository, under a root named by the `ITACA_MANAGEMENT_ROOT`
environment variable. The operative rule is CLAUDE.md, "Where the
session documents live"; this entry records why, and what was decided
by whom.

Two determinations, taken 2026-07-27 when the management content
migrated to the coordination hub:

**The plan ledger migrated with the rest.** The author's call, product
owner seat, taken against the implementing session's recommendation.
That recommendation was that the ledger stays here, because the
coordination charter lists what never belongs at that level as
"Requirements, plans, changelogs, architecture and command evidence live
in their repository", and the ledger is an itaca fact: its ids are cited
in itaca reviews and handoffs, it is validated by itaca's own skill, and
CLAUDE.md names it beside `docs/OPEN_QUESTIONS.md` and
`docs/M1_EXECUTION_PLAN.md`, both committed here. She weighed the
versioning gain higher. The sister repository did not migrate its
ledger, so the two libraries currently differ on this point, and the
divergence is registered at the coordination level rather than resolved
by either repository alone.

**The location is reached by variable, not by literal.** The rejected
alternative was rewriting the `_private/` literals to the hub path. It
was refused on an invariant this repository already held for
`ITACA_INCIDENT_LEDGER` and `ITACA_PLAN_VALIDATOR`: a hard-coded
personal path publishes one machine's layout into a public repository
and is wrong on every other clone, with a remedy the reader cannot
perform.

**The asymmetry inside the variable family is deliberate.** For the two
checkers, unset means the check does not run. For the root, unset means
a different location is used, so it cannot be an unconditional fallback:
after the migration `_private/` still exists and is empty, and an
unconditional fallback would write handoffs and ledger entries into a
directory nobody reads. Unset therefore uses `_private/` only while that
directory still holds the documents, and is otherwise a configuration
error. Set is checked for identity and not only existence, because the
sibling projects sit under one parent and a root pointed one folder
across would file handoffs into another project while reporting success.

**Guard.** `tests/test_management_root.py`. The rule is executable there
as `resolve_management_root`, driven over constructed environments
rather than over the machine's, so every branch runs on CI, where
nothing is configured, and so a developer's unexported variable is not
mistaken for a repository defect. Each refusal was reproduced and each
carries a three-part message; documentation alone would not have
satisfied the incident rule.

The same module pins four repository facts: that no tracked file matches
a session-document shape; that `_private/` is ignored by the committed
`.gitignore` specifically, rather than by any effective ignore source,
since that entry is the actual enforcement of the never-committed
guarantee once the location became a variable; that no tracked text file
carries a machine-absolute path in the drive-letter, MSYS or POSIX-home
form (it caught one that predated it, in `docs/PYFLIGHTSTREAM_ADOPTIONS.md`);
and that every skill reaching the session documents names the variable
and cites the section heading this rule lives under. The path sweep
recognizes those three forms and skips binary suffixes; it is a guard
against the known shapes, not a proof that no absolute path of any form
can exist.

**Rejected alternative:** a committed pointer file naming the root.
Rejected because it publishes the same machine path the variable exists
to keep out, and gitignoring it reproduces the environment variable with
more machinery and no version control.

---

## DD-32: The Python floor rises to 3.11 so `.itceq` is read by `tomllib`

**Date:** 2026-07-27
**Status:** confirmed

`.itceq` is a TOML-structured file (SRS Section 4.6, REQ-48), and the
parser that reads it is the whole job of M1 phase B3b. Against the
former 3.10 floor there was no way to read TOML from the standard
library, and OQ-28 put three options to the author: vendor a minimal
reader, hand-write a parser for the fixed grammar, or take `tomli` as a
conditional dependency with a REQ-82 and REQ-83 amendment.

She took none of them. The floor rises from 3.10 to 3.11, `tomllib`
enters the standard library, and the parser reads TOML with no
dependency, no vendored code, and no format code of ours. The
amendment lands on REQ-83, which is `\stable` and carries the language
baseline in its dependency table, through the normal SRS process.

**Why this over the three.** Each of the three answered the question by
paying for TOML somewhere else. A vendored reader is third-party code
we do not maintain but must keep, lint, and drift-pin. A hand parser is
format code of ours to maintain and test, refused already in DD-28 for
the writing direction and no better here. A conditional dependency puts
a third-party import in the path of a core feature and forces an
amendment to REQ-82 as well, weakening the NumPy-only rule for a file
format. Raising the floor pays nothing at all: it removes the problem
rather than relocating it, and it makes the data model chapter's claim
that `.itceq` is TOML true rather than approximate. What it costs is
users on 3.10, and none were identified when the decision was taken,
with that gap visible to the author at the time.

**This does not overturn DD-28.** `.itc_pipe` stays JSON. `tomllib`
reads and does not write, so the reason a pipeline cannot be TOML is
untouched by which interpreters ship it; the 3.11 half of that entry's
parenthetical is simply no longer load-bearing, and the null-type and
nesting reasons never depended on the floor. The asymmetry is the
direction of travel: `.itceq` is read and never written by the library,
`.itc_pipe` is both.

**Guard.** `tests/test_python_floor.py`. The floor was previously
guarded only by accident, by the REQ-105 sentinel test happening to
follow imports into the package on the oldest CI leg, so a refactor
could have removed the guard with nothing failing. The floor is now
declared once in `pyproject.toml` and every restatement is checked
against it: the PyPI classifiers, the `ruff` target version, and the
lowest leg of the CI test matrix. A fourth check binds the floor to the
code, refusing a floor below any standard-library module the library
imports, so removing 3.11 while `tomllib` is imported fails rather than
shipping a package that installs where it cannot import. The guard was
proven by mutation: moving `requires-python` alone turned the other
three red, each naming its own file and fix.

**Rejected alternative:** keeping the floor and reading `.itceq` with
one of the three OQ-28 options. Recorded above. **Rejected
alternative:** raising the floor silently as package metadata. Refused
because the baseline is normative in a `\stable` requirement, binds the
CI matrix and the published classifiers, and a metadata-only change
would leave the specification saying 3.10 while the package said 3.11.


---

## DD-33: The NumPy-only scope is stated as an exception list, not a package list

**Date:** 2026-07-27
**Status:** confirmed. Widens the enforcement scope of [[DD-02]], which
is not overturned: its statement about `core/`, `ops/` and
`uncertainty/` still holds.

REQ-82 named three packages, because at the 0.1.0 baseline those were
the packages that existed. Enforcement had already outgrown the text:
the ruff rule bans the three imports repository-wide with per-file
exemptions for `io/` and `utils/`, so the real scope was everything
except two. The amendment makes the requirement say that.

**Why an exception list.** A list of covered packages has to be
extended whenever a package is added, and the moment a package is added
is the moment it is least reviewed, so an unextended list silently
grants a new package no restriction at all. Stated as an exception
list, a new package is restricted by default and an exemption becomes a
deliberate act with a name attached. `pproc/` proved the point the same
week: it was created under the amended rule and was covered with no
text change.

**The guard had the same defect and was fixed with it.**
`tests/test_import_policy.py` enumerated package names in two literal
tuples, so the AST half of the enforcement stopped covering the newest
package while the ruff half kept covering it: the belt held and the
braces did not, in exactly the case the guard's own docstring says it
exists for. Both halves now discover packages by walking, and the two
exemption declarations are checked against each other by parsing
`per-file-ignores` rather than retyping it. The comparison is over
library package keys only, because `per-file-ignores` also exempts
`tests/`, which is not a package the AST guard walks; written as a
plain set equality it would fail on a correct configuration.

**Guard evidence.** Both failure modes were reproduced by mutation
before the fix was accepted: a new package importing pandas, which the
old guard passed and the new one names by file; and an exemption added
to ruff alone, which the new cross-check names on both sides.

**Rejected alternative:** extend the enumerated list to include
`pproc/` and move on. Rejected because it fixes one instance of a
defect whose structural cause is the enumeration itself, and the next
package would reintroduce it. The incident rule here is that a defect
is fixed at its structural cause on its first occurrence.

**Rejected alternative:** state REQ-82 as covering literally every
package with no exceptions, and move the pandas bridge out of `io/`.
Rejected as a much larger change to serve a tidier sentence: REQ-05 and
REQ-84 put the DataFrame bridge in `io/` deliberately and lazily, and
that is the design, not a concession.

---

## DD-34: The processor factory is named apart from the package it lives in

**Date:** 2026-07-27
**Status:** confirmed. Resolves OQ-29.

The factory is `itc.processor(name_or_path)`. The package is
`itc.pproc`. The SRS had given both the name `pproc`, and binding a
function under the package's own name shadows the attribute the import
machinery sets, so `itc.pproc.statistics(db)` could never resolve and
`import itaca.pproc as pp` would hand back a function without saying
so.

**Why rename the factory and not the package.** Measured across
`docs/srs/`, the name appears as an API name in 6 places, as a module
path in 13, and as a `pproc.<callable>` prefix in 16, the last being
REQ-49 to REQ-51. Renaming the factory touches only the 6, leaves the
13 paths untouched, and makes the 16 correct as written, because the
attribute goes back to being the module. Renaming the package would
have cost the 13 plus the directory and every import, and would still
have left the 16 to rewrite.

**A third sense was found while measuring, and it is why this needed
deciding rather than working around.** Chapter 9's worked example opens
`pproc = itc.pproc("ft_drag_polar", ...)`, so the SRS also used the
token as the conventional variable name for a processor instance. One
token meant the factory, the package, and an instance. REQ-51 depends
on the instance reading (`pproc(db, report=path)` as the equivalent of
`pproc.report(db, output=path)`) while REQ-49 depends on the namespace
reading, so no single meaning could be assigned by implementation
alone. The example's variable was renamed with the factory.

**Guard.** `tests/pproc/test_processor.py`, which asserts that
`itc.pproc` is the module, that `itc.pproc.parse_itceq` resolves, that
`itc.processor` is callable, and that `itaca.__all__` does not export
the name `pproc`. The last is the regression that matters: re-exporting
the factory under the package name is a one-line change that would
reintroduce the shadow silently.

**Rejected alternative:** a callable namespace object exported as
`itc.pproc`, satisfying both readings. Rejected by the author as
machinery paid to preserve a collision rather than to remove it.

**Rejected alternative:** keep the shadow and reach everything by
import. Rejected because `import itaca.pproc as pp` returning a
function is a silent trap, and because REQ-49 to REQ-51 would have had
to be rewritten away from the form they are specified in.


---

## DD-35: Reapplication is recognized from the data AND the History

**Date:** 2026-07-27
**Status:** confirmed. Refines the detection rule of [[DD-16]], whose
warn-and-refuse stance is unchanged.

A processor refuses a second application only when the VarFrame carries
every variable it produces **and** the History records this processor.
Matching names alone warn and then apply.

**Why the second piece of evidence.** Detection was originally by names
alone, on the reasoning that the frame is what a second application
would corrupt. The review pass asked what happens to a frame that
legitimately arrives carrying those names: a CSV with `CL` and `q_inf`
beside the raw forces, a hand-built frame, a reopened archive, or a
second processor with overlapping outputs. All of them were refused on
their FIRST application, with `force=True` the only way through. That
teaches the caller to pass `force=True` by reflex, which is precisely
the habit DD-16 exists to prevent, so name-only detection was working
against its own purpose.

**Why the warning stays on the names-only branch.** Overwriting four
variables that already exist is worth saying out loud even when it is
not a reapplication. What changed is that it no longer refuses.

**The accepted cost.** Where the History does not travel with the
data, the evidence is absent and a genuine second application warns
rather than refuses. That is narrower than it first looks, and narrower
than this entry first claimed: the draft-mode case named in the first
draft of this entry does not arise, because `__call__` passes
`history=True` on every write it makes, so a draft application is
signed exactly as a production one is. What remains is a frame rebuilt
from a CSV or JSON export, and one whose History was truncated by a
multi-input operation such as `concat`, which keeps only the first
input's. The `.itc` archive carries History, so the ordinary save and
reopen keeps the evidence.

**Guard.** `tests/pproc/test_processor.py` pins all three rows of the
table: names absent applies, names present without the signature warns
and applies, names present with the signature refuses. A fourth test
pins that the evidence survives a save and reopen, which is the property
the whole rule rests on.

**Rejected alternative:** warn and never refuse. Rejected as
contradicting DD-16 head on, since silent re-runs corrupt data by
applying corrections twice, and warnings are filtered by default.

**Rejected alternative:** keep names-only detection and document the
false positive. Rejected because the documentation would be a note
telling users when to bypass the guard.

---

## DD-36: Idempotence is declared in the .itceq file

**Date:** 2026-07-27
**Status:** confirmed

`[meta] idempotent` is a boolean, and it is the one typed field in a
section whose other fields are strings.

**Why.** REQ-48 says an `.itceq` file fully defines a reproducible
workflow, and idempotence decides whether that workflow may legally
re-run. With it only on the Python class (REQ-47), the sole way to
declare it for a file-defined processor was to subclass
`EquationProcessor` and construct it directly, going around
`itc.processor` entirely, so the property lived outside the
version-controlled artifact that is supposed to carry the workflow.

**Why the typed exception is explicit rather than a general loosening.**
`[meta]` stays strings-only for everything else, and the parser refuses
a quoted `idempotent = "True"` instead of accepting it. Under the old
rule that quoted form parsed cleanly and nothing ever read it, so the
error message's own suggested fix produced a silently ignored field,
which is a fail-loud defect in a guard rather than a formatting
preference. The flag is kept off the `meta` mapping on the spec, so
that mapping stays honestly typed as strings.

**Rejected alternative:** a new `[options]` section for processor flags.
Rejected for now as a sixth section in a format the SRS describes as
having five, for a single field; revisit if `auto_sort` or other
per-file options follow it, which would change the balance.

**Rejected alternative:** state that idempotence is Python-side only.
Rejected because it writes an exception into REQ-48's promise to buy
nothing.

---

## DD-37: A constant may not share a name with an equation target

**Date:** 2026-07-27
**Status:** confirmed

A name declared in `[constants]` and also written by `[equations]` or
`[corrections]` is refused when the file is read.

**Why.** Constants are substituted into every read before an expression
evaluates, so an equation writing that name produces a variable nothing
in the file can ever read: the equation runs and its result is
unreachable. Measured before the rule existed: `k = 2.0` in
`[constants]` with `k = "rho * 100.0"` in `[equations]` made
`x = "k + 1"` evaluate to `3.0`, and History recorded `x = 2.0 + 1`. A
wrong number, no error, and the substituted expression in the record so
not even the provenance showed it.

The parser already refuses seven other malformed shapes; this was the
one it accepted. A name with two definitions of different kinds has no
obvious reading, and the one the parser picks is invisible in the file,
so it is refused rather than resolved by a rule nobody can see.

**What stays legal.** Redefinition within the equation sections:
`[corrections]` replacing an `[equations]` target is the replacement
semantics SRS Section 4.6 provides for, and it is a different thing from
a constant and a target colliding.

**Rejected alternative:** let the constant win, documented. Rejected
because the wrongness is silent and the documentation would have to be
read before the file is written.

**Rejected alternative:** let the equation win. Rejected as inverting
the current behavior while staying just as silent.

## DD-38: The version is derived from the repository, not written in a file

**Date:** 2026-07-28
**Status:** confirmed

`itaca/core/version.py` no longer assigns `__version__`. The version is
computed at build time by `setuptools-scm` from the newest reachable
release tag, and read back at run time from the installed distribution
metadata.

**Why.** A hand-maintained literal is a fact that goes stale silently.
Measured as `ITACA-004`: the file held `0.1.0` while the tree carried
the entire M1 seam, so an sdist built from it was named
`itaca-0.1.0.tar.gz` while containing `Pipeline`, `core/sentinels.py`,
`ops/rotate.py` and the whole `pproc` package. Provenance and the `.itc`
writer both stamped that value, so a result carried a false statement
about which implementation produced it, which is the one thing
provenance exists to prevent.

The second reason is the one nobody had measured, and it decided the
choice between fixing the instance and fixing the cause. The vendored
version-identity rule refuses a FINAL version on an untagged commit.
With a literal, releasing means committing the bump and pushing the
branch BEFORE the tag, because the push gate refuses `--follow-tags` and
`--tags`. That leaves the branch red between the two pushes, at exactly
the moment a release is being cut, which is the moment people are most
likely to reach for a bypass. Deriving from the repository removes the
window rather than detecting it afterwards, which is what the incidents
rule asks for: the structural cause, on first occurrence.

**The scheme is `release-branch-semver`, deliberately.** The default
`guess-next-dev` names the next PATCH after the last tag, so this tree
would build as `0.1.1.devN`. That satisfies the checker, since `0.1.1`
is strictly greater than `0.1.0`, but it is semantically wrong: this
project ships milestones as MINOR releases (M0 to M3 as v0.1.0 to
v0.4.0), and a development version should name the release actually
being worked toward. `release-branch-semver` bumps the minor on `main`
and yields `0.2.0.devN`. On a tagged commit every scheme yields exactly
`X.Y.Z`, so the release path is unaffected by the choice.

`local_scheme = "no-local-version"` is required rather than cosmetic:
the default appends `+g<sha>`, which PyPI rejects on upload and which
the version-identity checker treats as its own separate failure.

**Accepted costs, stated because they are real.**

`setuptools-scm` becomes a build dependency. It is never imported by
`itaca`, so REQ-82 and DD-33 are untouched: the NumPy-only rule governs
what the packages import, and this runs inside the build backend's
isolated environment exactly as `setuptools` already does.

A source tree that was never installed can no longer report a version.
`version.py` raises `VersionResolutionError` instead of guessing,
because a guess would be written into Provenance and into `.itc`
archives as though it were a fact. The remedy is `pip install -e .`,
which is what the contributing guide already instructs.

An editable install freezes the version at install time, so
`itaca.__version__` goes stale in a working tree until the next
reinstall. This is a real daily-workflow wart and it is accepted: the
value is only load-bearing in a built artifact, and every artifact is
built from a fresh checkout.

**Rejected alternative:** keep the literal and adopt the checker's
`--devn-policy nonzero`, which the kit deliberately makes non-default so
that choosing the weaker promise is visible. Rejected because it is
detection rather than prevention: the version would answer "toward which
release" but never "which tree", the red window at tag time would
remain, and after each release someone must remember to bump the literal
or the identity gate reddens the next CI run. The incidents rule asks
for a guard that makes recurrence impossible.

**Known limitation, registered upward rather than worked around here.**
The vendored release gate checks out with `fetch-depth: 0` for its
`identity` and `build` jobs but not for `gates`. In a shallow tagless
checkout `setuptools-scm` derives `0.1.0.dev1` without failing, so that
job would test a package whose version is meaningless, and it would
degrade quietly rather than break. Both callers therefore fetch tags in
their `install` command. The correct fix is `fetch-depth: 0` on that
job, which lives in a hash-pinned kit body and is not this repository's
to edit.

## DD-39: A constant may not shadow a measured channel

**Date:** 2026-07-28
**Status:** confirmed
**Resolves:** OQ-31

A name declared in `[constants]` that the VarFrame also carries as a
variable is refused by `validate`, and therefore by the call, which runs
`validate` first.

**Why.** A constant is substituted into every read before an expression
evaluates, so a declared number silently beats a measured channel of the
same name. Measured as `ITACA-002`: a file declaring `rho = 1.225`
applied to a campaign flown at `rho = 0.9` produced `q_inf` 36 percent
high, and every coefficient downstream of it wrong by that factor. There
was no error, no warning, and no record of the substitution: History
recorded `compute('q_inf = 0.5 * 1.225 * V ** 2', ...)`, so not even the
provenance showed that a measurement had been discarded. `validate` is
the REQ-45 lifecycle step that exists to answer "can this frame feed
this processor" and it returned silently.

**Why this is symmetric with DD-37, not an extension of it.** DD-37
already refuses the collision between a constant and an equation target,
whose reasoning is that a name with two definitions of different kinds
has no obvious reading and the one the parser picks is invisible in the
file. That reasoning transfers whole; only the location of the second
definition differs. The in-file case is the HARMLESS one, where the
equation's result is merely unreachable. The frame case produces a wrong
number from correct-looking inputs, and the wind tunnel shape that makes
it likely, a nominal `rho` or `S_ref` declared in the file while the
acquisition system also logs it, is the common case rather than the
exotic one. The fix had landed on the safe instance and left the
dangerous one.

**Where it is checked, and why not at parse time.** The parser never
sees a frame: `parse_itceq` takes a path and `EquationProcessor.__init__`
takes a spec. `validate(db)` is the first step that holds both. The same
file is perfectly legal against a campaign that does not log that
channel, so this is not a file defect and `ItceqParseError` would be the
wrong class; `ProcessorValidationError` is the leaf `validate` already
raises.

The check reads the RESOLVED constants rather than the file's own,
because a `config=` override changes which number would win, and the
message must name the number that would actually have been used.

It is raised first and alone rather than folded into the existing
absence message, because the two fixes are opposites: that message ends
in "load the missing channels", and this one ends in "remove the entry
from [constants]".

**Scope.** The refusal is over `db.vars` only. Expressions read
variables, so a constant sharing a DIMENSION's name shadows nothing and
is not refused; measured, that case validates and applies cleanly. A
wider check would be over-refusal.

**Accepted cost, and it is the one nobody measured.** This breaks anyone
deliberately using a constant to override a bad channel. That path is
gone and the replacement is to correct the channel in the frame, which
is what `[corrections]` and `db.compute` are for. The author's decision
was recorded as REFUSE rather than warn, and it is not to be softened
without her changing it.

**Rejected alternative:** warn in `validate` and substitute anyway.
Rejected for the reason DD-37 rejected the same shape: the wrongness is
silent in the artifact even if the terminal said something, and a
warning is not carried in History, so a result read a week later shows
nothing.

**Rejected alternative:** an explicit override marker in the file, or a
`force=` flag. Rejected for this release as premature: no measured need
exists for it, and adding an escape hatch beside a refusal that has
never shipped would design the escape before the rule has been used.

## DD-40: The state hash is a semantic guarantee, defined representationally

**Date:** 2026-07-28
**Status:** confirmed
**Closes:** ITACA-003

REQ-103 states a guarantee rather than a field list: two VarFrames in
the same semantic state have the same hash. The enumeration in the
requirement follows from the definition instead of constituting it.

**Why.** Measured as `ITACA-003`: a frame whose angle dimension is
labeled `deg` and one labeled `rad`, with identical arrays, hashed
identically while `rotate` read the unit and produced `FZ = -1.0`
against `-0.894`. Two states with the same identity produced different
physics. The contradiction sat inside the SRS itself, with Section 4
calling unit a metadata field while REQ-101 required `rotate` to
interpret it.

Stating a field list was what allowed the drift, and it had drifted in
BOTH directions at once inside one requirement: units were outside the
hash and needed to be in, while the axis registry was already hashed by
the code and omitted from the reqbox. A guarantee cannot drift that way,
because the question stops being "is this field listed" and becomes
"does this change the state".

**What same semantic state means, at the floating-point boundary.** The
definition is REPRESENTATIONAL: field for field, the dtypes, shapes and
IEEE-754 bit patterns agree, and every covered metadata field agrees.

Two normalizations, both of things unobservable through the read-only
public surface (REQ-102): memory layout to C order (already done), and
byte order to the platform's native order. Normalizing byte order to
NATIVE rather than to a fixed canonical order is deliberate: it leaves
every existing hash unchanged, and it keeps the digest
platform-dependent, which REQ-103 already concedes.

Four deliberate non-normalizations, each with its reason:

- `-0.0` is not `0.0`. It is observable: `1.0 / x` yields negative
  infinity against positive infinity through the public API.
  Canonicalizing signed zeros would make the guarantee false rather
  than merely strict.
- A one-unit-in-the-last-place difference is a difference. Detecting
  exactly that is why the archive guard exists, and a tolerant digest
  is self-defeating: hashing is discontinuous, so every tolerance has
  boundary pairs that are within tolerance and land in different
  buckets, and the relation is not transitive. Tolerant comparison
  already has a home in `pproc.compare`, which REQ-103 names.
- `float32` is not `float64`. It changes the precision of every later
  operation, the dtype `to_numpy` returns, and the archive bytes.
- NaN payloads differ. This is the one honest asymmetry: no path reads
  a payload, so under a strictly observational definition two frames
  differing only in one would be indistinguishable. Normalizing was
  rejected because it costs a scan and a copy of every array on every
  hash, forever, to defend against a state no operation can produce.

**The cost, stated because the requirement must say it.** Hash
EQUALITY implies semantic identity. Hash INEQUALITY proves nothing about
semantic difference.

**The metadata boundary is WIDE:** every field the archive
reconstructs, which adds `description` and `long_name` to the units the
finding required, and `Axis.description`. The narrow alternative,
"every field an operation reads", was rejected on two grounds. The
archive persists and reconstructs description and long name, so under
the narrow line an editor could change what a variable claims to be
inside an archive the state hash certifies. And the narrow line
requires the SRS to defend, field by field and forever, why long name
sits outside a guarantee covering unit, while a field that becomes
load-bearing later falls silently outside. The review found that
argument in miniature: `pivot` promotes a Variable unit into the
Dimension unit that `rotate` reads, so a field that looked like pure
metadata is load-bearing one operation later.

**An absent field contributes nothing to the digest.** A frame that
declares no metadata hashes exactly as it did before metadata entered
the scope, which is the same rule the axis registry already used. This
is what bounds the compatibility break below rather than removing it.

**Accepted cost: the `.itc` compatibility break.** An archive written
before this change whose dims or variables carry a unit, description or
long name recomputes to a different digest and fails `itc.open`. The
author chose to accept and document the break rather than freeze a
legacy digest for the old scope. The error message therefore carries
the explanation, because the message is now the only thing standing
between an intact old archive and a false corruption report: it names
the scope change, cites this decision, and gives the remedy. An archive
with no metadata is unaffected, verified against the shipped example.

**Rejected alternative:** a frozen `_state_hash_legacy` pair that
verifies pre-0.2.0 archives under the old scope. Rejected by the author
as code that may never be edited again in exchange for a case a
re-export solves.

**Rejected alternative:** bump the `.itc` schema and verify old schemas
under the old scope permanently. Rejected for keeping a weaker
integrity guarantee alive for old files forever rather than marking
them as predating the scope.
