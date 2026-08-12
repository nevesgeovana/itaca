"""Tier-1 wiring of the execution guard (shared kit artifact, 0.2.20).

Usage example (TDD anchor)::

    decision, _ = judge("pytest -q | tail -5")
    assert decision == "deny"  # the status you read back is tail's

The guard refuses two shell shapes with a measured history in these
repositories, and refuses nothing else:

- ARM 1, a status-bearing command piped into a line filter. A pipeline's
  exit status is the LAST element's, so `pytest | tail` reports whether
  `tail` succeeded. `STATUS_BEARING` is deliberately short, because the arm
  is about STATUS and not about danger.
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


def test_the_execution_guard_is_deliberately_not_wired_yet() -> None:
    """VENDORED AND HELD, on the coordination level's instruction.

    ITA-17 vendored kit 0.2.20's guard AND wired it. The coordination level
    then answered two defects this lane had routed, accepted both as the
    kit's, and cut 0.2.22 to fix them. Its instruction for tonight: hold the
    guard, keep the body vendored and drift-pinned, do not hand-edit it, and
    re-pin at 0.2.22.

    THE TRADE, recorded because a disabled guard is the shape that quietly
    stays disabled. Arm 2 refuses a heredoc opener merely NAMED inside a
    quoted heredoc body (`ITC-20260811-2240`), and the operator has NO
    remedy: the token is already inside the strongest quoting the shell
    offers, and arm 2 blanks no data spans. A guard with no remedy teaches
    people to route around guards. Against that, one night of arm 1 coverage
    on a shell where arm 1 catches nothing anyway
    (`ITC-20260811-2250`, `LINE_FILTERS` is bash-only while this
    repository's primary shell is PowerShell).

    THIS TEST IS THE OPPOSITE OF THE ONE IT REPLACES, deliberately. It goes
    RED the moment anyone wires the guard, which is the signal to re-read
    this docstring and the channel entry behind it rather than to discover
    the held decision by being denied. When 0.2.22 is adopted, this test is
    replaced by the wiring assertion again, in the same commit that moves
    the two pins.

    The behavior cases in this module are unaffected and still run: they
    drive the vendored body directly, so they prove what the body does
    whether or not the harness invokes it.
    """
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    # The path is matched in full, not by the bare basename. A substring
    # match passed on any command merely CONTAINING the name, so a wrong
    # directory would have satisfied it; a QA lens found that in ITA-17
    # round one, while this test still asserted the wiring.
    expected = ".claude/hooks/execution_guard.py"
    wired = [
        hook
        for entry in entries
        for hook in entry.get("hooks", [])
        if expected in hook.get("command", "").replace("\\", "/")
    ]
    assert not wired, (
        f"{SETTINGS} now wires execution_guard.py, which ITA-17 deliberately "
        f"held pending kit 0.2.22. If 0.2.22 is adopted, that is correct and "
        f"this test is what must change: replace it with the wiring assertion "
        f"(present, matcher covering Bash and PowerShell, explicit timeout) in "
        f"the same commit that re-pins execution_guard.py and its companion. "
        f"If 0.2.22 is NOT adopted, unwire it: arm 2 refuses a heredoc opener "
        f"named inside a quoted body with no remedy available to the operator "
        f"(ITC-20260811-2240)."
    )
    # And the body must still be VENDORED while it is held, or the hold has
    # quietly become a removal and the re-pin at 0.2.22 has nothing to move.
    assert GUARD.is_file() and MUTATIONS.is_file(), (
        f"the guard is unwired AND its body is gone. Holding it means keeping "
        f"it vendored and drift-pinned so 0.2.22 is a re-pin rather than a "
        f"fresh adoption; see {GUARD} and {MUTATIONS}."
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


def test_a_powershell_line_filter_is_a_known_gap_not_an_exemption() -> None:
    """PowerShell loses a status the same way and the guard does not see it.

    THIS IS A GAP AND NOT A DESIGN INTENT, which is the whole point of the
    name. The first version of this case sat in the out-of-scope list
    above, where it read as a decision that PowerShell filters are fine.
    Two reviewer lenses found the contradiction in ITA-17 round one: the
    wiring test justifies the `Bash|PowerShell` matcher on the ground that
    otherwise "the shape it refuses simply moves to the other" shell, and
    on this repository's primary shell it already has.

    `LINE_FILTERS` in the vendored body matches `head|tail|wc` only.
    `Select-Object -Last`, `Measure-Object` and the `select` and `measure`
    aliases are PowerShell's equivalents and pass unrefused. The body is
    drift-pinned, so the fix is a kit promotion and is routed as
    `ITC-20260811-2250`, the execution guard's line filters are bash-only
    while it is wired for both shells.

    The assertion is deliberately written the way the CURRENT body behaves,
    so this test goes RED the day the kit closes the gap. That is the
    signal to delete this case and move it back up.
    """
    decision, _ = judge("pytest -q | Select-Object -Last 5")
    assert decision == "silent", (
        "the vendored guard now refuses a PowerShell line filter. That is "
        "the gap ITC-20260811-2250 asked the kit to close, so this test has "
        "done its job: delete it and move the case into "
        "test_an_ordinary_command_is_out_of_scope's refusal siblings."
    )


@pytest.mark.xfail(
    reason=(
        "ITC-20260811-2240: arm 2 does not blank data spans, so a heredoc "
        "opener NAMED inside a quoted heredoc body is parsed as a real "
        "opener. Arm 1 blanks them; arm 2 does not. Reproduced with a "
        "control in ITA-17 round one, where it denied a reviewer's own "
        "findings write. The body is drift-pinned, so this is routed to the "
        "kit and pinned here as a known defect rather than hidden."
    ),
    strict=True,
)
def test_a_quoted_heredoc_body_may_name_an_opener_without_being_refused() -> None:
    """The fourth instance of the documented false-positive class.

    STRICT xfail, so the day the kit fixes it this test fails as XPASS and
    forces the marker off. That is the property worth having: a known
    defect that quietly stops being one should not stay recorded as open.

    The control that isolates the cause is the sibling below: the same
    quoted heredoc, same backslash, WITHOUT the opener form in its prose,
    is out of scope. So it is the named opener that fires arm 2, not the
    backslash and not the heredoc.
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
    assert "30/30 passed" in done.stdout, done.stdout
