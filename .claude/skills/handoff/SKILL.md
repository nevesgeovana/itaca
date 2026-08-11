---
name: handoff
description: Session closure documentation for itaca. Writes the outgoing session handoff under the management root's handoffs/, refreshes its NEXT_SESSION.md forward prompt, and can also ingest an incoming capture. Use at the end of every working session, when a session must hand its context to an integrator who was not in the room, or when a capture from another session or a web thread needs to be folded into itaca's state.
argument-hint: "[out|in <file>]"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
side-effects: writes handoff briefs, the forward prompt and plan ledger entries under the management root; MAKES A COMMIT in this repository
---

Operation: `$ARGUMENTS`

Name the operation explicitly: `out` to write this session's closure, or
`in <file>` to ingest a capture. There is no bare default, because `out`
writes files and a commit and `in` needs its file argument; a missing or
ambiguous argument stops and asks rather than guessing.

A handoff is the continuity record of a session: what happened, what was
decided, and the one thing that would otherwise die when the session
ends. It is read by a session with none of this context, so its whole
value is in not making that session rediscover what is already known.
A handoff is a continuity record, not verified evidence: an ingested
claim is not true until this repository proves it.

Session documents live under the management root, never committed to
this repository: handoffs under its `handoffs/`, the working plan ledger
at its `plan/`, the forward prompt at its `NEXT_SESSION.md`. The design
documents (SRS sources, decision log companions) and the public surface
live in the repository; the closing commit covers only repository
changes, never the session documents.

The management root is `$ITACA_MANAGEMENT_ROOT`, resolved exactly as
CLAUDE.md ("Where the session documents live") defines it, including
what to do when it is unset or invalid. Resolve it before writing
anything, state the resolved root and which resolution branch produced
it in the handoff, and write to that path; a handoff written to an
assumed path that nobody reads is the failure this indirection exists to
prevent.

This skill owns `NEXT_SESSION.md` in that root: `out` and `in` are its only
writers. The plan skill's `next` produces the proposed window but does
not write the file; `out` draws that window in when it refreshes the
forward prompt, so the forward prompt has one owning skill.

All handoff content obeys the workspace guards: English only, American
English with Z, no em dashes or en dashes anywhere, no employer or
proprietary data, and no copy of a fact that already has a home. What is
recorded in `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`,
`docs/M1_EXECUTION_PLAN.md`, `docs/srs/`, or a plan entry is pointed at,
not repeated. Cite REQ, DD, and OQ ids wherever a claim rests on one, so
the reader can verify it at its source.

## `out`

Write `<management root>/handoffs/HANDOFF_<lane-or-topic>_<YYYY-MM-DD>.md`
(itaca uses a descriptive name, not a numbered sequence; the folder was
created in this shape and has no HND counter). Keep it under two pages,
with:

1. State, checked and not assumed: where `origin/main` is, whether the
   tree is clean, what is unpushed, and which commits shipped this
   session. Verify with git; do not assume.

   Verifying that it BUILDS is a separate step and it runs LAST, after
   this skill's own closing push; see "Closing CI check" below. Do not
   answer it here with `git ls-remote` or `git rev-list HEAD --not
   --remotes`: both answer questions about REFS and neither can go red
   when the build does.
2. Context: the session objective as stated at the start, and what
   actually happened, in one paragraph.
3. Decisions, each marked decided or proposed, with who decided.
   Decided-by-the-author items name her seat (product owner, domain
   expert, numerical analyst) where the call was hers.
4. Changes persisted: file paths, commits, and the test and CI status,
   named honestly per commit (which passes actually ran, since the
   attestation records what ran, not what was intended).
5. Open questions and contradictions, each routed to its home: a design
   question to `docs/OPEN_QUESTIONS.md`, approved scope to
   `docs/M1_EXECUTION_PLAN.md`, everything else to a plan ledger
   entry via `/plan`.
6. The single highest-value next action, and why it is next.

Then refresh the root's `NEXT_SESSION.md` from the window proposed by
`/plan next` (or the current ledger state if none was proposed) so the
next session opens against a current forward prompt, and commit the
repository-side changes of the session (the session documents themselves
are not committed).

### Closing CI check (the LAST step, after the closing push)

**Run this after the closing commit has been pushed, never before**, and
name the commit that was actually pushed:

    python .claude/tools/closing_ci_check.py --workflow CI --sha <pushed tip>

Placement is the whole point and it was wrong once: this used to sit in
item 1, above a closing commit and push that this skill itself makes, so
it answered about the state BEFORE the handoff's own push and a closing
commit that reddened CI was never asked about. Run last, or it verifies
the wrong tree.

`--workflow CI` is not optional and `--sha` is not decoration. With no
workflow named the checker downgrades a green to UNKNOWN, deliberately,
because a verdict over whatever runs happen to be indexed is not a
verdict; and with no `--sha` it answers about HEAD, which after a
session-document commit is not the commit that was pushed.

Read the EXIT STATUS, not the wording. Only 0, GREEN, permits this
handoff to call the work closed, successful, clean, or done. On RED (1),
RUNNING (3), UNKNOWN (4) or UNPUSHED (5), write what the checker names:
the work is PUSHED with CI state NOT VERIFIED, naming the sha and the
reason. RUNNING is the ordinary state right after a push and it resolves
in minutes, so waiting and re-running is usually the cheapest honest
path to a close; reporting NOT VERIFIED is the correct outcome, not a
failure of the session.

`INC-20260811-1745-itaca` is why this step exists: CI was red on `main`
for three consecutive pushes and every one of those sessions had checked
that its push landed.

### Public-surface pause point (confirm before the closing commit)

If the session changed anything user-visible (public API, behavior,
error messages, deprecations, examples), confirm before committing that:

1. `CHANGELOG.md` records the change in the Keep a Changelog format
   (REQ-94), under the right heading (Added, Changed, Deprecated,
   Removed, Fixed, Security);
2. the public pages it invalidates moved with it: README claims, the
   `examples/` that demonstrate it, and any docstring the change makes
   stale (immutability and provenance claims under REQ-18, the
   read-only-array guarantee under REQ-102, are load-bearing and often
   the first to drift);
3. the requirement statuses in `docs/srs/` match reality: anything
   marked implemented still names evidence that exists, and anything
   shipped this cycle appears as a requirement or an amendment, with the
   revision history and Chapter 11 updated together.

A session that cannot complete an item records it as a plan ledger
item in the same close, with a `ref`; silent deferral is the failure
mode this pause point exists to prevent.

### Review and gate reminder

Before the closing commit and any push, the `role-review` skill has run
its applicable passes (architect-reviewer, qa-engineer, vv-engineer,
tech-writer, api-designer; charters in `.claude/agents/`) and every
finding is fixed or registered. The `git push` gate
(`.claude/hooks/role_review_gate.py`) denies until the attestation
covers every commit the push makes new; the handoff does not write the
attestation, `role-review` does. If a defect appeared this session, the
`incident-analyst` charter governs its record: the fix carries a guard
and the evidence that the guard blocks the original failure, and an open
blocking incident stops the push.

## `in <file>`

Read the given file (typically a capture from another session or a web
thread). Then:

1. Extract decisions, findings, and next actions, and mark each as
   decided or proposed with its source.
2. Fold the forward-looking parts into the root's `NEXT_SESSION.md`, and
   stage candidate items through `/plan add` (so each gets a timestamp id
   and passes the ledger validator, rather than being written straight
   into the ledger folder) as `status: open`, with a note that they await
   the author's confirmation, for her to accept via `/plan`. itaca plan
   statuses are `open`, `doing`, `done`, `dropped`;
   there is no separate proposed state, so an unconfirmed item is an
   `open` item whose note says so.
3. File the capture into the root's `handoffs/` under the
   descriptive-name shape so the record is kept.

Never mark an ingested claim as verified without evidence from this
repository (a passing test, a committed report, or a citation to the
SRS or the decision log). An ingested claim that overstates its own
evidence is exactly the defect class the incident rule exists to catch.
