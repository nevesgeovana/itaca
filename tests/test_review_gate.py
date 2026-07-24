"""The role-review push gate must not fail open (process guard).

Usage example (TDD anchor)::

    is_push, git_c_path, args = _find_git_push("git push; echo done")
    assert is_push is True

The gate blocks a publish until an attestation names the exact commit
being sent. Its parsing functions are pure, and a v1 of this hook
already shipped bypass holes, so they are pinned here: a command form
that reaches the remote but is not recognized makes the gate fail open,
which is the one failure mode a gate may not have. The hook lives
outside the ``itaca`` package, so it is loaded by path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_HOOK = (
    Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "role_review_gate.py"
)


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_role_review_gate", _HOOK)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    """Load the hook, and fail rather than skip when it is missing.

    This fixture used to skip. Deleting or renaming the hook therefore
    removed 30 guard assertions and the suite still reported green,
    which is the self-skipping evidence the gate exists to replace.
    """
    assert _HOOK.is_file(), (
        f"the push gate hook is missing at {_HOOK}. It is a required guard, "
        "not an optional one: without it nothing blocks an unreviewed push."
    )
    return _load_gate()


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin main",
        # Separator forms: shlex(posix=False) keeps "push;" and "push|cat"
        # as single tokens, so a naive equality test fails open here.
        "git push;",
        "git push; echo done",
        "git push|cat",
        "git push && echo done",
        "cd /tmp && git push",
        # Global options before the subcommand.
        "git -C /repo push",
        "git --git-dir=/repo/.git push",
        "git -c user.name=x push",
    ],
)
def test_a_push_is_recognized(gate: ModuleType, command: str) -> None:
    """Every form that reaches the remote must arm the gate."""
    is_push, _, _ = gate._find_git_push(command)
    assert is_push is True, f"gate would fail open on {command!r}"


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "git status",
        "git pushx",
        "gitk push",
        "git commit -m 'git push now'",
        'git commit -m "mention git push in prose"',
    ],
)
def test_a_non_push_is_not_recognized(gate: ModuleType, command: str) -> None:
    """A quoted mention must not block unrelated work."""
    is_push, _, _ = gate._find_git_push(command)
    assert is_push is False, f"gate would block {command!r}"


@pytest.mark.parametrize(
    "command",
    [
        "git push origin v0.2.0",
        "git push origin refs/tags/v0.2.0",
        "git push origin v0.2.0rc1",
    ],
)
def test_a_release_grade_push_is_classified(gate: ModuleType, command: str) -> None:
    """A release push additionally requires the release attestation."""
    is_push, _, args = gate._find_git_push(command)
    assert is_push is True
    assert gate._is_release_push(args) is True, command


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin main",
        "git push origin fix/v1.2.3-regression",
    ],
)
def test_an_ordinary_push_is_not_release_grade(gate: ModuleType, command: str) -> None:
    """A branch name that merely looks like a version is not a release."""
    _, _, args = gate._find_git_push(command)
    assert gate._is_release_push(args) is False, command


@pytest.mark.parametrize(
    "command",
    [
        "git push --tags",
        "git push --tags;",
        "git push --follow-tags",
        "git push --all origin",
        "git push --mirror origin",
    ],
)
def test_a_blanket_ref_push_cannot_be_scoped(gate: ModuleType, command: str) -> None:
    """These forms send refs the gate cannot enumerate without the remote.

    They were once classified as ordinary or as release-grade and then
    scoped from HEAD, so --follow-tags, the ordinary release command,
    published a tag no attestation covered. Refusing to scope them is
    the honest answer; the deny message asks for the ref by name.
    """
    _, _, args = gate._find_git_push(command)
    # v0.2.0 (S5b, FIX 3): _push_scope also returns the resolved target
    # remote so the range can be scoped to it; the blanket forms still
    # short-circuit before a remote is known, so it comes back empty.
    commits, problem, fix, _remote = gate._push_scope(args, Path("."))
    assert commits == []
    assert "cannot enumerate" in problem, command
    assert fix, command


def test_the_c_option_target_is_extracted(gate: ModuleType) -> None:
    """The gate must evaluate the repository the push actually targets."""
    _, path, _ = gate._find_git_push("git -C /somewhere/else push")
    assert path == "/somewhere/else"


def test_unbalanced_quotes_fail_closed(gate: ModuleType) -> None:
    """An unparseable command that mentions the verbs is treated as a push."""
    is_push, _, _ = gate._find_git_push("git push 'unbalanced")
    assert is_push is True


# v0.2.0 (S5b) hardening: the gate must see a push inside a shell wrapper.
@pytest.mark.parametrize(
    "command",
    [
        # POSIX short-flag clusters that carry an inline command.
        "bash -c 'git push'",
        "bash -lc 'git push origin main'",
        "sh -c \"git push\"",
        "zsh -ec 'git push'",
        # PowerShell accepts a case-insensitive prefix of -Command.
        "powershell -Command 'git push'",
        "powershell -command \"git push origin main\"",
        "pwsh -Comm 'git push'",
        # cmd /c.
        "cmd /c \"git push\"",
        # Nested wrapper, still within the bounded recursion depth.
        "bash -c \"bash -c 'git push'\"",
    ],
)
def test_a_shell_wrapped_push_is_recognized(gate: ModuleType, command: str) -> None:
    """A wrapped push reaches the remote, so a gate that misses it fails open.

    The v1 matcher looked for a git executable and never recursed into a
    shell wrapper, so ``bash -lc "git push"`` and every family variant ran
    a real push while the gate saw a benign ``bash``. The command flag is
    matched by shell family, not a literal set, so ``-lc`` and ``-command``
    are caught as well as ``-c`` and ``-Command``.
    """
    is_push, _, _ = gate._find_git_push(command)
    assert is_push is True, f"gate fails open on {command!r}"


def test_a_wrapper_that_does_not_run_a_push_is_not_flagged(gate: ModuleType) -> None:
    """The wrapper recursion must not turn every shell command into a push."""
    is_push, _, _ = gate._find_git_push("bash -c 'ls -la'")
    assert is_push is False


def test_an_unconditional_force_is_refused_as_author_only(gate: ModuleType) -> None:
    """``git push --force`` rewrites published history: no attestation covers it.

    Unconditional ``-f`` / ``--force`` were classed as safe options and
    rode the normal attestation, so a reviewed push could silently rewrite
    the remote. They are now author-only: ``_push_scope`` refuses on
    policy before it even resolves the range. The safe variants
    (``--force-with-lease``) stay on the attestation path, pinned by
    ``tests/test_push_gate.py``.
    """
    for option in ("-f", "--force"):
        commits, problem, fix, _remote = gate._push_scope(
            [option, "origin", "main"], Path(".")
        )
        assert commits == [], option
        assert "force" in problem.lower(), option
        assert fix, option
