# ITACA development workspace

## Identity

ITACA, Integrated Toolkit for Aerospace Computation and Analysis. Public
Python library (MIT) for rigorous engineering data management, analysis,
and computation. Author and sole decision maker: Geovana Neves. Import
convention: `import itaca as itc`. Tagline: From data to wisdom.

## Authority chain

1. `docs/srs/` is the authoritative specification (document 0.2.0,
   2026-07-23; baseline 0.1.0 was the first workspace-tracked
   version). The SRS describes desired
   behavior; code is verified against the SRS, and the SRS is changed only
   when a requirement itself is wrong or ambiguous, with the revision
   history and Chapter 11 updated together.
2. `docs/DECISIONS.md` records why. Frozen entries, append-only,
   supersede rather than edit; the current DD range lives in the file.
3. `docs/OPEN_QUESTIONS.md` records design questions and resolutions,
   append-only. New questions are appended as they arise.
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
(revisit during v0.2.0). REQ-101 (condition-dependent axes) was
validated as written by Geovana (2026-07-23, ultraplan Batch A,
Q-003): implement fully in M1 phase B2; the reqbox moves
draft-to-stable through the SRS process once implemented and tested.
REQ-104, REQ-105, and REQ-106 entered as draft with ids confirmed by
Geovana (Q-002); their code is unblocked in the M1 windows. Do not
freeze draft implementations without her confirmation; everything
tagged stable may proceed.

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

## Role passes (adopted 2026-07-23)

Before a work item closes, the `role-review` skill has run its
applicable reviewer passes (architect, QA, V&V, tech writer, API
designer; charters in `.claude/agents/`) on the item's diff, and
every finding is fixed or registered (`docs/OPEN_QUESTIONS.md` for
design questions, the milestone execution plan for approved scope, or
the working plan ledger in `_private/plan/`, one file per entry, whose
format is defined in `_private/plan/README.md`, for everything else).
Geovana keeps the non-delegable seats:
product owner, domain expert, numerical analyst. The sister
pyflightstream repository carries the same process (DD-23).

Mandatory push and release gate (adopted 2026-07-23, after a
pyflightstream release ran paraphrased manual checks instead of the
specialist agents): "role-review" means invoking the `role-review`
skill so the real reviewer agents run, never a hand-written
paraphrase. A `git push` PreToolUse hook
(`.claude/hooks/role_review_gate.py`) blocks every push until an
attestation covers every commit the push makes new, computed per
resolved ref as `git rev-list <ref> --not --remotes` plus the ref
itself, always. The ref stays in scope even when the range is empty:
the ordinary release order (branch first, then tag) leaves the tagged
commit already on the remote, and set containment over an empty range
is vacuously true, so checking the range alone once let an unattested
tag clear the gate. Push forms whose scope cannot be resolved offline
(`--all`, `--mirror`, `--tags`, `--follow-tags`, deletions) are
denied rather than guessed at; name the branch or tag. An explicit
version tag additionally requires the release attestation (full-scope
review of the release diff).

What the mechanism enforces is exactly this: an attestation exists
naming every commit in scope. It does not prove the agents ran, and
the recorded `passes` list is never checked. That last step rests on
whoever writes the attestation, which is why the skill, not a
paraphrase, must be what writes it. The attestation is written by
`.claude/hooks/write_attestation.py` as the skill's closing step, in
`.claude/.role_review_attestation.json` (local, gitignored). A commit
made after attesting re-arms the gate: an unreviewed commit never
ships. `tests/test_push_gate.py` and `tests/test_review_gate.py` pin
this behavior; do not weaken the gate without a test that fails first.

Write the attestation and the push as separate commands. The hook
inspects the whole command string, so a combined command is seen as a
push and denied before the attestation runs.

## Incidents (adopted 2026-07-23)

A defect is fixed at its **structural cause on its first occurrence**,
not on its second. The fix is not complete until it carries a guard
that makes recurrence impossible and the evidence that the guard
blocks the original failure when re-run. Documentation is not a guard:
a note, a comment, or a line in this file records a guard, and if the
only enforcement is that someone reads and complies, the failure
recurs. A guard nobody tried to break is a guess, so mutate the code
it protects and show the guard fails.

Incidents are recorded in the shared ledger with the sister
repository, located by the `ITACA_INCIDENT_LEDGER` environment
variable, never by a literal path in a versioned file. The variable
names the directory holding `check_incidents.py` (or the checker
itself); unset means the check does not apply, so a clone that never
configured it can still push, while set but unreachable blocks every
push by design. The `incident-analyst` agent (charter in
`.claude/agents/`) drafts the record: symptom, proximate cause,
structural cause, guard, guard evidence, cross-repository impact.
Whether an incident blocks is Geovana's call, and while one marked
blocking is open the gate denies. No new work ships on top of a defect
whose structural cause is still unfixed.

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

M1, release v0.2.0 "Analysis Core, computation complete" (SRS
Chapter 10 as re-baselined 2026-07-23; docs/M1_EXECUTION_PLAN.md is
the approved plan). In scope: ops (expand, concat, interpolate,
average, integrate, smooth, diff, fitmodel, fitvalue), axes base with
condition-dependent frames (REQ-38/100/101), pipeline and .itc_pipe
(REQ-53..55), processor infrastructure (REQ-45..48), no-default
sentinel (REQ-105), accessors (REQ-106), dev-only uncertainties
oracle (DD-25). Stretch scope (same week or fast v0.2.1): options
registry (REQ-104), plot core, WT builtins, statistics and compare.
v0.1.0 shipped 2026-07-22 (PyPI and Zenodo). Cross-repo decision
queue: pyflightstream `_private/DECISION_QUEUE.md`.
