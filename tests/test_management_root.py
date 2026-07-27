"""Keep the management root honest, the way the plan checker is kept honest.

Usage example (TDD anchor)::

    root = _resolve()  # from ITACA_MANAGEMENT_ROOT
    assert root is None or (root / "plan" / "README.md").is_file()

The session documents (inbox, handoffs, ``NEXT_SESSION.md``, the plan
ledger, ``progress/``) live under a management root outside this
repository, named by ``ITACA_MANAGEMENT_ROOT``. CLAUDE.md, "Where the
session documents live", is the single home of the resolution rule; this
module is its guard, because that repository's own incident policy says
documentation is not a guard.

What each test exists to catch, all of them real failure modes rather
than hypotheticals:

- a configured root that does not exist, or that exists but belongs to a
  sibling project (they sit under one parent, so a root one folder
  across would file handoffs into another project and validate the wrong
  ledger while reporting a healthy count);
- the unset branch resolving onto a ``_private/`` that no longer holds
  the documents, which is the state this machine entered when the
  content migrated on 2026-07-27, and which would otherwise send every
  session artifact into a directory nobody reads;
- a session document becoming tracked, which used to be structurally
  impossible because one gitignore literal covered the only location,
  and became possible the moment the location turned into a variable;
- a machine-absolute path reaching this public repository, which is the
  invariant the indirection exists to hold.

The environment-dependent tests skip when unconfigured, exactly as the
plan checker's do, so a clone that configured nothing still runs green.
The repository-wide tests never skip: they hold regardless of anyone's
machine.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SECTION = "Where the session documents live"

#: Session-document shapes. If one of these is ever tracked, the "never
#: committed" guarantee has been lost.
_SESSION_SHAPES = (
    "NEXT_SESSION.md",
    "handoffs/HANDOFF_",
    "plan/ITC-",
    "progress/",
)

#: Skills that reach the management root and must route through the rule.
_SKILLS = ("plan", "handoff", "role-review", "audit")


def _flat(text: str) -> str:
    """Collapse whitespace so a citation still matches when it wraps a line.

    These files are hard-wrapped near 72 characters, so a quoted section
    title routinely straddles a newline. Matching the raw text would make
    the guard fail on reflowing rather than on a broken pointer.
    """
    return " ".join(text.split())


def _resolve() -> Path | None:
    """The configured management root, or None when unset."""
    configured = os.environ.get("ITACA_MANAGEMENT_ROOT")
    if not configured:
        return None
    return Path(configured)


def _tracked() -> list[str]:
    """Every path git tracks in this repository."""
    done = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.splitlines()


def test_a_configured_root_exists_and_is_itacas() -> None:
    """A set ITACA_MANAGEMENT_ROOT names an existing itaca management root.

    Existence is not identity. The sibling projects live beside this one
    under a single parent, so a root pointed one folder across satisfies
    "is a directory" while every skill then writes into another project.
    The root is recognized by ``plan/README.md`` naming the ITACA ledger,
    which is the same reasoning that makes the plan checker assert the
    checker's basename rather than settling for a readable file.
    """
    root = _resolve()
    if root is None:
        pytest.skip(
            "ITACA_MANAGEMENT_ROOT is unset; the fallback branch is tested separately"
        )
    assert root.is_dir(), (
        f"ITACA_MANAGEMENT_ROOT is set to {root}, which is not a directory. "
        f"Session documents cannot be written. Set it to the itaca management "
        f"root, or unset it to use _private/."
    )
    marker = root / "plan" / "README.md"
    assert marker.is_file(), (
        f"ITACA_MANAGEMENT_ROOT is set to {root}, which has no plan/README.md, "
        f"so it is not an itaca management root. Session documents would be "
        f"written into the wrong tree. Point it at the itaca management root."
    )
    assert "ITACA plan ledger" in marker.read_text(encoding="utf-8"), (
        f"ITACA_MANAGEMENT_ROOT is set to {root}, whose plan/README.md does not "
        f"name the ITACA plan ledger, so it belongs to another project. Point "
        f"it at the itaca management root."
    )


def test_the_unset_fallback_is_not_a_hollow_directory() -> None:
    """Unset is only safe while _private/ still holds the session documents.

    The rule reads "unset uses ``_private/`` when that directory still
    holds the session documents". An empty or document-less ``_private/``
    is a configuration error, not a fallback: writing a handoff there
    succeeds and is never read again, which is the failure the whole
    indirection exists to prevent.
    """
    if _resolve() is not None:
        pytest.skip("ITACA_MANAGEMENT_ROOT is set; the fallback branch does not apply")
    private = _REPO / "_private"
    if not private.exists():
        pytest.skip(
            "ITACA_MANAGEMENT_ROOT is unset and _private/ is absent; a clean clone"
        )
    assert any(private.iterdir()), (
        "ITACA_MANAGEMENT_ROOT is unset and _private/ is empty, so the session "
        "documents have no home. Writing them here would put them where nobody "
        "reads them. Set ITACA_MANAGEMENT_ROOT to the management root."
    )


def test_no_session_document_is_tracked() -> None:
    """The "never committed" guarantee survives the location becoming a variable.

    It used to rest on one gitignore literal covering the only place the
    documents could be. With the location configurable, nothing structural
    stopped a document from being copied back in and committed, so the
    guarantee is asserted here against the index rather than the filesystem.
    """
    offenders = [
        path
        for path in _tracked()
        for shape in _SESSION_SHAPES
        if shape in path and not path.startswith(".claude/skills/")
    ]
    assert not offenders, (
        f"These tracked files look like session documents: {offenders}. Session "
        f"documents live under the management root and are never committed to "
        f"this repository. Remove them from the index."
    )


def test_private_stays_gitignored() -> None:
    """_private/ is the fallback root, so its exclusion is enforcement.

    CLAUDE.md cites this as the enforcement half of the invariant that no
    proprietary material enters the repository in any form; the
    house-style exclusion beside it is only a scanning exemption. An
    enforcement claim that nothing checks is the shape this repository
    treats as a finding.
    """
    done = subprocess.run(
        ["git", "check-ignore", "-q", "_private/probe.md"],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (
        "_private/ is no longer git-ignored, so the fallback session-document "
        "root can be committed. Restore the _private/ entry in .gitignore."
    )


def test_no_committed_file_carries_a_machine_absolute_path() -> None:
    """The reason this is a variable at all, asserted rather than asserted-to.

    A hard-coded personal path would publish one machine's layout into a
    public repository and be wrong on every clone. That is the stated
    rationale for all three ITACA_ variables, so a literal that reappears
    should fail here rather than ship.
    """
    pattern = re.compile(r"[A-Za-z]:[\\/](?:WORK|Users)[\\/]", re.IGNORECASE)
    offenders: list[str] = []
    for path in _tracked():
        full = _REPO / path
        if full.suffix.lower() not in {
            ".md",
            ".py",
            ".toml",
            ".cfg",
            ".json",
            ".yaml",
            ".yml",
        }:
            continue
        if not full.is_file():
            continue
        for lineno, line in enumerate(
            full.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if pattern.search(line):
                offenders.append(f"{path}:{lineno}")
    assert not offenders, (
        f"These committed lines carry a machine-absolute path: {offenders}. This "
        f"repository is public; locate the target through an environment "
        f"variable instead, as CLAUDE.md requires."
    )


def test_every_skill_routes_through_the_single_home() -> None:
    """A skill that names the root must reach the rule, not restate a guess.

    Written after a review found the audit skill naming the management
    root while giving no variable and no pointer, so a session invoked as
    ``/audit`` alone had nothing to resolve from and was authorized to
    create the directory it guessed at.
    """
    claude_md = _flat((_REPO / "CLAUDE.md").read_text(encoding="utf-8"))
    assert _SECTION in claude_md, (
        f"CLAUDE.md no longer contains the section {_SECTION!r}, which every "
        f"skill quotes as the home of the resolution rule. Renaming it leaves "
        f"those pointers dangling; keep the heading or update every citation."
    )
    for skill in _SKILLS:
        text = _flat(
            (_REPO / ".claude" / "skills" / skill / "SKILL.md").read_text(
                encoding="utf-8"
            )
        )
        if "management root" not in text:
            continue
        assert "ITACA_MANAGEMENT_ROOT" in text and _SECTION in text, (
            f"The {skill} skill names the management root but does not name "
            f"ITACA_MANAGEMENT_ROOT and cite {_SECTION!r}. A skill invoked on "
            f"its own would have to guess the path. Add the pointer."
        )
