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
**Proposed handling:** carry the derivation together with the OQ-18
work (Q-004) so Geovana validates one coherent coefficient-space
story; if deferred, the `fitmodel` raise is documented in REQ-31 and
a `fitmodel` row is added to the REQ-98 table stating the raise.
**SRS:** REQ-31, REQ-98 (Table to gain a `fitmodel` row); OQ-18.

---

## OQ-25: Origin-tag reduction across a fit or integral

**Status:** open; surfaced 2026-07-23 during M1 Phase B1
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
