"""Every subprocess spawn carries its own ``env=`` keyword, judged per CALL.

WHAT THE VENDORED CHECKER PROVES, stated first because the obvious summary
overstates it. It proves an ``env`` keyword is PRESENT on the call node. It
does not prove the keyword's VALUE is a stripped environment: ``env=None``
is inheritance, which is the ``COV_CORE_*`` failure mode itself, and is
reported clean, and a ``**kwargs`` splat is reported UNVERIFIABLE and also
exits 0. The checker's own docstring says so, and that boundary is right
for an artifact two repositories share.
``test_every_spawn_in_the_suite_passes_the_stripping_helper`` below is what
closes it here.

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
requires an ``env`` keyword ON the ``Call`` node, so a neighbor's keyword
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
both read exactly like compliance.

They are REPLACED rather than moved, and only one of the two lands on the
checker's own accounting line. ``scanned`` becomes ``_MODULE_FLOOR`` over
a wider tree. ``interpreter_spawns`` cannot: the checker counts spawns of
ANY program and does not distinguish an interpreter, so a floor on its
number would be held up by the git spawns alone while the population the
``COV_CORE_*`` incident belongs to went to zero. ``_INTERPRETER_FLOOR``
therefore stays a source-level count, in the value walk below.

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

import ast
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

_ROOT = Path(__file__).resolve().parents[1]
_KIT = _ROOT / ".claude" / "kit"
_SPAWN_CHECK = _KIT / "check_spawn_env.py"
_SPAWN_MUTATIONS = _KIT / "check_spawn_env_mutations.py"

#: The directories the guard covers. Both trees, so a spawn added to
#: library code is judged by the same rule as one added to the suite.
#:
#: `.claude/` IS EXCLUDED, and the reason is stated because an unstated
#: scope boundary is how a reader concludes the tree is clean. Measured on
#: 2026-08-02, `python .claude/kit/check_spawn_env.py .claude` reports
#: `checked 19 module(s), 21 spawn call(s), 20 unguarded, 0 unverifiable`.
#: Every one of the twenty is inside a VENDORED KIT BODY, which this
#: repository is forbidden to hand-edit: the drift pin in
#: `tests/test_kit_drift.py` refuses it, so the fix is a kit promotion and
#: not an edit here. Walking that tree would produce a permanent red no
#: lane could clear, which is the shape that teaches a repository to switch
#: a guard off. Routed rather than absorbed.
_WALKED = ("tests", "itaca")

#: Floors on the checker's own accounting line, set well under the counts
#: measured on 2026-08-02 by `check_spawn_env.py tests itaca`, which
#: reported 147 modules and 33 spawn calls, so they catch a walk that
#: collapsed rather than ordinary drift.
#:
#: THESE REPLACE THE RETIRED GUARD'S FLOORS, they do not carry them over,
#: and the difference matters in one direction. The retired floors were 20
#: test MODULES and 10 spawns OF `sys.executable`; these are 100 modules
#: over two trees and 20 spawns OF ANY KIND. The second is a WIDER
#: population, so a collapse confined to interpreter spawns, which is the
#: population the `COV_CORE_*` incident belongs to, would no longer be
#: floored: the git spawns alone hold the number above 20.
#:
#: `_INTERPRETER_FLOOR` is therefore kept as a second floor, on the narrow
#: population, counted from the source rather than from the checker, which
#: does not distinguish an interpreter from any other program.
_MODULE_FLOOR = 100
_SPAWN_FLOOR = 20

#: A SEPARATE floor for the value walk below, which counts a different
#: population: the calls it can resolve an `env=` value for, over the same
#: two trees. The two numbers are equal today, 33 and 33, only because
#: `itaca/` holds no `subprocess` call at all, and one constant serving two
#: populations stops meaning what its comment says the day they diverge.
#: That is the defect `_INTERPRETER_FLOOR` was split out for, one reader
#: over, and it is not repeated here.
_VALUE_WALK_SPAWN_FLOOR = 20
_INTERPRETER_FLOOR = 10

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
    the ones the retired window guard carried, insofar as the checker's
    own counts can carry them; the module docstring says which one cannot
    and where it went instead.

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


def _spawn_calls(*trees: str) -> list[tuple[Path, ast.Call]]:
    """Every ``subprocess`` spawn Call under ``trees``, with its module.

    The same node set the vendored checker judges, over the same trees,
    read here for the one question the checker deliberately does not
    answer: what the ``env`` keyword's VALUE is.

    The caller passes ``_WALKED`` rather than a literal. A first version
    walked ``tests`` alone while the checker walked both, which was
    harmless only because ``itaca/`` holds no ``subprocess`` call at all,
    and would have gone silently false on the first spawn added to library
    code while the docstring said the gap was closed.
    """
    names = {"run", "Popen", "call", "check_call", "check_output"}
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted(
        candidate for tree in trees for candidate in (_ROOT / tree).rglob("*.py")
    ):
        tree_ast = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree_ast):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if (
                isinstance(callee, ast.Attribute)
                and callee.attr in names
                and isinstance(callee.value, ast.Name)
                and callee.value.id == "subprocess"
            ):
                found.append((path, node))
    return found


#: The two helpers that strip coverage measurement. `hook_env` builds on
#: `child_env` and additionally clears every ledger-shaped variable, so it
#: is a narrowing of the same guarantee rather than a second one.
_HELPERS = frozenset({"child_env", "hook_env"})

#: The TypeAlias a CONSUMING module declares for the `child_env` fixture,
#: which is how a module in a subdirectory reaches the helper without
#: importing it (`tests/core/test_version_resolution.py` defines it). A
#: parameter annotated with it is the helper under another name.
#:
#: `tests/conftest.py` itself annotates the fixture
#: `Callable[..., dict[str, str]]`, so this alias is a convention of the
#: consumers and not of the fixture. A module that annotates the fixture
#: some other way is NOT recognized here and its spawn sites are reported,
#: which is the safe direction and is why the alias is not guessed at.
_FIXTURE_ANNOTATION = "EnvFactory"


@cache
def _helper_names(path: Path) -> frozenset[str]:
    """Every name in ``path`` that IS one of the helpers.

    Cached per path: this is called once per spawn call and would
    otherwise re-read and re-parse a module for every call in it, on a
    guard the commit tier pays for.

    Three ways a spawn site legitimately reaches them, all of them present
    in this suite, and a first version of this walk recognized only the
    first and reported the other two as offenders:

    1. calling one directly, ``env=child_env()``;
    2. binding one to a local first, ``env = hook_env(...)`` then
       ``env=env``, which the push-gate helper does;
    3. taking the fixture as a parameter, ``env: EnvFactory``, then
       ``env=env(PYTHONPATH=...)``, which is what a module in a
       subdirectory must do.

    A BOUND NAME IS TRUSTED ONLY IF EVERY ASSIGNMENT TO IT IS A HELPER
    CALL, and that is not fussiness. This walk is flow-insensitive: it
    sees a module's names, not a function's. Trusting a name on ONE
    helper assignment let a DIFFERENT function in the same module write
    ``env = os.environ.copy()`` and pass ``env=env`` unreported, which is
    the exact `COV_CORE_*` inheritance this guard exists to stop. Round
    two measured that on a synthetic module: `env=os.environ` and
    `env=None` were reported and the rebound local was not. Latent rather
    than live here, because the only assignments to `env` under `tests/`
    today are the helper itself and one `hook_env(...)`.
    """
    names = set(_HELPERS)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.arg)
            and node.annotation is not None
            and _FIXTURE_ANNOTATION in ast.unparse(node.annotation)
        ):
            names.add(node.arg)
    # A second pass, because an assignment may name a fixture parameter
    # collected above and the walk order does not guarantee it was seen.
    # Every assignment to a name is collected, helper or not, so a name
    # assigned anything else anywhere is subtracted rather than trusted.
    bound: dict[str, list[bool]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        callee = node.value.func if isinstance(node.value, ast.Call) else None
        from_helper = isinstance(callee, ast.Name) and callee.id in names
        for target in node.targets:
            if isinstance(target, ast.Name):
                bound.setdefault(target.id, []).append(from_helper)
    names.update(name for name, sources in bound.items() if all(sources))
    return frozenset(names)


def _is_the_helper(value: ast.expr, names: frozenset[str]) -> bool:
    """Whether an ``env=`` value comes from one of the helpers."""
    if isinstance(value, ast.Name):
        return value.id in names
    if isinstance(value, ast.Call):
        callee = value.func
        if isinstance(callee, ast.Name):
            return callee.id in names
        if isinstance(callee, ast.Attribute):
            return callee.attr in names
    return False


def test_every_spawn_in_the_suite_passes_the_stripping_helper() -> None:
    """`env=` PRESENCE is not `env=child_env()`, and only one of them is safe.

    The vendored checker requires an ``env`` keyword ON the call and stops
    there, which its own docstring states: it cannot see inside a dict it
    did not build. That is the right boundary for a shared artifact and it
    leaves one gap this repository can close on its own. ``env=os.environ``
    satisfies the checker exactly as ``env=child_env()`` does, and it
    re-introduces the whole failure the rule exists for: a child that
    inherits ``COV_CORE_*`` starts coverage without branch data and aborts
    the run in teardown, AFTER every test has passed.

    The retired window guard had the same gap, matching the text ``env=``,
    so this is new ground rather than a regression. It is closed here
    because the eight sites this lane changed were changed on the strength
    of that helper, and nothing asserted they use it.

    THE SCOPE IS ``_WALKED``, the same two trees the checker walks, so the
    claim above is true by construction and not by ``itaca/`` happening to
    hold no spawn today.

    WHAT IT STILL CANNOT SEE, because a guard's exceptions are worth its
    claim: this walk is FLOW-INSENSITIVE. It reads a module's names, not a
    function's. A name is trusted only when EVERY assignment to it in the
    module is a helper call, which is what keeps one rebinding elsewhere
    from excusing a site, but a value reached through a call this walk
    cannot resolve is not judged at all.

    Read the accounting: a walk that found no call would satisfy
    ``assert not offenders`` and read exactly like compliance.
    """
    offenders: list[str] = []
    interpreter_spawns = 0
    calls = _spawn_calls(*_WALKED)
    for path, node in calls:
        env = next((kw for kw in node.keywords if kw.arg == "env"), None)
        argv = node.args[0] if node.args else None
        if isinstance(argv, ast.List) and argv.elts:
            first = argv.elts[0]
            if (
                isinstance(first, ast.Attribute)
                and first.attr == "executable"
                and isinstance(first.value, ast.Name)
                and first.value.id == "sys"
            ):
                interpreter_spawns += 1
        if env is None:
            continue  # the vendored checker owns that verdict, not this one
        if not _is_the_helper(env.value, _helper_names(path)):
            offenders.append(f"{path.relative_to(_ROOT).as_posix()}:{node.lineno}")
    assert len(calls) >= _VALUE_WALK_SPAWN_FLOOR, (
        f"the value walk found only {len(calls)} spawn call(s) under "
        f"{list(_WALKED)}, below the floor of {_VALUE_WALK_SPAWN_FLOOR}. The "
        f"walk is finding nothing, so a green verdict here means nothing; fix "
        f"the walk before reading it."
    )
    assert interpreter_spawns >= _INTERPRETER_FLOOR, (
        f"only {interpreter_spawns} spawn(s) of sys.executable were found, "
        f"below the floor of {_INTERPRETER_FLOOR}. That is the NARROW "
        f"population the COV_CORE_* incident belongs to, and the checker's "
        f"own count cannot see it because it does not distinguish an "
        f"interpreter from any other program. A count this low means the "
        f"idiom moved and this walk no longer sees it."
    )
    assert not offenders, (
        f"these spawn calls pass an env= whose value is not child_env() or "
        f"hook_env(): {offenders}. The vendored checker accepts any env "
        f"keyword, so env=os.environ satisfies it while inheriting "
        f"COV_CORE_* and aborting the run after every test has passed. Pass "
        f"the stripping helper, or add a new helper here and to this list "
        f"deliberately."
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
