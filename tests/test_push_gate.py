"""End to end guards for the role-review push gate hook.

Usage example (TDD anchor)::

    decision = decide(repo, "git" + " push origin main")
    assert decision == "deny"  # nothing attested yet

``tests/test_review_gate.py`` pins the gate's pure parsing functions.
This file pins the decision itself, because the parsing can be right
while the enforcement is wrong: the range fix that closed the
attest-only-the-tip hole in pyflightstream opened a worse one on the
release path, and only an adversarial review caught it. The hook is
process infrastructure rather than library code, so these guards were
written after the port rather than before it; that ordering is a
deliberate exception to the TDD rule, which governs the ``itaca``
package.

Each test builds a throwaway repository with a local bare remote, so
nothing here touches the real checkout, the real attestation, or the
shared incident ledger. The hook is invoked exactly as the harness
invokes it: the PreToolUse payload on stdin, a permission decision on
stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from gate_locator import ledger_env  # one reader of the gate's ledger variable

# MEASURED 108 s on 2026-07-30, and the cost is in SETUP rather than in the
# assertions: the module collects 60 tests, and those that build a scratch
# git repository and spawn the hook as a subprocess cost 1.1 to 2.5 s apiece.
# An earlier version of this comment said 42, which is neither the collected
# count nor a number it identified; a reviewer measured 60.
#
# NOT weakened by the marker. This module pins a gate that must not fail
# open, so it runs at pre-push, where it blocks, and in CI on every pull
# request. What it stops doing is running 42 subprocess spawns on a commit
# that touched a docstring.
pytestmark = pytest.mark.slow

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "role_review_gate.py"
ATTESTATION = Path(".claude") / ".role_review_attestation.json"


# READ from the gate rather than written here. A literal in this file was a
# second copy of one fact, and when kit 0.2.8 renamed the variable
# (COORD_INCIDENT_LEDGER, author decision LEDGER-ENVVAR) this module went on
# exporting the old name: five cases then set a variable the gate does not
# read, so the gate saw an unset ledger and denied, and the failures reported
# nothing about what they test. `tests/gate_locator.py` is the single reader,
# shared with tests/test_house_style.py, and it refuses an ambiguous gate.
LEDGER_ENV = ledger_env()
#: Every variable whose name ends this way is stripped from a hook subprocess
#: environment, not just the one the gate currently reads. The retired
#: ITACA_INCIDENT_LEDGER and the sister's PYFS_INCIDENT_LEDGER are both
#: exported on the author's machine, so leaving them in place made this
#: module's hermeticity claim false the moment a gate revision read either:
#: measured, a decoy assignment that fooled the reader above sent 24 cases to
#: consult the real ledger.
_LEDGER_SUFFIX = "_LEDGER"
# Built by concatenation so this file never contains the literal command
# it tests; the gate scans command text and would flag work on this file.
PUSH = "git" + " push"


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


#: The default for ``ledger=``: a CLEAN stub ledger built beside the
#: throwaway repository. Distinct from ``None``, which means the variable is
#: genuinely unset, because kit 0.2.8 made those two different answers: an
#: absent ledger now DENIES. Before 0.2.8 an unset variable read as "the
#: check does not apply", so stripping it was both hermetic and neutral, and
#: one default served every case. It is no longer neutral, and a test about
#: ref scoping must not deny because of a variable it never mentions.
_CLEAN = object()


def hook_env(ledger: str | None) -> dict[str, str]:
    """The environment a hook subprocess runs in.

    ``child_env`` (tests/conftest.py) strips coverage measurement. EVERY
    ledger-shaped variable is stripped and only the one the gate reads is set,
    to whatever the caller resolved, so no case depends on the state of a
    ledger outside the repository.

    Stripping the whole family rather than one name is the difference between
    a hermeticity claim and a hermeticity guarantee. The retired
    ``ITACA_INCIDENT_LEDGER`` and the sister repository's
    ``PYFS_INCIDENT_LEDGER`` are both exported on the author's machine, so a
    gate revision reading either would have quietly handed this suite the real
    ledger while this docstring said otherwise.

    ``ledger`` has NO DEFAULT, deliberately. It defaulted to None, which meant
    "unset", which was neutral at kit 0.2.6 and is a DENIAL at 0.2.8. A
    defaulted call would now produce a puzzling refusal that reads as a review
    failure, so the choice is made explicit at every call site.
    """
    stripped = {name: None for name in os.environ if name.endswith(_LEDGER_SUFFIX)}
    return child_env(**{**stripped, LEDGER_ENV: ledger})


def _resolve_ledger(repo: Path, ledger: str | None | object) -> str | None:
    """Turn the ``ledger=`` argument into an environment value.

    ``_CLEAN`` builds a stub that runs and reports no blocking incident, so
    the incident half of the gate is CONFIGURED and quiet. ``None`` leaves
    the variable unset, which since kit 0.2.8 is itself a denial.
    """
    if ledger is _CLEAN:
        return stub_ledger(repo.parent / "clean_ledger", 0, "clean for")
    assert ledger is None or isinstance(ledger, str)
    return ledger


def judge(
    repo: Path, command: str, ledger: str | None | object = _CLEAN
) -> tuple[str, str]:
    """Run the hook on ``command`` and return (decision, reason).

    The incident ledger is a clean stub by default, never the real one, so
    the suite stays hermetic: inheriting the author's ledger would make every
    case depend on state outside the repository, and a real open incident
    would fail tests that are not about incidents at all. Pass ``None``
    explicitly to test the unset variable, which is a denial in its own right.
    """
    env = hook_env(_resolve_ledger(repo, ledger))
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
    )
    if not done.stdout.strip():
        return "allow", ""
    out = json.loads(done.stdout)["hookSpecificOutput"]
    return str(out["permissionDecision"]), str(out.get("permissionDecisionReason", ""))


def decide(repo: Path, command: str, ledger: str | None | object = _CLEAN) -> str:
    """Run the hook on ``command`` and return its permission decision."""
    return judge(repo, command, ledger)[0]


def stderr_of(repo: Path, command: str, ledger: str | None | object = _CLEAN) -> str:
    """Run the hook on ``command`` and return what it wrote to stderr.

    The permission decision travels on stdout; the gate's observability
    line (a passing gate announcing itself) travels on stderr, which
    ``judge`` does not surface. Kept separate so the decision helpers stay
    about the decision.
    """
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        cwd=repo,
        env=hook_env(_resolve_ledger(repo, ledger)),
    )
    return done.stderr


def stub_ledger(folder: Path, exit_code: int, message: str) -> str:
    """Write a fake check_incidents.py that exits with ``exit_code``.

    The real ledger lives outside the repository, so the only way to
    exercise the branch that matters (a checker that runs and reports a
    blocking incident) is to stand one up here. Without this the gate
    could be disabled entirely and the suite would stay green.
    """
    folder.mkdir(parents=True, exist_ok=True)
    checker = folder / "check_incidents.py"
    checker.write_text(
        f"import sys\nprint({message!r} + ' ' + sys.argv[1])\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return str(folder)


def attest(repo: Path, commits: list[str], kind: str = "review") -> None:
    """Write an attestation covering ``commits``."""
    path = repo / ATTESTATION
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    existing[kind] = {"head": commits[0] if commits else "", "commits": commits}
    path.write_text(json.dumps(existing), encoding="utf-8")


def add_commit(repo: Path, name: str) -> str:
    """Add one commit and return its sha."""
    (repo / f"{name}.txt").write_text(name, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one pushed commit and a local bare remote."""
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
    # Name the branch, so a test that pushes "main" by name pushes a ref
    # that exists locally. git init picks master or main depending on the
    # installation, and the gate now resolves the named ref.
    git(work, "branch", "-M", "main")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    git(work, "fetch", "-q", "origin")
    return work


def test_unattested_push_is_denied(repo: Path) -> None:
    """A new commit with no attestation never ships."""
    add_commit(repo, "one")
    assert decide(repo, f"{PUSH} origin main") == "deny"


def test_attested_range_is_allowed(repo: Path) -> None:
    """An attestation covering every new commit clears the gate."""
    first = add_commit(repo, "one")
    second = add_commit(repo, "two")
    attest(repo, [second, first])
    assert decide(repo, f"{PUSH} origin main") == "allow"


def test_attesting_only_the_tip_is_denied(repo: Path) -> None:
    """The defect ITACA's own role review found: no free rides for ancestors.

    The fixture forces two unpushed commits rather than letting the case
    skip itself when the repository happens to hold only one, because
    the previous evidence for this gate was a script whose main case
    could skip itself and still report all clear.
    """
    add_commit(repo, "one")
    tip = add_commit(repo, "two")
    attest(repo, [tip])
    assert decide(repo, f"{PUSH} origin main") == "deny"


def test_tag_push_needs_the_release_attestation_when_the_branch_is_pushed(
    repo: Path,
) -> None:
    """The regression the range fix introduced, and the reason for in_scope.

    Pushing the branch first leaves the tagged commit already on the
    remote, so the range of new commits is empty. Set containment over
    an empty range is vacuously true, which briefly let an unattested
    tag reach the publish workflow.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
    git(repo, "fetch", "-q", "origin")
    git(repo, "tag", "v9.9.9")
    assert git(repo, "rev-list", "HEAD", "--not", "--remotes") == ""
    # Review-attested but not release-attested: the release gate holds.
    assert decide(repo, f"{PUSH} origin v9.9.9") == "deny"
    attest(repo, [head], kind="release")
    assert decide(repo, f"{PUSH} origin v9.9.9") == "allow"


def test_a_configured_but_unreadable_ledger_blocks(repo: Path, tmp_path: Path) -> None:
    """A ledger that cannot be consulted must not read as all clear.

    THE SUB-KIND IS ASSERTED, not only the denial, and kit 0.2.8 is why. Until
    then an unset variable was neutral, so a deny on this path could only have
    come from the configured-but-broken case and ``== "deny"`` discriminated by
    itself. Now BOTH deny, so the bare assertion separates nothing: measured,
    relabelling the gate's unreadable-checker branch to ``unconfigured`` left
    the whole module green.

    The two have OPPOSITE remedies, which is what makes conflating them cost
    something. ``[config]`` says "export the variable", and an operator who has
    already exported it is told to do the thing they did. ``[ledger]`` says the
    configured path holds no readable checker, which is the real fix.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    decision, reason = judge(
        repo, f"{PUSH} origin main", ledger=str(tmp_path / "nowhere")
    )
    assert decision == "deny", (
        f"a configured ledger that cannot be consulted read as all clear: {reason!r}"
    )
    assert "[ledger]" in reason, (
        f"the unreachable-ledger deny does not carry the [ledger] sub-kind, so "
        f"it cannot be told from the unset-variable deny, whose remedy is the "
        f"opposite one: {reason!r}"
    )
    assert "[config]" not in reason, (
        f"the unreachable-ledger deny carries the [config] sub-kind, which "
        f"tells an operator who HAS exported the variable to export it: "
        f"{reason!r}"
    )


def test_an_unconfigured_ledger_denies_rather_than_failing_open(repo: Path) -> None:
    """An absent ledger DENIES. Kit 0.2.8, author decision LEDGER-ENVVAR.

    THIS TEST USED TO ASSERT THE OPPOSITE, and the inversion is the point.
    It read "without the environment variable the incident gate does not
    apply", on the reasoning that the shared ledger is one author's local
    artifact and a clone that never configured it must still be able to push.
    That reasoning is what failed: an unset variable read as permission, so
    the coordination repository, the level that WRITES the incidents, pushed
    past a blocking incident it had itself recorded, because the variable it
    derived had never existed. Measured there on 2026-07-29 with a blocking
    incident open: itaca blocked, pyflightstream blocked, the hub NOT.

    A guard that treats its own missing configuration as permission is not a
    guard. So absence is now a refusal, and a repository that genuinely has
    no ledger says so by pointing the variable at one.

    The remedy is one export, which is why the deny carries its own
    ``[config]`` sub-kind rather than the ledger-repair or run-the-analyst
    wording: a message that does not say "export this" turns a deployment
    step into a mystery.

    itaca ran kit 0.2.6 until 2026-07-30 and therefore carried the fail-open
    branch for a day after the fix existed (``ITC-20260730-0215``).
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    decision, reason = judge(repo, f"{PUSH} origin main", ledger=None)
    assert decision == "deny", (
        f"an unset {LEDGER_ENV} allowed a push, so the incident gate can fail "
        f"open: on a clone that configured nothing, a blocking incident is "
        f"never consulted and the push proceeds. Reason: {reason!r}"
    )
    assert "[config]" in reason, (
        f"the unset-ledger deny does not carry the [config] sub-kind, so it "
        f"reads as a ledger or review problem rather than as one missing "
        f"export: {reason!r}"
    )
    assert LEDGER_ENV in reason, (
        f"the deny does not name the variable to set, which is the whole "
        f"remedy: {reason!r}"
    )
    # And the attestation is not what is holding it: the same push with a
    # configured clean ledger goes through, so this case isolates the ledger.
    assert decide(repo, f"{PUSH} origin main") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "git status",
        'git commit -m "one"',
        "git fetch origin",
        'echo "explain the git push gate"',
        "python .claude/hooks/write_attestation.py review qa",
    ],
)
def test_an_unconfigured_ledger_denies_pushes_and_nothing_else(
    repo: Path, command: str
) -> None:
    """The positive control for the fail-closed branch: its SCOPE.

    Kit 0.2.8's own comment on ``LEDGER_ENV`` says a copy vendored before the
    variable is set "denies every command in that repository until it is". That
    overstates the code: ``main`` calls ``_allow_silently`` when the command is
    not a recognized push, so an unset variable refuses pushes and nothing
    else. The correction is routed to the kit; the GUARD belongs here, because
    the claim itaca depends on is the narrow one.

    Without this control the widened refusal has no bound. A kit revision that
    consulted the ledger before classifying the command would deny every shell
    command on any clone that had not exported the variable, and the whole
    module would stay green, because every other case here now runs with a
    CONFIGURED ledger by default. The ``[config]`` message would make it read
    as a first-time setup step rather than as a gate that had escaped its
    scope.

    Same shape as the positive control beside the widened force refusal: a
    refusal is only as good as the statement of what it does not refuse.
    """
    add_commit(repo, "one")
    assert decide(repo, command, ledger=None) == "allow", (
        f"an unset {LEDGER_ENV} denied {command!r}, which is not a push. The "
        f"fail-closed branch has escaped its scope: on a clone that has not "
        f"exported the variable, ordinary work would stop and the [config] "
        f"message would read as a setup step rather than as a defect."
    )


def test_a_trailing_command_does_not_defeat_the_gate(repo: Path) -> None:
    """``push; echo done`` reaches the remote, so it must be recognized.

    ``shlex(posix=False)`` leaves ``push;`` as a single token, and the
    v1 comparison against ``"push"`` missed it. That failed open on the
    most natural way to type a push followed by anything else.
    """
    add_commit(repo, "one")
    assert decide(repo, f"{PUSH} origin main; echo done") == "deny"


def test_a_quoted_mention_of_the_command_is_not_a_push(repo: Path) -> None:
    """A commit message naming the command must not trip the gate."""
    add_commit(repo, "one")
    assert decide(repo, f'git commit -m "explain the {PUSH} gate"') == "allow"


def test_a_named_branch_is_scoped_by_that_branch_not_by_head(repo: Path) -> None:
    """Pushing a ref that is not HEAD must be judged on that ref.

    Scoping from HEAD let a branch carrying unattested commits ship
    whenever HEAD happened to be attested, which is the same free ride
    for unreviewed work that the range check exists to stop.
    """
    head = add_commit(repo, "one")
    git(repo, "branch", "side")
    git(repo, "checkout", "-q", "side")
    add_commit(repo, "unreviewed")
    git(repo, "checkout", "-q", "main")
    attest(repo, [head])
    assert git(repo, "rev-parse", "HEAD") == head
    assert decide(repo, f"{PUSH} origin side") == "deny"
    assert decide(repo, f"{PUSH} origin side:main") == "deny"


def test_a_push_the_gate_cannot_scope_is_denied(repo: Path) -> None:
    """--all, --mirror and --tags send refs the gate cannot enumerate.

    Offline there is no way to tell which tags the remote already has, so
    the honest answer is to refuse and ask for the ref by name. Allowing
    would be a guard discharging its assertion by not making one:
    --follow-tags is the ordinary release command, and it published an
    unattested tag while the suite stayed green.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    attest(repo, [head], kind="release")
    for form in ("--all", "--mirror", "--tags", "--follow-tags"):
        decision, reason = judge(repo, f"{PUSH} {form} origin")
        assert decision == "deny", form
        assert "cannot determine" in reason, form
        # v0.2.2: the highest-traffic deny path carries the [scope] sub-kind.
        # Pin it, or a regression could drop or rename the most common
        # bracket while the suite stayed green.
        assert "role-review gate: [scope]" in reason, form


def test_a_deletion_refspec_is_denied(repo: Path) -> None:
    """A push that removes a remote ref is not something the gate can bless."""
    head = add_commit(repo, "one")
    attest(repo, [head])
    decision, reason = judge(repo, f"{PUSH} origin :main")
    assert decision == "deny"
    # v0.2.2: a deletion is a policy stop, not a scope failure. It is now
    # framed as [policy], so it must not claim the gate cannot scope it.
    assert "role-review gate: [policy]" in reason
    assert "refused on policy, not scope" in reason
    assert "cannot determine" not in reason


def test_an_open_blocking_incident_denies(repo: Path, tmp_path: Path) -> None:
    """The branch the incident gate exists for, driven by a real checker.

    Only the unreachable-ledger path was covered before, so the whole
    incident gate could be deleted with the suite green.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    ledger = stub_ledger(tmp_path / "ledger", 1, "INC-1 open and blocking for")
    decision, reason = judge(repo, f"{PUSH} origin main", ledger=ledger)
    assert decision == "deny"
    # v0.2.0 (S5b, FIX 6): every deny opens with one prefix and a
    # bracketed sub-kind, replacing the divergent "INCIDENT GATE:" voice.
    assert "role-review gate: [incident]" in reason
    assert "INC-1 open and blocking for" in reason
    # The two failure classes have opposite remedies and must not share
    # a message: this one is a real incident, not an unreadable ledger.
    assert "incident-analyst" in reason
    assert "could not be consulted" not in reason


def test_a_clean_ledger_allows(repo: Path, tmp_path: Path) -> None:
    """A checker that reports no blocking incident must not block."""
    head = add_commit(repo, "one")
    attest(repo, [head])
    ledger = stub_ledger(tmp_path / "ledger", 0, "clean for")
    assert decide(repo, f"{PUSH} origin main", ledger=ledger) == "allow"


def test_the_incident_query_uses_the_project_name(repo: Path, tmp_path: Path) -> None:
    """The queried identity must survive a clone into a renamed directory.

    Taking it from the folder name meant a clone named anything else
    queried an unknown repository, got a clean answer, and shipped.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "itaca"\n', encoding="utf-8"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pyproject")
    attest(repo, _pushed(repo))
    ledger = stub_ledger(tmp_path / "ledger", 1, "queried")
    decision, reason = judge(repo, f"{PUSH} origin main", ledger=ledger)
    assert decision == "deny"
    assert "queried itaca" in reason, reason


def test_the_deny_names_the_range_to_review(repo: Path) -> None:
    """The reason must carry the command that clears it, not just a complaint.

    A reader who follows the role-review skill default reviews the last
    commit, which is the wrong scope for this denial and re-arms the gate.
    """
    add_commit(repo, "one")
    tip = add_commit(repo, "two")
    decision, reason = judge(repo, f"{PUSH} origin main")
    assert decision == "deny"
    # v0.2.0 (S5b, FIX 6): the review deny now shares the one gate prefix
    # with a [review] sub-kind, replacing the old "ROLE-REVIEW GATE:" voice.
    assert "role-review gate: [review]" in reason
    assert "ROLE-REVIEW GATE" not in reason
    assert f"{tip} --not --remotes" in reason, reason


def test_the_fail_closed_reason_does_not_offer_to_disable_the_gate() -> None:
    """A confused gate must not hand over its own bypass as a remedy.

    The fail-closed message is read by an agent under time pressure. It
    once offered turning the hook off through /hooks as a co-equal
    option, next to actually fixing the problem.
    """
    text = HOOK.read_text(encoding="utf-8")
    assert "via /hooks" not in text
    assert "disable the hook" not in text


def test_settings_json_wires_the_hook() -> None:
    """A hook nobody invokes is not a guard.

    Every other test here runs the script by path, so the suite passed
    identically with the registration deleted, the matcher narrowed, or
    the path drifted.
    """
    settings = json.loads(
        (HOOK.parents[1] / "settings.json").read_text(encoding="utf-8")
    )
    entries = settings["hooks"]["PreToolUse"]
    wired = [
        hook
        for entry in entries
        for hook in entry.get("hooks", [])
        if "role_review_gate.py" in hook.get("command", "")
    ]
    assert wired, "no PreToolUse hook invokes role_review_gate.py"
    matchers = [
        entry["matcher"]
        for entry in entries
        if any("role_review_gate.py" in h.get("command", "") for h in entry["hooks"])
    ]
    assert any("Bash" in m and "PowerShell" in m for m in matchers), matchers


def _pushed(repo: Path) -> list[str]:
    """The commits a push from ``repo`` would make new."""
    listed = git(repo, "rev-list", "HEAD", "--not", "--remotes")
    return [c for c in listed.splitlines() if c]


@pytest.mark.parametrize(
    "form",
    ["--follow-tag", "--tag", "--mirro", "--al", "--delet", "--prune"],
)
def test_an_abbreviated_blanket_option_is_still_refused(repo: Path, form: str) -> None:
    """Git accepts any unambiguous prefix of a long option.

    A refusal keyed on exact spellings moved the hole rather than
    closing it: `--follow-tag` runs, and it published an unattested tag
    four keystrokes short of the spelling the gate knew.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    attest(repo, [head], kind="release")
    decision, reason = judge(repo, f"{PUSH} {form} origin main")
    assert decision == "deny", form
    assert "cannot determine" in reason, form


@pytest.mark.parametrize(
    "option",
    ["-u", "--force-with-lease", "-q", "--atomic", "--dry-run", "-o ci.skip"],
)
def test_an_ordinary_option_does_not_block_an_attested_push(
    repo: Path, option: str
) -> None:
    """The positive control the refusal needs.

    Widening the refusal is the natural fix for the abbreviation hole,
    and without this the suite cannot tell a correct widening from a
    gate that blocks every real push.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    assert decide(repo, f"{PUSH} {option} origin main") == "allow", option


@pytest.mark.parametrize(
    "spec",
    ["v9.9.9:v9.9.9", "refs/tags/v9.9.9:refs/tags/v9.9.9", "HEAD:refs/tags/v9.9.9"],
)
def test_a_tag_written_as_a_refspec_is_still_release_grade(
    repo: Path, spec: str
) -> None:
    """The form a blocked operator reaches for next.

    Release classification matched the whole token, so a colon refspec
    scoped correctly, passed the review gate, and skipped the release
    attestation for a syntax git treats as equivalent.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    git(repo, "tag", "v9.9.9")
    assert decide(repo, f"{PUSH} origin {spec}") == "deny", spec
    attest(repo, [head], kind="release")
    assert decide(repo, f"{PUSH} origin {spec}") == "allow", spec


def test_a_configured_push_refspec_makes_a_bare_push_unscopable(repo: Path) -> None:
    """`git push origin` does not always mean the current branch.

    Under push.default=matching, or with remote.<name>.push configured,
    a bare push sends every matching branch while the gate scoped HEAD
    alone, so unattested commits on any other branch shipped.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    assert decide(repo, f"{PUSH} origin") == "allow"
    git(repo, "config", "push.default", "matching")
    decision, reason = judge(repo, f"{PUSH} origin")
    assert decision == "deny"
    assert "cannot determine" in reason
    git(repo, "config", "push.default", "simple")
    git(repo, "config", "remote.origin.push", "refs/heads/*:refs/heads/*")
    assert decide(repo, f"{PUSH} origin") == "deny"


def test_a_multi_ref_push_scopes_every_ref(repo: Path) -> None:
    """The release-day form: branch and tag in one command."""
    head = add_commit(repo, "one")
    git(repo, "branch", "side")
    git(repo, "checkout", "-q", "side")
    unattested = add_commit(repo, "unreviewed")
    git(repo, "checkout", "-q", "main")
    attest(repo, [head])
    decision, reason = judge(repo, f"{PUSH} origin main side")
    assert decision == "deny"
    assert unattested[:12] in reason


def test_a_deletion_deny_does_not_prescribe_pushing_the_ref(repo: Path) -> None:
    """A fix that cannot reach the goal is not a fix.

    Telling a user who wants to remove a remote ref to push one by name
    is unactionable, and every unscopable case shared that one sentence.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    _, reason = judge(repo, f"{PUSH} origin :main")
    assert "author decision" in reason
    assert "Push the branch or tag by name" not in reason


def test_the_deny_range_command_is_one_git_can_run(repo: Path) -> None:
    """A synthesized `<oldest>^..<tip>` dies on a root commit.

    The reason must print the expression the gate itself computed, not
    a range reconstructed from list positions.
    """
    add_commit(repo, "one")
    _, reason = judge(repo, f"{PUSH} origin main")
    assert "--not --remotes" in reason
    assert "^.." not in reason


def test_an_unreadable_incident_file_gets_the_repair_remedy(
    repo: Path, tmp_path: Path
) -> None:
    """The two incident classes must stay separable from checker output."""
    head = add_commit(repo, "one")
    attest(repo, [head])
    ledger = stub_ledger(tmp_path / "ledger", 1, "UNREADABLE header in INC-2 for")
    decision, reason = judge(repo, f"{PUSH} origin main", ledger=ledger)
    assert decision == "deny"
    assert "could not be consulted" in reason
    assert "incident-analyst" not in reason
    # v0.2.2: an unreadable ledger and a real open incident have opposite
    # remedies, so the unreachable case gets its own [ledger] sub-kind
    # rather than sharing [incident].
    assert "role-review gate: [ledger]" in reason
    assert "role-review gate: [incident]" not in reason


def test_the_identity_ignores_other_tables_and_inline_comments(
    repo: Path, tmp_path: Path
) -> None:
    """A prefix match on a raw line is not a TOML parser."""
    head = add_commit(repo, "one")
    (repo / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "wrong"\n\n[project]\nname = "itaca"  # published\n',
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pyproject")
    attest(repo, [*_pushed(repo), head])
    ledger = stub_ledger(tmp_path / "ledger", 1, "queried")
    _, reason = judge(repo, f"{PUSH} origin main", ledger=ledger)
    assert "queried itaca\n" in reason or "queried itaca " in reason, reason


def test_a_bare_push_resolves_the_remote_it_would_actually_use(repo: Path) -> None:
    """`git push` with no remote does not always mean origin.

    Git resolves branch.<current>.pushRemote, then remote.pushDefault,
    then branch.<current>.remote, then origin. Reading the config for
    `origin` alone closed the push.default half of this hole and left
    the remote-selection half open.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    git(repo, "remote", "add", "upstream", str(repo.parent / "remote.git"))
    git(repo, "config", "branch.main.remote", "upstream")
    git(repo, "config", "remote.upstream.push", "refs/heads/*:refs/heads/*")
    decision, reason = judge(repo, PUSH)
    assert decision == "deny"
    assert "cannot determine" in reason


def test_the_review_deny_tells_a_non_head_push_to_pass_the_ref(repo: Path) -> None:
    """The review check runs first, so it is where the loop happens.

    The release deny carries the "pass the ref" instruction, but a
    review denial on a ref behind HEAD is reached first, and the skill's
    documented invocation stamps HEAD again: push, deny, re-attest,
    deny.
    """
    add_commit(repo, "one")
    _, reason = judge(repo, f"{PUSH} origin main")
    assert "write_attestation.py review" in reason
    assert "stamps HEAD by default" in reason


def test_the_deny_range_covers_every_ref_it_refused(repo: Path) -> None:
    """Naming targets[0] understated the scope on a multi-ref push."""
    head = add_commit(repo, "one")
    git(repo, "branch", "side")
    git(repo, "checkout", "-q", "side")
    add_commit(repo, "unreviewed")
    git(repo, "checkout", "-q", "main")
    attest(repo, [head])
    _, reason = judge(repo, f"{PUSH} origin main side")
    side = git(repo, "rev-parse", "side")
    assert side in reason


def test_the_review_deny_names_the_ref_that_is_behind_head(repo: Path) -> None:
    """The loop only happens when the pushed ref is not HEAD.

    The earlier test pushed `main` while main was HEAD, so the deny
    could name HEAD unconditionally and still pass: the scenario in its
    own name was never exercised.
    """
    behind = add_commit(repo, "one")
    git(repo, "tag", "v0.1.0")
    add_commit(repo, "two")
    assert git(repo, "rev-parse", "v0.1.0") == behind
    assert git(repo, "rev-parse", "HEAD") != behind
    _, reason = judge(repo, f"{PUSH} origin v0.1.0")
    assert "write_attestation.py review" in reason
    # Naming HEAD here is the loop: the writer would stamp HEAD, which
    # does not cover the tag, and the same denial repeats.
    assert "<passes,that,ran> v0.1.0" in reason, reason


@pytest.mark.fast  # 0.06 s, and it guards the helper every spawn site uses
def test_a_child_process_does_not_start_coverage() -> None:
    """A child that measures without branch data aborts the whole run.

    This is the defect that turned CI red on every test leg of commit
    48009bc: the failure is in teardown, after all tests pass, so
    nothing in the suite pointed at it.

    The assertion is behavioral rather than a list of variable names.
    A name list has to track whatever the installed pytest-cov and
    coverage read, and a first version of this guard asserted a wider
    set than the helper stripped, so adding --cov-branch would have
    turned it red while the contract still held. Asking the child
    whether coverage started cannot drift.
    """
    done = subprocess.run(
        [sys.executable, "-c", "import sys; print('coverage' in sys.modules)"],
        capture_output=True,
        text=True,
        env=child_env(),
        check=True,
    )
    assert done.stdout.strip() == "False", done.stdout


# `test_no_spawn_site_bypasses_child_env` STOOD HERE and is RETIRED at kit
# 0.2.16, in favour of `tests/test_spawn_env.py`. It is named rather than
# deleted silently, because a guard that disappears from a file reads as a
# guard that was never needed.
#
# It decided whether a spawn site passed an explicit environment by reading
# a fixed window of fourteen lines after each `subprocess.run(`, and
# `ITC-20260802-0200` is written about exactly that. Lane ITA-11 round two
# met BOTH of the shape's failure directions in one commit: a neighbour's
# `env=` sixteen lines away excused two real offenders, and a correct call
# whose argv was written one element per line was reported as an offender
# seventeen lines from its own opening. The vendored checker judges the
# CALL, parsed with `ast`, so neither direction is reachable.
#
# Two guards claiming the same coverage teach a reader to trust neither, so
# it is retired rather than kept beside the checker. Its two accounting
# floors were NOT dropped: they moved onto the checker's own checked-count
# line, which is what tells a clean tree apart from a walk that opened
# nothing. `test_a_child_process_does_not_start_coverage` above is the
# BEHAVIORAL half and stays here; neither guard replaces it.


def test_no_partial_coverage_file_survives_a_hook_run(repo: Path) -> None:
    """The observable symptom, pinned where a future change would show.

    The child writes to the parent's absolute data file path, which is
    the repository root on every platform, so this guard is valid here
    and not only on the platform that went red.
    """
    root = Path(__file__).resolve().parents[1]
    before = set(root.glob(".coverage.*"))
    add_commit(repo, "one")
    decide(repo, f"{PUSH} origin main")
    assert not set(root.glob(".coverage.*")) - before


@pytest.mark.parametrize("option", ["--force", "-f"])
def test_a_bare_force_push_is_denied_even_when_fully_attested(
    repo: Path, option: str
) -> None:
    """Unconditional force rewrites published history: an author-only call.

    An attestation certifies that a range was reviewed; it cannot license
    discarding commits already on the remote. So even a push whose range
    is fully attested is denied when it carries a bare ``--force`` / ``-f``.
    Previously these were safe options and such a push was allowed, which
    is the behavior this case flips.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    decision, reason = judge(repo, f"{PUSH} {option} origin main")
    assert decision == "deny", option
    assert "force" in reason.lower(), option
    assert "author decision" in reason, option
    # The deny must be actionable: name the safe alternative, or the
    # operator is left with a refusal and no path forward.
    assert "--force-with-lease" in reason, option
    # v0.2.2: a force is a policy stop whose scope IS resolvable, so it is
    # framed as [policy] and must NOT claim the gate cannot determine scope.
    assert "role-review gate: [policy]" in reason, option
    assert "refused on policy, not scope" in reason, option
    assert "cannot determine" not in reason, option


def test_a_force_with_lease_push_still_rides_the_attestation(repo: Path) -> None:
    """The safe force variant refuses on its own if the remote moved.

    It must stay on the normal attestation path, or the author-only deny
    for bare force would have swept up the safe form too. This is the
    positive control that a widened force refusal did not overreach.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    assert decide(repo, f"{PUSH} --force-with-lease origin main") == "allow"


def test_a_shell_wrapped_unattested_push_is_denied(repo: Path) -> None:
    """``bash -c "git push"`` reaches the remote, so the gate must see it.

    The wrapper hid the push from the v1 gate, which recognized only a
    bare git executable and failed open on every shell-wrapped form. An
    unattested push wrapped in ``bash -c`` must deny exactly as the bare
    form does.
    """
    add_commit(repo, "one")  # unattested
    decision, reason = judge(repo, f'bash -c "{PUSH} origin main"')
    assert decision == "deny"
    # Deny for the right reason: a wrapped push that reached the review
    # check, not a scope refusal that happened to also deny.
    assert "role-review gate: [review]" in reason


def test_the_passing_gate_announces_itself_on_stderr(repo: Path) -> None:
    """A passing gate must not look exactly like an absent one in the logs.

    The final all-checks-passed allow stays a silent permission outcome
    (no stdout, so the normal permission flow is not auto-approved) but
    prints one line to stderr naming the repo and the in-scope commit
    count. Without this a disabled or misfiring gate would be
    indistinguishable from a gate that ran and allowed.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    decision, _ = judge(repo, f"{PUSH} origin main")
    assert decision == "allow"
    assert "role-review gate: evaluated and ALLOWED" in stderr_of(
        repo, f"{PUSH} origin main"
    )


def test_a_shell_wrapped_attested_push_is_allowed_because_it_was_seen(
    repo: Path,
) -> None:
    """The wrapper detection must allow a wrapped push that IS attested.

    A plain ``decision == allow`` cannot tell "allowed because recognized
    and attested" from "allowed because the wrapper hid it and the gate
    never ran", so this asserts the passing-gate stderr line, which only
    the recognized-and-evaluated path emits.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    wrapped = f'bash -c "{PUSH} origin main"'
    assert decide(repo, wrapped) == "allow"
    assert "role-review gate: evaluated and ALLOWED" in stderr_of(repo, wrapped)


def test_a_multi_tag_release_deny_names_every_tag(repo: Path) -> None:
    """A release deny that named only the first tag left the second uncovered.

    Pushing two version tags in one command must deny (no release
    attestation) with the [release] sub-kind, name BOTH tags in the
    reason, and prescribe a writer command that lists both, so one pass
    covers the whole push instead of looping tag by tag.
    """
    head = add_commit(repo, "one")
    attest(repo, [head])
    git(repo, "tag", "v9.9.8")
    git(repo, "tag", "v9.9.9")
    decision, reason = judge(repo, f"{PUSH} origin v9.9.8 v9.9.9")
    assert decision == "deny"
    assert "role-review gate: [release]" in reason
    assert "RELEASE GATE" not in reason
    assert "v9.9.8" in reason and "v9.9.9" in reason
    # The prescribed writer command must carry both tags, not just one.
    writer = reason[reason.index("write_attestation.py release") :]
    assert "v9.9.8" in writer and "v9.9.9" in writer


def test_a_push_with_no_resolvable_repo_denies_with_the_repo_kind(
    tmp_path: Path,
) -> None:
    """A push where no git repository resolves denies with the [repo] sub-kind.

    v0.2.2 gave the "no repo resolves" deny its own bracket. The fixture
    everywhere else builds a valid repo, so this path (and its bracket) had
    no test; a re-fork could drop or mislabel it while the suite stayed
    green. tmp_path sits under the OS temp dir, not inside any checkout, so
    git resolves no repository here.

    The [gate] top-level fail-closed catch-all is a documented residual: it
    fires only on an unexpected internal exception, which cannot be
    triggered honestly through the subprocess boundary these tests use.
    """
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    decision, reason = judge(non_repo, f"{PUSH} origin main")
    assert decision == "deny"
    assert "role-review gate: [repo]" in reason


def test_a_shell_wrapped_attested_push_is_allowed(repo: Path) -> None:
    """The wrapper detection must not block a wrapped push that is attested."""
    head = add_commit(repo, "one")
    attest(repo, [head])
    assert decide(repo, f'bash -c "{PUSH} origin main"') == "allow"
