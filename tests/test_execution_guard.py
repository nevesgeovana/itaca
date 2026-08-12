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

# Built by concatenation so this file never contains the shapes it tests as
# literal command text. The push-gate module does the same for its own
# reason, and here it matters more: this guard is WIRED, so a literal in a
# command string a session runs would be refused. The heredoc opener is
# assembled for the same reason.
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
    matcher as the push gate: a guard wired for `Bash` alone would not see
    a PowerShell command, and this repository's sessions use both.
    """
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    wired = [
        (entry, hook)
        for entry in entries
        for hook in entry.get("hooks", [])
        if "execution_guard.py" in hook.get("command", "")
    ]
    assert wired, (
        f"no PreToolUse hook in {SETTINGS} invokes execution_guard.py, so the "
        f"vendored body runs never. Wire it, or stop vendoring it."
    )
    for entry, hook in wired:
        matcher = entry["matcher"]
        assert "Bash" in matcher and "PowerShell" in matcher, (
            f"the execution guard is wired on matcher {matcher!r}. It must see "
            f"both shells, or the shape it refuses simply moves to the other."
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
        # PowerShell's own filter, which is not one of the three listed.
        "pytest -q | Select-Object -Last 5",
    ],
)
def test_an_ordinary_command_is_out_of_scope(command: str) -> None:
    """The controls, and they carry as much weight as the refusals.

    A guard that denied all five would be one every session learns to work
    around, which is the reason the kit narrowed this from the blanket ban
    the source report recommended. `pytest -q > out.txt` and the unpiped
    form are exactly what the refusal messages tell an operator to do, so
    if either were refused the guard would prescribe a denied command.
    """
    decision, reason = judge(command)
    assert decision == "silent", f"{command!r} was refused: {reason}"


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
