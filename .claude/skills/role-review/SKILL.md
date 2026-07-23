---
name: role-review
description: Run the role-based reviewer passes (architect, QA, V&V, tech writer, API designer) on a work item's diff and drive every finding to fixed or registered. Use before closing any work item; the development rules cite this skill.
argument-hint: "[git range | staged | last-commit]"
---

Role-based review per the team-role model adopted 2026-07-23 (DD-23
records the shared process with the sister pyflightstream
repository): the implementer never closes an item as its only
reviewer. Each pass is an agent from `.claude/agents/` with its own
charter; this skill decides which passes apply, runs them, and
enforces the update-or-fix rule on their findings. The charter
template is documented in `ROLE_TEMPLATE.md` next to this file.

## 1. Resolve the work item's diff

`$ARGUMENTS` may be a git range (`main..HEAD`, `HEAD~2..`), `staged`,
or `last-commit`. Default when empty: the uncommitted changes
(staged plus unstaged) if any exist, else the last commit. Produce
the file list and keep the item's intent in one sentence; the
reviewers receive both and read the repository themselves.

## 2. Decide the applicable passes

| Reviewer | Runs when the diff touches |
|---|---|
| architect-reviewer | public API; new or moved modules; imports (NumPy-only core rule); dependencies; anything contradicting a DD |
| qa-engineer | anything under `itaca/` or `tests/` |
| vv-engineer | requirement implementation status; `docs/srs/`; uncertainty mathematics; draft-tagged requirements (REQ-101, the OQ-18 row of REQ-98); guarantee claims |
| tech-writer | public API, docstrings, README, CHANGELOG, `examples/`, SRS prose |
| api-designer | new or changed public signatures; error messages; examples |

Any code change runs at least qa-engineer and tech-writer. A
docs-only change runs tech-writer alone. When in doubt whether a
pass applies, it applies.

## 3. Run the passes

Spawn every applicable reviewer in parallel (one Agent call each),
passing the git range, the file list, and the intent sentence. Do
not summarize the diff for them beyond that; their charters tell
them what to read. Wait for all passes before acting on any finding.

## 4. Update or fix, never leave for later

For each finding, in severity order: fix it in-session, or append it
to `docs/OPEN_QUESTIONS.md` with the next free OQ id (design
questions) or to the current milestone execution plan (work items),
or record in the session notes why it is not a defect (with the
reviewer named, so the disagreement is auditable). Findings that
require a non-delegable seat (product owner, domain expert,
numerical analyst) become questions to the author, never an agent's
call. Re-run a reviewer only when its findings forced substantive
rework of the item.

## 5. Record the passes

The session close lists, per work item: the passes that ran,
findings fixed, findings registered, and questions raised to the
author. A clean pass is recorded as clean; silence is not a record.

## 6. Write the push attestation (mandatory, clears the git-push gate)

The `git push` gate (`.claude/hooks/role_review_gate.py`) blocks every
push until an attestation says these agent passes actually ran for the
exact commit being pushed. It exists because a past pyflightstream
release ran paraphrased manual checks instead of the agents; the
attestation is the mechanical proof that the real agents ran, and the
same protocol applies here per the shared review process (DD-23).

As the closing step, after every applicable pass has run and every
finding is fixed or registered, and after the reviewed work is
committed (the attestation names the commit that will be pushed):

```
python .claude/hooks/write_attestation.py review architect,qa,vv,tech-writer,api-designer
```

Pass the passes you actually ran. For a milestone release tag (a
`vX.Y.Z` push), also run the full-scope review of the release diff and
write the release attestation:

```
python .claude/hooks/write_attestation.py release architect,qa,vv,tech-writer,api-designer
```

The script stamps the current HEAD into
`.claude/.role_review_attestation.json` (local, gitignored). A commit
made after attesting re-arms the gate until you re-review and
re-attest: an unreviewed commit never ships. Never write the
attestation without running the agents.
