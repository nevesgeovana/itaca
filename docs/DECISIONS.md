# ITACA Architectural Decisions Log

This file captures the **architectural decisions** that shaped ITACA v0.1.0.
It is the long-form companion to the design-decision boxes (DD-01 to DD-22)
in the SRS; later entries (DD-23 onward) are recorded here first and enter
the SRS at its next baseline. The SRS states the decision; this file
records why.
Since 2026-07-21 this file is tracked in the research workspace
(`threads/itaca/`); the SRS carries the same baseline as DLV-008.

Every entry is a frozen record. New decisions are appended; old decisions
are never edited in place. If a decision is overturned, a new entry
supersedes it and references the old one.

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
