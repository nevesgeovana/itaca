#!/usr/bin/env python3
"""Prove `closing_ci_check.py` can still fail, by breaking it on purpose.

The shared incident ledger's rule: "a guard is proven by mutation: change
the code it protects and show the guard fails. A guard nobody tried to
break is a guess." ``tests/test_closing_ci_check.py`` shows the checker
REFUSES the states it must refuse; that is necessary and not sufficient,
because a checker could refuse for a reason other than the line believed to
be doing the work. This file removes each load-bearing line and shows the
refusal turns into a PASS.

Each mutation is asserted PRESENT before it is applied, so a rewrite that
renames a line silently makes this file fail rather than quietly testing
nothing. That failure mode is the whole reason the kit companions do it,
and it is the one this repository has already been bitten by.

Read the output, not only the exit code: the per-mutant lines say which
refusal each removal turned into a pass.

Exit status: 0 when every mutant was caught, 1 otherwise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHECK = Path(__file__).resolve().parent / "closing_ci_check.py"

GREEN, RED, CONFIG, RUNNING, UNKNOWN, UNPUSHED = 0, 1, 2, 3, 4, 5

#: (label, original fragment, replacement, fixture, baseline, mutated)
#:
#: ``fixture`` names which scratch repository the case runs in:
#: ``pushed`` (HEAD on the remote, stub answers ``ci_exit``), ``local``
#: (one unpushed commit), or ``bare`` (no ci_state.py vendored anywhere).
MUTANTS: list[tuple[str, str, str, str, int, int, int]] = [
    (
        "the non-green refusal is removed, so every state reports closed",
        "        if state == GREEN:\n            return EXIT[GREEN]",
        "        if state != 'nothing is ever this':\n            return EXIT[GREEN]",
        "pushed",
        RED,
        RED,
        GREEN,
    ),
    (
        "a refused state returns success instead of its own exit code",
        "        return EXIT.get(state, CONFIG)",
        "        return 0",
        "pushed",
        RED,
        RED,
        GREEN,
    ),
    (
        "the unpushed precondition is dropped, so a local commit reads green",
        "        if unpushed:",
        "        if False:",
        "local",
        GREEN,
        UNPUSHED,
        GREEN,
    ),
    (
        "an unrecognized ci_state exit defaults to green instead of UNKNOWN",
        "    state = CI_EXIT_STATE.get(done.returncode, UNKNOWN)",
        "    state = CI_EXIT_STATE.get(done.returncode, GREEN)",
        "pushed",
        99,
        UNKNOWN,
        GREEN,
    ),
    # MUTATE THE DECISION, NOT THE BRANCH. The first version of this case
    # deleted the `if body is None:` test, and it proved the wrong thing: the
    # mutant fell through to running a body named "None", which fails, so it
    # still refused, with exit 2 for a misleading reason. A refusal that turns
    # into a differently labeled refusal is not the failure this file is
    # about. What fail-closed forbids is an absent checker being read as
    # PERMISSION, so the mutation makes that branch return green.
    (
        "an absent ci_state.py is read as permission instead of a refusal",
        'f"that cannot run is not a clean answer.",\n'
        "                file=sys.stderr,\n"
        "            )\n"
        "            return CONFIG",
        'f"that cannot run is not a clean answer.",\n'
        "                file=sys.stderr,\n"
        "            )\n"
        "            return EXIT[GREEN]",
        "bare",
        GREEN,
        CONFIG,
        GREEN,
    ),
]


def git(repo: Path, *args: str) -> None:
    """Run one git command in ``repo``, raising on failure."""
    subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=os.environ.copy(),
    )


def build(root: Path, kind: str, ci_exit: int) -> Path:
    """Build a scratch repository of one of the three shapes."""
    remote = root / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", str(remote)],
        check=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    work = root / "work"
    work.mkdir()
    git(work, "init", "-q")
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "T")
    (work / "a.txt").write_text("a", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "branch", "-M", "main")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    git(work, "fetch", "-q", "origin")
    hooks = work / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    if kind != "bare":
        (hooks / "ci_state.py").write_text(
            f"import sys\nprint('ci-state: stub')\nsys.exit({ci_exit})\n",
            encoding="utf-8",
        )
    if kind == "local":
        (work / "b.txt").write_text("b", encoding="utf-8")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "local only")
    return work


def run_check(body: Path, repo: Path) -> int:
    """Run a (possibly mutated) checker body against ``repo``."""
    done = subprocess.run(
        [sys.executable, str(body), "--repo", str(repo)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=repo,
    )
    return done.returncode


def main() -> int:
    """Apply every mutation and report which refusals it removed."""
    source = CHECK.read_text(encoding="utf-8")
    failures = 0
    print(f"mutating {CHECK.name}, {len(MUTANTS)} mutant(s)\n")
    for label, original, replacement, kind, ci_exit, baseline, expected in MUTANTS:
        # ASSERTED PRESENT FIRST. A mutation whose target has been renamed
        # would otherwise apply nothing and "pass" against an unmutated body.
        if original not in source:
            print(
                f"  [FAIL] {label}\n         target line is ABSENT from "
                f"{CHECK.name}; this mutant tested NOTHING"
            )
            failures += 1
            continue
        root = Path(tempfile.mkdtemp(prefix="closing_ci_mut_"))
        try:
            repo = build(root, kind, ci_exit)
            actual_base = run_check(CHECK, repo)
            if actual_base != baseline:
                print(
                    f"  [FAIL] {label}\n         the UNMUTATED checker exited "
                    f"{actual_base}, expected {baseline}; the case is not "
                    f"measuring what it names"
                )
                failures += 1
                continue
            mutant = root / "mutant.py"
            mutant.write_text(
                source.replace(original, replacement, 1), encoding="utf-8"
            )
            # The mutant must find the same ci_state the original does, and
            # it is resolved beside the BODY, so the stub is copied next to it.
            stub = repo / ".claude" / "hooks" / "ci_state.py"
            if stub.is_file():
                shutil.copyfile(stub, root / "ci_state.py")
            actual = run_check(mutant, repo)
            if actual == expected:
                print(
                    f"  [ok  ] {label}\n         baseline exit={baseline}, "
                    f"mutated exit={actual} (expected {expected})"
                )
            else:
                print(
                    f"  [FAIL] {label}\n         mutated exit={actual}, "
                    f"expected {expected}; the removed line was not what "
                    f"produced the refusal"
                )
                failures += 1
        finally:
            shutil.rmtree(root, ignore_errors=True)
    caught = len(MUTANTS) - failures
    print(
        f"\n{caught}/{len(MUTANTS)} mutants confirmed: each removal above "
        f"turns a refusal into a pass"
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
