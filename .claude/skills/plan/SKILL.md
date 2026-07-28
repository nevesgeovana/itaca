---
name: plan
description: Planning state over the itaca plan ledger and the milestone map. Report progress, add agreed items, or propose the next work window, then validate the ledger. Use when the author asks for plan status or the state of the milestone, when the author asks to propose the next work window, when a review or a decision produces work that must be registered, or whenever an entry lands in the plan ledger and its shape should be checked. Session close is the handoff skill's trigger, not this one; that skill writes the forward prompt, drawing on the window this skill proposes.
argument-hint: "[status|add|next]"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
disable-model-invocation: false
---

Operation: `$ARGUMENTS`

The milestone map is M0 to M3, released incrementally as v0.1.0 to
v0.4.0 (CLAUDE.md, canonical terms). The current milestone is M1,
release v0.2.0 "Analysis Core, computation complete". The approved
scope of the current milestone is `docs/M1_EXECUTION_PLAN.md`, the plan
derived from SRS Chapter 10 as re-baselined 2026-07-23; it is committed
and changes through the SRS process. The SRS in `docs/srs/` is the
authoritative specification; the execution plan never contradicts it.

The ledger folder is `plan/` inside the management root, holding the
working items **one file per item**, named for its own id. The rules and
the entry format are in its `README.md`; read it before adding anything.

The management root is `$ITACA_MANAGEMENT_ROOT`, resolved exactly as
CLAUDE.md ("Where the session documents live") defines it, including
what to do when it is unset or invalid. Resolve it once at the start of
the operation, state the resolved root and which resolution branch
produced it in the session record, and use that value throughout; never
assume a path.

The ledger is one file per entry rather than a shared table for the
same reason the incident ledger is: two of the three founding failures
were concurrent writes to one shared file with a central counter. One
file per entry means there is nothing to contend for, and a truncating
write can destroy at most one entry.

Rules (the ledger's own `README.md` is the authoritative home of the
entry format; the rules below are restated only as far as this skill
enforces them, and any divergence is resolved in the README's favor):

- **Never allocate an id from a counter or a maximum.** A new item gets
  a timestamp id, `ITC-<YYYYMMDD>-<HHMM>-<slug>`, mirroring the incident
  id shape, so two sessions writing in the same minute do not collide
  unless they also pick the same slug, which is visible in the filename.
- **Never renumber or reuse an existing id.** Existing ids are cited in
  handoffs, review records, and the decision log; they keep their
  identity.
- The header block carries `id`, `milestone`, `priority`, `status` and
  `ref`. `status` is one of `open`, `doing`, `done`, `dropped`;
  `priority` is `P0` (blocks the milestone), `P1` (in the milestone),
  `P2` (wanted, not scheduled). `ref` cites the REQ, DD, OQ, review
  finding, or execution-plan phase the entry comes from, so every entry
  is traceable to its origin.
- A `dropped` entry says why in its notes and is never deleted, so the
  record stays append-only. A `status` change cites its evidence: a
  commit, a test run, or a committed report.
- Writes are **append-only** to the notes, or **atomic** for a new
  file: write a temp file in the same directory, validate, then
  `os.replace`. Never open a live entry with mode `w`.

Operations (default when empty: `status`, which is read-only and never
writes an entry):

* `status`: read the ledger folder, `docs/M1_EXECUTION_PLAN.md`, and the
  git log. Report per milestone phase: done, in progress, blocked, with
  the blocking reason and the distance to the phase exit criterion.
  Separate real milestone work from review-generated polish, because a
  sweep can produce many P2 entries that must not be budgeted as
  milestone scope.
* `add`: write one new file per item agreed in conversation, with a
  timestamp id and a `ref`. An item proposed by Claude but not yet
  confirmed by the author carries `status: open` and says in its notes
  that it awaits her confirmation, so an unconfirmed item is never read
  as decided. Items that need a non-delegable seat (product owner,
  domain expert, numerical analyst) are registered as questions to the
  author, not as decided scope.
* `next`: propose the next work window: which items, in what order,
  with what acceptance criteria, against the current phase exit
  criterion in `docs/M1_EXECUTION_PLAN.md`. Never decide alone; iterate
  with the author, then `add` the agreed items. `next` produces the proposed
  window and registers the items; it does not write
  `NEXT_SESSION.md` in the management root, which the handoff skill owns
  and refreshes
  at session close (`/handoff out`) drawing on this window, so the forward
  prompt keeps a single writer.

## Validating the ledger

After writing, validate the folder so a malformed entry surfaces now
rather than in a later session. The checker for the one-file-per-entry
shape is the shared-kit `check_plan_kit.py`. It supersedes this repo's
former `check_plan_entries.py` and the sister repository's `check_plan.py`:
both were live one-file-per-entry folder validators (neither a CSV
validator), and the only reason two could not coexist was that their
status and priority vocabularies conflicted. That conflict is the
coordination decision `COORD-vocab`, settled before the kit vendored a
single checker; `check_plan_kit.py` keeps every strict guard this repo
had (timestamp id, required `ref`, dropped-must-say-why, reject-unknown)
and widens the vocabulary to the union of both, so every existing itaca
entry still validates.

Resolve the checker from configuration, never from a machine-absolute
literal in this committed file. This mirrors exactly how the incident
ledger is located by `ITACA_INCIDENT_LEDGER` (CLAUDE.md, Incidents; and
`.claude/hooks/role_review_gate.py`): a hard-coded personal path would
publish one machine's layout into a public repository and be wrong on
every other clone, with a remedy the reader cannot perform.

The environment variable is `ITACA_PLAN_VALIDATOR`. Read it; never
assume a path.

- It names the directory holding `check_plan_kit.py`, or the checker
  file itself. If it points at a directory, look for `check_plan_kit.py`
  inside it.
- **Unset means the check is skipped**, not failed: a clone that never
  configured the validator can still work, exactly as an unset incident
  ledger does not apply. Say plainly in the session record that the
  ledger was written but not machine-validated, so the skipped check is
  visible and not mistaken for a pass.
- Set but pointing at no readable checker is a configuration error to
  report to the author, not a silent skip.

When it is set and readable, run it against the ledger folder. Both
arguments are **resolved absolute paths**: the checker is external, so a
path relative to this repository stops meaning the ledger as soon as the
root moves. Resolve the ledger first: it is `plan/` under the resolved
management root, resolved per CLAUDE.md including its unset and invalid
branches. Then substitute that path. Both forms below take that same
argument and both must be kept correct; fixing one and leaving the other
is how this breaks quietly.

These blocks are bash, which is the shell this skill is allowed. In
PowerShell the variables are `$env:ITACA_PLAN_VALIDATOR` and
`$env:ITACA_MANAGEMENT_ROOT`; a bare `$NAME` there expands to nothing
and the resulting error names a missing file, which reads misleadingly
as though the checker had moved.

```bash
python "$ITACA_PLAN_VALIDATOR/check_plan_kit.py" "<resolved ledger path>"
```

or, when the variable names the file directly:

```bash
python "$ITACA_PLAN_VALIDATOR" "<resolved ledger path>"
```

Read the entry count, not just the exit code. A folder that does not
exist is refused loudly (`not a directory`, non-zero), but an **empty**
folder reports `no entries` and exits **zero**, so a run against the
wrong path can look like a pass. Verified 2026-07-27. The count in the
output is what distinguishes a clean ledger from an empty one, and it
should match the number of entry files you expect.

A non-zero exit names the file and the failing check (a bad header, an
illegal `status` or `priority`, a `dropped` entry with no reason, an
empty body, an id that does not match the filename or the timestamp
shape, or a repeated id). Fix the entry and re-run; a validator that is
run and ignored is the same as no validator.

`check_plan_kit.py` is now a stamped shared-kit artifact: its canonical
master lives at the coordination level and the copy this skill runs is a
derived, drift-pinned vendoring of it. A change to the checker is made in
the kit and re-vendored, never hand-edited here. Its mutation companion
`check_plan_kit_mutations.py` sits beside it and is exercised by
`tests/test_plan_validator.py`, so a checker that silently stopped
failing is caught by the suite.
