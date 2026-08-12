# ITACA / pyflightstream shared process kit
# kit-version: 0.2.20
# artifact: execution_guard.py
# body-sha256: f309785a0c417d12be475e6f07e91458c91e5731bade1c814c67a1ee49565390
# canonical-source: BUILT for the kit 2026-08-11 (BRF-079 step 2). A PreToolUse guard for the two shell shapes that have actually corrupted files or produced a false green in these repositories: a status-bearing command whose exit code is read through a pipe, and a heredoc carrying a backslash or a non-printable byte. Deliberately NOT a blanket heredoc ban: 12 tracked files across the three trees carry heredocs and the kit fixed a heredoc defect at 0.2.1 by correcting rather than forbidding, and a guard that fires on ordinary use is one people learn to work around.
# note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
# END KIT PROVENANCE (body verbatim below)
#!/usr/bin/env python3
"""PreToolUse guard for two shell shapes with a measured history here.

WHY THIS EXISTS AND WHY IT IS NARROW. `BRF-079` read the /insights report
of 2026-08-11, which recommended banning heredocs outright and banning
piped exit-status reads. The ban was narrowed before it became a guard,
on this project's own reasoning at kit 0.2.9: a guard that fires on
ordinary use is a guard people learn to work around. Measured at the
time: twelve tracked files across the three repositories carry heredocs,
`git commit -F -` is ordinary, and the kit already fixed a heredoc defect
at 0.2.1 by CORRECTING rather than forbidding.

So this guard refuses exactly two shapes, both mechanically decidable
without judging intent:

ARM 1, THE PIPED STATUS. A command from ``STATUS_BEARING`` piped into a
line filter (``head``, ``tail``, ``wc``). A pipeline's exit status is the
LAST element's, not the checker's, so a red suite read through ``| tail``
reports green. The general rule cannot be automated, because a hook
cannot know whether a status matters. This arm does not try: it carries a
list of commands whose status ALWAYS matters, which is why the list is
short and why adding to it is a decision rather than a convenience. The
remedy is in the message: run it unpiped, or capture to a file and read
the status from the process.

ARM 2, THE CORRUPTING HEREDOC. A heredoc whose body carries a backslash
or a non-printable byte. This is the shape that mangled files here, not
heredocs as such. A QUOTED delimiter (``<<'EOF'``) disables shell
expansion and is exempt from the backslash half, since that is the form
that survives; the control-byte half applies to both, because no quoting
protects a parser from a stray ``\\x01``.

WHAT IT DOES NOT COVER, stated so it is not read as wider than it is. It
sees one command string at a time, so it cannot catch a status discarded
across two tool calls. It does not inspect files the command reads or
writes. And it judges no other pipeline: ``grep``, ``jq`` and the rest
lose a status exactly as ``tail`` does, and are not listed, because the
measured failures were the filters above and a list grown by imagination
is the allowlist failure the 2026-07-23 review already rejected once.

Exit codes: this is a hook, so it always exits 0 and speaks through the
PreToolUse JSON contract. Silence means out of scope.

Usage (as a PreToolUse hook, payload on stdin):
    execution_guard.py
"""

from __future__ import annotations

import json
import re
import sys

PREFIX = "execution guard: "

# Commands whose exit status ALWAYS matters. Short by design: every entry
# is a thing that answers red or green, and the guard's precision comes
# from the list being about status rather than about danger.
STATUS_BEARING = (
    "pytest",
    "mypy",
    "ruff",
    "git push",
)

# Script-shaped members of the same class, matched on the basename so a
# path prefix does not defeat them.
STATUS_BEARING_PATTERNS = (
    re.compile(r"\bcheck_[\w.\-]*\.py\b"),
    re.compile(r"\b[\w.\-]*_mutations\.py\b"),
    re.compile(r"\bverify_[\w.\-]*\.py\b"),
)

# The line filters that discard a status. Deliberately not extended to
# every filter that would: see the docstring.
LINE_FILTERS = re.compile(r"\|\s*(head|tail|wc)\b")

# ``<<`` or ``<<-`` then an optionally quoted delimiter.
HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# Anything outside printable ASCII plus tab, newline and carriage return.
CONTROL_BYTE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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


def _is_status_bearing(segment: str) -> str | None:
    """Return the matched status-bearing token in this pipeline segment."""
    for name in STATUS_BEARING:
        if re.search(r"(?<![\w.\-])" + re.escape(name) + r"(?![\w.\-])", segment):
            return name
    for pattern in STATUS_BEARING_PATTERNS:
        found = pattern.search(segment)
        if found:
            return found.group(0)
    return None


def _without_data_spans(command: str) -> str:
    """Blank heredoc bodies and quoted spans, keeping every offset valid.

    FOUND BY USING THIS GUARD, twice within its first hour, and both were
    false positives rather than catches. Arm 1 scanned the raw string, so
    a checker NAMED AS DATA counted as a command upstream of any later
    filter. First: a logbook entry describing `verify_hub.py` being
    piped, written into a heredoc, in a command that separately ended
    with `| head -2`. Second: `grep -n "run:.*pytest" file | head -20`,
    where `pytest` is the SEARCH PATTERN and nothing runs it.

    They are one class. A command name inside a heredoc body, a quoted
    search pattern or a commit message is text being handled, not a
    process being started. Both spans are blanked before arm 1 looks.

    THE MISS THIS BUYS, and it is deliberate: a quoted path to an
    executable (`python "kit/check_x.py" | tail`) is blanked too and will
    not be caught. That is accepted because a false POSITIVE gets a guard
    switched off, which is this kit's own reasoning at 0.2.9, and because
    a quoted executable path piped into a filter is rarer here than a
    checker named in a pattern or a message.

    Spans are replaced with spaces rather than removed so every offset
    the caller slices on still refers to the same position.
    """
    out = list(command)

    for opener in HEREDOC_OPEN.finditer(command):
        rest = command[opener.end():]
        end = re.search(
            r"^\s*" + re.escape(opener.group(2)) + r"\s*$", rest, re.M
        )
        stop = opener.end() + (end.start() if end else len(rest))
        for i in range(opener.end(), stop):
            if out[i] != "\n":
                out[i] = " "

    # Quoted spans, single and double. An unterminated quote blanks to the
    # end, which is the conservative direction: the guard sees less and
    # denies less, and it never denies on text it failed to parse.
    quote = None
    for i, ch in enumerate(command):
        if quote is None:
            if ch in "'\"":
                quote = ch
        elif ch == quote:
            quote = None
            out[i] = " "
            continue
        if quote is not None and out[i] != "\n":
            out[i] = " "

    return "".join(out)


def piped_status_offence(command: str) -> str | None:
    """A status-bearing command whose status is discarded by a filter.

    Only the text BEFORE the filter is examined for the checker, so a
    filter that merely appears later in an unrelated pipeline does not
    implicate an earlier command it does not consume. Heredoc bodies are
    blanked first, along with quoted spans: both are DATA being handled,
    not processes being started. See _without_data_spans.
    """
    scannable = _without_data_spans(command)
    match = LINE_FILTERS.search(scannable)
    if not match:
        return None
    upstream = scannable[: match.start()]
    name = _is_status_bearing(upstream)
    if not name:
        return None
    return name


def heredoc_offence(command: str) -> str | None:
    """A heredoc body carrying a backslash or a non-printable byte.

    The delimiter's quoting decides the backslash half only. A quoted
    delimiter (``<<'PY'``) disables expansion, which is the form that
    survives, so a backslash inside it is not the failure this arm was
    built from. No quoting protects a downstream parser from a control
    byte, so that half applies to every heredoc.
    """
    for opener in HEREDOC_OPEN.finditer(command):
        quoted = bool(opener.group(1))
        delimiter = opener.group(2)
        rest = command[opener.end():]
        end = re.search(r"^\s*" + re.escape(delimiter) + r"\s*$", rest, re.M)
        body = rest[: end.start()] if end else rest
        if CONTROL_BYTE.search(body):
            return f"a non-printable byte inside the <<{delimiter} body"
        if not quoted and "\\" in body:
            return (
                f"a backslash inside the unquoted <<{delimiter} body, which "
                f"the shell will consume"
            )
    return None


def main() -> None:
    """Evaluate the two arms on the PreToolUse payload from stdin."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # A payload this guard cannot read is not a violation it can
        # assert. It stays silent rather than denying, because unlike the
        # push gate this guard protects against a mistake and not against
        # an irreversible act, so failing closed here would block ordinary
        # work on a parsing problem of its own.
        _allow_silently()

    command = (payload.get("tool_input") or {}).get("command", "") or ""
    if not command.strip():
        _allow_silently()

    name = piped_status_offence(command)
    if name:
        _decide(
            "deny",
            PREFIX
            + f"[piped-status] `{name}` is piped into a line filter, so the "
            "exit status you read back is the filter's and not the "
            "checker's. A red suite reports green this way, and it has. Run "
            "it unpiped, or redirect to a file and read the status from the "
            "process.",
        )

    why = heredoc_offence(command)
    if why:
        _decide(
            "deny",
            PREFIX
            + f"[heredoc-content] {why}. Heredocs are fine and are not what "
            "this refuses; content that a shell rewrites on its way through "
            "one is. Author this with Write or Edit instead.",
        )

    _allow_silently()


if __name__ == "__main__":
    main()
