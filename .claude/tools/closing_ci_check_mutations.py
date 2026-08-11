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

#: (label, original, replacement, fixture, ci_exit, args, baseline, mutated)
#:
#: ``fixture`` names which scratch repository the case runs in:
#: ``pushed`` (HEAD on the remote, stub answers ``ci_exit``), ``local``
#: (one unpushed commit), ``bare`` (no ci_state.py vendored anywhere), or
#: ``recording`` (the stub answers GREEN only when it was actually GIVEN a
#: ``--workflow``, which is what makes the pass-through mutable).
#:
#: ``args`` are the arguments the checker is called with. Most cases need
#: ``--workflow CI``, because a GREEN over no named workflow is downgraded
#: to UNKNOWN and a case that omitted it would measure the downgrade rather
#: than the line it names.
#:
#: THE ARGV MUTANTS BELOW EXIST BECAUSE ROUND ONE MEASURED THIS FILE'S OWN
#: BLIND SPOT. A QA lens observed that every case in
#: ``tests/test_closing_ci_check.py`` stubs ``ci_state.py`` with a body that
#: IGNORES argv, so deleting the ``--workflow`` pass-through in ``_ask_ci``
#: left the whole suite green AND this companion still printed its full
#: score. A mutation companion that reports every mutant caught while a
#: real removal survives is the exact shape it exists to prevent, one level
#: up. The ``pushed_recording`` fixture writes the child's argv to a file so
#: the pass-through can be mutated and seen.
WF = ("--workflow", "CI")

MUTANTS: list[tuple[str, str, str, str, int, tuple[str, ...], int, int]] = [
    (
        "the non-green refusal is removed, so every state reports closed",
        "        if state == GREEN:\n            return EXIT[GREEN]",
        "        if state != 'nothing is ever this':\n            return EXIT[GREEN]",
        "pushed",
        RED,
        WF,
        RED,
        GREEN,
    ),
    (
        "a refused state returns success instead of its own exit code",
        "        return EXIT.get(state, CONFIG)",
        "        return 0",
        "pushed",
        RED,
        WF,
        RED,
        GREEN,
    ),
    # THE DEFAULT, mutated separately from the mapping. The mutant above
    # replaces the whole expression, so it never proves the DEFAULT arm is
    # load-bearing: `EXIT.get(state, 0)` would have kept every other mutant
    # green. Only `ci_state.py`'s own CONFIG state reaches that arm, since
    # CONFIG is not a key of EXIT. A QA lens found the gap in round two.
    (
        "the fallback for a state outside EXIT returns success",
        "        return EXIT.get(state, CONFIG)",
        "        return EXIT.get(state, 0)",
        "pushed",
        CONFIG,
        WF,
        CONFIG,
        GREEN,
    ),
    (
        "the unpushed precondition is dropped, so a local commit reads green",
        "        if unpushed:",
        "        if False:",
        "local",
        GREEN,
        WF,
        UNPUSHED,
        GREEN,
    ),
    (
        "a green over NO named workflow stops being downgraded to UNKNOWN",
        "        if state == GREEN and not workflows:",
        "        if False:",
        "pushed",
        GREEN,
        (),
        UNKNOWN,
        GREEN,
    ),
    # NO MUTANT FOR THE POSITIONAL BRANCH, and the absence is deliberate
    # rather than an oversight, so it is written down instead of leaving the
    # list to look complete. Removing `if not arg.startswith("--")` does NOT
    # turn the refusal into a pass: the positional then falls through to the
    # option path, where `"HEAD"[2:]` is `"AD"`, which is not a known option,
    # so the NEXT guard refuses it and the mutant exits 2 exactly as the
    # original did. Measured, not reasoned: the mutant was written, run, and
    # reported `mutated exit=2, expected 0`.
    #
    # That is two guards defending one property, which is fine and is why the
    # message is the thing worth testing rather than the exit code. The
    # positional case is pinned by its MESSAGE in
    # `tests/test_closing_ci_check.py`, by the parametrized case whose name
    # begins `test_an_argument_it_cannot_read_refuses_`. That name is given
    # as a prefix rather than in full because the full identifier does not
    # fit the line limit, and wrapping it across a comment break once made
    # it ungreppable, which is the same defect as naming it wrongly.
    # Keeping a mutant here that "passes" only because a neighbor catches it
    # is precisely the false confidence the absent-body mutant below was
    # already corrected for once.
    (
        "the parser stops refusing an unknown option and falls back to HEAD",
        "        if name not in KNOWN_OPTIONS:",
        "        if False:",
        "pushed",
        GREEN,
        (*WF, "--verbose", "yes"),
        CONFIG,
        GREEN,
    ),
    (
        "the --workflow names never reach ci_state, so it judges over "
        "whatever happens to be indexed",
        "                *[arg for name in workflows "
        'for arg in ("--workflow", name)],\n',
        "",
        "recording",
        GREEN,
        WF,
        GREEN,
        UNKNOWN,
    ),
    (
        "an unrecognized ci_state exit defaults to green instead of UNKNOWN",
        "    state = CI_EXIT_STATE.get(done.returncode, UNKNOWN)",
        "    state = CI_EXIT_STATE.get(done.returncode, GREEN)",
        "pushed",
        99,
        WF,
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
        'f"check that cannot run is not a clean answer."\n'
        "            )\n"
        "            return CONFIG",
        'f"check that cannot run is not a clean answer."\n'
        "            )\n"
        "            return EXIT[GREEN]",
        "bare",
        GREEN,
        WF,
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
    if kind == "recording":
        # ANSWERS ACCORDING TO ITS ARGV, which is the only stub shape that
        # can see the pass-through. It returns GREEN when it was actually
        # given a `--workflow` and UNKNOWN when it was not, which is what
        # `ci_state.py` itself does with a named workflow that has not
        # appeared. A stub that ignores argv, which is every other stub in
        # this file and in the test module, cannot distinguish a working
        # pass-through from a deleted one.
        (hooks / "ci_state.py").write_text(
            "import sys\n"
            "named = '--workflow' in sys.argv\n"
            "print('ci-state: stub, workflow named=%s' % named)\n"
            "sys.exit(0 if named else 4)\n",
            encoding="utf-8",
        )
    elif kind != "bare":
        (hooks / "ci_state.py").write_text(
            f"import sys\nprint('ci-state: stub')\nsys.exit({ci_exit})\n",
            encoding="utf-8",
        )
    if kind == "local":
        (work / "b.txt").write_text("b", encoding="utf-8")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "local only")
    return work


def run_check(body: Path, repo: Path, args: tuple[str, ...] = ()) -> int:
    """Run a (possibly mutated) checker body against ``repo``."""
    done = subprocess.run(
        [sys.executable, str(body), "--repo", str(repo), *args],
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
    for (
        label,
        original,
        replacement,
        kind,
        ci_exit,
        args,
        baseline,
        expected,
    ) in MUTANTS:
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
            actual_base = run_check(CHECK, repo, args)
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
            # The mutant is run from outside the repository and finds the
            # same `ci_state.py` the original does, because resolution is
            # relative to the REPOSITORY ROOT and no longer to the body's own
            # directory. That changed in round one: searching beside the body
            # let an unpinned copy shadow the vendored one, so the search list
            # now names only drift-pinned directories.
            actual = run_check(mutant, repo, args)
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
