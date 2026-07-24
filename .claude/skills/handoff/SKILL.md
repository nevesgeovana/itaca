---
name: handoff
description: Session closure documentation for itaca. Writes the outgoing session handoff under _private/handoffs/, refreshes the _private/NEXT_SESSION.md forward prompt, and can also ingest an incoming capture. Use at the end of every working session, when a session must hand its context to an integrator who was not in the room, or when a capture from another session or a web thread needs to be folded into itaca's state.
argument-hint: "[out|in <file>]"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
disable-model-invocation: false
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

Session documents live in `_private/` (a local synced junction),
never committed: handoffs under `_private/handoffs/`, the working plan
ledger at `_private/plan/`, the forward prompt at
`_private/NEXT_SESSION.md`. The design documents (SRS sources, decision
log companions) and the public surface live in the repository; the
closing commit covers only repository changes, never the session
documents.

All handoff content obeys the workspace guards: English only, American
English with Z, no em dashes or en dashes anywhere, no employer or
proprietary data, and no copy of a fact that already has a home. What is
recorded in `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`,
`docs/M1_EXECUTION_PLAN.md`, `docs/srs/`, or a plan entry is pointed at,
not repeated. Cite REQ, DD, and OQ ids wherever a claim rests on one, so
the reader can verify it at its source.

## `out`

Write `_private/handoffs/HANDOFF_<lane-or-topic>_<YYYY-MM-DD>.md`
(itaca uses a descriptive name, not a numbered sequence; the folder was
created in this shape and has no HND counter). Keep it under two pages,
with:

1. State, checked and not assumed: where `origin/main` is, whether the
   tree is clean, what is unpushed, and which commits shipped this
   session. Verify with git; do not assume.
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
   `docs/M1_EXECUTION_PLAN.md`, everything else to a `_private/plan/`
   entry via `/plan`.
6. The single highest-value next action, and why it is next.

Then refresh `_private/NEXT_SESSION.md` so the next session opens
against a current forward prompt, and commit the repository-side changes
of the session (the session documents themselves are not committed).

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

A session that cannot complete an item records it as a `_private/plan/`
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
2. Fold the forward-looking parts into `_private/NEXT_SESSION.md`, and
   stage candidate items through `/plan add` (so each gets a timestamp id
   and passes the ledger validator, rather than being written straight
   into `_private/plan/`) as `status: open`, with a note that they await
   the author's confirmation, for her to accept via `/plan`. itaca plan
   statuses are `open`, `doing`, `done`, `dropped`;
   there is no separate proposed state, so an unconfirmed item is an
   `open` item whose note says so.
3. File the capture into `_private/handoffs/` under the descriptive-name
   shape so the record is kept.

Never mark an ingested claim as verified without evidence from this
repository (a passing test, a committed report, or a citation to the
SRS or the decision log). An ingested claim that overstates its own
evidence is exactly the defect class the incident rule exists to catch.
