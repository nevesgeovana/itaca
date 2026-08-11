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
``ci_state.py``, an unresolvable repository, a ``gh`` that cannot answer and
any exception raised inside this mechanism all refuse. There is deliberately
no path through this file that prints a success sentence over a question it
could not ask.

Exit status, which is the whole interface and is ``ci_state.py``'s own
contract with one addition: 0 GREEN, 1 RED, 3 RUNNING, 4 UNKNOWN, 2 a CONFIG
error, and 5 UNPUSHED, which is this file's own and is not a CI state.

Usage:
    closing_ci_check.py [--sha <sha>] [--repo <path>] [--workflow <name> ...]
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
#: Where a vendored ``ci_state.py`` may sit, relative to the repository root.
#: The same list the gate carries, and for the same reason: this repository
#: vendors it beside the gate, and a single hard-coded path would break the
#: day that changes. Beside this file first, then the gate's directory.
CI_STATE_SEARCH = (".claude/hooks", ".claude/kit", ".claude/tools")
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
        absent body is a refusal at the caller, never a skip.
    """
    here = Path(__file__).resolve().parent / CI_STATE_NAME
    if here.is_file():
        return here
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


def _parse(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """Split ``argv`` into options and repeated ``--workflow`` values.

    Parameters
    ----------
    argv : list of str
        Arguments after the program name.

    Returns
    -------
    tuple of (dict, list of str)
        Flat options and the workflow names.
    """
    opts: dict[str, str] = {}
    workflows: list[str] = []
    walker = iter(argv)
    for arg in walker:
        if arg == "--workflow":
            workflows.append(next(walker, ""))
        elif arg.startswith("--"):
            opts[arg[2:]] = next(walker, "")
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
    try:
        opts, workflows = _parse(argv[1:])
        ok, top = _git(Path(opts.get("repo", ".")), "rev-parse", "--show-toplevel")
        if not ok or not top:
            print(
                f"closing-ci: CONFIG, no git repository resolves from "
                f"{opts.get('repo', '.')}: {top}. Run this from inside the "
                "checkout, or pass --repo.",
                file=sys.stderr,
            )
            return CONFIG
        root = Path(top)

        sha = opts.get("sha", "").strip()
        if not sha:
            ok, sha = _git(root, "rev-parse", "HEAD")
            if not ok or not sha:
                print(
                    f"closing-ci: CONFIG, could not read HEAD in {root}: {sha}. "
                    "Make at least one commit, or pass --sha.",
                    file=sys.stderr,
                )
                return CONFIG
        else:
            ok, resolved = _git(root, "rev-list", "-n", "1", sha)
            if not ok or not resolved:
                print(
                    f"closing-ci: CONFIG, {sha!r} does not resolve in {root}: "
                    f"{resolved}. Check the spelling.",
                    file=sys.stderr,
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
                f"on a remote: {unpushed}. Refusing rather than assuming it is.",
                file=sys.stderr,
            )
            return EXIT[UNKNOWN]
        if unpushed:
            count = len(unpushed.splitlines())
            print(
                f"closing-ci: UNPUSHED, {count} commit(s) up to and including "
                f"{sha[:12]} are on no remote, so no CI result about them can "
                f"exist. This lane may NOT report itself closed. Push first, "
                f"then re-run this check."
            )
            return UNPUSHED

        body = _locate_ci_state(root)
        if body is None:
            print(
                f"closing-ci: CONFIG, {CI_STATE_NAME} is not vendored anywhere "
                f"this check looks (beside this file, then "
                f"{', '.join(CI_STATE_SEARCH)}), so what CI concluded about "
                f"{sha[:12]} could not be asked at all. Vendor the kit's "
                f"{CI_STATE_NAME}. This is a refusal and not a skip: a check "
                f"that cannot run is not a clean answer.",
                file=sys.stderr,
            )
            return CONFIG

        state, detail = _ask_ci(body, root, sha, workflows)
        print(f"closing-ci: {state} for {sha}")
        print(detail)
        if state == GREEN:
            return EXIT[GREEN]
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
            "rather than reporting a state it never established.",
            file=sys.stderr,
        )
        return EXIT[UNKNOWN]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
