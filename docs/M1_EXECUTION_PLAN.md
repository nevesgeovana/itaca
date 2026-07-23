# M1 Execution Plan (release v0.2.0)

Status: approved by Geovana 2026-07-23 (ultraplan Batch A, decision
queue entries Q-001 and Q-003).
Authority: SRS 0.2.0 (`docs/srs/`, Chapter 10 scope, Chapters 6 and 7
requirements), DD-01 to DD-25, OQ catalog. Where this plan and the
SRS disagree, the SRS wins and the discrepancy is reported, not
patched. The Chapter 10 amendment of Section 2 was applied through
the normal SRS process together with this plan's approval (document
version 0.2.0).

## 1. Objective

Ship M1 as public release v0.2.0 on PyPI with a Zenodo DOI:
"Analysis Core, computation complete". The computation layer of the
analysis milestone lands whole (ops, axes base, pipeline, processor
infrastructure, the D2/D5/D6 adoptions); the presentation layer
(plot core with the D1 options registry) and the domain builtins
(WT processors, statistics, compare) form the STRETCH SCOPE:
attacked the same week by the stretch lane if capacity allows,
otherwise a fast v0.2.1. This split is the re-baseline decided by
Geovana on 2026-07-23 after the capacity measurement (M1 whole =
11-13 session units); it is recorded as an amendment to SRS
Chapter 10 (Section 2 below).

## 2. Scope and the Chapter 10 amendment

In scope (v0.2.0):

| Area | Requirements | Modules |
|---|---|---|
| Structural ops: expand, concat, interpolate | REQ-23, REQ-24, REQ-25 | `ops/`, `core/historyframe.py` |
| Numeric ops: average, integrate, smooth | REQ-27, REQ-28, REQ-29 | `ops/` |
| diff with moving-window polynomial | REQ-30 | `ops/diff.py` |
| fitmodel, fitvalue | REQ-31, REQ-32 | `ops/fitmodel.py`, `ops/fitvalue.py` |
| Axes base: Axis, rotate with propagation, translate_moments | REQ-38, REQ-100 (+DD-11) | `core/axes.py` |
| Condition-dependent frames | REQ-101 (validated) | `core/axes.py` |
| Pipeline and .itc_pipe | REQ-53, REQ-54, REQ-55 | `core/pipeline.py` |
| Processor infrastructure: protocol, factory, .itceq parser | REQ-45 to REQ-48 (+DD-16, DD-17) | `pproc/` |
| No-default sentinel | REQ-105 | `core/sentinels.py` |
| Accessor registration | REQ-106 | `core/accessors.py` |
| uncertainties dev-only oracle tier | DD-25 (no REQ) | dev deps, `tests/oracle/` |
| Sister-library docs page + pyflightstream-origin REQ channel | DD-23 | `docs/` |

STRETCH scope (same week if capacity allows, else v0.2.1; never
silently absorbed into v0.2.0's done):

| Area | Requirements | Modules |
|---|---|---|
| Options registry | REQ-104 (+DD-24) | `utils/options.py` |
| Plot core: datavis, ItcFigure, AIAA style, matplotlib backend | REQ-56, REQ-57, REQ-60, REQ-61 | `plot/` |
| Builtin processors WT_propeller, WT_balance_off | Chapter 10 M1 table | `pproc/builtin/` |
| statistics, compare | REQ-49, REQ-50 (+OQ-14) | `pproc/` |

Out of scope for M1 entirely (unchanged): everything in the M2/M3
tables (remaining processors, aero_polar, LaTeX reports, plotly,
Monte Carlo REQ-42, PROV export, surrogates, itc.aerospace); the
driver-side pandas/xarray migration (next window, gated by the axes
landing).

Chapter 10 amendment (applied with the document 0.2.0 bump): the M1
deliverables table splits into "v0.2.0 (computation)" and "v0.2.1
(presentation and builtins)" rows per the two tables above, with a
note recording the 2026-07-23 re-baseline decision and that the
stretch scope may still ship inside v0.2.0 if it is green in the
same window.

## 3. Gates on draft requirements and decisions

* REQ-101 was VALIDATED as written by Geovana (2026-07-23, Batch A,
  Q-003): B2 implements condition-dependent frames fully, with no
  didactic-raise fallback, and REQ-101 moves draft-to-stable through
  the normal SRS process once implemented and tested. `core/axes.py`
  freezes at the end of B2 with the full scope.
* OQ-18 (systematic weights through smooth/diff kernels): the REQ-98
  row for smooth and diff keeps the sanctioned raise; lane B prepares
  the worked derivation plus property tests BEFORE Batch B (Q-004) so
  Geovana validates rather than derives. If frozen in Batch B, the
  backfill lands in Phase B4.
* REQ-104/105/106 were approved with confirmed ids (Q-002) and are
  entered in the SRS as draft; their code is unblocked in its
  implementation windows.
* Every phase closes through the role-review skill (per-phase diff,
  applicable passes) and the coverage/mypy/ruff gates of the M0 plan.

## 4. Phases

Done-criteria per phase as in the M0 plan: TDD order, tests green,
coverage of touched modules at or above 90 percent, ruff and mypy
strict green, CHANGELOG updated, role-review passes run.

### Phase B0: Infrastructure and requirements (day 1)

* PyPI trusted publishing (OIDC) in the release workflow.
* This plan committed as `docs/M1_EXECUTION_PLAN.md`; Chapter 10
  amendment applied; REQ-104/105/106 entered as draft reqboxes;
  DD-24 (options registry adoption) and DD-25 (uncertainties as
  dev-only oracle) recorded.
* `core/sentinels.py` (REQ-105) first: tiny, unblocks every ops
  signature.

### Phase B1: Ops (days 1-3)

* expand, concat, interpolate (REQ-23..25) with HistoryFrame
  updates; average, integrate (REQ-27/28); smooth, diff (REQ-29/30)
  with the OQ-18 raise on the uncertainty row; fitmodel, fitvalue
  (REQ-31/32). Sentinel adopted throughout; the REQ-105 raise clause
  (an explicit sentinel where it is not the declared default raises)
  is a per-signature B1 acceptance item, tested with the first
  adopting operation; REQ-76 edge cases enter with their families;
  every op records History and declares its UncFrame effect (DD-18).

### Phase B2: Axes and accessors (days 3-4)

* `core/axes.py`: Axis, `db.rotate()` with uncertainty propagation,
  `db.translate_moments()` (REQ-38/100, DD-11); condition-dependent
  frames per REQ-101 as validated (Section 3); freeze at the end of
  the phase.
* `core/accessors.py` (REQ-106) complete with its snapshot/restore.
* SYNC S2: on merging axes + accessors to main, lane B posts the S2
  signal in the DECISION_QUEUE; the pyflightstream exporter lane (D)
  may then start.

### Phase B3: Pipeline and processor infrastructure (days 4-5)

* `core/pipeline.py` (REQ-53..55, indexed history, `.itc_pipe` IO).
* `pproc/`: Processor protocol, factory, `.itceq` parser with cycle
  detection and opt-in topological sort (REQ-45..48, DD-16/17).

### Phase B4: Hardening and release (days 5-7)

* OQ-18 backfill if frozen in Batch B; oracle tier (DD-25)
  exercising the GUM random component against `uncertainties` on
  small cases.
* Sister-library docs page; pyflightstream-origin candidate-REQ
  channel documented (exporter findings triage as M2 candidates).
* Evaluate doctest collection for the public Examples blocks
  (registered from the B0 role review: examples are currently
  demonstrated but not executed in CI and can rot silently).
* Full role-review sweep, coverage and guard audit, CHANGELOG
  assembly, v0.2.0 tag and publish (OIDC), Zenodo record. Release
  call is Geovana's (Batch C).

### Stretch phases (parallel stretch lane under Geovana's direction)

* SB1: options registry (REQ-104) with snapshot/restore and the
  message contract.
* SB2: plot core (REQ-56/57/60/61) with AIAATheme as the first
  registry consumer and a frozen testing theme; image comparisons by
  thresholded error metric, never byte equality.
* SB3: WT_propeller, WT_balance_off (+ companion .itceq files),
  statistics, compare (REQ-49/50); Geovana's SME acceptance on the
  WT processors.
* Ships inside v0.2.0 if green before the Batch C call; else tags
  v0.2.1 in the following days.

## 5. Risks carried from the ultraplan

* Geovana-throughput is the ranked top risk: all questions go
  through the DECISION_QUEUE and the three batches; only
  release-blocking findings interrupt.
* Axes is the hardest chunk (propagation math plus the full REQ-101
  scope); it is scheduled early inside B2 and never cut.
* The processor language (.itceq) is architecture, not domain: the
  builtins that exercise it are stretch, so the parser must carry
  its own fixture-based tests without them.
