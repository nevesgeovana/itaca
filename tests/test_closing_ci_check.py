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

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
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

    It carries its own traps, worth knowing before reading its output, and
    both were found by running mutants rather than by reasoning about them.
    The absent-body mutant first deleted the BRANCH, and the mutant still
    refused, because a body named "None" fails to run; it now mutates the
    DECISION to return green. The positional-argument branch has no mutant
    at all, because removing it leaves the unknown-option guard to refuse
    the same token, so the companion says so in place rather than carrying a
    mutant that passes on a neighbor's work.

    THE COMPANION'S OWN BLIND SPOT WAS THE FINDING THAT GREW IT. Round one
    measured that every stub here ignores argv, so deleting the
    `--workflow` pass-through left this suite green AND the companion still
    printed a full score. The `recording` fixture answers according to its
    argv, which is the only shape that can see a pass-through.
    """
    done = subprocess.run(
        [sys.executable, str(MUTATIONS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "9/9 mutants confirmed" in done.stdout, done.stdout


def test_a_green_run_lets_the_lane_report_closed(repo: Path) -> None:
    """The control, and it is what makes every refusal below meaningful.

    Four refusals prove nothing on their own: a checker that refused every
    state would produce all of them and would be a checker no lane could
    ever close through.

    It names a workflow, and must: since round one a GREEN over no named
    workflow is downgraded to UNKNOWN, so this case would otherwise measure
    the downgrade rather than the pass. That property has its own case in
    `test_a_green_with_no_named_workflow_is_downgraded`.
    """
    stub_ci_state(repo, GREEN, "GREEN, all runs concluded successfully")
    code, out = check(repo, "--workflow", "CI")
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
        # CONFIG is `ci_state.py` running and reporting that IT could not
        # answer, which is distinct from this checker failing to find it.
        # It reaches the refusal through the `EXIT.get(state, CONFIG)`
        # DEFAULT rather than through the mapping, so without this case that
        # default could be changed to 0 and every other case would stay
        # green. A QA lens measured exactly that gap in round two.
        (CONFIG, CONFIG, "CONFIG"),
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
    code, out = check(repo, "--workflow", "CI")
    assert code == expected, out
    assert f"closing-ci: {word}" in out, out
    assert "may NOT report itself closed" in out, out
    # The remedy must name what to write instead, or the lane invents one.
    assert "CI state NOT VERIFIED" in out, out
    # And the remedy must not name a state this run did not report: the
    # UNKNOWN default once printed "UNKNOWN is refused rather than assumed
    # benign" under a CONFIG verdict.
    if word != "UNKNOWN":
        assert "UNKNOWN is refused" not in out, out


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


@pytest.mark.parametrize(
    "args,phrase",
    [
        # The equals form: parsed as the option `sha=<value>` by the first
        # version, leaving no `sha` at all.
        (("--sha=deadbeefdeadbeef",), "does not resolve"),
        # An unknown option: recorded as an option name by the first
        # version, which then ate `--sha` as its VALUE.
        (("--verbose", "--sha", "HEAD"), "not an option"),
        # A positional: silently dropped by the first version.
        (("HEAD",), "no positional arguments"),
        # An option with no value at all.
        (("--sha",), "no value"),
        # An option whose value is another option.
        (("--sha", "--repo"), "another option"),
    ],
)
def test_an_argument_it_cannot_read_refuses_instead_of_answering_about_head(
    repo: Path, args: tuple[str, ...], phrase: str
) -> None:
    """THE WORST DEFECT ROUND ONE FOUND, and it was in the parser.

    Three reviewer lenses found the same shape independently. The first
    `_parse` recorded any `--` token as an option name and ignored anything
    else, so `--sha=abc`, `--verbose --sha abc` and a bare `abc` all left
    `opts` with no `sha`. The caller then fell back to HEAD and printed a
    GREEN verdict about a commit nobody asked about.

    That is the exact failure this whole file exists to prevent, one level
    up: a success sentence over a question that was never asked. The stub
    answers GREEN in every case below, so a regression here does not merely
    change a message, it lets the checker answer about the wrong commit.

    A regression would surface as exit 4 rather than 0 today, because none
    of these cases names a `--workflow` and the workflow downgrade landed in
    the same commit as the parser. That is a second guard catching the same
    class, not a reason to write the weaker assertion: `assert code ==
    CONFIG` distinguishes "refused the argument" from "fell through to
    HEAD and then tripped over something else".

    The equals form is ACCEPTED and refused on the sha's merits (it does not
    resolve), rather than refused as a form; the other four are refused as
    arguments. Both outcomes are non-zero, which is what matters.
    """
    stub_ci_state(repo, GREEN, "GREEN, and reaching this is the defect")
    code, out = check(repo, *args)
    assert code == CONFIG, out
    assert phrase in out, out
    assert "closing-ci: GREEN" not in out, out


def test_the_unpushed_exit_code_does_not_collide_with_the_kit_contract() -> None:
    """5 must stay free upstream, or two vocabularies collide silently.

    UNPUSHED is this repository's own state, added on top of `ci_state.py`'s
    published exit contract. That reuse is deliberate (DD-54 item 3), and it
    carries one one-directional trap: if the kit ever assigns 5 to a CI
    state, this checker would map that state onto a local meaning and the
    collision would be invisible.

    Reading the contract out of the checker rather than restating it is the
    point: a renumbering upstream that the vendored body adopts breaks this
    test rather than a close.
    """
    # READ FROM THE AUTHORITY, which is the vendored `ci_state.py` and not
    # this repository's restatement of it. The first version of this guard
    # parsed `CI_EXIT_STATE` out of `closing_ci_check.py`, which is a
    # hand-written second copy of the same fact, so it compared a literal
    # against a copy of itself and could not see the upstream renumbering
    # its own docstring claims it catches. A QA lens measured that in round
    # two. `.claude/hooks/ci_state.py` is drift-pinned by
    # `tests/test_kit_drift.py`, so it cannot change without a re-vendor.
    authority = _ROOT / ".claude" / "hooks" / "ci_state.py"
    assert authority.is_file(), (
        f"the vendored ci_state.py is missing at {authority}; this guard "
        f"cannot read the exit contract it is checking against."
    )
    body = authority.read_text(encoding="utf-8")
    contract = re.search(r"\nEXIT = \{([^}]*)\}", body)
    assert contract is not None, (
        f"could not find the EXIT mapping in {authority}; this guard cannot "
        f"say whether the UNPUSHED code collides with the kit contract."
    )
    codes = {int(code) for code in re.findall(r":\s*(\d+)", contract.group(1))}
    assert codes, f"the EXIT mapping parsed as empty from {authority}"
    # CONFIG is declared beside it rather than inside it, and it is part of
    # the same published contract, so read it too.
    config = re.search(r"\nCONFIG = (\d+)", body)
    if config:
        codes.add(int(config.group(1)))
    assert UNPUSHED not in codes, (
        f"exit {UNPUSHED} (UNPUSHED, this repository's own) is now also in "
        f"the vendored ci_state.py's published contract {sorted(codes)}. Two "
        f"vocabularies share one number, so a caller cannot tell a local "
        f"precondition from a CI state. Renumber UNPUSHED in "
        f".claude/tools/closing_ci_check.py and in this module's constants."
    )
    # And the restatement inside the checker must still agree with the
    # authority, or the checker maps upstream codes to the wrong states
    # while this guard reads the right file and passes.
    restated = re.search(
        r"CI_EXIT_STATE = \{([^}]*)\}", CHECK.read_text(encoding="utf-8")
    )
    assert restated is not None, f"could not find CI_EXIT_STATE in {CHECK}"
    mirrored = {int(code) for code in re.findall(r"(\d+):", restated.group(1))}
    assert mirrored == codes, (
        f"{CHECK} restates ci_state.py's exit contract as {sorted(mirrored)} "
        f"while the vendored body publishes {sorted(codes)}. The restatement "
        f"is a second copy of one fact and has drifted; make them equal."
    )


def test_a_repository_that_does_not_resolve_refuses(tmp_path: Path) -> None:
    """One of the five advertised fail-closed paths, previously untested.

    Round one found that two of the five paths the module docstring
    advertises had no case at all. This is the cheaper of the two: a
    directory under the OS temp root is inside no checkout, so git resolves
    no repository and the check must refuse rather than proceed against
    some ambient tree.
    """
    outside = tmp_path / "not_a_repo"
    outside.mkdir()
    code, out = check(outside)
    assert code == CONFIG, out
    assert "no git repository resolves" in out, out
    assert "closing-ci: GREEN" not in out, out


def test_a_green_with_no_named_workflow_is_downgraded(repo: Path) -> None:
    """A verdict over whatever happened to be indexed is not a verdict.

    The QA and V and V lenses found this together and it falsified the
    module docstring's strongest sentence. `ci_state.py` applies its "a
    named workflow that has not appeared is UNKNOWN, not absent" rule ONLY
    to names it is given, so with none, a workflow that has not been indexed
    yet or that stopped triggering is invisible, and every other run being
    green reads as GREEN forever.

    The stub answers GREEN in both halves below; the only difference is
    whether a workflow was named, which is exactly the property under test.
    """
    stub_ci_state(repo, GREEN, "GREEN, stubbed")
    code, out = check(repo)
    assert code == UNKNOWN, out
    assert "NO required workflow was named" in out, out
    assert "may NOT report itself closed" in out, out
    # And naming one restores the green, so the downgrade is the named
    # condition and not a checker that can no longer pass at all.
    code, out = check(repo, "--workflow", "CI")
    assert code == GREEN, out


def test_the_named_workflows_reach_ci_state(repo: Path) -> None:
    """The pass-through must actually be passed through.

    A gap the mutation companion could not see when it was written: every
    other case stubs `ci_state.py` with a body that ignores argv, so
    deleting the `--workflow` expansion in `_ask_ci` left the whole suite
    green. This stub records its argv instead, which is the only way to
    assert the flag survives the call boundary.
    """
    hooks = repo / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    record = repo / "argv.txt"
    (hooks / "ci_state.py").write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(record)!r}).write_text(' '.join(sys.argv[1:]))\n"
        "print('ci-state: GREEN, stubbed')\nsys.exit(0)\n",
        encoding="utf-8",
    )
    code, out = check(repo, "--workflow", "CI", "--workflow", "SRS build")
    assert code == GREEN, out
    argv = record.read_text(encoding="utf-8")
    assert "--workflow CI" in argv, argv
    assert "--workflow SRS build" in argv, argv


def test_the_handoff_skill_names_a_workflow_that_actually_exists() -> None:
    """The prescribed call must name workflows this repository really runs.

    The checker is stdlib-only and cannot parse the workflow files, so the
    required names live in the skill's prescribed command. That makes them a
    second copy of a fact, and this test is what stops the copy from
    drifting: every `--workflow` name the skill prescribes must be the
    `name:` of a workflow in `.github/workflows` that triggers on push.

    Discovery rather than enumeration, deliberately: a workflow renamed in
    `.github/workflows` reddens this rather than silently making the closing
    check ask about a workflow that no longer exists, which `ci_state.py`
    would answer UNKNOWN forever.
    """
    skill = (_ROOT / ".claude" / "skills" / "handoff" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    prescribed = set(re.findall(r"--workflow (\w[\w ]*?)(?= --|\n|$)", skill))
    assert prescribed, (
        "the handoff skill prescribes no --workflow, so its closing check "
        "downgrades every green to UNKNOWN and the step is unusable."
    )
    on_push: set[str] = set()
    for workflow in sorted((_ROOT / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            continue
        # PyYAML reads a bare `on:` key as the boolean True.
        triggers = loaded.get("on", loaded.get(True)) or {}
        if isinstance(triggers, dict) and "push" in triggers:
            on_push.add(str(loaded.get("name", "")))
    unknown = sorted(prescribed - on_push)
    assert not unknown, (
        f"the handoff skill prescribes --workflow {unknown}, which is not the "
        f"name of any push-triggered workflow in .github/workflows "
        f"({sorted(on_push)}). ci_state.py answers UNKNOWN forever for a "
        f"workflow that never appears, so the closing check would never go "
        f"green. Fix the name in the skill, or the workflow's `name:`."
    )


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

    PRESENCE IS NOT ENOUGH, and the first version of this test proved it.
    It asserted only that the path appeared SOMEWHERE in the skill, and it
    passed at `b82fe2b` with the step sitting in item 1, ABOVE the closing
    commit and push that the same skill makes, so the check answered about
    the state BEFORE the handoff's own push. An api-designer lens found the
    placement in round one and a QA lens found that this test could not see
    it in round two. So placement and arguments are asserted here too.

    It is still a PROSE check and its limit is stated rather than hidden: it
    proves the instruction is present, correctly placed and correctly
    parameterized, never that a session obeyed it. What makes obedience
    cheap is that the checker exits nonzero, so a lane that runs it cannot
    misread the answer. Closing that gap properly needs the close itself to
    be a mechanism rather than a report, which is registered and not done.
    """
    skill = _ROOT / ".claude" / "skills" / "handoff" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert ".claude/tools/closing_ci_check.py" in text, (
        f"{skill} does not name the closing CI check, so the guard for "
        f"INC-20260811-1745-itaca is vendored but not wired. Add the step "
        f"back to the closing sequence."
    )
    # PLACEMENT: after the instruction that pushes. Compared by offset
    # rather than by section heading, because a heading can be renamed
    # while the order stays wrong, and the order is the property.
    check_at = text.index(".claude/tools/closing_ci_check.py")
    push_at = text.index("commit the\nrepository-side changes of the session")
    assert check_at > push_at, (
        f"{skill} names the closing CI check at offset {check_at}, BEFORE the "
        f"closing commit and push at {push_at}. It then verifies the state "
        f"the handoff's own push is about to change, which is the defect "
        f"round one found. Move the step to the end of `out`."
    )
    # ARGUMENTS: without a named workflow the checker downgrades every green
    # to UNKNOWN, so a prescription that omits it makes the step unusable
    # and invites a session to ignore the answer.
    prescribed = text[check_at : check_at + 200]
    assert "--workflow" in prescribed, (
        f"{skill} prescribes the closing check without `--workflow`. A green "
        f"over no named workflow is downgraded to UNKNOWN by design, so the "
        f"step would never pass and would be routed around."
    )
    assert "--sha" in prescribed, (
        f"{skill} prescribes the closing check without `--sha`. It would then "
        f"answer about HEAD, which after a session-document commit is not the "
        f"commit that was pushed."
    )
