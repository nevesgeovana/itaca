"""Tier-1 wiring of the execution guard (shared kit artifact, 0.2.22).

Usage example (TDD anchor)::

    decision, _ = judge("pytest -q | tail -5")
    assert decision == "deny"  # the status you read back is tail's

The guard refuses two shell shapes with a measured history in these
repositories, and refuses nothing else:

- ARM 1, a status-bearing command piped into a line filter. A pipeline's
  exit status is the LAST element's, so `pytest | tail` reports whether
  `tail` succeeded. `STATUS_BEARING` is deliberately short, because the arm
  is about STATUS and not about danger. Since 0.2.22 the filter pattern is
  SPLIT by shell: `head`, `tail` and `wc` case-sensitively for bash, and
  `Select-Object`, `Measure-Object`, `select` and `measure`
  case-insensitively for PowerShell, because each shell's case rules are
  what that shell actually does. `Out-String` and `ForEach-Object` are a
  NAMED gap and have their own case below.
- ARM 2, a heredoc whose body carries a backslash or a control byte. NOT a
  heredoc ban: twelve tracked files across the three trees carry heredocs,
  and the kit fixed a heredoc defect at 0.2.1 by correcting rather than
  forbidding. A quoted delimiter is exempt from the backslash half, since
  that is the form that survives.

WHAT IS PINNED HERE, and it is the same three-part shape
`tests/test_side_effect_guard.py` uses for the S3 guard:

- the guard is PRESENT, so a rename fails loudly rather than removing the
  check silently;
- it is WIRED in the tracked `.claude/settings.json`, on the same matcher
  as the push gate, because a vendored hook nothing invokes is the shape
  this repository already names for `ITACA-006`; and
- it BEHAVES, on both arms and on controls, so the wiring is not the only
  thing asserted.

The mutation companion is a separate `guardproof` test, per the BRF-076
tier policy: proving the guard is well built is a different question from
whether behavior is correct, and it only changes when the guard changes.

Every case drives the guard as the harness does, with the PreToolUse
payload on stdin, and reads the permission decision from stdout. Silence
means out of scope, which is how the guard says "allow".
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

# Process-level: every case spawns the guard.
pytestmark = pytest.mark.slow

_ROOT = Path(__file__).resolve().parents[1]
GUARD = _ROOT / ".claude" / "hooks" / "execution_guard.py"
MUTATIONS = _ROOT / ".claude" / "hooks" / "execution_guard_mutations.py"
SETTINGS = _ROOT / ".claude" / "settings.json"

# Built by concatenation so this file does not contain the ARM 2 shapes as
# literal text: a heredoc opener followed by a backslash is what the wired
# guard refuses, and a session command carrying this file's contents would
# be denied. The push-gate module does the same for its own reason.
#
# THIS COVERS ARM 2 ONLY, corrected in ITA-17 round one where the claim
# read "never contains the shapes it tests". The arm 1 pipelines ARE
# literals below (`pytest -q | tail -5` and its siblings), and they are
# safe to write because the guard scans a COMMAND, not a file: this module
# is never a command. The narrower statement is the true one.
_HEREDOC = "<" + "<"
_BACKSLASH = chr(92)


def judge(command: str) -> tuple[str, str]:
    """Run the guard on ``command`` and return (decision, reason)."""
    done = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        env=child_env(),
    )
    if not done.stdout.strip():
        return "silent", ""
    out = json.loads(done.stdout)["hookSpecificOutput"]
    return str(out["permissionDecision"]), str(out.get("permissionDecisionReason", ""))


def test_the_guard_and_its_companion_are_present() -> None:
    """A hook loaded by path fails loudly if it is missing.

    Without this a rename removes the whole check and every behavior case
    below would report `silent`, which is indistinguishable from the guard
    correctly allowing. That is the self-skipping evidence the kit exists
    to replace.
    """
    assert GUARD.is_file(), f"the execution guard is missing at {GUARD}"
    assert MUTATIONS.is_file(), f"its mutation companion is missing at {MUTATIONS}"


def test_settings_json_wires_the_execution_guard() -> None:
    """The guard must be REGISTERED, not merely vendored.

    Every other case here runs the script by path, so the suite would pass
    identically with the registration deleted. It must also carry the same
    matcher as the push gate: at 0.2.22 arm 1 refuses BOTH shells' filters,
    so a guard wired for one of them would leave the other's shape free,
    which is the defect `ITC-20260811-2250` closed.

    WIRED, UNWIRED AND REWIRED IN ONE LANE, recorded here because the
    history is the argument. ITA-17 wired kit 0.2.20, its own reviewer panel
    found two defects in that body, the coordination level accepted both and
    the lane UNWIRED rather than leave a false positive with no operator
    remedy armed overnight. Kit 0.2.22 fixed both and this assertion came
    back. The intermediate state was a real decision, not a slip, and DD-57
    carries it.
    """
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    # The path is matched in full, not by the bare basename. A substring
    # match passed on any command merely CONTAINING the name, so a wrong
    # directory would have satisfied it; a QA lens found that in ITA-17
    # round one.
    expected = ".claude/hooks/execution_guard.py"
    wired = [
        (entry, hook)
        for entry in entries
        for hook in entry.get("hooks", [])
        if expected in hook.get("command", "").replace("\\", "/")
    ]
    assert wired, (
        f"no PreToolUse hook in {SETTINGS} invokes {expected}, so the vendored "
        f"body runs never. Wire it, or stop vendoring it."
    )
    for entry, hook in wired:
        matcher = entry["matcher"]
        assert "Bash" in matcher and "PowerShell" in matcher, (
            f"the execution guard is wired on matcher {matcher!r}. Since kit "
            f"0.2.22 arm 1 refuses both shells' line filters, so wiring one "
            f"shell leaves the other's shape free."
        )
        assert hook.get("timeout"), (
            "the execution guard entry declares no timeout, so it runs under "
            "the harness default this repository does not control."
        )


@pytest.mark.parametrize(
    "command,kind",
    [
        ("pytest -q | tail -5", "piped-status"),
        ("mypy | head -20", "piped-status"),
        ("ruff check . | wc -l", "piped-status"),
        ("python check_incidents.py itaca | head -3", "piped-status"),
        ("python x_mutations.py | wc -l", "piped-status"),
    ],
)
def test_a_status_bearing_command_piped_into_a_filter_is_refused(
    command: str, kind: str
) -> None:
    """ARM 1, on each shape of the STATUS_BEARING list.

    The pattern half matters as much as the literal half: `check_*.py` and
    `*_mutations.py` are matched on the basename, so a path prefix does not
    defeat them. This repository runs both constantly, and reading either
    through a filter is how a red checker reports green.
    """
    decision, reason = judge(command)
    assert decision == "deny", f"{command!r} was not refused: {reason}"
    assert kind in reason, reason
    # The remedy must be in the message, or the operator just removes the
    # pipe and loses the output they wanted.
    assert "unpiped" in reason or "file" in reason, reason


def test_a_corrupting_heredoc_is_refused() -> None:
    """ARM 2, the backslash half, on the unquoted form the shell rewrites."""
    command = f"cat {_HEREDOC}EOF > f.txt\nC:{_BACKSLASH}WORK{_BACKSLASH}path\nEOF"
    decision, reason = judge(command)
    assert decision == "deny", f"the heredoc was not refused: {reason}"
    assert "heredoc-content" in reason, reason
    # WHICH HALF fired, not merely that arm 2 did. Both halves emit
    # `heredoc-content`, so asserting the sub-kind alone cannot tell the
    # backslash rule from the control-byte rule, and this case would pass if
    # the two were swapped.
    assert "backslash" in reason, reason
    assert "Write or Edit" in reason, reason


def test_a_heredoc_carrying_a_control_byte_is_refused() -> None:
    """ARM 2, the control-byte half, which QUOTING DOES NOT EXEMPT.

    A quoted delimiter disables shell expansion, so it exempts the
    backslash half. It protects no parser from a stray control byte, which
    is why this case uses the quoted form deliberately: it is the one that
    proves the two halves are not the same rule.
    """
    command = f"cat {_HEREDOC}'EOF' > f.txt\nbad\x01byte\nEOF"
    decision, reason = judge(command)
    assert decision == "deny", f"the control byte was not refused: {reason}"
    assert "heredoc-content" in reason, reason
    assert "non-printable" in reason, reason


@pytest.mark.parametrize(
    "command",
    [
        # The same checkers, unpiped: the remedy the guard prescribes.
        "pytest -q",
        "pytest -q > out.txt",
        # A pipeline whose head is NOT status-bearing.
        "git log --oneline | head -5",
        # A quoted heredoc with an ordinary body.
        f"cat {_HEREDOC}'EOF' > f.txt\nplain text\nEOF",
        # THE DOCUMENTED FALSE-POSITIVE CLASS, in the form that quoting
        # fixes: a checker named as DATA inside a quoted span is blanked
        # before arm 1 scans, so it is out of scope. These live here, in the
        # blocking tier, and not only in the mutation companion: a re-vendor
        # that re-broadened the guard would otherwise pass the only local
        # gate that blocks, since `guardproof` is deselected at pre-push.
        'grep -n "check_incidents.py" notes.txt | head -3',
        'git commit -m "wire check_spawn_env.py" ',
        # A filter UPSTREAM of the checker, which loses no status.
        "cat notes.txt | head -3 && pytest -q",
        # A backslash inside a QUOTED heredoc body: exempt by design,
        # because the quoted form is the one the shell does not rewrite.
        f"cat {_HEREDOC}'EOF' > f.txt\nC:{_BACKSLASH}WORK{_BACKSLASH}path\nEOF",
    ],
)
def test_an_ordinary_command_is_out_of_scope(command: str) -> None:
    """The controls, and they carry as much weight as the refusals.

    A guard that denied all of these would be one every session learns to
    work around, which is the reason the kit narrowed this from the blanket
    ban the source report recommended. `pytest -q > out.txt` and the
    unpiped form are exactly what the refusal messages tell an operator to
    do, so if either were refused the guard would prescribe a denied
    command.

    The last four were promoted into this tier by ITA-17 round one, on a QA
    finding: the guard's already-measured exemptions were proven only by
    the mutation companion, which `guardproof` routes to CI, so the local
    blocking gate asserted none of them.
    """
    decision, reason = judge(command)
    assert decision == "silent", f"{command!r} was refused: {reason}"


@pytest.mark.parametrize(
    "command,label",
    [
        ("pytest -q | Select-Object -Last 5", "Select-Object"),
        ("pytest -q | select -Last 5", "the select alias"),
        ("pytest -q | Measure-Object -Line", "Measure-Object"),
        ("pytest -q | measure", "the measure alias"),
        # Case-INSENSITIVE on the PowerShell half, because PowerShell is.
        ("pytest -q | SELECT-OBJECT -Last 5", "an upper-case spelling"),
    ],
)
def test_a_powershell_line_filter_is_refused_since_0222(
    command: str, label: str
) -> None:
    """The gap this repository routed, now closed, asserted as closed.

    THIS CASE HAS BEEN THREE THINGS IN ONE LANE and the sequence is the
    point. It began as an out-of-scope CONTROL, asserting that a PowerShell
    filter is fine, one screen below a wiring test justifying the
    `Bash|PowerShell` matcher on the ground that the refused shape must not
    be able to move shells. Two reviewer lenses found that contradiction. It
    became `test_a_powershell_line_filter_is_a_known_gap_not_an_exemption`,
    written to the CURRENT behavior so it would go RED when the kit closed
    the gap. Kit 0.2.22 closed it, the test went red exactly as designed,
    and it is now the assertion that the gap is shut.

    A guard that could only be tested when it was broken would not have
    survived that transition, which is why the middle form was written to
    flip rather than to pass forever.
    """
    decision, reason = judge(command)
    assert decision == "deny", f"{label} was not refused: {command!r}"
    assert "piped-status" in reason, reason


@pytest.mark.parametrize(
    "command,label",
    [
        ("pytest -q | Out-String", "Out-String"),
        ("pytest -q | ForEach-Object { $_ }", "ForEach-Object"),
    ],
)
def test_out_string_is_a_named_gap_with_its_reasoning(command: str, label: str) -> None:
    """Still allowed, and the reason is written rather than left implicit.

    `Out-String` and `ForEach-Object` drop no lines, and `$LASTEXITCODE`
    survives a PowerShell pipeline, so the status a caller needs is still
    recoverable. That is not true of `$?` in bash, which is why the bash
    half of the pattern is wider. The kit wrote that reasoning at the line
    rather than leaving it to be discovered.

    IF THAT REASONING IS WRONG, this test is the place the disagreement
    surfaces, and the line to change is the kit's. It is asserted rather
    than omitted so the gap is a decision on the record instead of an
    absence nobody can see.
    """
    decision, _ = judge(command)
    assert decision == "silent", (
        f"{label} is now refused. If the kit widened the PowerShell half "
        f"deliberately, that is correct and this test should become a "
        f"refusal case; if not, it is a false positive on a cmdlet that "
        f"loses no status."
    )


def test_the_bash_half_stays_case_sensitive() -> None:
    """Each shell's case rules are what that shell actually does.

    0.2.22 split the pattern rather than making one case-insensitive rule,
    and this is the half that would be wrong if it had not: `TAIL` is not
    `tail` to bash, so refusing it would be a false positive.
    """
    decision, _ = judge("pytest -q | TAIL -5")
    assert decision == "silent", (
        "the bash half of the filter pattern has become case-insensitive, "
        "which refuses a command bash would not even resolve."
    )


def test_a_quoted_heredoc_body_may_name_an_opener_without_being_refused() -> None:
    """The fourth false positive, reproduced here and fixed in kit 0.2.22.

    THE STRICT XFAIL DID ITS JOB AND IS GONE. This case was pinned as
    `xfail(strict=True)` while `ITC-20260811-2240` was open, precisely so
    that the day the kit fixed it the test would fail as XPASS and force the
    marker off rather than leaving a closed defect recorded as open. That is
    what happened, in the same night.

    The defect: arm 2 did not blank data spans, so a heredoc opener merely
    NAMED inside a quoted heredoc body was parsed as a real opener. Arm 1
    blanked them; arm 2 did not. It denied a QA reviewer's own findings
    write while that reviewer was writing up this very finding.

    0.2.22 extracts a data mask and tests the OPENER's position against it
    while still reading the body from the raw command, which is the right
    shape: a real heredoc's body is exactly what this arm exists to inspect,
    so masking the body would have broken the arm to fix the false positive.

    THIS REPRODUCTION'S BACKSLASH WAS LOAD-BEARING, and the kit said so: its
    first draft of the fix carried a case with nothing after the named
    opener that either arm objects to, so the command was silent BEFORE and
    AFTER the fix, a vacuous proof. The mutant refused to flip, which caught
    it. The control below is what makes this case specific.
    """
    command = (
        f"cat {_HEREDOC}'MD' > notes.md\n"
        f"The guard refuses {_HEREDOC}EOF bodies carrying "
        f"C:{_BACKSLASH}WORK paths.\n"
        "MD"
    )
    decision, reason = judge(command)
    assert decision == "silent", f"refused prose that names an opener: {reason}"


def test_the_control_that_isolates_the_arm_two_false_positive() -> None:
    """The same quoted heredoc without the opener form is out of scope.

    Without this, the xfail above proves only that SOMETHING in that
    command is refused. With it, the difference between the two is exactly
    the spelled-out opener, which is what makes the routed finding specific
    enough for the kit to act on.
    """
    command = (
        f"cat {_HEREDOC}'MD' > notes.md\n"
        f"The guard refuses heredoc bodies carrying "
        f"C:{_BACKSLASH}WORK paths.\n"
        "MD"
    )
    decision, reason = judge(command)
    assert decision == "silent", f"the control was refused too: {reason}"


@pytest.mark.guardproof
def test_the_execution_guard_can_still_fail() -> None:
    """The mutation companion proves each arm is load-bearing.

    Marked `guardproof` per BRF-076: its subject is the guard's own
    machinery, so it runs in CI rather than at pre-push.
    """
    done = subprocess.run(
        [sys.executable, str(MUTATIONS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    # 41 cases and 10 mutants at 0.2.22, up from 30 and 7 at 0.2.20. The
    # count is asserted rather than merely the exit code, for the reason
    # this repository asserts every accounting line: a companion that
    # silently stopped building half its cases would still exit 0.
    assert "41/41 passed" in done.stdout, done.stdout
