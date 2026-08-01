"""Every subprocess spawn passes an explicit environment, judged per CALL.

Usage example (TDD anchor)::

    done = _run(str(_SPAWN_CHECK), "tests", "itaca")
    assert done.returncode == 0, done.stdout + done.stderr

WHY THIS MODULE REPLACES A TEST RATHER THAN JOINING IT. Until kit 0.2.16
this repository answered the same question with
``test_no_spawn_site_bypasses_child_env`` in ``tests/test_push_gate.py``,
which searched a fixed window of fourteen lines after each
``subprocess.run(``. ``ITC-20260802-0200`` is written about that guard, and
lane ITA-11 round two met BOTH of its failure directions in one commit: a
helper's ``env=child_env()`` sixteen lines below a DIFFERENT function's
call excused two real offenders, and ``_ask``, which DID pass the
environment seventeen lines after its own opening line because its argv
was written one element per line, was reported as an offender.

The pressure a window creates is the dangerous half. The obvious repair is
to WIDEN the window until the false red goes away, and a widened window is
how a real offender becomes invisible.

Retiring the window guard rather than keeping both is this repository's
call, made here. The adoption brief asks only that the two not be left
claiming the same coverage, because two guards that disagree teach a
reader to trust neither. The retired one has both failure directions
reachable; the vendored checker parses each module with ``ast`` and
requires an ``env`` keyword ON the ``Call`` node, so a neighbour's keyword
is a different node and is invisible to it.

WHAT WAS MEASURED WHEN THE CHECKER FIRST RAN HERE, before anything was
edited::

    python .claude/kit/check_spawn_env.py tests
    -> checked 79 module(s), 32 spawn call(s), 8 unguarded, 0 unverifiable

All eight were ``git`` spawns. The retired guard reported none of them
because it only ever considered spawns of ``sys.executable``: the
``COV_CORE_*`` failure it was written for is a Python-child failure. The
wider claim is the correct one, since a child that inherits the whole
environment inherits whatever the runner injected, and ``git`` reads a
large part of it. All eight were fixed in the commit that vendored the
checker, because a wired checker that is red wires nothing.

THE ACCOUNTING IS WHAT THE RETIREMENT MUST NOT LOSE. The retired guard
carried two floors, ``scanned >= 20`` and ``interpreter_spawns >= 10``,
which exist because ``assert not offenders`` alone is satisfied by a walk
that opened nothing and by a spawn idiom the scan stopped recognizing, and
both read exactly like compliance. The checker prints its own accounting
line, so the floors move onto THAT line rather than being dropped.

WHAT IS NOT REPLACED. ``test_a_child_process_does_not_start_coverage`` in
``tests/test_push_gate.py`` stays where it is. It is the BEHAVIORAL half,
asking a spawned child whether coverage started, and neither the window
guard nor this checker answers that question.

THE SCOPE IS BOTH TREES, ``tests`` and ``itaca``, and not a naming
convention. The package spawns nothing today; walking it anyway is the
incident's second, smaller item, since a guard whose scope is a filename
convention is a guard with a door in it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

_ROOT = Path(__file__).resolve().parents[1]
_KIT = _ROOT / ".claude" / "kit"
_SPAWN_CHECK = _KIT / "check_spawn_env.py"
_SPAWN_MUTATIONS = _KIT / "check_spawn_env_mutations.py"

#: The directories the guard covers. Both trees, so a spawn added to
#: library code is judged by the same rule as one added to the suite.
_WALKED = ("tests", "itaca")

#: Floors on the checker's own accounting line, set well under the counts
#: measured on adoption (147 modules, 32 spawn calls) so they catch a walk
#: that collapsed rather than ordinary drift.
_MODULE_FLOOR = 100
_SPAWN_FLOOR = 20

_COUNTS = re.compile(
    r"checked (\d+) module\(s\), (\d+) spawn call\(s\), "
    r"(\d+) unguarded, (\d+) unverifiable"
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=str(_ROOT),
    )


def test_the_vendored_spawn_checker_is_present() -> None:
    """A checker loaded by path fails loudly if it is missing.

    Without this a rename would remove the whole check while the suite
    stayed green, which is the self-skipping evidence the kit exists to
    replace.
    """
    for checker in (_SPAWN_CHECK, _SPAWN_MUTATIONS):
        assert checker.is_file(), f"vendored kit checker missing at {checker}"


def test_the_spawn_checker_refuses_a_bad_invocation() -> None:
    """A CONFIG error exits 2 and is never reported as a clean tree.

    The cheapest possible proof that the vendored copy RUNS at all. A copy
    whose header was corrupted on vendoring parses as a SyntaxError, the
    body hash is untouched because the marker splits header from body, and
    `tests/test_kit_drift.py` stays green.
    """
    done = _run(str(_SPAWN_CHECK))
    assert done.returncode == 2, (
        f"expected exit 2 (CONFIG) from a bare invocation, got "
        f"{done.returncode}.\n{done.stdout}{done.stderr}"
    )
    assert "usage:" in (done.stdout + done.stderr).lower(), (
        f"the checker refused without saying how to invoke it, which is the "
        f"three-part error rule broken.\n{done.stdout}{done.stderr}"
    )


def test_no_spawn_site_in_either_tree_bypasses_an_explicit_environment() -> None:
    """The guard itself: every spawn call carries its own ``env=``.

    READ THE ACCOUNTING, not only the verdict. A clean exit is also what a
    walk that opened nothing produces, and what a checker that stopped
    recognizing the spawn idiom produces, and both read exactly like
    compliance. The floors below are what tells those apart, and they are
    the ones the retired window guard carried, moved onto the line the
    checker prints for itself.

    The UNVERIFIABLE count is read and reported rather than pinned. A
    ``**kwargs`` splat satisfies the check and is named as unverifiable,
    because the checker cannot see inside a dict it did not build; there
    are none here today and a future one is not a failure.
    """
    done = _run(str(_SPAWN_CHECK), *_WALKED)
    match = _COUNTS.search(done.stdout)
    assert match is not None, (
        f"the spawn checker printed no accounting line, so a clean verdict "
        f"here would mean nothing. Its output format changed, or it did not "
        f"run at all.\n{done.stdout}{done.stderr}"
    )
    modules, spawns, unguarded, unverifiable = (int(g) for g in match.groups())
    assert modules >= _MODULE_FLOOR, (
        f"the spawn walk opened only {modules} module(s) across {_WALKED}, "
        f"far below this repository's size. The walk is finding nothing, so "
        f"a green verdict means nothing; fix the walk before reading it."
    )
    assert spawns >= _SPAWN_FLOOR, (
        f"the walk recognized only {spawns} spawn call(s). This suite spawns "
        f"processes from many modules, so a count this low means the idiom "
        f"moved and the checker no longer sees it, not that the sites went "
        f"away. The verdict below would then be vacuous."
    )
    assert done.returncode == 0, (
        f"{unguarded} spawn call(s) pass no explicit env=, and "
        f"{unverifiable} could not be verified. A child that inherits this "
        f"process's whole environment inherits whatever the test runner "
        f"injected; the COV_CORE_* case aborted CI here after every test had "
        f"passed. Put env= ON THE CALL, and never widen a window to make a "
        f"report go away: judging a call by the lines around it is the "
        f"defect this checker replaced.\n{done.stdout}{done.stderr}"
    )


@pytest.mark.slow
def test_the_spawn_checker_can_still_fail() -> None:
    """The mutation companion proves the guard still bites.

    MEASURED 1.39 s inside pytest, which is UNDER the commit tier's 3.0 s
    budget, so the marker is not a budget exemption and is not claimed as
    one. It carries `slow` because its cost is a mutation companion's
    cost: it spawns the checker once per case and once per case per
    mutant, so it grows with the KIT's case list rather than with anything
    this repository does, and the commit tier should not inherit that
    growth silently. The same reasoning marks the round-cap and citation
    companions.

    The marker moves WHERE it runs and never WHETHER: the pre-push tier
    and CI both run it and both block. The three tests above stay in the
    commit tier, so a vendored copy that does not parse, and a real
    offender, are both caught at the cheapest gate.

    The counts are pinned for the reason the other companions' are: the
    body-sha256 pin in `tests/test_kit_drift.py` fails first on any byte
    change, so these literals are defense in depth for one specific path,
    a re-vendor where the hash is updated mechanically and a shrunken case
    list goes unnoticed.
    """
    done = _run(str(_SPAWN_MUTATIONS))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "all 6 mutants are denied" in done.stdout, (
        f"the spawn mutation companion did not report all 6 mutants denied. "
        f"Two opposite remedies: if a re-vendor changed the count, move it "
        f"here and in tests/test_kit_drift.py's manifest note together; if it "
        f"did not, a mutant SURVIVED and the checker no longer refuses what "
        f"it claims to. Output:\n{done.stdout}"
    )
    assert "All 11 cases hold" in done.stdout, (
        f"the spawn mutation companion did not report 11 cases. The mutants "
        f"can be denied by a shrunken case list, so this count is what "
        f"catches a re-vendor that quietly dropped cases. If the kit really "
        f"changed it, move the pin; do not delete it. Output:\n{done.stdout}"
    )
