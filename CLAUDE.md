# ITACA development workspace

## Identity

ITACA, Integrated Toolkit for Aerospace Computation and Analysis. Public
Python library (MIT) for rigorous engineering data management, analysis,
and computation. Author and sole decision maker: Geovana Neves. Import
convention: `import itaca as itc`. Tagline: From data to wisdom.

## Authority chain

1. `docs/srs/` is the authoritative specification (document 0.1.0,
   2026-07-21, first workspace-tracked version). The SRS describes desired
   behavior; code is verified against the SRS, and the SRS is changed only
   when a requirement itself is wrong or ambiguous, with the revision
   history and Chapter 11 updated together.
2. `docs/DECISIONS.md` (DD-01 to DD-22) records why. Frozen entries,
   append-only, supersede rather than edit.
3. `docs/OPEN_QUESTIONS.md` (OQ-01 to OQ-18) records design questions and
   resolutions. New questions are appended as they arise.
4. The research workspace thread (`AeropropulsiveResearch/threads/itaca/`)
   holds the DLV-008 snapshot of this baseline; from now on this
   repository is the living home of the SRS and companions.

Canonical terms (supersede any older material): equation files are
`.itceq`; string derivation is `db.compute`; `Processor` is a
`typing.Protocol`; the figure wrapper is `ItcFigure`; expression parsing
uses the stdlib `ast` module; uncertainty has two components (systematic
and random); releases are incremental (M0 to M3 as v0.1.0 to v0.4.0).

## Gate before coding draft requirements

REQ-98 and REQ-99 were validated by Geovana at the M0 Phase 4
checkpoint (2026-07-21, SRS document 0.1.1) and are stable; the
smooth and diff row of REQ-98 remains provisional pending OQ-18
(revisit during v0.2.0). REQ-101 (condition-dependent axes, v0.2.0
scope) is still tagged draft pending her validation. Do not freeze
draft implementations without her confirmation; everything tagged
stable may proceed.

## Development rules (non-negotiable)

* TDD: usage example first, then failing tests, then minimal
  implementation, then refactor. Pull requests without tests are
  rejected regardless of correctness.
* Coverage at or above 90 percent, hard CI gate (`pytest-cov`).
* `core/`, `ops/`, and `uncertainty/` import only NumPy and the standard
  library. No xarray, dask, or pandas there, enforced by a ruff
  import-policy rule and a guard test.
* Every operation returns a new object, records itself in History, and
  declares its UncFrame effect (REQ-98). Arrays are read-only
  (`writeable=False`, REQ-102).
* Type hints everywhere public; `mypy --strict` on the public API.
  NumPy-format docstrings with Parameters, Returns, Raises, Examples.
* Lint and format with ruff (`ruff check`, `ruff format`). Conventional
  Commits. `CHANGELOG.md` updated with every public API change.
* Error messages carry three parts: object involved, operation
  attempted, suggested fix. All exceptions derive from `ITACAError`.
* English everywhere in artifacts, American English with Z. Conversation
  with Geovana may be in Portuguese; every artifact is English.
* Never use em dashes or en dashes anywhere, in any file. No exceptions.
* Example and test data are synthetic or publicly licensed with stated
  provenance. Employer-origin or proprietary data never enter this
  repository, in any form. `_private/` is gitignored for local staging.

## What Claude should do here

* Follow the SRS requirement by requirement; cite REQ, DD, and OQ ids in
  commits and pull request descriptions where they apply.
* Flag any design decision that breaks immutability, provenance, the
  NumPy-only rule, or the minimal API principle, instead of implementing
  it silently.
* Prefer `itc.load` dict mode in production examples (most traceable).
* Keep expression operators isolated and independently testable, with
  property-based tests (Hypothesis) for every math kernel contract.
* When the SRS and this file disagree, the SRS wins; report the
  discrepancy to Geovana rather than patching either silently.
* Update `docs/srs/` (revision history plus Chapter 11) together with any
  requirement change; requirement evolution is monitored from the 0.1.0
  baseline onward.

## Current milestone

M0, release v0.1.0 (SRS Chapter 10): VarFrame, UncFrame, HistoryFrame,
all load modes, inspect and pivot, manifest, diagnostics, summary,
operating modes, select, at, squeeze, fill, combine, compute with
symbolic two-component LPU including covariance, exports, units,
immutability and hash invariants, full test suite, CI, pre-commit. Axes
move to v0.2.0; Monte Carlo and PROV export to v0.3.0. Release gates:
green CI, LICENSE and CITATION.cff present, example-data provenance
scrub, PyPI name registration (`itaca`, verified free 2026-07-21).
