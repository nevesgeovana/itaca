# ITACA development workspace

## Identity

ITACA, Integrated Toolkit for Aerospace Computation and Analysis. Public
Python library (MIT) for rigorous engineering data management, analysis,
and computation. Author and sole decision maker: Geovana Neves. Import
convention: `import itaca as itc`. Tagline: From data to wisdom.

## Authority chain

1. `docs/srs/` is the authoritative specification (document 0.2.5,
   2026-07-30; baseline 0.1.0 was the first workspace-tracked
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
Q-003) and promoted from draft to stable in the SRS (reqbox and
revision history); its specification is frozen and it is implemented
fully in M1 phase B2.
REQ-104, REQ-105, and REQ-106 entered as draft with ids confirmed by
Geovana (Q-002); their code is unblocked in the M1 windows. Do not
freeze draft implementations without her confirmation; everything
tagged stable may proceed.

## Development rules (non-negotiable)

* TDD: usage example first, then failing tests, then minimal
  implementation, then refactor. Pull requests without tests are
  rejected regardless of correctness.
* Coverage at or above 90 percent, hard CI gate (`pytest-cov`).
* Every package imports only NumPy and the standard library, except
  `io/` and `utils/`, which may import pandas lazily (REQ-05, REQ-84).
  No xarray, dask, or pandas anywhere else, enforced by a ruff
  import-policy rule and a guard test. REQ-82 was amended to this
  exception-list form on 2026-07-27 (DD-33); it previously named
  `core/`, `ops/`, and `uncertainty/`, which was narrower than what CI
  enforced. Both halves of the enforcement discover packages rather
  than enumerate them, so a package added later is restricted by
  default and an exemption is a deliberate act.
* Every operation returns a new object and records itself in History
  (REQ-18), and declares its UncFrame effect (REQ-98). Arrays are
  read-only (`writeable=False`, REQ-102).
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
  repository, in any form. `_private/` is gitignored for local staging;
  see "Where the session documents live" below.

## Role passes (adopted 2026-07-23)

Before a work item closes, the `role-review` skill has run its
applicable reviewer passes (architect, QA, V&V, tech writer, API
designer; charters in `.claude/agents/`) on the item's diff, and
every finding is fixed or registered (`docs/OPEN_QUESTIONS.md` for
design questions, the milestone execution plan for approved scope, or
the working plan ledger, the management root's `plan/` (see "Where the
session documents live"), one file per entry, whose format is defined in
that folder's own `README.md`, for everything else).
Geovana keeps the non-delegable seats:
product owner, domain expert, numerical analyst. The sister
pyflightstream repository carries the same process (DD-23).
Session planning, closure, and periodic audit run through the plan,
handoff, and audit skills in `.claude/skills/` (session documents under
the management root below, never committed here). The plan ledger is
validated by the
checker named in the `ITACA_PLAN_VALIDATOR` environment variable (the
plan skill holds the mechanism): unset skips validation, set but
unreachable is a configuration error. `COORD_INCIDENT_LEDGER` locates the
incident checker the same way, with one difference that matters: unset
SKIPS validation there and DENIES a push here.

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

## Where the session documents live (adopted 2026-07-27)

The session documents live under a **management root** outside this
repository, and are never committed here: the inbox, handoffs, the
forward prompt `NEXT_SESSION.md`, the working plan ledger `plan/`, audit
reports `progress/`, session logs, and working decision notes. Working
decision notes are drafts and candidates; `docs/DECISIONS.md` is not one
of them and stays committed here, as the authority chain says.

This section is the single home of the resolution rule below. The plan,
handoff, role-review, and audit skills point at it and do not restate
it; where one appears to, this file wins.

The root is named by the `ITACA_MANAGEMENT_ROOT` environment variable,
never by a literal path in a versioned file, for the same reason
`COORD_INCIDENT_LEDGER` and `ITACA_PLAN_VALIDATOR` are: this repository
is public, and a hard-coded personal path publishes one machine's layout
and is wrong on every other clone.

| Variable | Names | Unset | Set but invalid | Mechanism | Guard |
|---|---|---|---|---|---|
| `ITACA_MANAGEMENT_ROOT` | the session-document root | use `_private/` if it still holds the documents, else stop | stop and report | the skills | `tests/test_management_root.py` |
| `ITACA_PLAN_VALIDATOR` | `check_plan_kit.py`, or its directory | skip validation, say so | stop and report | the plan skill | `tests/test_plan_validator.py` |
| `COORD_INCIDENT_LEDGER` | `check_incidents.py`, or its directory | **push gate DENIES** | push gate denies | `.claude/hooks/role_review_gate.py` | `tests/test_push_gate.py`, `tests/test_kit_drift.py`, `tests/test_house_style.py` |

Unset never blocks a clone that configured nothing, which is the point
of the branch, but it does not mean the same thing across the family:
for the two checkers it means the check does not run, while for the root
it means a different location is used. The root is therefore the one
member whose unset branch has a stop case, because a location that does
not exist cannot be silently substituted the way a skipped check can:

- **Unset uses `_private/` in this repository** when that directory
  still holds the session documents, which is the pre-migration layout
  and any clone that never configured anything.
- **Unset and `_private/` is absent or holds no session documents is a
  configuration error.** Stop and report; do not create the tree. After
  the 2026-07-27 migration this is the state in this repository, so an
  unconditional fallback would write handoffs and ledger entries into an
  empty directory nobody reads. Non-emptiness is not the test:
  `_private/` is also local staging, so one staged file there is not the
  session documents.
- **Set but not an existing directory, or an existing directory that is
  not itaca's management root, is a configuration error.** Stop and
  report; never fall back silently. Existence alone is not identity: the
  sibling projects sit next to this one under the same parent, and a
  root pointed one folder across would validate the wrong ledger and
  file handoffs into another project. The root is recognized by
  `plan/README.md` naming the ITACA plan ledger.

Report a configuration error the way every other error here is reported:
the object involved, the operation attempted, and the suggested fix. For
example, "ITACA_MANAGEMENT_ROOT is set to <path>, which is not a
directory; session documents cannot be written; set it to the itaca
management root or unset it to use _private/".

State the resolved root and which resolution branch produced it in the
session record, exactly as a skipped plan validation must be stated. A
resolution that is never announced cannot be noticed when it is wrong.

Resolve the root before writing, and pass the **resolved** path onward.
A repository-relative path stops meaning the ledger as soon as the root
moves. Read a checker's entry count and its OUTPUT, not only its exit
code. The plan checker used to make that advice load-bearing: an **empty**
folder reported `no entries` and exited **zero** (measured 2026-07-27), so
a run against the wrong path looked like a pass. Kit 0.2.10 fixed it,
adopted here on 2026-07-30 (`ITC-20260727-1612`): an empty walk now exits
**2**, CANNOT VERIFY, meaning nothing was validated. Neither code maps to
one cause, so the output is what tells them apart: **1** is a path refused
with a cause, either bad entries or a path that is not a directory, and
**2** covers an empty folder, an unreadable `legacy_ids.txt` (CONFIG
ERROR, which names the file) and a bad invocation. The habit stands
anyway, for two reasons that outlive the fix: a checker whose output
wording changes goes blind in a way no exit code reports, and this is a
family of tools, so the next one need not have adopted the rule.
`tests/test_plan_validator.py` pins the refusal, its exit code and the
shape-to-cause mapping, because the kit's own mutation companion has no
empty-walk case (`ITC-20260730-0205`).

The management content migrated to the coordination hub on 2026-07-27
under an author decision, including the plan ledger, whose migration was
her product owner call (DD-31). `_private/` remains in `.gitignore`
(the enforcement, pinned by `tests/test_management_root.py`) and remains
excluded from the `tests/test_house_style.py` walk (a scanning
exemption, not enforcement), so the invariant above that no proprietary
material enters this repository in any form is unchanged in force and in
meaning.

On the backup that the migration displaced: as of 2026-07-27 the kit's
`snap.sh` snapshotted `_private/`, which is now empty, so it protects
nothing here and the migrated content relies on the hub's git instead.
The pre-migration history remains in the local snapshot repository that
tool maintains, at the commit recorded in the migration's plan entry.
That the hub actually tracks every migrated file is the hub's to
guarantee, not this repository's, and it did not hold at the moment of
the move: the routing note carries the evidence and the open item.

## Incidents (adopted 2026-07-23)

A defect is fixed at its **structural cause on its first occurrence**,
not on its second. The fix is not complete until it carries a guard
that makes recurrence impossible and the evidence that the guard
blocks the original failure when re-run. That headline is kept here so a
clone reads the rule without leaving the repository; the full policy
statement, including why documentation is not a guard and why a guard
must be proven by mutation, lives in the shared ledger's own README
(located by `COORD_INCIDENT_LEDGER`), the cross-repo authority both
libraries point at. This section keeps only the headline and defers the
policy detail there rather than restating it.

Incidents are recorded in the shared ledger with the sister
repository, located by the `COORD_INCIDENT_LEDGER` environment
variable, never by a literal path in a versioned file. The variable
names the directory holding `check_incidents.py` (or the checker
itself). **Unset DENIES a push**, and so does set but unreachable: this
is the one member of the locator family whose absence is a refusal rather
than a skip, because a guard that reads its own missing configuration as
permission is not a guard. Export it before working in a fresh clone.

The `incident-analyst` agent (charter in
`.claude/agents/`) drafts the record: symptom, proximate cause,
structural cause, guard, guard evidence, cross-repository impact.
Whether an incident blocks is Geovana's call, and while one marked
blocking is open the gate denies. No new work ships on top of a defect
whose structural cause is still unfixed.

**One name, and how it got there.** Author decision LEDGER-ENVVAR made
`COORD_INCIDENT_LEDGER` the single name for every workspace sharing this
ledger, and kit 0.2.8 carried it into the push gate together with the change
that matters more: an ABSENT ledger now denies instead of reading as
does-not-apply. itaca ran kit 0.2.6 until 2026-07-30 and so carried the
fail-open branch for a day after the fix existed, which the coordination
level measured and routed back here (`ITC-20260730-0215`, closed by the
re-vendor). On a clone that had configured nothing, the incident half of the
gate did not gate.

`tests/test_house_style.py` reads the variable out of the vendored gate and
requires the locator table to name exactly that one, in both directions, so
the two cannot be renamed apart again. `tests/test_push_gate.py` pins the
refusal itself: the test that used to assert an unset ledger allows a push
now asserts it denies, and names the `[config]` sub-kind, because the remedy
is one export and a message that does not say so turns a deployment step
into a mystery.

`docs/DECISIONS.md` still names the old variable inside DD-31. DD entries are
frozen and append-only, so it is left as written; this section is the
operative rule.

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
v0.1.0 shipped 2026-07-22 (PyPI and Zenodo). The cross-repo decision
queue is owned by the coordination level, the home of the questions that
gate work in more than one workspace. It sits above this repository and
above the management root, which is itaca's alone, so it has no locator
here by design: a session raises such a question to the author and she
routes it, rather than resolving a path to another workspace's tree. The
former pointer into the sister repository's private tree was removed on
2026-07-27, because a path into another repository's private layout is
exactly what this repository does not depend on.
