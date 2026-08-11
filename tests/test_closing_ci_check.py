"""Guards for the closing CI check: a push may not be CALLED closed unguarded.

Usage example (TDD anchor)::

    state, out = check(repo, ci_exit=1)   # ci_state.py says RED
    assert state == 1                      # the close is refused

``INC-20260811-1745-itaca``. Every lane's closing sequence proved the
commits ARRIVED and never that they BUILD: ``git ls-remote`` and ``git
rev-list HEAD --not --remotes`` both answer questions about REFS, and
neither can go red when the build does. Measured on 2026-08-02, CI was red
on ``main`` for three consecutive pushes and no session noticed.

WHY THE PUSH GATE IS NOT THIS GUARD, since that is the mistake the record
was written to prevent. Kit 0.2.18's CI arm fires only on an explicit
version TAG, and its own companion PASSES on ``an ordinary branch push on a
RED commit is not this arm's business``. ``tests/test_push_gate.py``
asserts that ALLOW deliberately, in
``test_an_ordinary_branch_push_is_not_this_arms_business``. The three
pushes that produced this record had no tag in sight, so the tag arm cannot
reach them and this module is the branch half.

WHAT IS PINNED HERE, in the order the checker decides:

- a commit that is on no remote refuses UNPUSHED, before CI is asked at
  all, because a local commit has no CI result by construction;
- an absent ``ci_state.py`` refuses CONFIG rather than skipping;
- every non-green CI state refuses, one case each, and the refusal carries
  the sentence a lane must write instead of "closed";
- GREEN passes, which is the control that stops the four refusals above
  from being satisfied by a checker that refuses everything;
- an exit code OUTSIDE ``ci_state.py``'s documented contract is UNKNOWN and
  refuses, so a state added there can never arrive here as a silent pass.

THE STUB IS THE POINT, not a shortcut. RED, RUNNING and UNKNOWN cannot be
produced on demand from a real remote, and a suite that waited for a real
red CI run would test nothing on most days. The stub stands in for
``ci_state.py`` alone; what it cannot fake is the checker's own decision,
which is what these cases measure. The live half, against this repository's
real remote and a commit CI genuinely reported RED on, is recorded as guard
evidence in the incident.

Every case builds a throwaway repository with a local bare remote, so
nothing here touches the real checkout or the real remote, and the checker
runs as a subprocess through ``child_env`` so a child never starts coverage
(see tests/conftest.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

# Process-level: every case spawns the checker, and several spawn git as
# well. It runs at pre-push and in CI, exactly like the other gate modules.
pytestmark = pytest.mark.slow

_ROOT = Path(__file__).resolve().parents[1]
CHECK = _ROOT / ".claude" / "tools" / "closing_ci_check.py"
MUTATIONS = _ROOT / ".claude" / "tools" / "closing_ci_check_mutations.py"

#: The checker's exit taxonomy, which is ``ci_state.py``'s contract plus
#: UNPUSHED. Named here so a case reads as its outcome rather than a number,
#: and so a renumbering breaks one line instead of twelve.
GREEN, RED, CONFIG, RUNNING, UNKNOWN, UNPUSHED = 0, 1, 2, 3, 4, 5


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return stripped stdout."""
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=child_env(),
    )
    return done.stdout.strip()


def stub_ci_state(repo: Path, exit_code: int | None, message: str = "stub") -> None:
    """Write a fake ``ci_state.py`` into the fixture, or none at all.

    ``exit_code`` of None writes nothing, which is the CONFIG case: the
    checker then finds the body nowhere it looks. The stub lands in
    ``.claude/hooks`` because that is where this repository vendors the real
    one and the first entry of the checker's search list.
    """
    hooks = repo / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    if exit_code is None:
        return
    (hooks / "ci_state.py").write_text(
        f"import sys\nprint('ci-state: {message}')\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )


def check(repo: Path, *args: str) -> tuple[int, str]:
    """Run the closing check in ``repo`` and return (exit code, output)."""
    done = subprocess.run(
        [sys.executable, str(CHECK), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=repo,
    )
    return done.returncode, done.stdout + done.stderr


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose HEAD is pushed to a local bare remote."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", str(remote)], check=True, env=child_env()
    )
    work = tmp_path / "work"
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
    return work


def test_the_checker_is_present() -> None:
    """A checker loaded by path fails loudly if it is missing.

    Without this a rename removes the whole guard and every case below
    would report the same CONFIG exit as a genuine misconfiguration, which
    is the self-skipping evidence the incident rule exists to replace.
    """
    assert CHECK.is_file(), f"the closing CI check is missing at {CHECK}"
    assert MUTATIONS.is_file(), f"its mutation companion is missing at {MUTATIONS}"


@pytest.mark.guardproof
def test_the_closing_check_can_still_fail() -> None:
    """The mutation companion proves each refusal is load-bearing.

    The ledger's rule is that a guard is proven by mutation, because the
    cases above could all pass against a checker that refuses for a reason
    other than the line believed to be doing the work. The companion removes
    each load-bearing decision and requires the refusal to become a PASS.

    It carries its own trap, worth knowing before reading its output: the
    first version of its absent-body mutant deleted the BRANCH, and the
    mutant still refused, because a body named "None" fails to run. A
    refusal that becomes a differently labeled refusal proves nothing about
    failing closed, so the mutation now makes that branch return green.
    """
    done = subprocess.run(
        [sys.executable, str(MUTATIONS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "5/5 mutants confirmed" in done.stdout, done.stdout


def test_a_green_run_lets_the_lane_report_closed(repo: Path) -> None:
    """The control, and it is what makes every refusal below meaningful.

    Four refusals prove nothing on their own: a checker that refused every
    state would produce all of them and would be a checker no lane could
    ever close through.
    """
    stub_ci_state(repo, GREEN, "GREEN, all runs concluded successfully")
    code, out = check(repo)
    assert code == GREEN, out
    assert "closing-ci: GREEN" in out, out
    # The refusal sentence must NOT appear on the one state that permits it.
    assert "may NOT report itself closed" not in out, out


@pytest.mark.parametrize(
    "ci_exit,expected,word",
    [
        (RED, RED, "RED"),
        (RUNNING, RUNNING, "RUNNING"),
        (UNKNOWN, UNKNOWN, "UNKNOWN"),
    ],
)
def test_every_non_green_state_refuses_the_claim(
    repo: Path, ci_exit: int, expected: int, word: str
) -> None:
    """RED, RUNNING and UNKNOWN each forbid the claim, and say which.

    This is the guard `INC-20260811-1745-itaca` asks for. RUNNING is the
    ordinary case right after a push and is refused anyway: an unfinished
    run is not a green one, and the record's whole point is that a lane
    called three red pushes clean without asking.
    """
    stub_ci_state(repo, ci_exit, f"{word}, stubbed")
    code, out = check(repo)
    assert code == expected, out
    assert f"closing-ci: {word}" in out, out
    assert "may NOT report itself closed" in out, out
    # The remedy must name what to write instead, or the lane invents one.
    assert "CI state NOT VERIFIED" in out, out


def test_the_refusal_forbids_the_synonyms_too(repo: Path) -> None:
    """ "Closed" is not the only word a lane reaches for.

    The failure is a CLAIM that the work landed clean, and a report saying
    "pushed successfully" makes it just as squarely as one saying "closed".
    The refusal names the synonyms so that obeying it literally is enough.
    """
    stub_ci_state(repo, RED, "RED, stubbed")
    _, out = check(repo)
    for word in ("successful", "clean", "done"):
        assert word in out, f"the refusal does not forbid {word!r}: {out}"


def test_an_unpushed_commit_refuses_before_ci_is_asked(repo: Path) -> None:
    """A local commit has no CI result by construction, and says so.

    Asking CI about a commit that never left the machine returns "no run is
    visible", which is UNKNOWN and reads as a network problem. It is a
    different failure with a different remedy, so it gets its own exit code
    and its own sentence. The stub is GREEN here deliberately: if the check
    asked CI at all, this case would pass with exit 0, so the assertion
    below is what proves the precondition runs FIRST.
    """
    stub_ci_state(repo, GREEN, "GREEN, and this must never be reached")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "local only")
    code, out = check(repo)
    assert code == UNPUSHED, out
    assert "UNPUSHED" in out, out
    assert "on no remote" in out, out
    assert "may NOT report itself closed" in out, out


def test_an_absent_ci_state_refuses_rather_than_skipping(repo: Path) -> None:
    """The fail-closed half, on the COORD_INCIDENT_LEDGER precedent.

    A guard that reads its own missing information as permission is not a
    guard. This repository has already paid for that once: kit 0.2.6's push
    gate read an absent ledger as does-not-apply.
    """
    stub_ci_state(repo, None)
    code, out = check(repo)
    assert code == CONFIG, out
    assert "not vendored" in out, out
    assert "refusal and not a skip" in out, out


def test_an_exit_code_outside_the_contract_is_unknown(repo: Path) -> None:
    """A state `ci_state.py` adds later must not arrive here as a pass.

    The exit mapping is read as a MAPPING and never as "nonzero is bad":
    99 is not in the contract, so it is UNKNOWN, and UNKNOWN refuses. Had
    it been read as a default-to-pass table, a future state would have
    silently become permission.
    """
    stub_ci_state(repo, 99, "a state this contract does not know")
    code, out = check(repo)
    assert code == UNKNOWN, out
    assert "outside its documented contract" in out, out
    assert "may NOT report itself closed" in out, out


def test_a_named_sha_that_does_not_resolve_is_a_config_error(repo: Path) -> None:
    """A misspelled --sha must refuse, never fall back to HEAD.

    Falling back would answer a question about a DIFFERENT commit than the
    one asked about and report it as the answer, which is the shape of
    every false-green in this repository's ledger.
    """
    stub_ci_state(repo, GREEN)
    code, out = check(repo, "--sha", "deadbeefdeadbeef")
    assert code == CONFIG, out
    assert "does not resolve" in out, out


def test_the_handoff_skill_actually_runs_this_check() -> None:
    """The guard must be WIRED into the closing sequence, not merely present.

    A checker sitting in `.claude/tools` that nothing calls is the same
    shape as the defect it exists to catch, which is exactly what this
    repository already says about `ITACA-006`. This asserts the handoff
    skill names the checker by path, so deleting the step from the skill
    reddens the suite.

    It is a PROSE check and its limit is stated rather than hidden: it
    proves the instruction is present, never that a session obeyed it. What
    makes obedience cheap is that the checker exits nonzero, so a lane that
    runs it cannot misread the answer. Closing that gap properly needs the
    close itself to be a mechanism rather than a report, which is registered
    and not done here.
    """
    skill = _ROOT / ".claude" / "skills" / "handoff" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert ".claude/tools/closing_ci_check.py" in text, (
        f"{skill} does not name the closing CI check, so the guard for "
        f"INC-20260811-1745-itaca is vendored but not wired. Add the step "
        f"back to the closing sequence."
    )
