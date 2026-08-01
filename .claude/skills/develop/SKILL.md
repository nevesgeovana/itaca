---
name: develop
description: Execute one itaca work item end to end, in the repository's own order: pin the item to an authority, usage example, falsifying test measured RED on the base, minimal implementation, refactor, records in the same step, gate, commit, then review. Use whenever a work item is about to be implemented, whether it comes from the milestone execution plan, the plan ledger, a review finding, or the author directly. Planning is the plan skill, closure is handoff, and the reviewer passes are role-review; this skill covers the middle, where the change is actually made.
argument-hint: "<plan ledger id | REQ/DD/OQ id | one sentence naming the item>"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, Skill
side-effects: writes source, tests and docs in this repository; writes plan ledger entries and session records under the resolved management root; makes commits
disable-model-invocation: true
---

Work item: `$ARGUMENTS`

This skill exists because planning, auditing, closing and reviewing each
had one and developing did not, so the highest-ceremony part of the
process ran from prose that had to be reconstructed every session
(REV007-007). It is a **loading order, not a second rulebook**. Every rule
it needs already lives in `CLAUDE.md`, `docs/srs/`, `docs/DECISIONS.md`
and the plan ledger's `README.md`; this file points at them and never
restates them. A rule copied in here is a rule that will drift, which is
REV007-005 in miniature.

## 1. Pin the item to an authority, before touching anything

An item that cannot name a **REQ, DD or OQ id** is not ready to
implement. Find it or ask the author; do not infer the requirement from
the code, which makes the code its own specification.

Then resolve, in this order and stopping at the first that fails:

* **The management root**, named by `ITACA_MANAGEMENT_ROOT` and resolved
  exactly as `CLAUDE.md` ("Where the session documents live") defines it,
  including its unset and invalid branches. Read the variable; never
  assume a path. State the resolved root and which branch produced it in
  the session record. Every ledger and record path below is under the
  **resolved** root, never a literal.
* **The requirement's status.** A requirement tagged **draft** may be
  implemented and must never be frozen without the author's confirmation
  (`CLAUDE.md`, "Gate before coding draft requirements"). If the item
  would settle draft behavior, that is a question to the author, not a
  judgment call. Say which of the two it is before writing a test.
* **The item's ledger entry.** If the item has one, set it `doing`. If it
  has none and it is real work, register it first with the `plan` skill;
  work that exists only in a transcript is work nobody can find.
* **Whether the SRS and `CLAUDE.md` agree** on the behavior at issue. If
  they do not, the SRS wins and the discrepancy is reported to the
  author, never patched silently.

## 2. Usage example first

Write the call as a user would make it, in the docstring `Examples`
section or in `examples/`, before any test. It is the first place a wrong
interface is cheap to fix, and it is what `api-designer` will read.

**When the item is a defect fix with no new interface**, there is no new
call to write and this step is the reproduction instead: the shortest
call that exhibits the defect, in the test module's own docstring. Skip
the step only when you can say which existing example already covers the
call, and say it.

## 3. The falsifying test, measured RED on the base

This is the whole technical content of TDD and the only part of it a
final diff can evidence, so it is the one step this skill asks you to
**record a measurement for**.

Write the test that fails for the item's reason. Run it against the tree
**as it is, before the implementation exists**, and keep the output: the
test id and the way it failed.

* Read the exit status **from the process**, never through a pipe. A
  `pytest ... | tail` has reported exit 0 for a run that exited 4.
* A test that errors on an import or a missing name is not yet a
  falsifying test. Make it fail on the **assertion**, so what turns it
  green is the behavior and not the existence of a symbol.
* If the test is green before the implementation, the item is either
  already done or the test does not measure it. Both are findings; stop
  and say which.
* **Measure the carrier, never the mention.** A guard satisfied by an id
  in a comment, a docstring or an assertion message is not a guard. This
  repository has paid for that three times in one session.

## 4. Minimal implementation, then refactor

Make that test pass and nothing more. Then refactor with the suite green.
Scope beyond the item goes to the ledger, not into the diff.

**Before an edit made under review pressure**, the rule is "Design before
edit" in `.claude/kit/review-policy.md`. Read it there. It carries its own
measurement and the reason a one-line fix is the dangerous one, and it is
deliberately NOT repeated here: a rule restated in three places is a rule
that will disagree with itself, which is the whole reason it went into the
shared policy rather than into this skill.

## 5. Records in the same step, not as a closing pass

Whatever the change touches writes its record **in the same step**, so a
session that ends early leaves no undocumented change:

| the change touches | it also writes |
|---|---|
| public API or behavior | `CHANGELOG.md` |
| a requirement's meaning | `docs/srs/`, revision history and Chapter 11 together |
| a design question, resolved or raised | `docs/OPEN_QUESTIONS.md` |
| a decision about why | `docs/DECISIONS.md`, append-only, never edited |
| anything else worth finding later | a plan ledger entry, via the `plan` skill |

A defect found on the way is governed by `CLAUDE.md` ("Incidents"): fixed
at its structural cause on its first occurrence, carrying a guard and the
evidence that the guard blocks the original failure.

## 6. Definition of done, by pointer

Coverage, ruff, `mypy --strict`, NumPy docstring sections, the three-part
error message, the import policy, Conventional Commits: all of it is in
`CLAUDE.md` ("Development rules") and the SRS. Read them there.

**Run the repository's own gate rather than a command written here.** The
gate is `.pre-commit-config.yaml`, and it moves: naming its commands in
this file would make the skill stale the week the tiers change again.
Committing runs the commit tier; pushing runs the full suite with
coverage. Both are hooks, so `pre-commit install` once per clone installs
every type it declares.

## 7. Commit, and only then review

**Review runs on a COMMITTED range.** This is a change of habit: the
`role-review` skill now opens one detached worktree per lens through
`.claude/kit/review_runner.py`, and a worktree cannot be opened on
uncommitted work. So commit first, review second, and fold the findings
in with `--amend` or a `--fixup`.

The commit message carries, in its body, the two things the diff cannot
show by itself: **the RED measurement from step 3** and a `Refs:` trailer
naming every REQ, DD, OQ and ledger id the item touched.

Then invoke the `role-review` skill over the committed range. It decides
which passes apply, runs the reviewer agents, and drives every finding to
fixed or registered. The reviewer charters in `.claude/agents/` pin their
own model and effort; nothing here overrides them.

The push gate and the attestation belong to `role-review` and to the
moment of the push. This skill does not write an attestation, and a
session that reviews without pushing records its review where the next
session will find it, in the resolved root, and says plainly that the
full suite has not yet run over those commits.

## 8. Close the item

Set the ledger entry `done`, citing its evidence: the commit, the test
run, or the committed report. An item closed without evidence is the
false-closure failure this workspace already records; verify the closure
against the code, never against the plan.
