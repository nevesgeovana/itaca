# ITACA Open Questions Log

This file records architectural and API questions that arose during the
design of ITACA, together with the chosen answer and the rationale. Each
entry is a permanent record: once resolved, a question is not deleted, only
tagged with its resolution and (if appropriate) cross-referenced to the SRS
requirement it produced.

New questions are appended as they arise during development. The convention:

| Status | Meaning |
|---|---|
| **resolved** | Decision made; implemented in the SRS |
| **deferred** | Recognized but consciously postponed; revisit at noted version |
| **open** | Active; awaiting decision |

---

## OQ-01: UncFrame semantics: VarFrame structurally, or separate type?

**Status:** resolved (Option A confirmed)
**Resolution:** UncFrame is structurally a VarFrame restricted to standard
uncertainties. Same dimensions, same variable names, same indexing.
**SRS:** Section 4.2; DD-05.
**Why:** plotting and exporting uncertainty data become trivial: they reuse
the VarFrame machinery directly. The marginal type-system gain of a separate
class did not justify doubling the surface to maintain.

---

## OQ-02: Provenance vs. History split: final form?

**Status:** resolved (split confirmed)
**Resolution:** Provenance and History are separate objects. Provenance is
static and immutable, established at load time. History is append-only,
indexed, and exportable as a Pipeline subrange.
**SRS:** Sections 4.4.1, 4.4.2; DD-01.

---

## OQ-03: Idempotence policy for processors

**Status:** resolved (Option C with default = warn-and-refuse)
**Resolution:** processors declare `idempotent: bool`. Default is `False`,
meaning a second application raises `ProcessorIdempotenceWarning` and
refuses unless the caller passes `force=True`. A warning is always emitted
when the processor reapplies.
**SRS:** REQ-47; DD-16.

---

## OQ-04: `.itceq` cycle detection and ordering

**Status:** resolved (file order default; optional topological sort with
feedback)
**Resolution:** equations evaluate in file order by default. Setting
`auto_sort=True` enables topological sort; the parser reports the resolved
order to the user as feedback. Cycles are caught at parse time in either
mode.
**SRS:** REQ-48; DD-17.

---

## OQ-05: Canonical axis convention and custom-axis support

**Status:** resolved (AIAA default + custom Axis class in core)
**Resolution:** AIAA R-004A-1992 is the canonical default. Custom axes are
first-class objects (`core/axes.py`), each carrying a 3×3 rotation matrix
relative to the canonical body axis. `db.rotate(target_axis)` applies the
rotation to detected vector groups and propagates uncertainty through the
rotation matrix as Jacobian, including covariance terms when present.
**SRS:** Section 4.7; REQ-38; DD-11.
**Note:** axis rotation is in `core/`, not in `itc.aerospace`, because WT
bookkeeping requires it independently of the aerospace subpackage.

---

## OQ-06: WT corrections as named processors vs. generic apply_corrections

**Status:** resolved (Option A: named processors)
**Resolution:** each WT correction (solid blockage, wake blockage,
streamline curvature, buoyancy) is a named processor under
`pproc/builtin/wt_corrections.py`, composable into a pipeline. Each
correction records its own History entry.
**SRS:** Roadmap M2.

---

## OQ-07: Mode mixing in binary operations: final policy

**Status:** resolved (strict)
**Resolution:** binary operations require both inputs to share the same
operating mode. Mixed-mode combinations raise `OperatingModeMixError`. The
user must call `db.promote(...)` or `db.demote(...)` explicitly.
**SRS:** REQ-12; DD-07.

---

## OQ-08: Units strategy

**Status:** resolved (custom internal table, no external dependency)
**Resolution:** unit metadata on `Dimension` and `Variable` is optional.
Conversion is implemented in `utils/units.py` with a hand-curated table.
External libraries (`pint`, `astropy.units`) are not used.
**SRS:** REQ-73; DD-13; NREQ-09.

---

## OQ-09: Uncertainty correlation: when?

**Status:** resolved (in v0.1.0)
**Resolution:** correlation handling ships with v0.1.0. The propagation
engine always evaluates the full GUM clause-5 formula, which reduces to the
independence form when the correlation matrix is zero. Users opt in by
calling `db.set_correlation(...)`.
**SRS:** REQ-40, REQ-41; DD-14.
**Why earlier than originally planned:** wind tunnel multi-channel
calibrations produce correlated uncertainties as the norm, not the
exception. Shipping a propagation engine that ignores them by construction
would systematically underestimate combined uncertainty for the dominant
ITACA use case.

---

## OQ-10: HistoryFrame interaction with reductions

**Status:** resolved (Option A: worst-case rule)
**Resolution:** the result tag is `-1` if any contributor is `-1`, else
`+1` if any is `+1`, else `0`.
**SRS:** Section 4.3 ("Reductions" paragraph).

---

## OQ-11: fitmodel coefficient labeling convention

**Status:** resolved (`alpha^0`, `alpha^1`, ..., `alpha^N`)
**Resolution:** the new dimension keeps the original name suffixed by
`_coef` and uses coordinate labels of the form `alpha^0`, `alpha^1`, ...,
`alpha^N`, mirroring the variable's exponent in the polynomial fit.
**SRS:** REQ-31.

---

## OQ-12: DataVis multi-plot row count computation

**Status:** resolved (Option A: ceil + blank cells)
**Resolution:** `n_rows = ceil(n_total / n_cols)`; trailing cells are
blank. Default subplot size is 3.5 × 3 inches.
**SRS:** REQ-58.

---

## OQ-13: `.itc_surr` format: embed source or only hash?

**Status:** resolved (hash by default; optional embed via flag)
**Resolution:** `Surrogate.save(path, embed_source=False)` writes only the
SHA-256 of the source VarFrame by default. Passing `embed_source=True`
embeds the full source for self-contained audit, at the cost of a larger
file.
**SRS:** Section 4.8; REQ-64.

---

## OQ-14: N-way `pproc.compare`: positional or named inputs?

**Status:** resolved (named inputs required)
**Resolution:** `pproc.compare(reference=db_ref, **named_inputs)` requires
keyword-only named inputs. Output variables are suffixed by the input
names, not by positional indices.
**SRS:** REQ-50.

---

## OQ-15: Aerospace SRS scope: distributed propulsion in v0.4 or later?

**Status:** resolved (removed from roadmap)
**Resolution:** distributed propulsion is removed from the v0.1.0 roadmap
and from the post-release planned features. It is deferred to a future
roadmap exercise after the core aerospace framework stabilizes.
**SRS:** Chapter 10 (post-release roadmap, no longer mentions distributed
propulsion).

---

## OQ-16: Boundary between ITACA and the solver driver package

**Status:** resolved (2026-07-21, workspace baseline)
**Resolution:** ITACA is solver-agnostic and contains no solver automation
(NREQ-10, DD-22). Solver drivers (in Geovana's ecosystem, pyflightstream)
own solver scripting, execution, and version compatibility; they
interoperate with ITACA through `itc.load` and the export formats, and may
emit ITACA-compatible datasets. ITACA remains the generic data-management,
uncertainty, and plotting layer.
**Why:** the two packages were converging on the same post-processing
mission (the driver's xarray-backed result structures vs the VarFrame).
Two competing frameworks by the same author would split effort and
credibility; an explicit boundary lets each stay small and correct.
**Note:** adopted on Linka's recommendation with Geovana's approval of the
full review implementation, 2026-07-21. Revisit only if the driver's
post-processing layer needs capabilities ITACA declines to provide.

---

## OQ-17: Release model, single or incremental

**Status:** resolved (2026-07-21, workspace baseline)
**Resolution:** incremental public releases, one per milestone, each on
PyPI with a Zenodo DOI (DD-21). M0 slimmed: axes to v0.2.0, Monte Carlo
and PROV export to v0.3.0.
**SRS:** Chapter 10; DD-21.
**Why:** the v0.1.0b roadmap had silently reversed the founding
incremental plan into a single big-bang release; for a solo maintainer
that maximizes time to first feedback and concentrates risk.

---

## OQ-18: Two-component propagation weights through smoothing and diff

**Status:** open; revisit during v0.2.0 implementation
**Question:** for `smooth` and `diff`, the systematic component is fully
correlated across points, so its propagation through kernel weights
reduces to the weight sum applied to a common bias, while the random
component follows the RSS of weights. Whether the systematic component
should additionally track sign changes of the weights (relevant for
derivative kernels, where a common bias cancels exactly) needs a worked
derivation and property-based tests before the rule in REQ-98 is frozen
for these two operations.

---

## OQ-19: Dict-mode representation of dimensions swept within a file

**Status:** resolved (2026-07-21, approved by Geovana during M0 Phase 2)
**Resolution:** in `itc.load` dict mode, a coordinate tuple position may
hold the sentinel `"*"` to declare that the dimension is swept within
that file; the coordinate values are then read from the file column of
the same name. Tuple length always equals `len(dims)` (REQ-03 letter
preserved). The sentinel mirrors the manifest `*` convention (REQ-15).
**SRS:** REQ-03, REQ-15. To be folded into the SRS text at the next
document revision (Chapter 11 and revision history updated together).

---

## OQ-20: Where the manifest gets its file-to-coordinates mapping

**Status:** resolved (2026-07-21, approved by Geovana during M0 Phase 2)
**Resolution:** `Provenance` carries an additional field
`source_coords` recording, per source file, the dimension coordinate
values (or `"*"`) captured at load time. It is origin information, so
it lives in Provenance, is immutable, and is excluded from the state
hash like all Provenance fields. `db.manifest` is a pure read of this
record.
**SRS:** REQ-15, Section 4.4.1 (Provenance table to gain one row at
the next document revision).

---

## OQ-21: String-valued columns in loaded tables

**Status:** resolved (2026-07-21, approved by Geovana during M0 Phase 2)
**Resolution:** string-valued columns are accepted only as dimension
coordinates (dict-mode tuples or in-file swept columns); loading a
string column as a variable raises `DataError` with the suggestion to
use it as a dimension. Variables remain numeric arrays with `np.nan`
for missing entries (Section 4.1.4).
**SRS:** REQ-01, REQ-04, REQ-05, Section 4.1.4.

---

## OQ-22: Scope of the draft-mode export guard

**Status:** resolved (2026-07-21, approved by Geovana during M0 Phase 2)
**Resolution:** the `DraftModeExportError` guard (REQ-11) protects
result exports (`save`, `to_csv`, `to_json`, `to_pandas`,
`to_numpy`). Inspection artifacts (`db.manifest` files,
`db.diagnostics(log=...)` logs) are exploration aids and are exempt;
they exist precisely to understand draft data.
**SRS:** REQ-11 (wording to gain the clarification at the next
document revision).

---

## OQ-23: Does declared correlation apply to both uncertainty components?

**Status:** resolved (2026-07-21, approved by Geovana at the M0 Phase 4
checkpoint)
**Question:** `set_correlation` declares one coefficient per variable
pair, but the UncFrame carries two components. The SRS did not state
whether r(a, b) enters the LPU for the systematic component, the
random component, or both.
**Resolution:** the declared coefficient applies identically to both
components, in `compute` propagation and in the `cross_correlation=`
of `combine`. A future need for per-component correlation (e.g.
common calibration biasing only the systematic parts) would be a new
requirement, not a reinterpretation.
**SRS:** Section 4.2 (document 0.1.1); REQ-40, REQ-41.

---

## OQ-24: Coefficient-space uncertainty rule for fitmodel

**Status:** open; surfaced 2026-07-23 during M1 Phase B1
**Question:** the normative REQ-98 table (Table "Normative UncFrame
semantics per operation") lists `interpolate`, `fill`, and `fitvalue`
as propagating through fit weights, but has no row for `fitmodel`.
Unlike `fitvalue` (a linear evaluation of stored coefficients),
`fitmodel` maps sampled values to least-squares polynomial
coefficients: the coefficient covariance is the Gauss-Markov
`(X^T X)^-1 X^T Sigma X (X^T X)^-1`, whose two-component split and
per-coefficient correlation are not obvious and interact with OQ-18
(the same kernel-weight question). Until a rule is worked and
validated, `fitmodel` follows DD-18 and raises when uncertainty is
present, consistent with the sanctioned smooth/diff raise.
**Decision (2026-07-23, M1 Phase B1, Geovana):** `fitvalue` also
raises when uncertainty is present, deferring with `fitmodel` even
though its forward `sum_k c_k t^k` evaluation is exact and linear.
Rationale: a `fitmodel` output carries no coefficient uncertainty
until this question is resolved, so the forward branch would only ever
fire on a hand-assembled frame; keeping forward and inverse frozen
together avoids shipping half a coefficient-space story. Both raise;
the REQ-98 table carries a `fitmodel`/`fitvalue` provisional row.
**Proposed handling:** carry the derivation together with the OQ-18
work (Q-004) so Geovana validates one coherent coefficient-space
story.
**SRS:** REQ-31, REQ-32, REQ-98 (Table `fitmodel`/`fitvalue`
provisional row); OQ-18.

---

## OQ-25: Origin-tag reduction across a fit or integral

**Status:** resolved (2026-07-23, confirmed by Geovana); surfaced during
M1 Phase B1
**Resolution:** the four implemented rules are the intended semantics
and are folded into Section 4.3: weight-based reductions take the
worst-case tag over the nonzero-weight cells; `fitmodel` spreads the
worst case across the coefficients of a fitted line; `fitvalue` tags
in-range `+1` and out-of-range `-1`; windowed `smooth`/`diff` take the
worst case over each moving window.
**SRS:** Section 4.3 (updated 2026-07-23).

<!-- original question retained below -->

**Original question (M1 Phase B1):**
**Question:** the HistoryFrame worst-case rule (OQ-10) was defined for
elementwise and windowed operations. `average`, `integrate`,
`fitmodel`, and `fitvalue` collapse or expand the tag grid: the B1
implementation reduces a collapsed line to its worst-case tag over the
weighted cells, spreads a fitted line's worst case across its
coefficients, and tags a `fitvalue` point by whether it lies inside
the recorded fit range. These choices are reasonable but were made in
implementation, not specified. They should be stated in Section 4.3 or
confirmed as the intended semantics.
**Proposed handling:** low-risk documentation item; confirm the four
rules and fold them into Section 4.3 at the next document revision.
**SRS:** Section 4.3; REQ-27, REQ-28, REQ-31, REQ-32.

---

## OQ-26: Correlation involving frame angles in rotation propagation

**Status:** open; surfaced 2026-07-23 during M1 Phase B2
**Question:** `db.rotate` propagates uncertainty through the exact
rotation Jacobian on the within-cell component covariance (REQ-98,
OQ-23) plus a chain-rule term for uncertain frame angles (REQ-101).
The B2 implementation treats the frame angles (alpha, beta) as
mutually independent and independent of the vector components: the
sensitivities to a shared angle across the source and target frames
are accumulated into one `dR/dtheta` before squaring (so a shared
angle does not double-count and cancels correctly), but a *declared*
correlation whose pair touches an angle variable (angle-angle, or
component-angle, the cross terms `2 s_i s_j cov` of the joint
covariance) is not consulted. This is a first-order LPU shortcut and
collides with stable REQ-40 ("the correlation matrix is consulted by
every uncertainty propagation operation"). To avoid a silent drop,
`rotate` currently *raises* when a declared correlation involves a
frame angle rather than ignoring it.
**Proposed handling:** the numerical-analyst seat confirms the angle
independence model (and the raise as the fail-loud stance), or
specifies the joint angle-component covariance to propagate. Carry
with the OQ-18/OQ-24 uncertainty work (Q-004). Until resolved, the
independence assumption is stated in the REQ-101 reqbox and the
`rotate` docstring, and the raise stands.
**SRS:** REQ-101, REQ-40, REQ-98; OQ-23.

## OQ-27: Findings routed to the ledger are unauditable from a clone

**Raised:** 2026-07-27 (V and V pass on the management-root migration,
DD-31)
**Status:** open
**Question:** The working plan ledger left this repository on 2026-07-27
(DD-31), so every finding a review routes there is now unreachable from
a clone, and unreachable from CI. The `role-review` skill routes
findings to one of three homes: `docs/OPEN_QUESTIONS.md` and
`docs/M1_EXECUTION_PLAN.md`, both committed here, and the ledger, which
is not. Before the migration all three were at least present on the same
machine; now the third is behind an environment variable that a public
reader cannot satisfy. The migration commit itself cites two ledger ids
in `CLAUDE.md` and one in `docs/DECISIONS.md`, which a reader of those
files cannot open.

This is not the same as the incident ledger, whose detail was
deliberately placed outside the repository with a headline kept here.
That trade was made explicitly. This one was a side effect of moving the
plan ledger, and was not discussed when the move was decided.

**Proposed handling:** the product owner seat decides one of: accept it,
on the same reasoning as the incident ledger, and state the trade where
a reader meets a ledger id; or require that anything cited from a
committed file also exists in a committed home, so a ledger id never
appears in `docs/` or `CLAUDE.md` without a committed counterpart; or
bring the ledger back and solve its versioning another way. Related to
the registered question of whether the ledger was management content at
all.

**SRS:** none directly; process, DD-31, DD-23.

---

## OQ-28: How does the `.itceq` parser read TOML against a 3.10 floor?

**Raised:** 2026-07-23 (M1 review, finding D2; blocked phase B3b)
**Status:** resolved 2026-07-27 (none of the three options; the floor
rises)
**Question:** SRS Section 4.6 specifies `.itceq` as a TOML-structured
file and REQ-48 makes the parser the whole job of M1 phase B3b. Against
the 3.10 floor of REQ-83 there was no TOML reader in the standard
library, and the NumPy-only rule (REQ-82) bars a third-party one from
library code. Three options were put to the author: vendor a minimal
reader, hand-write a parser for the fixed grammar, or take `tomli` as a
conditional dependency with a REQ-82 and REQ-83 amendment.

**Resolution:** none of the three. The Python floor rises from 3.10 to
3.11, so `tomllib` is in the standard library and the parser reads TOML
with no dependency, no vendored code, and no format code of ours.
REQ-82 is untouched. REQ-83 is amended through the normal SRS process:
it is `\stable` and carries the language baseline, and the amendment
moved the CI matrix, the PyPI classifiers, and the `ruff` target
version with it. The registered fact that the floor was guarded only by
accident was closed at the same time:
`tests/test_python_floor.py` pins every restatement to the single
`requires-python` declaration, and refuses a floor below any
standard-library module the library imports.

**Why:** each of the three options answered the question by paying for
TOML somewhere else, and this one removes the problem instead of
relocating it. It also makes Section 4.6's claim that `.itceq` is TOML
true rather than approximate. The cost is users on 3.10; none were
identified, and the decision was taken with that gap visible. DD-32
carries the full reasoning, including why DD-28 and the JSON
`.itc_pipe` encoding are unaffected: `tomllib` reads and does not
write, so the reason a pipeline cannot be TOML never depended on the
floor.

**SRS:** REQ-48, REQ-83, Section 4.6; DD-32, DD-28, DD-17, OQ-04.

---

## OQ-29: `itc.pproc` is a function and `itaca.pproc` is a package

**Raised:** 2026-07-27 (M1 phase B3b implementation)
**Status:** resolved 2026-07-27 (the factory is renamed to
`itc.processor`; the package keeps its name)
**Question:** The SRS named both, and they collided on one attribute.
Chapter 5's top-level API surface gave `itc.pproc(name_or_path)` as the
processor factory, and Chapter 5's module tree gives `pproc/` as the
package holding it. Binding the factory at the package top level
shadows the subpackage attribute, so `itc.pproc(...)` called the
factory while `itc.pproc.parse_itceq` did not resolve and
`import itaca.pproc as pp` returned the function rather than the
module.

It cost nothing while everything the package exports was reached by
import. It would have started costing at REQ-49 to REQ-51, which are
written as `pproc.statistics(db, along="repeat")`,
`pproc.compare(reference=..., **named)`, and `pproc.report(db, ...)`.
Measuring the token across the SRS turned up a third sense: Chapter 9's
worked example opens `pproc = itc.pproc("ft_drag_polar", ...)`, so the
same name also served as the conventional variable for a processor
instance. REQ-51 depends on that instance reading, since
`pproc(db, report=path)` is given as equivalent to
`pproc.report(db, output=path)`, while REQ-49 depends on the namespace
reading. One token, three meanings, and no single one assignable by
implementation alone.

**Resolution:** the factory is renamed to `itc.processor`; the package
keeps `pproc`. The attribute `itc.pproc` is therefore the module again,
`itc.pproc.statistics(db)` will resolve when REQ-49 lands, and
`itc.processor` follows the constructor pattern the top-level API
surface already uses for `itc.datavis` and `itc.surrogate`. REQ-46 is
`\stable`, so the rename went through the SRS process; the Chapter 9
example variable was renamed with it.

**Why this rather than renaming the package:** measured across
`docs/srs/`, the token appears as an API name in 6 places, as a module
path in 13, and as a `pproc.<callable>` prefix in 16. Renaming the
factory touches only the 6 and makes the 16 correct as written.
Renaming the package would have cost the 13 plus the directory and
every import, and left the 16 to rewrite anyway. DD-34 carries the
reasoning and the rejected alternatives, including the callable
namespace object that would have satisfied both readings.

**Guard:** `tests/pproc/test_processor.py` pins that `itc.pproc` is the
module, that `itc.processor` is callable, and that `itaca.__all__` does
not export `pproc`, which is the one-line change that would reintroduce
the shadow.

**SRS:** Chapter 5 (top-level API surface, module tree, DD-04); REQ-46,
REQ-49, REQ-50, REQ-51; DD-34.

---

## OQ-30: `itc.surrogate` will collide with `itaca.surrogate` exactly as `pproc` did

**Raised:** 2026-07-27 (V and V pass on M1 phase B3b, while checking the
OQ-29 resolution)
**Status:** open
**Question:** OQ-29 was resolved by renaming the processor factory,
because binding a function at the package top level under its own
package's name shadows the subpackage attribute. The same shape is
already specified elsewhere and has not been built yet: Chapter 5 gives
`itc.surrogate(...)` in the top-level API table and `surrogate/` in the
module tree. Binding that factory will shadow `itaca.surrogate` on that
attribute, exactly as `itc.pproc` shadowed `itaca.pproc`.

The V and V pass found this while checking that the OQ-29 resolution
cited a sound precedent. It did not: both the resolution text and the
`itaca.pproc` module docstring justified `itc.processor` by the pattern
"already used for `itc.datavis` and `itc.surrogate`". `itc.datavis` is
sound, its package being `plot/`. `itc.surrogate` is the second instance
of the defect, not a precedent for avoiding it.

`surrogate/` is M3 (v0.4.0), so nothing is broken today. Registering it
now is the point: the choice is cheap before the package exists and
expensive after, which is the whole lesson of OQ-29.

**Proposed handling:** the API designer seat decides, before `surrogate/`
is created, whether to rename that factory as REQ-46's was, rename the
package, or accept the shadow with the consequences stated. Whichever
way, generalize the guard: `tests/pproc/test_processor.py` currently
asserts only that `itaca.__all__` omits the literal name `pproc`, which
blocks the first instance and nothing else. A guard asserting that no
member of `itaca.__all__` equals a subpackage directory name under
`itaca/` would have caught this class rather than this case, which is
what the incident rule asks of a guard.

**SRS:** Chapter 5 (top-level API surface, module tree); REQ-46; OQ-29,
DD-34.

---

## OQ-31: A `[constants]` name that the VarFrame also carries is silent

**Raised:** 2026-07-27 (V and V re-review of the DD-37 decision)
**Status:** resolved (DD-39, 2026-07-28)
**Question:** DD-37 refuses a name declared in `[constants]` that is
also an equation target, because a constant is substituted into every
read and the equation would run with its result unreachable. The
file-versus-frame form of the same collision is not refused and is not
reported: a file declaring `rho = 1.225` in `[constants]`, applied to a
frame carrying a measured `rho` channel, substitutes the declared number
into every read and ignores the measurement entirely. Nothing says so.
`_required` deliberately removes constants from `required_variables`,
so `validate` never inspects the overlap.

DD-37's stated reason for refusing the in-file case is that a name with
two definitions of different kinds has no obvious reading and the one
the parser picks is invisible in the file. That reasoning transfers
whole. The difference is only where the second definition lives, and the
parser cannot see the frame while `validate(db)` can.

This one is worse than the in-file case in one respect: a declared
constant silently overriding a measured channel is a wrong number
produced from correct-looking inputs, and the wind tunnel case that
makes it likely, a nominal `rho` or `S_ref` declared in the file while
the acquisition system also logs it, is the common one rather than the
exotic one.

**Proposed handling:** the author decides between warning in `validate`
and refusing there, with `force=` or an explicit `[constants]` override
marker as the escape. Whichever way, the check belongs in `validate`,
which is the REQ-45 lifecycle step that exists to answer "can this frame
feed this processor" before anything runs.

**Resolved:** 2026-07-28, by the author: **REFUSE**. A constant
colliding with a measured channel raises in `validate`, symmetric with
DD-37, which already refuses the in-file sibling. See DD-39 for the
reasoning, the scope (`db.vars` only, so a dimension name is
unaffected), and the accepted cost: anyone deliberately using a constant
to override a bad channel loses that path, and the replacement is to
correct the channel in the frame.

**SRS:** REQ-45, REQ-46, REQ-48, Section 4.6; DD-37.

---

## OQ-32: `auto_sort` is not in the file, while idempotence now is

**Raised:** 2026-07-27 (V and V re-review of the DD-36 decision)
**Status:** open
**Question:** DD-36 moved idempotence into `[meta]` on REQ-48's promise
that an `.itceq` file fully defines a reproducible workflow. The same
argument applies verbatim to `auto_sort`, which remains a caller
argument only, and which changes results in two ways: it reorders
evaluation, and it makes a file run that file order would refuse as a
forward reference. So after DD-36 the "fully defines" claim is more true
on one axis and unchanged on the axis that changes numbers.

`spec.sorted` and the `info()` line mitigate by disclosure, not by
definition: the same file still computes different things depending on
how it was opened.

This is registered here rather than left where it was first written.
DD-36 parked it in its own rejected-alternative paragraph ("revisit if
`auto_sort` or other per-file options follow it"), and the decision log
is frozen and append-only, so nothing would ever revisit it there. An
open question is the surface that gets read again.

**Proposed handling:** the author decides whether the evaluation-order
choice belongs in the file, which is the DD-36 argument applied
consistently, and if so whether both flags move into a typed `[options]`
section, which was DD-36's rejected alternative and becomes the better
shape once there are two of them. Revisit at v0.2.1, with the built-in
processors as the first real files.

**SRS:** REQ-46, REQ-48, Section 4.6; DD-17, DD-36.

---

## OQ-33: Units have no home in the `.itceq` format

**Raised:** 2026-07-27 (API-designer pass on M1 phase B3b)
**Status:** deferred (revisit when the built-in processors are written,
v0.2.1)
**Question:** `[constants]` and `[uncertainties]` carry units only in
`#` comments, which `tomllib` discards. So `info()` can never print
them, a `config=` override is a bare number with no unit anywhere in the
object, and the SRS sample's own annotations (`# m^2, reference wing
area`, `# N, balance calibration`) are illustration rather than data.
`itc.units` exists in `utils/` and the file format sits outside it.

**Deferral, by the author, 2026-07-27:** decide when `WT_propeller` and
`WT_balance_off` are written, with real files in hand. The format has no
external user yet, and the right shape depends on how many quantities
actually need a unit, which the builtins will show rather than argue.
The candidate form, recorded so the deferral is not a blank: a value may
be written either as a bare number or as
`{ value = 0.1963, unit = "m^2" }`, with the bare form remaining valid.

**Proposed handling on revisit:** the author decides between that
optional form, a statement in Section 4.6 that absolute values are in
the unit of the variable they name and constants are pure numbers whose
unit is the author's responsibility, and leaving it as is.

**SRS:** Section 4.6; REQ-46, REQ-48, REQ-99.

---

## OQ-34: Joint covariance across vector groups in rotation propagation

**Raised:** 2026-07-28 (ITACA-025 fix, REV-001)
**Status:** open
**Question:** `rotate` now transforms the covariance WITHIN a vector
group and writes the recomputed coefficients back to the pair store. It
does not transform a pair that joins a rotated component to anything
outside its group: a force-to-moment pair when only the force group is
rotated, a group-to-scalar pair such as `rho(FX, q_inf)`, or a pair
between two groups rotated by different composite matrices. Such a pair
would be left holding its pre-rotation coefficient, which is exactly the
ITACA-025 defect in a different place, so it is refused rather than
silently kept or silently dropped.

The correct treatment is known and is not hard; what is missing is the
decision to widen the propagation scope and the storage that would carry
it. For a linear transform `R` applied to group `F` while `X` is
untouched, `cov(F'_k, X) = sum_j R_kj cov(F_j, X)`; for two groups
transformed by `R` and `R2`, `cov(F'_k, M'_l) = sum_jm R_kj R2_lm
cov(F_j, M_m)`. A shared uncertain frame angle additionally induces
`sum_a (dR/dtheta_a v_F)_k (dR2/dtheta_a v_M)_l u_a^2`, which the
within-group angle term already computes for the diagonal block.

**Proposed handling:** the author decides between widening rotation
propagation to the full joint covariance over every declared pair, and
keeping the interim fail-loud stance. The interim stance is what ships:
the refusal names the pair and says to drop and redeclare it in the
target axis.

**SRS:** REQ-38, REQ-40, REQ-101; OQ-23, OQ-26.

---

## OQ-35: The degeneracy and drop constants in the rotation write-back

**Raised:** 2026-07-28 (ITACA-025 fix, REV-001)
**Status:** open (numerical-analyst seat)
**Question:** Recomputing a correlation coefficient from the transformed
covariance divides by the transformed standard deviations, so a
component whose transformed variance is zero has no defined coefficient.
The PRIMARY mask is exact and needs no constant: measured through the
real code path, a rank-deficient rotation gives a transformed variance
of EXACTLY 0.0 and a 0/0 quotient, so `sd == 0` or a non-finite quotient
is what fires. Two engineering constants sit beside it and neither is
frozen:

- `_VAR_FLOOR`, a relative floor below which a transformed variance is
  treated as degenerate rather than as a real quantity. Round-off dust
  in genuinely rank-deficient rotations was measured up to 1.3e-16
  relative, so the floor must sit above that and far below any real
  variance ratio.
- `_RHO_FLOOR`, below which a recomputed coefficient is dropped rather
  than stored as numerical noise.

The clip to `[-1, 1]` is NOT one of these: it is mandatory, not
cosmetic. An unclipped write-back was measured at -1.0000000000001619
for a declared coefficient of +1 at 34 degrees, and at 1.0000005175008824
over random rank-one draws, which `CorrelationMatrix` rejects.

**Proposed handling:** the numerical-analyst seat sets both constants
with measured evidence, or replaces the relative floor with a condition
number test on the transformed covariance.

**SRS:** REQ-40, REQ-41, REQ-101.

---

## OQ-36: A declared correlation on a frame carrying no uncertainty

**Raised:** 2026-07-28 (ITACA-025 fix, REV-001)
**Status:** open
**Question:** `set_correlation` is accepted on a frame that carries no
uncertainty at all, and that state is how several ITACA-025 instances
were reachable through the public API: `diff`, `fitmodel` and `fitvalue`
all refuse uncertainty (REQ-98, OQ-18, OQ-24) while a correlation may
still be declared beside them.

It also leaves `rotate` with a case it cannot resolve. When a group
carries no uncertainty, the rotation computes no covariance, so there is
nothing to recompute a coefficient from. The declared pair is therefore
left EXACTLY as declared, even though it describes the pre-rotation
components. Deleting it would be worse (an operation that computed
nothing would silently discard a user declaration), and inventing one is
not possible, so the stale-but-untouched state ships.

The cleaner question underneath: should a correlation without any
uncertainty be a legal frame state at all? A correlation coefficient
between two exact quantities has no operational meaning, and refusing it
at declaration time would close this case and simplify three others.

**Proposed handling:** the author decides between refusing
`set_correlation` on a frame with no `UncFrame`, keeping it legal and
documenting the rotate carve-out, and keeping it legal while making
`rotate` refuse rather than carry.

**SRS:** REQ-39, REQ-40, REQ-98, REQ-101.

---

## OQ-37: Which NumPy keyword arguments should the expression language accept?

**Raised:** 2026-07-28 (ITACA-023 fix, REV-001)
**Status:** open (deferred; the refusal ships)
**Question:** `np.round(x, decimals=2)` parsed, ran WITHOUT the keyword,
and History recorded the expression WITH it, so the record showed an
intent the execution did not honor. Keywords are now refused at the
single call funnel, which closes the provenance hole and cannot produce
a wrong number, but it permanently narrows the language until someone
builds the supported subset.

The author chose refusal over implementation because the admission gate
is the whole NumPy namespace rather than an allowlist: 479 public
callables, only 293 with introspectable signatures, and `out=`, `axis=`,
`keepdims=`, `where=`, `dtype=`, `casting=` and `order=` each break an
ITACA invariant (in-place writes, rank changes, dtype changes, or a
second masking mechanism beside `where=` on `compute` itself).

A defensible subset is value-only, shape-preserving keywords on a
curated function list: `decimals=` on `np.round`, `a_min=` and `a_max=`
on `np.clip`. That subset needs an integer-preserving literal node,
because `Const` coerces every numeric literal to float and
`np.round(x, decimals=2.0)` is not the same call. Changing the literal
node changes History operation strings and therefore state hashes
(REQ-103), so this is a milestone item with a migration note, not a
follow-up patch.

**Proposed handling:** the author decides the curated list when a real
`.itceq` file or example needs one, with the state-hash migration
planned in the same window.

**SRS:** REQ-33, REQ-36, REQ-44, REQ-103.

---

## OQ-38: Should `Provenance.mode` be part of the state hash?

**Raised:** 2026-07-28 (DD-40 review, REV-001 ITACA-003)
**Status:** open
**Question:** `mode` is read and acted on: it decides whether an
operation is recorded in History at all, `concat` refuses mixed modes,
and the draft-export guard turns on it. It is not volatile, and the
`.itc` archive persists and reconstructs it. On the "reads and acts on"
test that DD-40 uses for metadata, it belongs in the hash.

It is excluded today only because the WHOLE `Provenance` record is
excluded, and REQ-103's exclusion list names volatile fields
specifically (timestamps, user identity, source paths, version) rather
than the record.

Note the narrow shape of the gap: `promote` and `demote` already enter
the hash through the operation string, so the only unhashed case is the
mode a frame was BORN in, and that is exactly the mode that decides
whether a History exists to be hashed.

**Deferred by the author, 2026-07-28:** not folded into DD-40, because
including it widens the requirement into `Provenance`, a different
boundary from the one that decision ruled on. Revisit as its own
revision.

**SRS:** REQ-08 to REQ-12, REQ-103; DD-40.

---

## OQ-39: `VarFrame.coords` is carried, read by nothing, and persisted by nothing

**Raised:** 2026-07-28 (DD-40 review, REV-001 ITACA-003)
**Status:** open
**Question:** The `coords` field is propagated everywhere: `_derive`
carries it through `dataclasses.replace` and `pivot` carries it
explicitly. But no operation reads it (`integrate` takes its own
`coords=` argument and never `db.coords`), and neither `save` nor
`itc.open` writes or reconstructs it, so a coordinate-system tag set on
a frame is silently LOST on save and reopen.

That is a defect in its own right, and it is why the field was not
added to the state hash while DD-40 was widening the scope: hashing a
field nothing reads would be wrong, and it would paper over the
persistence gap rather than fixing it.

**Proposed handling:** the author decides between persisting `coords`
in the `.itc` format and hashing it, giving it a reader, and removing
the field. Whichever way, the silent loss on round trip is the part
that must not survive.

**SRS:** REQ-28, REQ-70, REQ-103.

## OQ-40: A NaN in an UncFrame means both "missing" and "invalid"

**Raised:** 2026-07-29 (CHK-1 remediation, REV-003 R3-ITA-007)
**Status:** open
**Question:** `set_uncertainty` now refuses a non-finite DECLARED
magnitude, which closes the reported instance. It does not close the
defect: `_resolve_value` computes a relative spec as
`fraction * abs(values)`, so a perfectly valid `"5%"` against a variable
carrying NaN still writes a NaN standard uncertainty, and the `.itc`
reopen path and propagation results bypass the scalar check entirely.

The structural home for the rule is `UncFrame._normalize`, beside the
negativity check and on the assembled array. That was implemented and
reverted, and the measurement is the reason: it fails
`tests/ops/test_compute.py::TestWhereFill::test_uncertainty_only_for_filtered_in`
and both `tests/ops/test_fill.py::TestFillUncertainty` cases, because
`compute(where=, fill=)` and `fill` write NaN deliberately into the
uncertainty array for cells the operation did not touch.

So one array carries two meanings of NaN: "this cell has no propagated
uncertainty" and "this uncertainty is not a number". A finiteness rule
cannot be added until they are distinguishable.

**Proposed handling:** the numerical analyst seat decides. Options as
they stand: carry an explicit mask beside the components so missing is
representable without NaN; keep NaN as missing and validate only at the
declaration boundary, stating the rule in REQ-39; or forbid NaN in the
array and give the untouched-cell case a zero with a tag.

**Narrowed, 2026-07-30 (FND-040, lane ITA-2G). WITHDRAWN THE SAME DAY;
read the block after it.** The relative-spec half
is closed and this question is NOT what closed it. `_resolve_value` now
refuses when a relative magnitude resolves to a non-finite array, which
is a rule on a DECLARATION boundary: what it sees is what a declaration
just produced, and NaN has one meaning there. That is the second option
above applied to the declaration boundary only, and it was taken because
it needs no answer to the question below; REQ-39 is not amended, because
what changed is a refusal the requirement's own "standard uncertainty"
already implies rather than a new rule about the values.

What remains open is exactly the assembled-array half, unchanged: the
UncFrame carries NaN both for "this cell has no propagated uncertainty"
and for "this uncertainty is not a number", and the reverted rule stays
reverted until they are distinguishable. The `.itc` reopen path and
propagation results still bypass every declaration check, which is the
same hole this entry named at the start.

**A second attempt, and a second revert, 2026-07-30 (FND-040, lane
ITA-2G).** The paragraph above is left standing and superseded rather
than deleted, because this file is append-only and the rule does not
carve out a paragraph written the same day in the same unpushed lane.
Its last sentence is right and its first two are wrong; here is what
actually happened.

The lane put a finiteness rule in `_resolve_value`, on the
RESOLVED array rather than on the assembled one, reasoning that a
declaration boundary sees only what a declaration just produced and so
needs no answer to the question above. It worked: measured 5 failing
tests before and the whole suite green after, and none of the tests that
blocked the first attempt go through that path.

It was reverted anyway, by the V and V and architect passes, and the
reason is worth more than the fix. REQ-39 is STABLE and states this
exact limit in its own normative text: "The rule is scoped to the
DECLARED magnitude, and that limit is stated rather than implied. A
relative specification resolves against the data, so a valid `5%`
against a variable carrying NaN still yields a non-finite standard
uncertainty. The structural home of the check is the UncFrame ...
blocked on OQ-40." A check anywhere changes the behavior that paragraph
describes, so the SRS moves first or nothing moves. The lane's own note
here claimed "REQ-39 is not amended, because what changed is a refusal
the requirement's own 'standard uncertainty' already implies", and that
was false. It stands above with a withdrawal marker rather than being
deleted, because a wrong reason left unmarked is what the third attempt
would read, and a deleted one is not a record.

**So the question now has an order attached to it,** and that is the
part a later session needs. Two attempts have been reverted for two
different reasons: the first for breaking the tests that write NaN
deliberately, the second for outrunning the requirement. Whatever the
seat decides, REQ-39's scoping paragraph is amended in the same change,
with the document version, the revision history and Chapter 11. The
three options are laid out in the plan ledger as `ITC-20260730-2249`.

What remains open is unchanged in substance: the UncFrame carries NaN
both for "this cell has no propagated uncertainty" and for "this
uncertainty is not a number", and the `.itc` reopen path and propagation
results bypass every declaration check.

**SRS:** REQ-39, REQ-98, REQ-99.

## OQ-41: Three refusals prescribe a rename, and there is no rename operation

**Raised:** 2026-07-29 (CHK-1 remediation, API designer pass)
**Status:** open
**Question:** The CHK1-001 and R3-ITA-008 refusals both tell the user to
rename a variable. No `rename` exists anywhere in the package, and
`itc.load` has no rename or column-mapping parameter, so the third part
of the three-part message names a capability the library does not have.

The motivating case is the one the fix was built for: a wind-tunnel CSV
carrying an Oswald efficiency column `e` loads, is visible in
`db.vars["e"]`, and every expression reading it is now refused. The
available exits are all outside the library or outside provenance: edit
the source file, which changes `source_hash` and the archived campaign
file; go through pandas and reload, which drops `source_files`; or
`dataclasses.replace` through a private path, which `set_metadata`'s own
docstring condemns by name. For a CSV, folder or dict source there is no
`names=` to correct at all.

**Proposed handling:** the author decides, since this is a public
surface addition and a domain vocabulary call. Options: a recorded
`db.rename({old: new})` that rewrites dims, vars, uncertainty keys,
correlation pairs, tags and vector groups together, which is also the
missing symmetric partner of `set_metadata`; an `itc.load(..., rename=)`
for file sources only; or keeping the refusals and naming only routes
that exist, with their provenance cost stated. The messages currently
take the third option.

**SRS:** REQ-01, REQ-44, REQ-101.

Correction appended 2026-07-29 (ITC-20260729-1450, architect and API
designer passes): the SRS line above should read REQ-01, REQ-44, REQ-45.
REQ-101 is condition-dependent axes and has nothing to do with a rename;
REQ-45 is the requirement carrying the third of the three refusal sites
the heading counts, through `Processor.validate`. Appended rather than
edited, per the append-only rule.

## OQ-42: Does the interpolation polynomial weight matrix apply to fill's polyfit path?

**Raised:** 2026-07-29 (ITC-20260729-1450, V&V, architect and API
designer passes, independently)
**Status:** open
**Question:** `fill(method="polyfit")` refuses when uncertainty is
present and WAS carried as a provisional row of REQ-98 pending OQ-18,
which is the state at the moment of raising; REQ-98 now points that row
here instead, and this file is append-only so the tense records it. Two
reviewer passes established that OQ-18 as written cannot lift it: OQ-18
asks whether the systematic component should track sign changes of
`smooth` and `diff` KERNEL weights, and the fill polyfit refusal is not
a question about the sign of a weight. It is that the fill path emits no
weights at all.

That framing was itself challenged, correctly. `polyfit_matrix(x,
targets, deg) = vander_t @ pinv(vander)` in `ops/_interp_kernels.py` is
the exact least-squares polynomial weight matrix, and
`db.interpolate(method="polyfit", deg=...)` reaches it and propagates
both components through it with no uncertainty guard. So a polynomial
weight rule is not hypothetical in this library; it ships, and REQ-98's
table declares it exact. On the `global_fit=True` path it is the same
rule, over the whole VALID set rather than the whole grid: `_fill_line`
sets its support to the non-NaN indices, so even the global path selects
by the missingness pattern. That is a smaller difference from
interpolation than the moving window's, and it is not zero.

**Why it is not simply an implementation gap.** The moving-window path
differs from interpolation in a way that is not cosmetic: fill chooses
the support set PER GAP from the cells that are not NaN, so the weight
matrix depends on the missingness pattern rather than on the grid alone.
Interpolation never faces that. Whether the same matrix is admissible
there, and what it means for the systematic component when the support
changes between neighboring gaps, is the substance of the question.

**Proposed handling:** the numerical-analyst seat decides, and this is
her call rather than an implementer's, because the answer changes what
the library GUARANTEES and not only what it computes. Options: adopt
`polyfit_matrix` over the chosen support and remove
`fill(method="polyfit")` from the provisional family, returning REQ-98's
count to four; adopt it for `global_fit=True` only, where the support is
the whole valid set, and keep the moving-window path refusing; or keep
both refusing until OQ-18 settles the sign question, on the ground that
the two share the mixed-sign systematic behavior already carried as a
validation item.

**Measured, and reproducible rather than recollected:** the polyfit fill
is linear in the variable values to within floating-point round-off, so
linearity is not the obstacle and an exact weight rule does exist to be
adopted. Pinned by `tests/ops/test_fill.py::TestPolyfitLinearity`, which
checks `fill(a) + fill(b) == fill(a + b)` over 50 random cases on each
path: worst relative departure 5.8e-14 for the moving window and 5.8e-15
for `global_fit`, measured 2026-07-29. An earlier figure of 1.3e-13 was
carried in prose with no case attached; it is the same order, and the
test is what should be re-run rather than either number trusted.

**Why option 3 names OQ-18 after this entry argues OQ-18 cannot reach
here:** answering and gating are different. OQ-18 as written cannot
ANSWER the fill question, which is why this entry exists. Option 3 is a
choice to GATE the fill decision behind OQ-18 anyway, on the ground that
both share the mixed-sign systematic behavior and deciding them apart
risks two incompatible rules. That is a sequencing preference, not a
claim that OQ-18 covers this case.

**SRS:** REQ-26, REQ-98.

---

## OQ-43: Does a correction propagate over a declared uncertainty on its own target?

**Raised:** 2026-07-30 (lane ITA-2C, while fixing R4-ITA-003 /
`ITC-20260730-0105`; found by a probe of my own, not by the finding)
**Status:** open
**Question:** an `.itceq` declares `[uncertainties] CL = 0.01`, produces
`CL` with an `[equations]` line, and then rewrites it with a
`[corrections]` line. The declared uncertainty is assigned once the
equation has written `CL`, and the correction then recomputes `CL` and
PROPAGATES over it, so the frame ships an uncertainty the file did not
declare. Which of the two the file means is a domain question, not an
implementation choice.

**Measured, 2026-07-30, at the fixed tree.** With
`[uncertainties] x = 1.0, CL = 0.01`, `[equations] CL = "2*x"` and
`[corrections] CL = "CL * 2"`, the frame ships `u(CL) = 0.02`. The same
file with a correction that adds a constant, `CL = "CL - 1"`, ships
`u(CL) = 0.01`, because that propagation happens to be an identity. So the
answer today depends on the ALGEBRA of the correction, which is the part
worth deciding deliberately.

**Why this is not R4-ITA-003 and was deliberately left alone.** That defect
was that the declaration was sorted by whether the incoming VarFrame
already carried the name, so one file gave two answers and in the worse
branch shipped a different number. Its fix classifies by what the file
produces. This case is unchanged by that fix, gives the same answer whether
or not the frame carried `CL`, and is reachable only through a file that
both declares and corrects the same name. Changing it under cover of the
defect fix would have been a new rule invented at the point of a wrong
answer, which is the thing this repository refuses.

**The two readings, and the cost of each.** Reading A, today's behavior: a
declaration attaches to the output of the EQUATION that produces the name,
and a correction is an operation like any other, so it propagates. This is
consistent with `[corrections]` being ordinary computation and with the
principle that every operation declares its uncertainty effect (REQ-98).
Its cost is that a file's `[uncertainties]` section does not describe what
the file SHIPS, which is what a reader will assume it does. Reading B: a
declaration is what the file asserts about the name at the end, so it is
assigned after the LAST line that writes it. Its cost is that a later
correction reading the same name would then propagate from a value that is
about to be overridden, which is the inconsistency the mid-loop assignment
exists to prevent (REQ-41, REQ-99), so B needs a rule for that case rather
than only a move.

**Who decides:** the numerical analyst and the domain expert, both
non-delegable seats. A third option exists and is theirs too: refuse the
file at parse time when a name is both declared in `[uncertainties]` and
rewritten by a `[corrections]` line, on the ground that it is ambiguous and
the author should say which she means. That is symmetric with DD-37 and
DD-39, which already refuse two other collisions rather than choosing a
winner silently.

**SRS:** Section 4.6 (`[uncertainties]` application moment, stated at
document 0.2.4), REQ-41, REQ-99.

---

## OQ-44: What does a relative declaration resolve against when it is applied twice?

**Raised:** 2026-07-30 (lane ITA-2C, round-2 V&V pass on the R4-ITA-003
fix)
**Status:** open
**Question:** an `[uncertainties]` value may be a relative spec such as
`"10%"`, resolved against the variable's own values at the moment it is
assigned. Under the rule stated at SRS document 0.2.5, a name the frame
CARRIES and the file also WRITES is assigned twice, so a relative spec
resolves twice, against two different sets of values. One declaration then
produces two numbers, and lines evaluated between the two assignments
propagate from the first.

**Measured, 2026-07-30, at the fixed tree.** File:

```
[uncertainties] CL = "10%"
[equations]     CD = "CL * 2"
[corrections]   CL = "CL + 90"
```

against a frame carrying `CL = [10, 10]`:

```
CL  value [100, 100]   u(CL) = [10.0, 10.0]   ten percent of the CORRECTED value
CD  value [20, 20]     u(CD) = [2.0, 2.0]     two times ten percent of the INPUT
```

Both numbers are defensible in isolation and the pair is not: the shipped
frame reports `u(CL) = 10` beside `CD = CL * 2` in History, where 20 would
follow from the reported value. A reader reconciling the two cannot.

**Why an absolute declaration does not have this problem.** `5.0` is `5.0`
at both moments, so the second assignment is idempotent and the question
does not arise. The ambiguity is created entirely by resolution against
data that the file itself changes in between. A non-scaling correction is
what exposes it; with `CL = "CL * 1.02"` the two resolutions coincide
numerically and nothing looks wrong.

**Not OQ-43.** That question is about a name written MORE than once, where
the second write propagates over the declaration. Here `CL` is written
once. This is the carried-and-written overlap, which is the case the
two-question rule introduced deliberately.

**The readings, and what each costs.** (A) Resolve once, at the first
assignment, and reuse the resolved absolute value at the second: the two
numbers agree, and `u(CL)` is then ten percent of a value `CL` no longer
has. (B) Resolve at each assignment, which is today's behavior: each number
is ten percent of the value it is attached to at that moment, and the pair
is inconsistent. (C) Refuse a relative declaration on a name that is both
carried and written, symmetric with DD-37 and DD-39, which already refuse
two other collisions rather than choosing a winner silently.

**Who decides:** the numerical analyst, with the domain expert. The choice
is about what a percentage in an `.itceq` file MEANS, which is not an
implementation detail.

**SRS:** Section 4.6 (the application moment, document 0.2.5), REQ-39,
REQ-99.

---

## OQ-45: Should a declared uncertainty override the random component too?

**Raised:** 2026-07-30 (lane ITA-2C, round-2 QA and V&V passes,
independently)
**Status:** open
**Question:** an `.itceq` `[uncertainties]` entry is assigned as the
SYSTEMATIC component, which is what `set_uncertainty` defaults to and what
SRS Chapter 8 describes. A frame arriving with a RANDOM component for the
same variable therefore keeps it, and it propagates into everything derived
from that variable. So the sentence "no uncertainty the frame arrived with
is ever read for a name the file declares" is true of one component and
false of the other.

**Measured, 2026-07-30, at the fixed tree.** File declaring
`CL = 0.01`, with `[equations] CD = "CL * 2"` and
`[corrections] CL = "CL * 1.02"`, against a frame carrying
`u_random(CL) = 99.0`:

```
u_systematic  CL = 0.01     CD = 0.02      the declaration, and its propagation
u_random      CL = 100.98   CD = 198.0     the frame's own value, propagated
```

The 198.0 is the same shape of number this lane closed on the systematic
side: finite, plausible, and selected by what the caller's frame happened to
carry rather than by anything the file says.

**Three readings.** (A) Today's: a declaration is a systematic-component
statement and the random component is the caller's, untouched. Defensible,
and consistent with REQ-99's separation, but it means a file cannot fully
specify the uncertainty of a variable it declares. (B) A declaration
overrides both components, zeroing the random one unless the file says
otherwise. Simple, and destroys information the caller may have measured.
(C) The section gains an explicit component, so
`CL = { systematic = 0.01, random = 0.002 }` or similar, and a bare value
keeps meaning (A). Most expressive, and a file-format change.

**Why it is registered rather than decided.** Which components an
`.itceq` file may speak for is a measurement-semantics question, not an
implementation one, and (B) discards data. Today's behavior is pinned by
`tests/pproc/test_processor.py::test_a_declaration_does_not_touch_the_random_component`
so the direction cannot change unannounced; that test pins the answer, it
does not argue for it.

**Who decides:** the numerical analyst and the domain expert.

**SRS:** Section 4.6 (document 0.2.5), REQ-39, REQ-99, Chapter 8.

---

## OQ-46: Should a declared uncertainty be withdrawable?

**Raised:** 2026-07-30 (lane ITA-2C, v0.2.0 release review, API-designer
pass)
**Status:** open
**Question:** `db.set_uncertainty` has no inverse. Once a VarFrame carries
an UncFrame the only way back is to re-run from `itc.load`. The release
notes for v0.2.0 state that limitation and say the question "is registered
and belongs to the author"; it was not registered anywhere, which is what
this entry corrects.

**Why it is not cosmetic.** Five operations in v0.2.0 refuse to propagate
uncertainty and their suggested fix is "run this before assigning
uncertainty". Applying a processor assigns its `[uncertainties]` section
itself, so `proc(db).smooth(...)` refuses even though the caller never
called `set_uncertainty`, and the advice becomes unfollowable: there is no
verb that gets back to a frame without one.

**The asymmetry that makes it a design question rather than a gap.** This
release introduced two withdrawal idioms and they disagree, so whichever is
chosen here settles which one the library means:

| verb | how it is undone | shipped |
|---|---|---|
| `set_metadata` | pass `None` as the field value | new in 0.2.0 |
| `set_correlation` | a separate `drop_correlation` method | new in 0.2.0 |
| `set_uncertainty` | nothing | 0.1.0, no inverse |

**The options.** (A) `db.drop_uncertainty(names=None, *, component=None)`,
symmetric with `drop_correlation`, recorded in History and replayable. Adds
a public name; makes the `drop_*` idiom the library's answer. (B) Extend
`set_uncertainty` to accept `None` per name, matching `set_metadata`. No new
public name, and it makes `drop_correlation` the odd one out. (C) Ship as
is: re-running from `itc.load` is the only way back, and that is a
deliberate position because an uncertainty silently removable is a
provenance hazard.

**Note what (C) costs, since it is the current state and therefore the
default.** REQ-18 says every operation records itself, so a withdrawal that
IS recorded is not a provenance hazard; the hazard would be an unrecorded
one. That weakens (C) considerably, which is why this is worth deciding
rather than leaving.

**Who decides:** the product owner, with the numerical analyst on whether a
partial withdrawal (one component, or one variable) is meaningful at all.

**SRS:** REQ-39, REQ-40, REQ-98, REQ-18.

---

## OQ-47: Should the shipped artifact be built on an interpreter CI exercises?

**Raised:** 2026-07-30 (lane ITA-10, kit 0.2.14 adoption; architect,
V&V and API-designer passes independently)
**Status:** open
**Question:** `release.yml`'s `release` gate call builds the artifact that
ships on Python 3.12. Neither `ci.yml`'s matrix nor `release.yml`'s
`breadth` matrix contains 3.12: both run 3.11 latest, 3.11 minimum, and
3.13 latest. So 3.12 is the one supported interpreter that no push to
`main` ever exercises, and a 3.12-only regression surfaces first at tag
time, which is the most expensive moment to find one.

**Why it is a question and not a defect.** The shipped build is not
untested: the `release` call runs the full gate set (lint, types, tests
with the 90 percent floor, the identity check, the build and the smoke of
that build) on 3.12 at tag time. `pyproject.toml` advertises 3.12 as
supported, so building on it is legitimate. And rule 5 of
`check_release_gate.py` permits the tag path being a superset of CI, so
nothing refuses the arrangement. What is open is whether the arrangement
is the one wanted.

**Why it surfaced now.** FND-070's stated direction was that the tag path
ran ONE interpreter that CI's matrix did not contain, and the kit 0.2.14
adoption closed it: `breadth` now reproduces CI's matrix entry for entry.
Its mirror stayed open and is invisible to the checker by design, since
rule 5 skips a gate call carrying no matrix. BRF-068 explicitly left the
interpreter choice to this repository ("Whether `python-version: 3.12`
remains the interpreter of the shipped build ... is a library decision"),
so the adoption preserved the existing value rather than moving it.

**The three answers, and the cost of each.**

| answer | cost |
|---|---|
| Add 3.12 to `ci.yml` and to `breadth` | a fourth leg on every push and every tag, and rule 5 keeps the two in step |
| Build the shipped artifact on a leg CI already runs | no new CI minutes; changes which interpreter produces the wheel |
| Keep 3.12 and record why | free, and the residual stays, so `release.yml` should then say a pure-Python wheel is insensitive to its build interpreter |

The third is defensible for a pure-Python wheel and is the cheapest, but
it is an argument nobody has written down yet, and writing it down is what
would make it a decision rather than an omission.

**Who decides:** the product owner, on which interpreters this library
promises; the answer is not delegable to a lane.

**SRS:** REQ-83, REQ-95.

---

## OQ-48: Should the auto_sort report stay on stdout?

**Raised:** 2026-07-30, lane ITA-9, while closing
`ITC-20260723-2042-io-pivot-prints-to-stdout-from-library-code`.
**Status:** open.

`db.pivot(auto_detect=True)` printed the dimension list it resolved on
every call. Nothing chartered that: REQ-14 specifies the detection and
says nothing about announcing it, and the test that pinned the print cited
REQ-76, which is the required-edge-case list and only requires the case to
be tested. It was fixed in the same commit: the message now goes to the
module logger at INFO, the convention `core/provenance.py` and
`io/loader.py` already use.

The structural walk that closed it found one other print in a computation
path, and that one is different, which is why it is a question rather than
a second fix.

**The question.** `parse_itceq(..., auto_sort=True)` prints the resolved
equation order, and it is chartered twice. **REQ-48 is the normative
carrier and it is stable**: "passing `auto_sort=True` to the parser
enables topological sorting by dependency, in which case the parser
reports the resolved order to the user as feedback." **DD-17 records the
decision** in the same words and adds the rationale, that "the feedback
makes the resolved order auditable". So the report is decided behavior,
not an oversight, and it is decided at the level of the specification
rather than only in the decision log. Neither names a destination.

But P-08 grants terminal output to "inspection, summary, and diagnostic
methods", and a parser is none of those. A library that writes to stdout
from a data path corrupts the output of any program using it as a
component, and no argument the caller passes can stop it.

**Why the obvious fix is not obviously right.** Moving it to
`logger.info` would satisfy P-08, and it is what the pivot half does. It
would also make DD-17's feedback invisible: with no logging configured,
Python's last-resort handler emits at WARNING, so an INFO record reaches
nobody. That silently retires a decided behavior, which is the reason this
lane did not do it.

**The four answers, and the cost of each.**

| answer | cost |
|---|---|
| Keep the print, supersede nothing | a library data path keeps writing to stdout, and the guard in `tests/test_stdout_discipline.py` carries a standing exemption |
| Move to `logger.info` and supersede DD-17 | P-08 satisfied; DD-17's auditability claim is retired unless something replaces it |
| Move to `logger.info` AND expose the order on the returned object | the order is already on `spec.equations`, so this is mostly writing down that the return value IS the audit trail; costs one docstring and a superseding DD |
| Report through `warnings.warn` | visible by default, and the codebase already uses `warnings` for the caller's attention; but the resolved order is not a warning, and a filter would suppress it |

The third is the only one that keeps both authorities: `spec.equations`
carries the resolved order and `spec.sorted` says the sort ran, so the
feedback is auditable programmatically rather than by reading a terminal.
That is an argument, not a decision.

**What any answer other than the first costs.** REQ-48 is stable, so
retiring the report is an SRS change: the requirement text, the revision
history and Chapter 11 move together, and a superseding DD alone is not
enough. That is the correction that matters most here, because the first
draft of this entry said a new DD would suffice, having found only DD-17.
DD-17 is frozen and append-only either way, so it is superseded rather
than edited.

**Who decides:** the product owner, on whether a library surface may write
to stdout at all and on what replaces the auditability REQ-48 and DD-17
promise if it may not.

**SRS:** P-08, REQ-14, REQ-48, REQ-76. **DD:** DD-17.

---

## OQ-49: What does an infinity mean to a reduction and to a coverage count?

**Raised:** 2026-07-30, lane ITA-2G, while closing FND-045 and FND-083
(BRF-059).
**Status:** open (numerical-analyst seat).

Two independent findings, one question under both. Neither is answered
here, because both fixes closed a violation of what the code and the SRS
already SAY, and neither needed the answer.

**What was measured.** `average()` used `np.isfinite` as its presence
mask, so the mean of `[1.0, +inf]` was `[1.]`: a finite mean over a set
containing an infinity, reported with nothing said. `db.diagnostics()`
counted an infinity into `non_finite` and then said nothing about it, so
an all-infinity variable reported `coverage = 1.0` and an EMPTY
`warnings` tuple, where the all-NaN control reported `coverage = 0.0`
and two warnings.

**What the fixes did, and deliberately did not do.** `average` now masks
on `~np.isnan`, because REQ-27 is stable and says "arithmetic mean of
non-NaN values", so the code was contradicting its own requirement.
`diagnostics` now warns when a variable carries non-finite values,
because REQ-17 exists to carry data-quality warnings and silence about a
variable with no usable value is not one. Neither fix decides the
question below.

**The question, in two faces.**

*In a reduction.* An infinity now enters the mean and the result is
infinite. That is REQ-27 read literally and it is arguably the honest
answer: the data says infinity, so the mean says infinity. The
alternative is that a reduction should REFUSE non-finite data the way
`set_uncertainty` refuses a non-finite magnitude, on the ground that an
infinity in measured aerodynamic data is a defect of acquisition rather
than a value. That would be an SRS change to REQ-27 and it would apply
to `integrate` and `smooth` alike, not to `average` alone.

*And in the UNCERTAINTY of that reduction,* which is the sharper half
and was missing from the first draft of this entry. One mask feeds the
value, the populated count and the REQ-98/REQ-99 reduction weights, so
an infinite cell is now counted as an independent measurement and the
random component's `1/sqrt(N)` gain shrinks the reported uncertainty of
the mean because of a cell carrying no measurement. Reading a different
mask for the count than for the value would be worse, dividing the sum
of one set by the size of another, so the coupling is deliberate and it
is pinned by a test. But it means "an infinity is data" is not only a
statement about the value: under it, an infinity makes the mean's
uncertainty smaller. Whoever answers the value question answers this
one with it.

*In a coverage count.* `DiagnosticsReport.coverage` is documented as a
"populated fraction", and an infinity occupies its cell, so 1.0 is
defensible. REQ-90 pulls the other way: it describes the sparse backing
store as "the underlying NumPy arrays plus a finite-mask", and a
finite-mask does not include an infinity. If coverage is finite-based,
an all-infinity variable is 0.0 covered and REQ-90's sparse threshold
fires on it. The two readings differ for exactly the data that motivated
the finding, and no requirement adjudicates between them.

**Why they are one question.** Both ask whether this library treats an
infinity as DATA or as INVALID. Answering one and not the other would
leave a frame whose mean is infinite and whose coverage is complete, or
one whose coverage is zero and whose mean carries the value anyway. The
seat should answer once.

**Who decides:** the numerical analyst, with the product owner where the
answer changes REQ-27, REQ-17 or REQ-90.

**SRS:** REQ-17, REQ-27, REQ-90.

## OQ-50: Should an .itceq processor expand its equations against the root variables?

**Raised:** 2026-07-31, lane ITA-2B, while implementing the SEAT-UNC
interim refusal (FND-058, BRF-059).
**Status:** open (product owner, with the numerical analyst).

**What was measured.** The processor is an ordinary sequence of
`compute` calls, so it inherits the between-call lineage loss exactly.
On the BALANCE test workflow, whose `[corrections]` compute a blockage
factor from `CL` and then apply it to `CL`, measured on `dde261c` before
the refusal existed, with `FZ = [100, 200, 300]`, `V = 50`,
`rho = 1.225`:

    processor       u(CL_corr) = [0.00164167 0.00166855 0.0017128 ]
    one expression  u(CL_corr) = [0.00164342 0.00167564 0.00172907]
    ratio                      = [0.99893605 0.99577124 0.99058533]

It UNDERSTATED, by 0.1 to 0.9 percent, growing with `CL`. The magnitude
is small on this fixture and the direction is the dangerous one, and a
correction that depends on the coefficient it corrects is not an unusual
workflow: it is what a blockage or a wall correction IS.

**Why it is a question rather than a fix.** There is an obvious repair.
The processor knows its whole equation set and resolves it into
dependency order already, so it could substitute each earlier target
into the later equations and compute every target from the ROOT
variables in a single expression. That is the same rewrite the refusal
suggests to a user, applied automatically, and it would make the
processor correct and silent instead of correct and refusing.

Three things stop this lane from simply doing it:

* It changes what History RECORDS. The operation strings would carry
  expanded equations rather than the lines the user wrote in the file,
  which changes the state hash and what a reader of the provenance sees.
  A user who wrote `CL_corr = CL * blockage` and reads back a 90
  character expansion is owed an explanation.
* It collides with OQ-43. A target whose uncertainty is RE-DECLARED by
  the `[uncertainties]` section after it is written must not be expanded
  through, because the declaration overrides the propagated value; an
  equation expanded past it would propagate from the original roots and
  silently ignore the declaration. That is a second wrong answer, not a
  fix, and OQ-43 is itself open.
* It is the `pproc` layer's behavior, not the uncertainty engine's.

**What ships in the interim.** The refusal, which is SEAT-UNC's posture
applied consistently: a processor whose corrections read what they
correct now raises `UncertaintyLineageError` naming the pair, instead of
returning an understated number. A processor whose equations read only
root variables is unaffected, which is the common shape.

**Who decides:** the product owner, on whether the flagship data
reduction path refuses or expands; the numerical analyst on the
interaction with OQ-43.

**SRS:** REQ-41, REQ-45, REQ-53, REQ-99.

## OQ-51: Should translate_moments record the correlation it induces, as rotate already does?

**Raised:** 2026-07-31, lane ITA-2B, while writing the guard for the
FND-074 refusal (PUSH review round two).
**Status:** open (numerical analyst, with the product owner).

**What was measured, and it was not what this lane expected.** Writing a
test to prove that `rotate` loses induced correlation the way
`translate_moments` does, the test failed: on a SINGLE-condition frame,
`rotate` does not lose it. With `u(FX) = 0.1` and `u(FZ) = 0.2` on a
declared force group:

    turned.correlation  ->  {('FX', 'FZ'): 0.47379635782970037}

It computes the coefficient its own Jacobian induces and writes it into
the frame as an ordinary declared pair. A later `compute` over the two
rotated components reads that coefficient through the clause-5 formula
and is CORRECT, and the SEAT-UNC refusal steps aside on its own, because
a declared pair is already the documented escape hatch.

**And the qualification that makes this a real question rather than a
copy-this-code ticket.** Review round three measured the other shape and
it is the ordinary one. On a two-condition sweep, which is exactly the
REQ-101 case:

    turned.correlation  ->  None
    operation           ->  rotate(..., correlation_not_stored=[('FX','FZ')])

A `CorrelationMatrix` pair is ONE scalar for a whole variable pair, and
the induced coefficient generally varies per grid cell. `rotate` stores
it only when it resolves to a single constant across cells, and
otherwise records `correlation_not_stored` and drops it rather than
inventing a number. So `rotate` does NOT solve the general problem; it
solves the representable case and declines the rest, and in the declined
case this lane's ancestry detector is what stops the understatement.

That is the honest statement of the asymmetry: `translate_moments` never
stores the induced pair, `rotate` stores it when it is representable.
The gap between them is real but narrower than one operation doing the
right thing and the other doing the wrong one.

**The question.** Should `translate_moments` write the induced
force-moment correlation the way `rotate` writes the induced
component-component correlation? If it should, the FND-074 refusal
disappears and is replaced by a correct number, which is strictly better
than a refusal with a workaround.

**What has to be answered first, and why this lane did not just do it.**

* A `CorrelationMatrix` pair is ONE scalar for a whole variable pair,
  while the induced coefficient generally varies per grid cell: it
  depends on the offset and on the force values at that cell. `rotate`
  resolves to a scalar; whether that resolution is sound in general, or
  is sound only for the cases rotate faces, is a numerical-analyst
  question and it applies to both operations.
* Writing a correlation the USER did not declare changes what
  `db.correlation` means. Today it is a record of user statements, and
  every message in the library that says "the declared correlation"
  would become ambiguous. `rotate` already crossed that line, which may
  itself be worth revisiting rather than replicating.
* It is the same boundary SEAT-UNC drew. Recording an induced
  coefficient is one step from recording sensitivities, which is the
  v0.3.0 lineage work this lane was told not to build through.

**A third option the answer should consider.** REQ-38 already says
`correlation_not_stored` is recorded rather than raising, so that
"refusing to invent a coefficient must not break the REQ-101 case". Per
the measurement above that case is now refused one operation later, by
this lane's detector. So the REQ-38 rationale and the REQ-41 behavior
point in opposite directions, and whoever answers this should say which
one moves (VV-15).

**What ships in the interim.** The refusal, which is correct and
conservative whatever the answer. If the answer is yes, REQ-100's
refusal paragraph is replaced by a propagation statement and the
`translate_moments` half of this lane is superseded.

**Who decides:** the numerical analyst on whether a scalar pair can
represent the induced covariance soundly; the product owner on whether
`db.correlation` may hold coefficients the user did not write.

**SRS:** REQ-40, REQ-41, REQ-98, REQ-100.

---

## OQ-52: Should an unset `ITACA_PLAN_VALIDATOR` still skip validation silently?

**Status:** open (product owner)

**Raised:** 2026-08-01, lane ITA-4, the kit floor.

`CLAUDE.md` gives three different meanings of "unset" across one family
of three locator variables, and says so explicitly because the word
looks like one branch and is not: `ITACA_PLAN_VALIDATOR` SKIPS the
validation, `ITACA_MANAGEMENT_ROOT` SUBSTITUTES a location and stops if
it holds nothing, and `COORD_INCIDENT_LEDGER` DENIES a push.

The charter supplies the argument against its own first row. About
`COORD_INCIDENT_LEDGER` it says "a guard that reads its own missing
configuration as permission is not a guard, and this one did read it
that way until kit 0.2.8". That sentence is about guards, and the plan
validator is a guard. The skip is also announced by CONVENTION: the
charter requires a session to state it in the record, and no mechanism
enforces that, so an unannounced skip and a pass leave the same trace.
This is the shape of `ITC-20260727-1542`, where plan validation had
been silently skipping for days while the drift test stayed green.

Three arguments cut the other way and none is weak. The plan validator
gates nothing, unlike the incident ledger, whose absence denies a push
because that is a safety property; denying on unset would stop work
that has nothing to do with the ledger. `ITACA_MANAGEMENT_ROOT` already
stops when the documents cannot be found at all, so the uncovered case
is narrower than it first appears: a ledger that exists and is not
checked. And the asymmetry is deliberate and documented, in a section
whose whole purpose is that no two members agree.

**Options.** (A) Leave it. (B) Unset DENIES, matching
`COORD_INCIDENT_LEDGER`, so two of three members stop disagreeing about
the same word. (C) Unset still skips, but the skip becomes machine
visible rather than conventional.

**The lane's recommendation is C, weakly.** It keeps the branch the
charter deliberately made different and removes the property that is
indefensible on its own terms, which is that the skip is SILENT rather
than that it is a skip. A is the one that should not survive, being the
option whose cost the charter has already argued against.

**Who decides:** the product owner. This changes a rule the charter
states, and the locator table is her seat.

**Full analysis:** plan entry `ITC-20260801-1400`.

---

## OQ-53: Should the vendored kit be checked for CURRENCY, and by what locator?

**Status:** open (product owner)

**Raised:** 2026-08-01, lane ITA-4, the kit floor.

`tests/test_kit_drift.py` proves a vendored copy cannot be silently
HAND-EDITED, and its own docstring states that it does NOT prove a copy
is CURRENT with the kit, because its manifest is an inlined frozen copy
rather than a live read of the master. So a repository that has fallen
behind stays green until someone moves a pin by hand.

That limit is not theoretical. This lane compared every pin against the
kit README's manifest table with a throwaway script and found three
rows behind, one of which mattered: the deployed plan checker had been
upgraded while the mutation companion proving it can still fail was left
seven versions back, invisible because each half was self-consistent
with its own pin.

Making that comparison a test needs a locator naming the kit master,
which would be a fourth member of the locator family, and the family's
semantics are charter material. It also needs an answer for what an
unset locator means, which is OQ-52's question one artifact over, so the
two are worth answering together rather than a month apart.

**The tension.** The inlined manifest is deliberate: it lets the drift
test run with no cross-repository filesystem access and it cannot
deadlock a push. A live read gives up that property in exchange for
seeing staleness. A third shape, a periodic reconciliation that is not
part of the push gate, may fit better than either.

**Who decides:** the product owner, on whether the locator family gains
a member and on what its unset branch means.

**Full analysis:** plan entry `ITC-20260801-0900`.
