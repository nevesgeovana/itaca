<!--
ITACA / pyflightstream shared process kit
kit-version: 0.2.15
artifact: version-control.md
body-sha256: b8119d989a4b1acf9f3913e4f478a643f34ed1506ff4552c9518ffeb49594a0b
canonical-source: BUILT for the kit (0.2.15, HUB-11) from the author's proposal of 2026-08-01. In two lanes the push step failed five separate ways and none of them was about the code; three of the five are addressed by carrying the correct sequence as a template so an operator does not reconstruct it, at a fraction of the cost of the two the pre-push receipt addresses. Records: ITC-20260801-2330, ITC-20260801-0900, coordination/DESIGN_HUB-11_kit_batch.md item 2.
note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
END KIT PROVENANCE (body verbatim below)
-->
---
name: version-control
description: The correct sequence for committing, attesting and pushing in a repository carrying the shared push gate, with the verification step that does not trust an exit code. Use whenever work is about to be committed or pushed, when a push was denied and the reason is not obvious, when a push appeared to fail but may have succeeded, or when staging a change that other sessions may share the tree with. It carries the sequence as a template so it is not reconstructed from memory.
allowed-tools: Bash, Read, Grep, Glob
side-effects: none
---

# Committing and pushing, in the order that works

This skill exists because the push step is where lanes lose time to
failures that have nothing to do with the code. In two measured lanes it
failed five separate ways in one evening:

1. a redirection flag after `git push` in the same command string, denied
   by the review gate reading it as a ref it could not resolve;
2. an agent background task killed inside the suite, twice, for a cause
   that is NOT established;
3. `pytest` and `mypy` absent from PATH because the shell had no
   environment activated, so the hook refused, correctly and fail-closed;
4. a PowerShell PATH assignment sent to a bash shell;
5. an in-session shell with a two-minute timeout, so a thirteen-minute
   hook could not run there at all.

Three of those, 1, 3 and 4, are answered by following the sequence below
rather than by any mechanism. Number 5 is answered by the pre-push
receipt, `prepush_receipt.py`, which stops the suite being run a second
time on content that already passed. Number 2 is NOT answered by anything
here, and its cause is not known; do not record it as known.

## The rule this whole file follows from

**The push gate is a `PreToolUse` hook.** It inspects the WHOLE command
string BEFORE anything in it runs. Everything below follows from that one
fact:

- A string that commits and then pushes is checked against a state in
  which the commit does not exist yet.
- A string that writes the attestation and then pushes is denied before
  the attestation is written.
- A flag after `git push` is read as part of the push, including a
  redirection the shell would have consumed.

So: **five separate commands, in this order, with nothing appended to any
of them.**

## 1. Activate the environment, and prove it

A hook that runs `pytest` or `mypy` finds them only if the environment is
active in the shell the hook inherits. An inactive environment produces a
refusal that looks like a tooling failure and is not one.

Activate using the syntax of the shell you are actually in. Sending a
PowerShell assignment to a bash tool, or the reverse, is one of the five
measured failures and it does not announce itself; it produces a command
not found, or nothing at all.

    # PowerShell
    .\.venv\Scripts\Activate.ps1

    # bash / git-bash
    source .venv/Scripts/activate     # Windows layout
    source .venv/bin/activate         # POSIX layout

Then PROVE it, in the same shell, before relying on it:

    python -c "import sys; print(sys.prefix)"

If that does not print the repository's own environment, nothing after it
is trustworthy. Do not proceed by adding a directory to PATH by hand;
activate properly, because PATH edits are per-shell and the next tool call
may be a different shell.

## 2. Commit, staging BY PATH

    git add <path> <path> ...
    git commit -m "<message>"

**Never `git add .`, `git add -A`, or a directory.** Another session, an
agent, or a generated artifact may hold changes in the same tree, and a
directory-wide stage commits work you did not make and cannot describe.
This is the tree-ownership rule and it is not advisory: never revert,
restore, checkout, stash or commit a change you did not make.

If the tree carries changes that are not yours, stage only your paths and
say in the message what the commit covers.

## 3. Attest, as its own command, with no pipe

    python .claude/hooks/write_attestation.py review <passes> <ref> [<ref> ...]

Three things, each of which has failed at least once:

- **Its own command.** Not joined to the push by `&&`, `;` or a newline.
  The gate would see the push in the same string and deny before this
  runs.
- **No pipe.** A piped command's exit status is the pipeline's, not the
  writer's. Read the status from the process.
- **Cover the whole range.** The attestation must cover every commit the
  push makes new, plus the ref being pushed. Review the unpushed RANGE,
  not the tip:

      git rev-list HEAD --not --remotes --oneline

  If that lists more than one commit, the review had to cover all of
  them. The writer says so in its own output when it does.

`<passes>` is the comma-separated list of the reviewer passes that
ACTUALLY ran. It is an audit record. A pass named here that did not run is
a false statement in the one file whose job is being trustworthy.

## 4. Push, alone

    git push origin <branch>

Nothing appended. No `2>&1`, no `> log.txt`, no `&& echo done`, no second
command after a semicolon. A redirection after `git push` was denied by
the gate as an unresolvable ref, which is the gate failing CLOSED and
doing its job; the fix is the command, not the gate.

Push a SISTER repository with `git -C <repo> push origin <branch>`, so the
gate resolves that repository's own rules rather than the current
directory's.

## 5. Verify on the remote, NOT by the exit code

**This is the step most often skipped and it is the one that is load
bearing.**

    git ls-remote origin <branch>
    git rev-list HEAD --not --remotes

The first prints the commit the remote now holds; compare it to your
`HEAD`. The second must print NOTHING when the push succeeded: anything it
prints is a commit the remote does not have.

WHY, and it is mechanical rather than stylistic. PowerShell 5.1 wraps a
native command's stderr into an ErrorRecord and sets `$?` to false even
when the process exited 0, and `git push` writes its progress to stderr.
So a SUCCESSFUL push reads as a failure, and a session that trusts the
status will re-push, re-run a suite, or conclude that work was lost that
was not. The remote's own answer is the only trustworthy one.

The same reasoning applies in reverse: never redirect a native command's
stderr in PowerShell to make it look clean. It changes the status you are
about to read.

## If the push is denied

Read the deny message; it names its own category.

- `[config]` and a variable name: the incident ledger variable is not set
  in this shell. An ABSENT ledger DENIES, deliberately, because an
  unreadable ledger cannot prove that no blocking incident exists. Export
  it and try again.
- A blocking incident: the ledger holds an open blocking record naming
  this repository. It is fixed or downgraded through the incident process,
  never worked around.
- A review refusal: the attestation is missing, or covers fewer commits
  than the push makes new. Re-read step 3, including the range.
- An unresolvable ref: something was appended to the push. Re-read step 4.

**Never `--no-verify`.** Every mechanism above exists because a step was
routed around once.

## What this skill does not do

It runs nothing and enforces nothing. It is the sequence written down so
that it is not reconstructed under pressure. Every refusal it describes
still fires exactly as before if it is ignored.

It also does not cover merges, conflicts, branching strategies or multiple
remotes. The repositories it was written for carry linear history and one
remote, and describing a workflow nobody here runs would be a worse lie
than saying so.
