#!/usr/bin/env python3
"""Refuse to call a push CLOSED until CI has concluded green on it.

This is itaca's caller for the kit's ``ci_state.py``, on the POST-PUSH side
of the boundary. The gate (``.claude/hooks/role_review_gate.py``, kit
0.2.18) is the caller on the pre-push side and refuses a release-grade push
over a tag whose commit CI has not concluded green. This file is the other
half, and the two are deliberately not the same mechanism because they
answer at different moments about different things.

WHY IT EXISTS: ``INC-20260811-1745-itaca``. Every lane's closing sequence
proved the commits ARRIVED and never that they BUILD. ``git ls-remote`` and
``git rev-list HEAD --not --remotes`` both answer questions about the
remote's REFS, and neither can go red when the build does. Measured on
2026-08-02: CI was red on ``main`` for three consecutive pushes and no
session noticed, because every session had checked that its push landed.

THE GATE ARM CANNOT COVER THIS, which is the finding that made 1745 a
separate record rather than a duplicate. That arm fires only on an explicit
version TAG; its own companion PASSES on ``an ordinary branch push on a RED
commit is not this arm's business``. The three red pushes were ordinary
pushes to ``main`` with no tag in sight. Measured live on 2026-08-11 in this
repository: the same red commit denies ``[ci-red]`` when a tag names it and
is ALLOWED when it is pushed as a branch.

WHAT THIS DOES NOT DO, said first because it is the usual misreading. It
does not block a push. The push has already happened by the time this runs;
there is nothing left to prevent. It forbids the CLAIM. A lane that reports
itself closed is asserting that its work landed clean, and until now it made
that assertion without asking anything.

THE DECISION TABLE IS NOT HERE. ``ci_state.py`` is the kit's authority on
what CI concluded about one SHA, it already carries the four states and the
rule that UNKNOWN is never green, and this file BINDS it rather than
re-deriving it. Two mechanisms holding one rule in two vocabularies is how
they drift apart. What this file adds is the two things that body cannot
know: WHICH commit a close is about, and whether that commit is even on the
remote yet.

    GREEN     the lane may report the work closed
    RED       it may NOT; the report names the failing run
    RUNNING   it may NOT; it reports work pushed, CI NOT VERIFIED
    UNKNOWN   it may NOT; it reports work pushed, CI NOT VERIFIED, with why
    UNPUSHED  it may NOT; commits are still local, so no CI can exist

FAILING CLOSED IS THE LOAD-BEARING HALF and it follows the precedent this
repository already applies to ``COORD_INCIDENT_LEDGER``: a guard that reads
its own missing information as permission is not a guard. An absent
``ci_state.py``, an unresolvable repository, an argument this file will not
guess at, a ``gh`` that cannot answer, an exit code outside ``ci_state.py``'s
contract, and any exception raised inside this mechanism all refuse.

THAT SENTENCE USED TO END "there is deliberately no path through this file
that prints a success sentence over a question it could not ask", and the
first round of review falsified it three times over, so it is replaced by
what is actually true rather than repaired in place. The three paths were:
``--sha=<value>`` and any unknown flag parsed into nothing, so the checker
silently answered about HEAD; and a GREEN computed over NO NAMED WORKFLOW,
which is a verdict about whatever runs happened to be indexed. All three are
closed below, the first two in ``_parse`` and the third by DOWNGRADING a
workflow-less GREEN to UNKNOWN. The claim now is narrower and checkable:
**every state this file reports as GREEN was asked about a named workflow,
on a commit that is on a remote, by a body that ran.**

NAME THE WORKFLOWS. ``--workflow`` may be repeated, and passing none is not
the convenient default it looks like: ``ci_state.py`` only applies its "a
named workflow that has not appeared is UNKNOWN, not absent" rule to names
it was given. In this repository the workflow that must have run for an
ordinary branch push is ``CI``; the others are ``workflow_call`` targets or
fire on a tag.

Exit status, which is the whole interface and is ``ci_state.py``'s own
contract with one addition: 0 GREEN, 1 RED, 3 RUNNING, 4 UNKNOWN, 2 a CONFIG
error, and 5 UNPUSHED, which is this file's own and is not a CI state. 5 is
free in the upstream contract today and a test asserts it stays free, so an
upstream renumbering breaks a test rather than a close.

Usage:
    closing_ci_check.py [--sha <sha>] [--repo <path>] [--workflow <name> ...]

    # this repository's closing invocation
    closing_ci_check.py --workflow CI
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

GREEN, RED, RUNNING, UNKNOWN = "GREEN", "RED", "RUNNING", "UNKNOWN"
EXIT = {GREEN: 0, RED: 1, RUNNING: 3, UNKNOWN: 4}
CONFIG = 2
UNPUSHED = 5

#: ``ci_state.py``'s documented exit contract, read as a MAPPING. A value
#: outside it is UNKNOWN, so a state added there can never arrive here as a
#: silent pass.
CI_EXIT_STATE = {0: GREEN, 1: RED, 3: RUNNING, 4: UNKNOWN, 2: "CONFIG"}

CI_STATE_NAME = "ci_state.py"
#: Where a vendored ``ci_state.py`` may sit, relative to the repository root,
#: and it lists ONLY the two directories whose contents are drift-pinned.
#:
#: The first version searched beside this file as well, and an architecture
#: lens measured what that opens: this file lives in ``.claude/tools``, which
#: `tests/test_kit_drift.py` does not sweep, so an unpinned `ci_state.py`
#: dropped next to it would SHADOW the vendored copy and be used with nothing
#: going red. The gate carries a longer list for a different reason, that it
#: must work in two repositories with different layouts; this file serves one
#: repository and names the pinned homes.
CI_STATE_SEARCH = (".claude/hooks", ".claude/kit")
CI_TIMEOUT = 120.0


def _git(root: Path, *args: str) -> tuple[bool, str]:
    """Run one git command in ``root``.

    Parameters
    ----------
    root : Path
        Directory to run git in.
    *args : str
        Arguments after ``git``.

    Returns
    -------
    tuple of (bool, str)
        Whether git succeeded, and its stripped stdout or its error text.
    """
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"git could not be run ({type(error).__name__}: {error})"
    if done.returncode != 0:
        return False, (done.stderr or done.stdout or "git failed").strip()
    return True, done.stdout.strip()


def _locate_ci_state(root: Path) -> Path | None:
    """Find the vendored ``ci_state.py``, or None.

    Parameters
    ----------
    root : Path
        The repository root.

    Returns
    -------
    Path or None
        The body to run, or None when it is nowhere this file looks. An
        absent body is a refusal at the caller, never a skip. Only
        drift-pinned directories are searched, so the body that answers is
        always one `tests/test_kit_drift.py` would redden if it changed.
    """
    for folder in CI_STATE_SEARCH:
        candidate = root / folder / CI_STATE_NAME
        if candidate.is_file():
            return candidate
    return None


def _ask_ci(body: Path, root: Path, sha: str, workflows: list[str]) -> tuple[str, str]:
    """Ask ``ci_state.py`` what CI concluded about one commit.

    Run as a SUBPROCESS rather than imported, so this file consumes the
    published exit-status contract instead of reaching into another body's
    internals, and so the call can be bounded.

    Parameters
    ----------
    body : Path
        The vendored ``ci_state.py``.
    root : Path
        Repository root, passed through as ``--repo``.
    sha : str
        The commit to ask about.
    workflows : list of str
        Workflow names that must be present, passed through unchanged.

    Returns
    -------
    tuple of (str, str)
        The state and what the checker said. Every failure is UNKNOWN.
    """
    try:
        done = subprocess.run(
            [
                sys.executable,
                str(body),
                "poll",
                "--sha",
                sha,
                "--repo",
                str(root),
                *[arg for name in workflows for arg in ("--workflow", name)],
            ],
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
            timeout=CI_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return UNKNOWN, f"{CI_STATE_NAME} did not answer within {CI_TIMEOUT:.0f}s"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return UNKNOWN, (
            f"{CI_STATE_NAME} could not be run ({type(error).__name__}: {error})"
        )
    detail = (done.stdout.strip() + "\n" + done.stderr.strip()).strip()
    state = CI_EXIT_STATE.get(done.returncode, UNKNOWN)
    if done.returncode not in CI_EXIT_STATE:
        detail = (
            f"{CI_STATE_NAME} exited {done.returncode}, which is outside its "
            f"documented contract {sorted(CI_EXIT_STATE)}, so its answer cannot "
            f"be read at all.\n{detail}"
        )
    return state, detail


#: The complete option set. A token outside it is REFUSED rather than
#: ignored, which is the whole point of naming it: see `_parse`.
KNOWN_OPTIONS = ("sha", "repo", "workflow")


class ArgumentError(Exception):
    """An argument this checker will not guess at."""


def _parse(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """Split ``argv`` into options and repeated ``--workflow`` values.

    REFUSES WHAT IT DOES NOT UNDERSTAND, and this is the fix for the worst
    defect three reviewer lenses found in the first version of this file.
    That version recorded any ``--`` token as an option name and ignored
    everything else, so ``--sha=abc`` parsed as the option ``sha=abc``,
    ``--verbose --sha abc`` consumed ``--sha`` as the VALUE of
    ``--verbose``, and a bare positional was dropped. In all three the
    resulting ``opts`` had no ``sha``, the caller silently fell back to
    HEAD, and the checker printed a GREEN verdict about a commit nobody
    asked about. A guard whose whole subject is "do not answer a question
    you were not asked" cannot have that in its own argument parser.

    So: unknown option, missing value, a value that looks like another
    option, and any positional argument all raise. The ``--opt=value``
    form is accepted rather than refused, because refusing a form every
    other command-line tool accepts would send an operator to the same
    silent place by a different road.

    Parameters
    ----------
    argv : list of str
        Arguments after the program name.

    Returns
    -------
    tuple of (dict, list of str)
        Flat options and the workflow names.

    Raises
    ------
    ArgumentError
        On any token this function will not guess at.
    """
    opts: dict[str, str] = {}
    workflows: list[str] = []
    walker = iter(argv)
    for arg in walker:
        if not arg.startswith("--"):
            raise ArgumentError(
                f"{arg!r} is not an option of this check, and this check takes "
                f"no positional arguments. Name the commit with --sha <sha>"
            )
        name, sep, inline = arg[2:].partition("=")
        if name not in KNOWN_OPTIONS:
            raise ArgumentError(
                f"--{name} is not an option of this check; the options are "
                f"{', '.join('--' + option for option in KNOWN_OPTIONS)}. "
                f"Check the spelling"
            )
        value = inline if sep else next(walker, "")
        if not value or (not sep and value.startswith("--")):
            raise ArgumentError(
                f"--{name} was given no value"
                + (f", and {value!r} is another option" if value else "")
                + f". Write it as --{name} <value> or --{name}=<value>"
            )
        if name == "workflow":
            workflows.append(value)
        else:
            opts[name] = value
    return opts, workflows


def main(argv: list[str]) -> int:
    """Refuse a closing claim unless CI concluded green on the pushed commit.

    Parameters
    ----------
    argv : list of str
        The full argument vector, ``sys.argv``.

    Returns
    -------
    int
        0 GREEN, 1 RED, 3 RUNNING, 4 UNKNOWN, 2 CONFIG, 5 UNPUSHED.
    """
    # EVERY LINE THIS FUNCTION PRINTS GOES TO STDOUT, deliberately and
    # uniformly. The first version split them: CONFIG and the internal
    # exception went to stderr while the verdict and the refusal sentence
    # went to stdout, so an operator or a wrapper capturing one stream saw a
    # refusal with no reason, or a reason with no refusal. The verdict IS
    # this program's output, so it belongs on the output stream, and there is
    # no second class of message here to justify a second stream.
    try:
        try:
            opts, workflows = _parse(argv[1:])
        except ArgumentError as bad:
            print(
                f"closing-ci: CONFIG, this check was called with an argument it "
                f"will not guess at: {bad}. Refusing rather than answering "
                f"about some other commit.\n"
                f"Usage: closing_ci_check.py [--sha <sha>] [--repo <path>] "
                f"[--workflow <name>] ..."
            )
            return CONFIG
        ok, top = _git(Path(opts.get("repo", ".")), "rev-parse", "--show-toplevel")
        if not ok or not top:
            print(
                f"closing-ci: CONFIG, no git repository resolves from "
                f"{opts.get('repo', '.')}: {top}. Run this from inside the "
                "checkout, or pass --repo <path to the checkout>."
            )
            return CONFIG
        root = Path(top)

        sha = opts.get("sha", "").strip()
        if not sha:
            ok, sha = _git(root, "rev-parse", "HEAD")
            if not ok or not sha:
                print(
                    f"closing-ci: CONFIG, could not read HEAD in {root}: {sha}. "
                    "Make at least one commit, or name one with --sha <sha>."
                )
                return CONFIG
        else:
            ok, resolved = _git(root, "rev-list", "-n", "1", sha)
            if not ok or not resolved:
                print(
                    f"closing-ci: CONFIG, {sha!r} does not resolve in {root}: "
                    f"{resolved}. Check the spelling, or run `git fetch origin` "
                    f"if it is a commit this clone has not seen yet."
                )
                return CONFIG
            sha = resolved

        # THE PRECONDITION ci_state.py CANNOT CHECK, and it is not a CI
        # state. A commit that never left this machine has no CI result by
        # construction, and asking about it returns "no run is visible",
        # which is UNKNOWN and would be reported as a network-ish problem.
        # It is a different failure with a different remedy: push first.
        ok, unpushed = _git(root, "rev-list", sha, "--not", "--remotes")
        if not ok:
            print(
                f"closing-ci: UNKNOWN, could not establish whether {sha[:12]} is "
                f"on a remote: {unpushed}. Refusing rather than assuming it is. "
                f"Check `git remote -v` names a remote and run `git fetch "
                f"origin`, then re-run this check."
            )
            return EXIT[UNKNOWN]
        if unpushed:
            count = len(unpushed.splitlines())
            print(
                f"closing-ci: UNPUSHED, {count} commit(s) up to and including "
                f"{sha[:12]} are on no remote, so no CI result about them can "
                f"exist. This lane may NOT report itself closed. Push them, "
                f"then re-run this check. If they ARE pushed, this clone's "
                f"remote-tracking refs are stale: run `git fetch origin` first, "
                f"because this check reads them and not the remote."
            )
            return UNPUSHED

        body = _locate_ci_state(root)
        if body is None:
            print(
                f"closing-ci: CONFIG, {CI_STATE_NAME} is not vendored in any "
                f"drift-pinned directory this check looks in "
                f"({', '.join(CI_STATE_SEARCH)}), so what CI concluded about "
                f"{sha[:12]} could not be asked at all. Vendor the kit's "
                f"{CI_STATE_NAME} into .claude/hooks and pin it in "
                f"tests/test_kit_drift.py. This is a refusal and not a skip: a "
                f"check that cannot run is not a clean answer."
            )
            return CONFIG

        state, detail = _ask_ci(body, root, sha, workflows)

        # A GREEN OVER NO NAMED WORKFLOW IS NOT A GREEN, and this branch is
        # the repair for the defect three lenses found together. `ci_state`
        # applies its "a named workflow that has not appeared is UNKNOWN,
        # not absent" clause ONLY when names are given. With none, the
        # verdict is computed over whatever runs happen to be INDEXED, so a
        # workflow that has not appeared yet, or that stopped triggering at
        # all, is invisible and every other run being green reads as GREEN
        # forever. That is the same false-green the kit fixed inside
        # `ci_state` per workflow, reintroduced one level up at the caller.
        #
        # Only GREEN is downgraded. RED, RUNNING and UNKNOWN already forbid
        # the claim, and a red run is a red run whether or not the set was
        # complete.
        if state == GREEN and not workflows:
            state = UNKNOWN
            detail = (
                f"{detail}\nclosing-ci: but NO required workflow was named, so "
                f"this verdict covers only the runs that happen to be indexed "
                f"for {sha[:12]} right now. A workflow that has not appeared "
                f"yet, or that stopped triggering, is invisible to it. Name "
                f"what must have run, for example --workflow CI"
            )

        print(f"closing-ci: {state} for {sha}")
        print(detail)
        if state == GREEN:
            return EXIT[GREEN]

        # THE REMEDY, PER STATE. The pre-push half of this rule
        # (`role_review_gate.py`) gives one and this half did not, so for the
        # same CI state an operator was told what to do before a push and
        # only what to write after it. RUNNING is the state a lane hits most,
        # immediately after its own push, and the cheapest honest path out of
        # it is to wait and ask again; a refusal that does not say so reads as
        # a dead end and invites the claim it exists to forbid.
        remedy = {
            RED: (
                "Fix the failure and push again. The close waits for the fix, "
                "not the other way around."
            ),
            RUNNING: (
                "This is the ordinary state right after a push and it usually "
                "resolves in minutes. Wait for the run to conclude and re-run "
                "this check; that is the cheapest path to a legitimate close."
            ),
        }.get(
            state,
            "Run `gh auth status` and `gh run list --commit "
            f"{sha}` (the FULL hash) and fix what they report, then re-run "
            "this check. UNKNOWN is refused rather than assumed benign.",
        )
        print(f"closing-ci: {remedy}")
        print(
            "closing-ci: this lane may NOT report itself closed, and may not "
            "call this push successful, clean, or done. Report the work as "
            f"PUSHED with CI state NOT VERIFIED, naming {sha} and the reason "
            "above. Proving a push ARRIVED is not proving it BUILDS "
            "(INC-20260811-1745-itaca)."
        )
        return EXIT.get(state, CONFIG)
    except Exception as error:
        # Fail CLOSED on anything at all. A close is a claim, and a mechanism
        # that raised has established nothing that would justify making it.
        # The bare `except Exception` is deliberate and is the same choice
        # `ci_state.py` makes for the same reason: an unanticipated failure
        # inside a guard must become a refusal, never an escape.
        print(
            f"closing-ci: UNKNOWN, this mechanism raised: {error!r}. Refusing "
            "rather than reporting a state it never established. Re-run it and "
            "report the traceback; a defect in this check costs time and must "
            "never cost safety, so do not read this as a pass. To close while "
            "it is broken, read CI yourself with `gh run list --commit "
            "<sha>` and say in the record that this check could not run."
        )
        return EXIT[UNKNOWN]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
