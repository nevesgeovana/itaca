---
name: role-review
description: Run the role-based reviewer passes (architect, QA, V&V, tech writer, API designer) on a work item's diff and drive every finding to fixed or registered. Use before closing any work item; the development rules cite this skill.
argument-hint: "[git range | staged | last-commit]"
allowed-tools: Task, Bash, Read, Write, Edit, Grep, Glob
disable-model-invocation: true
side-effects: creates and removes review worktrees; writes findings  # role-review
---

Role-based review per the team-role model adopted 2026-07-23 (DD-23
records the shared process with the sister pyflightstream
repository): the implementer never closes an item as its only
reviewer. Each pass is an agent from `.claude/agents/` with its own
charter; this skill decides which passes apply, runs them, and
enforces the update-or-fix rule on their findings. The charter
template is documented in `ROLE_TEMPLATE.md` next to this file.

## 1. Resolve the work item's diff

**THE WORK MUST BE COMMITTED BEFORE THIS SKILL RUNS.** Review happens on
a committed range, never on a dirty tree. If you have uncommitted work,
commit it first; when the findings land, `git commit --amend` or a
`--fixup` on top is how you fold the fixes in. That pushes toward
smaller and more frequent commits, which is the direction this
workspace already wants.

This changed on 2026-07-30 when the isolated runner was installed (step
3), and the reason is written here because a rule whose reason is
missing gets reverted by the next person who finds it annoying:

1. **The rest of the system already assumes committed.** The push gate
   reads the unpushed range, and `write_attestation.py` has refused on a
   dirty tree since kit 0.2.9. Dirty-tree review was the outlier here,
   not the norm.
2. **It does not reduce the incident that motivated the isolation, it
   REMOVES it.** A reviewer ran `git restore` in the live tree and
   destroyed a lane's edits; those edits were uncommitted. On a detached
   worktree at a ref there is nothing uncommitted left to destroy.
3. **It is affordable only because the commit tier is fast.** Committing
   before review is real friction at a five-minute commit gate and
   nothing at a thirty-second one. The two shipped together, deliberately.

`$ARGUMENTS` may be a git range (`main..HEAD`, `HEAD~2..`) or
`last-commit`. Default when empty: the unpushed range, `git rev-list
HEAD --not --remotes`, which is exactly what the next push would send
and therefore what the push gate will demand an attestation for.
Produce the file list and keep the item's intent in one sentence; the
reviewers receive both, and each reads its own worktree.

## 2. Decide the applicable passes

| Reviewer | Runs when the diff touches |
|---|---|
| architect-reviewer | public API; new or moved modules; imports (NumPy-only core rule); dependencies; anything contradicting a DD |
| qa-engineer | anything under `itaca/` or `tests/` |
| vv-engineer | requirement implementation status; `docs/srs/`; uncertainty mathematics; draft-tagged requirements (REQ-104 to REQ-106, the OQ-18 row of REQ-98); guarantee claims |
| tech-writer | public API, docstrings, README, CHANGELOG, `examples/`, SRS prose |
| api-designer | new or changed public signatures; error messages; examples |

Any code change runs at least qa-engineer and tech-writer. A
docs-only change runs tech-writer alone. When in doubt whether a
pass applies, it applies.

## 3. Run the passes

**Open one isolated worktree per lens FIRST.** A reviewer never receives
the live tree as its working directory:

```
python .claude/kit/review_runner.py open . <lens> [<lens> ...]
```

It prints one line per lens, tab separated, with FIVE fields:

```
<lens>	<worktree>	<diff>	<paths>	<findings>
```

The worktree is a DETACHED, PRISTINE checkout of the reviewed ref. The
other three are ABSOLUTE paths to `RR_DIFF.patch`, `RR_PATHS.txt` and an
empty `RR_FINDINGS.md`, and they sit in a sidecar directory BESIDE the
worktree, not inside it. Give each reviewer its own worktree as the
directory to work in AND the three paths; a lens told to look in its own
directory for them finds nothing. Pass `--base <rev>` when the range is
not the unpushed one.

Read the five fields by splitting on the tab; do not assume the file
names or reconstruct the paths from the worktree, which is exactly the
assumption kit 0.2.15 invalidated.

This is `REV007-003`, and it answers two recorded failures with one
structural cause, reviewers executing inside a tree someone else is
mutating: a lens ran `git restore` in the live tree and destroyed a
lane's edits, and two Bash-holding lenses shared one worktree and
corrupted each other's measurements (`ITC-20260730-0250`). Until this
was vendored, the charters' prohibition paragraphs were the only
control, and a prohibition is not a mechanism.

**Why the three files moved out, and why no lens prompt should mention
them again.** They used to live inside the worktree, where they are
untracked-but-not-ignored, so this repository's own house-style walk
scanned them; `RR_DIFF.patch` contains the diff, so any diff touching a
file that quotes the author's name made every lens report a RED that does
not exist on the reviewed ref. Lane ITA-4 measured it twice, from two
independent lenses, and worked around it by carrying an "ignore these
files" paragraph in all four lens prompts. That paragraph is now WRONG
and must not be reintroduced: the defect is fixed at its cause
(`ITC-20260801-1600`), the worktree is pristine under any scanning
discipline, and a prompt that still names the workaround teaches the next
lane that it is needed.

Then spawn every applicable reviewer in parallel (one Agent call each),
passing its worktree path, the git range, and the intent sentence. Do
not summarize the diff for them beyond that; their charters tell them
what to read. Wait for all passes before acting on any finding.

Close the worktrees when every pass has reported, and only then:

```
python .claude/kit/review_runner.py close .
```

`close` collects EVERY `RR_FINDINGS.md` first and only then attempts the
removals, continuing past any it cannot make and exiting 1 with each
failure named. A lens still running inside its own worktree is the
ordinary case, not an exceptional one, and it no longer strands the
worktrees after it or destroys their findings (`ITC-20260801-0130`). A
crashed run deliberately leaves the trees on disk for inspection, and a
later `close` still finds them, so never remove one by hand.

**Run `close` with the body you opened with.** The shared temp root is
keyed on the repository's name AND a digest of its path, so a worktree
opened by an older body is not found under a newer root. Before
re-vendoring this artifact, close first and confirm with
`git worktree list`.

The five gated charters pin `model: opus` and `effort: low` in their
own frontmatter (author decision 11, BRF-064, installed 2026-07-30),
so you do not pass either on the Agent call and must not override
them. The reason is independence: without the pin a reviewer inherits
the IMPLEMENTING session's model, so a lane running a weaker model
reviews its own work with a weaker reviewer, exactly when that matters
most. `tests/test_house_style.py` pins it in both directions;
`incident-analyst` is deliberately unpinned here because it is a
kit-derived body whose pin arrives by re-vendor.

**The falsifiable safeguard, recorded and deliberately not built.** If
the count or quality of findings per review drops after the effort
pin, the RELEASE tier returns to `effort: high` by the author's
decision. The falsifier is the record already being written: findings
per review are countable in the review rounds and attestations, so
"did low reduce what reviews catch" is a measurable claim rather than
an impression. Do not build tooling for it; the claim needs only the
numbers already there.


## 4. Update or fix, never leave for later

For each finding, in severity order: fix it in-session, or append it
to `docs/OPEN_QUESTIONS.md` with the next free OQ id (design
questions), or to the current milestone execution plan (approved
scope), or to the working plan ledger (the management root's `plan/`,
the root being `$ITACA_MANAGEMENT_ROOT` resolved exactly as CLAUDE.md
("Where the session documents live") defines it), one file per
entry, whose format is defined in that folder's own `README.md`
(everything else), or record in the session notes why it is not a
defect (with the reviewer named, so the disagreement is auditable).
Findings that
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
push until an attestation covers **every commit the push makes new**,
not the tip. Review the whole unpushed range: `git rev-list HEAD --not
--remotes` is exactly what the next push moves, and attesting only the
tip once let four ancestors ship unreviewed.

What the mechanism enforces is that such an attestation exists. It does
not prove these agents ran: the `passes` field is recorded and never
checked, and anything that can write the file clears the gate. That
last step rests on you. It exists because a past pyflightstream release
ran paraphrased manual checks instead of the agents, and the same
protocol applies here per the shared review process (DD-23).

As the closing step, after every applicable pass has run and every
finding is fixed or registered, and after the reviewed work is
committed (the attestation names the commits that will be pushed):

```
python .claude/hooks/write_attestation.py review architect,qa,vv,tech-writer,api-designer
```

Pass the passes you actually ran. For a milestone release tag (a
`vX.Y.Z` push), also run the full-scope review of the release diff and
write the release attestation:

```
python .claude/hooks/write_attestation.py release architect,qa,vv,tech-writer,api-designer v0.2.0
```

Pass the tag as the third argument. The script stamps HEAD by default,
and a tag that sits behind HEAD would never become covered, so the gate
would deny a command that looks correct.

Push the branch and the tag by name, in separate commands.
`--follow-tags`, `--tags`, `--all` and `--mirror` are denied: the gate
cannot resolve what they send without asking the remote, and
`--follow-tags` is how an unattested tag reached a publish workflow
once. Keep the attestation write and the push in separate commands too,
since the hook reads the whole command string and would see the push.

The script stamps the named ref together with every commit not yet on a
remote, into `.claude/.role_review_attestation.json` (local,
gitignored). A commit made after attesting re-arms the gate until you
re-review and re-attest: an unreviewed commit never ships. Never write
the attestation without running the agents.
