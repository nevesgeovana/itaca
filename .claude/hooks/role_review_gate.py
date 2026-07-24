#!/usr/bin/env python3
r"""Mandatory role-review gate on git push (PreToolUse hook, Bash + PowerShell).

Why this exists: on 2026-07-23 the v0.3.0 release ran generic
paraphrased checks instead of invoking the specialist reviewer agents,
because "role-review" was read as a text instruction rather than the
skill that spawns the agents. Documentation alone did not prevent it.
This hook makes the protocol mechanical: a git push is blocked until an
attestation says the role-review skill (the real agents) ran for the
exact commit being pushed, and a release-grade push (a version tag or
--tags/--follow-tags) additionally requires the release attestation
(full-scope audit plus the role-review sweep of every item).

The hook cannot itself run the agents (subagents are the model's to
invoke). It blocks and tells the model what to run; the skills write
the attestation as their closing step (see write_attestation.py).

What this mechanism actually enforces, stated exactly: an attestation
exists that names every commit in scope for this push. It does NOT
prove the reviewer agents ran. The ``passes`` field is recorded and
never checked, and any process that can write the file can clear the
gate. That residual trust sits with the operator. Claiming more than
this would make the gate the thing it guards against, an assurance
whose evidence nobody verified.

Design (hardened 2026-07-23 after the gate's own role review found
bypass holes in v1):
- The command is tokenized, not substring-matched, so ``git -C <path>
  push``, ``git --git-dir=... push`` and ``cd x && git push`` are all
  recognized (v1's ``\bgit\s+push\b`` missed them and failed open).
- The in-script detection is the ONLY scope filter: settings.json uses
  the bare ``Bash|PowerShell`` matcher with no ``if`` glob, because the
  permission-rule glob ``Bash(git push*)`` is prefix-anchored and would
  itself miss the compound forms above.
- Fails CLOSED: once the command looks like a git push, any error
  (unreadable stdin, missing git, unresolvable HEAD, malformed
  attestation) denies with an explanation. Only genuinely out-of-scope
  calls (not a push, not a git repo) allow silently.
- Release-grade detection reads the refs being pushed (an explicit
  ``vX...`` tag argument, or --tags/--follow-tags), NOT substrings of
  the whole command (so a branch named ``fix/v1.2.3`` is not a false
  release) and NOT tags that merely happen to sit at HEAD.

The attestation path is duplicated in write_attestation.py:ATTESTATION
and .gitignore; a rename must touch all three.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ATTESTATION = ".claude/.role_review_attestation.json"
# The shared incident ledger is located by environment variable, never by
# a literal path in a committed file: a hard-coded personal path would
# publish a local layout and deny every push from any other clone, with a
# remedy the reader cannot perform. Unset means the check does not apply;
# set but unreadable blocks.
LEDGER_ENV = "ITACA_INCIDENT_LEDGER"
CHECKER_NAME = "check_incidents.py"
# A version tag argument: v followed by a digit, then version-ish
# characters (covers v0.3.0 and pre-releases like v0.3.0rc1, matching
# the release workflow's `v*` publish trigger). Anchored to the whole
# token, so a branch name like fix/v1.2.3-regression does not match.
VERSION_TAG_TOKEN = re.compile(r"^(?:refs/tags/)?v\d[\w.\-]*$")


def _decide(decision: str, reason: str) -> None:
    """Emit a PreToolUse permission decision and exit."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def _allow_silently() -> None:
    """Out of scope: emit nothing, let the normal permission flow run."""
    sys.exit(0)


_SEPARATORS = ";|&"


def _strip_heredocs(command: str) -> str:
    """Remove heredoc bodies before the command is tokenized.

    A heredoc body is data the shell feeds to another program, not a
    command it runs. Leaving it in means a commit message that merely
    describes a push blocks the commit that documents it, which is both
    a false positive and an incentive to write vaguer messages.
    """
    lines = command.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        opener = re.search(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)", line)
        index += 1
        if opener is None:
            continue
        delimiter = opener.group(2)
        while index < len(lines) and lines[index].strip() != delimiter:
            index += 1
        if index < len(lines):
            index += 1  # drop the closing delimiter line too
    return "\n".join(kept)


def _split_on_separators(tokens: list[str]) -> list[str]:
    """Split unquoted tokens on shell separators.

    ``shlex(posix=False)`` leaves ``push|cat`` as one token, which a
    ``== "push"`` comparison misses. Quoted tokens are left intact, so a
    commit message that merely mentions the command still does not
    match.
    """
    expanded: list[str] = []
    for token in tokens:
        if token[:1] in ("'", '"'):
            expanded.append(token)
            continue
        expanded.extend(part for part in re.split(r"[;|&]+", token) if part)
    return expanded


def _unquote(token: str) -> str:
    """Strip quotes and adjacent shell separators from a token.

    ``shlex(posix=False)`` does not split on ``;`` or ``|``, so
    ``git push; echo done`` tokenizes with ``push;`` as one token and a
    naive ``== "push"`` comparison misses it. That made the gate fail
    OPEN on the single most natural way to type a push followed by
    anything else. Separators are stripped from both ends before any
    comparison.
    """
    token = token.strip(_SEPARATORS)
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1]
    return token.strip(_SEPARATORS)


def _find_git_push(command: str) -> tuple[bool, str | None, list[str]]:
    """Detect a git push in a possibly-compound command.

    Returns ``(is_push, git_c_path, args_after_push)``. ``git_c_path`` is
    the target of a ``-C <path>`` global option when present (so the gate
    evaluates the right repository), else None.

    The command is tokenized with ``shlex`` so quoting is respected: a
    "git push" that appears INSIDE a quoted string (for example a commit
    message that mentions the command) is a single token and never
    matches, while a real ``... && git push`` (the shell operator is its
    own token) does. On unbalanced quotes the parse fails; then, if the
    raw text contains both ``git`` and ``push`` as words, fail closed by
    treating it as a push we could not confirm safe.
    """
    try:
        tokens = _split_on_separators(
            shlex.split(_strip_heredocs(command), posix=False)
        )
    except ValueError:
        if re.search(r"\bgit\b", command) and re.search(r"\bpush\b", command):
            return True, None, []
        return False, None, []

    i = 0
    while i < len(tokens):
        exe = _unquote(tokens[i]).replace("\\", "/").rsplit("/", 1)[-1].lower()
        if exe not in ("git", "git.exe"):
            i += 1
            continue
        # Walk global options (-C <path>, --git-dir=..., -c k=v, ...) to
        # the subcommand token.
        j = i + 1
        git_c_path: str | None = None
        while j < len(tokens):
            tok = _unquote(tokens[j])
            if tok == "-C" and j + 1 < len(tokens):
                git_c_path = _unquote(tokens[j + 1])
                j += 2
                continue
            if tok.startswith("--git-dir="):
                git_c_path = tok.split("=", 1)[1]
                j += 1
                continue
            if tok == "-c" and j + 1 < len(tokens):
                j += 2
                continue
            if tok.startswith("-"):
                j += 1
                continue
            break
        if j < len(tokens) and _unquote(tokens[j]) == "push":
            return True, git_c_path, [_unquote(t) for t in tokens[j + 1 :]]
        i = j
    return False, None, []


def _git(root: Path, *args: str) -> str:
    """Run git in ``root``; empty string on any failure (caller decides)."""
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        ).stdout.strip()
    except (OSError, ValueError):
        return ""


def _pushed_commits(root: Path, target: str) -> list[str]:
    """List the commits this push would make newly available on the remote.

    ``git rev-list <target> --not --remotes`` is everything reachable
    from the target that no remote-tracking ref already has. That is the
    real range a push moves, and it needs no refspec parsing, so
    ``git push``, ``git push origin main`` and a tag push are all handled
    the same way. Empty means the remote already has everything.
    """
    listed = _git(root, "rev-list", target, "--not", "--remotes")
    return [c for c in listed.splitlines() if c]


def _blocking_incidents(repo_name: str) -> tuple[bool, str, str]:
    """Ask the configured ledger whether an open incident blocks this repo.

    Returns ``(blocked, kind, detail)``. ``kind`` separates the two
    failure classes because their remedies are opposite: ``"incident"``
    is a real open blocking incident, ``"unreachable"`` is a ledger that
    is configured but could not be consulted.
    """
    configured = os.environ.get(LEDGER_ENV, "").strip()
    if not configured:
        return False, "", ""
    checker = Path(configured)
    if checker.is_dir():
        checker = checker / CHECKER_NAME
    if not checker.is_file():
        return (
            True,
            "unreachable",
            f"{LEDGER_ENV} points at {configured}, where {CHECKER_NAME} is "
            "not readable",
        )
    try:
        done = subprocess.run(
            [sys.executable, str(checker), repo_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return (
            True,
            "unreachable",
            f"the checker could not run ({type(error).__name__}: {error})",
        )
    if done.returncode == 0:
        return False, "", ""
    detail = (
        done.stdout.strip()
        or done.stderr.strip()
        or "the checker reported a blocking state"
    )
    return True, "unreachable" if "UNREADABLE" in detail else "incident", detail


# Options that send refs the gate cannot enumerate offline. --tags and
# --follow-tags are the sharp ones: there is no way to tell which tags the
# remote already has without talking to it, so a scope computed from local
# state silently omits the tag being published. --follow-tags is the
# ordinary release command, and it shipped an unattested tag while every
# test stayed green.
UNSCOPABLE_OPTIONS = frozenset(
    {"--all", "--mirror", "--tags", "--follow-tags", "--delete", "-d"}
)


def _push_scope(args_after_push: list[str], root: Path) -> tuple[list[str], str]:
    """Resolve the commits this push sends, or say why it cannot.

    Returns ``(commits, problem)``. A non-empty ``problem`` means the
    gate could not determine what the push sends and must deny: a guard
    that guesses at its own scope is not a guard.

    The first non-option token is the remote; the rest are refspecs,
    whose source side (before ``:``) is resolved locally. With no
    refspec the push sends the current branch, so the scope is HEAD.
    """
    tokens = [_unquote(raw) for raw in args_after_push]
    for tok in tokens:
        if tok in UNSCOPABLE_OPTIONS:
            return [], f"the {tok} form sends refs the gate cannot enumerate"

    positional = [t for t in tokens if not t.startswith("-")]
    # The first positional is the remote (a name or a URL), never a ref.
    refspecs = positional[1:]
    if not refspecs:
        head = _git(root, "rev-parse", "HEAD")
        return ([head] if head else []), ("" if head else "HEAD does not resolve")

    commits: list[str] = []
    for spec in refspecs:
        source = spec.lstrip("+").split(":", 1)[0]
        if not source:
            return [], f"the refspec {spec!r} deletes a remote ref"
        commit = _git(root, "rev-list", "-n", "1", source)
        if not commit:
            return [], f"the ref {source!r} does not resolve in this checkout"
        commits.append(commit)
    return commits, ""


def _is_release_push(args_after_push: list[str]) -> bool:
    """Classify a push as release-grade from the refs it names.

    Release-grade when an argument is an explicit version tag. The
    --tags forms never reach this question: they are refused earlier as
    unscopable, which is also what stops them from publishing a tag the
    release attestation never covered.
    """
    return any(VERSION_TAG_TOKEN.match(_unquote(raw)) for raw in args_after_push)


def _repo_identity(root: Path) -> str:
    """Name this repository for the incident query.

    From ``[project] name`` in pyproject.toml, which travels with the
    clone. The checkout directory name does not: a clone into
    ``itaca-review``, a worktree, or a renamed folder would query an
    unknown repository, get a clean answer, and allow. Falling back to
    the folder name keeps the gate working in a checkout with no
    pyproject, which is the only case where nothing better exists.
    """
    config = root / "pyproject.toml"
    section = ""
    try:
        for line in config.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped
                continue
            if section == "[project]" and stripped.startswith("name"):
                _, sep, value = stripped.partition("=")
                if sep:
                    name = value.strip().strip("\"'")
                    if name:
                        return name
    except OSError:
        pass
    return root.name


def main() -> None:
    """Evaluate the push gate on the PreToolUse payload from stdin."""
    # Out-of-scope calls (not a push, not a repo) allow silently; once a
    # push is recognized, every failure path denies (fail closed).
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Cannot read the command: if this hook fired at all it was on a
        # tool call, but with no command we cannot confirm a push, so stay
        # out of the way rather than block unrelated tools.
        _allow_silently()

    command = (payload.get("tool_input") or {}).get("command", "") or ""
    is_push, git_c_path, args_after_push = _find_git_push(command)
    if not is_push:
        _allow_silently()

    try:
        base = Path(git_c_path) if git_c_path else Path.cwd()
        top = _git(base, "rev-parse", "--show-toplevel")
        if not top:
            # Looks like a git push but no repo resolves: fail closed.
            _decide(
                "deny",
                "role-review gate: this looks like a git push but no git "
                f"repository resolves from {base}. Run it from inside the "
                "repo (or fix the -C path); the gate must be able to check "
                "the role-review attestation before a push.",
            )
        root = Path(top)

        head = _git(root, "rev-parse", "HEAD")
        if not head:
            _decide(
                "deny",
                "role-review gate: could not read HEAD (no commits yet, or "
                "a detached or corrupt checkout). Make at least one commit "
                "and confirm `git rev-parse HEAD` succeeds from the repo "
                "root, then push.",
            )

        is_release = _is_release_push(args_after_push)
        # The refs this push actually sends, resolved from the command.
        # Scoping from HEAD instead let a push of any other ref clear the
        # gate whenever HEAD happened to be attested.
        targets, problem = _push_scope(args_after_push, root)
        if problem:
            _decide(
                "deny",
                "role-review gate: the gate cannot determine which commits "
                f"this push sends, because {problem}. Push the branch or tag "
                "by name (for example `origin main` or `origin v0.2.0`) so "
                "the gate can resolve the ref and check it against the "
                "attestation. Refusing is deliberate: a guard that guesses "
                "at its own scope proves nothing.",
            )

        att_path = root / ATTESTATION
        try:
            att = (
                json.loads(att_path.read_text(encoding="utf-8"))
                if att_path.is_file()
                else {}
            )
        except (json.JSONDecodeError, ValueError, OSError):
            att = {}

        # An open blocking incident stops every push, before the review
        # question is even asked: no new work ships on top of a defect
        # whose structural cause is still unfixed. The repository identity
        # comes from the checkout, never a literal, so a copy that forgot
        # to edit it cannot query the wrong repository, get a clean
        # answer, and allow.
        repo_name = _repo_identity(root)
        blocked, kind, detail = _blocking_incidents(repo_name)
        if blocked and kind == "unreachable":
            _decide(
                "deny",
                "INCIDENT GATE: the incident ledger is configured but could not be "
                f"consulted:\n{detail}\n"
                f"Resync or repair it, or correct {LEDGER_ENV}, then push. The gate "
                "blocks rather than assume nothing is wrong; if an incident file is "
                "named as unreadable, repair its header block (id, status, blocking, "
                "repos, and blocking_reason when blocking is false).",
            )
        if blocked:
            _decide(
                "deny",
                "INCIDENT GATE: the shared incident ledger has an open incident that "
                f"blocks a push from {repo_name}:\n{detail}\n"
                "Run the incident-analyst agent, fix the incident at its structural "
                "cause, give it a guard and the evidence that the guard blocks the "
                "original failure when re-run, and set its status to fixed. Marking it "
                "non-blocking to get past this gate is the failure this "
                "protocol exists to prevent.",
            )

        # The attestation must cover EVERY commit the push makes new, not
        # just the tip: checking the tip alone let unpushed ancestors ship
        # unreviewed. ITACA's own role review found that defect.
        # Every ref sent is ALWAYS in scope, even when it moves zero new
        # commits. Set containment over an empty range is vacuously true,
        # and the ordinary release order (branch first, then tag) leaves
        # the tagged commit already on the remote: checking only the range
        # let an unattested tag through. A guard whose assertion can be
        # discharged by having nothing to assert about is not a guard.
        in_scope: list[str] = []
        for ref_commit in targets:
            in_scope.extend(_pushed_commits(root, ref_commit))
            in_scope.append(ref_commit)
        in_scope = list(dict.fromkeys(in_scope))
        review = att.get("review") or {}
        covered = set(
            review.get("commits") or ([review["head"]] if review.get("head") else [])
        )
        missing = [c for c in in_scope if c not in covered]
        if missing:
            listed = ", ".join(c[:12] for c in missing[:8])
            more = f" and {len(missing) - 8} more" if len(missing) > 8 else ""
            # Name the range. The role-review skill defaults to the last
            # commit when given nothing, which is the wrong scope for this
            # denial, so a reader who obeys the message literally re-arms
            # the gate instead of clearing it.
            span = f"{in_scope[-1]}^..{in_scope[0]}"
            _decide(
                "deny",
                f"ROLE-REVIEW GATE: {len(missing)} of the {len(in_scope)} commit(s) in "
                f"scope for this push are not covered by any role-review attestation: "
                f"{listed}{more}. Run the role-review skill (the specialist agents: "
                "architect, QA, V&V, tech writer, API designer as applicable) over the "
                f"WHOLE pushed range, which is `{span}`, not only the tip; read "
                f"it with `git log --oneline {span}`. Fix or register every "
                "finding and let the "
                "skill write the attestation. Do NOT paraphrase the review as manual "
                "checks. If you amended or rebased since attesting, the commits "
                "changed: re-review and re-attest. Then push.",
            )

        if is_release:
            release = att.get("release") or {}
            rel_covered = set(
                release.get("commits")
                or ([release["head"]] if release.get("head") else [])
            )
            rel_missing = [c for c in in_scope if c not in rel_covered]
            if rel_missing:
                _decide(
                    "deny",
                    "RELEASE GATE: this is a release-grade push (an explicit version "
                    "tag) but the release attestation does not cover "
                    f"{len(rel_missing)} of the {len(in_scope)} commit(s) being "
                    "released, including the tagged commit itself when the branch was "
                    "pushed first. Run the role-review skill over the whole release "
                    "diff (every applicable pass, full scope, not the last item only), "
                    "fix or register every finding, then write the release attestation "
                    "with `python .claude/hooks/write_attestation.py release "
                    "<passes,that,ran>`, and only then push the tag.",
                )

        # Attestation covers the pushed commit: let the normal permission
        # flow proceed.
        _allow_silently()
    except Exception as error:  # a gate must fail closed
        _decide(
            "deny",
            "role-review gate: the gate could not be evaluated for this "
            f"push ({type(error).__name__}: {error}). Failing closed. "
            "Resolve the error, then push. If the gate itself is broken, "
            "stop and tell Geovana: turning the gate off to ship is an "
            "author decision, not a workaround, and it is the exact move "
            "this protocol exists to prevent.",
        )


if __name__ == "__main__":
    main()
