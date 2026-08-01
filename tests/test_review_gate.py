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
    # v0.2.2: _push_scope returns (commits, problem, fix, remote, kind).
    # A blanket form is a genuinely unresolvable range, so kind is "scope".
    commits, problem, fix, _remote, kind = gate._push_scope(args, Path("."))
    assert commits == []
    assert "cannot enumerate" in problem, command
    assert fix, command
    assert kind == "scope", command


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
        'sh -c "git push"',
        "zsh -ec 'git push'",
        # PowerShell accepts a case-insensitive prefix of -Command.
        "powershell -Command 'git push'",
        'powershell -command "git push origin main"',
        "pwsh -Comm 'git push'",
        # cmd /c.
        'cmd /c "git push"',
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
        commits, problem, fix, _remote, kind = gate._push_scope(
            [option, "origin", "main"], Path(".")
        )
        assert commits == [], option
        assert "force" in problem.lower(), option
        assert fix, option
        # v0.2.2: a force stop is a policy refusal, not a scope failure;
        # the caller frames the two differently, so kind distinguishes them.
        assert kind == "policy", option


def test_the_heredoc_stripper_actually_removes_a_body(gate: ModuleType) -> None:
    """The stripper must delete a heredoc body, not merely the end decision.

    A stray control byte once broke the heredoc-opener regex so
    ``_strip_heredocs`` matched nothing and stripped nothing (the closed
    incident INC-20260724-0912, re-forked into the 0.2.0 kit body). The
    end-to-end decision stayed correct by luck, so only a test that asserts
    the body is gone catches a dead stripper. This pins the stripper itself
    so a re-fork of that byte turns CI red.
    """
    command = (
        "git commit -F - <<EOF\n"
        "this message body mentions git push but must be stripped\n"
        "EOF"
    )
    stripped = gate._strip_heredocs(command)
    assert "must be stripped" not in stripped, "heredoc body was not removed"
    # The opener line itself is kept; only the body is dropped.
    assert "git commit -F -" in stripped


# INC-20260802-1450-shared, and the reason these live here rather than
# beside the drift pin. Kit 0.2.16 closed a FAIL-OPEN in this body: an
# unterminated heredoc opener made `_strip_heredocs` drop every remaining
# line of the command, and a real `git push` went with them. The only thing
# in this repository that would have noticed its return was the body-sha256
# pin in `tests/test_kit_drift.py`, which is a CHANGE detector and not a
# BEHAVIOR detector: a re-vendor that regresses the branch and updates the
# hash mechanically ships green.
#
# That is the same argument `test_the_heredoc_stripper_actually_removes_a_body`
# above was written from, one incident earlier, and it is why the assertion
# surface is `_find_git_push` and `_strip_heredocs` rather than the
# end-to-end decision: an end-to-end verdict can stay correct by luck.
#
# MEASURED RED against the 0.2.8 body taken out of git at ad0698b, before
# the pin moved: 4 of the 5 CASES below were wrong there and 0 are wrong
# on the vendored 0.2.16 body. The unit is the case and not the assert
# statement, because a reader cannot infer it: counted as asserts it is 6
# of 8, since each of the three fail-open cases fails both of its
# assertions. The three fail-open cases each stripped the push away and
# reported `is_push=False`; the here-string commit was DENIED as a push
# although it is a commit.
#
# THE FIFTH ASSERTION WAS ALREADY CORRECT AT 0.2.8, and it is named rather
# than quietly counted: a push written AFTER a terminated here-string was
# kept there too. It is a regression detector for something the fix must
# not break, not evidence that the fix works, and a guard whose whole set
# measured red would have been the stronger claim. This one does not, so
# the number is 4 of 5.
_UNTERMINATED_OPENERS = (
    ('git commit -m "see the <<EOF form"', "a message naming the <<EOF form"),
    ('git commit -m "about <<HEREDOC" &&', "the same with a trailing &&"),
    ('git commit -m "a << b"', "a << that is not a heredoc at all"),
)


@pytest.mark.parametrize(
    "first_line,why",
    _UNTERMINATED_OPENERS,
    ids=[why for _, why in _UNTERMINATED_OPENERS],
)
def test_an_unterminated_opener_never_hides_the_push_on_the_next_line(
    gate: ModuleType, first_line: str, why: str
) -> None:
    """An opener with no terminator must strip NOTHING (`INC-20260802-1450-shared`).

    Stripping can only ever take tokens AWAY from what is scanned, so in a
    gate that must fail closed there is exactly one safe reading of an input
    the stripper does not understand, and it is to strip nothing.

    The documented fallback does not save this. The design note says an
    unbalanced quote makes the parse fail and raw text matching `git` and
    `push` is then treated as a push; that is false in general, because
    `shlex.split(..., posix=False)` does not raise on every unbalanced
    quote. A stripping bug therefore yields a CLEAN PARSE with the push
    missing from it, and nothing downstream notices.
    """
    command = f"{first_line}\ngit push origin main"
    stripped = gate._strip_heredocs(command)
    assert "git push origin main" in stripped, (
        f"the stripper dropped a real push that follows {why}. An opener "
        f"whose terminator never arrives must leave the command as written; "
        f"anything else removes tokens the gate has to scan."
    )
    is_push, _, _ = gate._find_git_push(command)
    assert is_push is True, (
        f"the gate does not see the push that follows {why}. This is "
        f"INC-20260802-1450-shared: is_push False is not a weaker refusal, "
        f"it is no refusal at all, because the gate returns without "
        f"evaluating an attestation, a ledger or a release check."
    )


def test_a_powershell_here_string_hides_the_push_its_body_mentions(
    gate: ModuleType,
) -> None:
    """A commit whose MESSAGE describes a push is not a push (`ITC-20260801-2245`).

    The opposite direction to the test above, closed in the same kit
    promotion, and it is a false POSITIVE rather than a fail-open: a
    PowerShell here-string leaves an odd quote count, `shlex` raised, and
    the fail-closed fallback denied a COMMIT on the word `pre-push` alone,
    because a hyphen is a word boundary. Every commit message in this lane
    describes the push path, so the cost was a workaround (`git commit -F`)
    carried in a skill.

    The second assertion is what keeps the fix honest: a here-string that IS
    terminated must still not hide a push written after its terminator.
    """
    hidden = (
        "git commit -m @'\n"
        "this message body mentions git push and pre-push and must be data\n"
        "'@"
    )
    is_push, _, _ = gate._find_git_push(hidden)
    assert is_push is False, (
        "a commit whose here-string MESSAGE mentions a push is denied as a "
        "push. The here-string body is data; nothing inside one may make the "
        "gate see a push."
    )
    followed = f"{hidden}\ngit push origin main"
    stripped = gate._strip_heredocs(followed)
    assert "git push origin main" in stripped, (
        "a terminated here-string swallowed the push written AFTER its "
        "terminator. Only the lines strictly between the opener and the "
        "terminator are data."
    )
