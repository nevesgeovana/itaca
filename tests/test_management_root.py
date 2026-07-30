"""Keep the management root honest, the way the plan checker is kept honest.

Usage example (TDD anchor)::

    root, branch = resolve_management_root("C:/hub/itaca", repo=_REPO)
    assert branch == "variable"

The session documents (inbox, handoffs, ``NEXT_SESSION.md``, the plan
ledger, ``progress/``, session logs, working decision notes) live under a
management root outside this repository, named by
``ITACA_MANAGEMENT_ROOT``. CLAUDE.md, "Where the session documents live",
is the single home of the resolution rule; this module is its guard,
because this repository's own incident policy says documentation is not
a guard.

``resolve_management_root`` is the rule as executable code, and the
tests below drive it over **constructed** environments rather than
observing the machine's. That matters for two reasons found in review:
a guard that only inspects the ambient environment reddens the suite
when a developer's shell has not picked up a variable, which is a
configuration fact and not a repository defect; and it exercises none of
its own logic on CI, where nothing is configured, so the branch the
guard exists to prove would never run.

The failure modes each test pins, all of them observed rather than
imagined:

- a configured root that does not exist, or that exists but belongs to a
  sibling project (they sit under one parent, so a root one folder
  across would file handoffs into another project and validate the wrong
  ledger while reporting a healthy count);
- the unset branch resolving onto a ``_private/`` that no longer holds
  the documents, which is the state this repository entered when the
  content migrated on 2026-07-27, and which would otherwise send every
  session artifact into a directory nobody reads. Non-emptiness is not
  enough: ``_private/`` has a second documented use as local staging, so
  one staged file must not make a hollow tree look like a root;
- a session document becoming tracked, which used to be structurally
  impossible because one gitignore literal covered the only location,
  and became possible the moment the location turned into a variable;
- a machine-absolute path reaching this public repository, which is the
  invariant the indirection exists to hold;
- a skill naming the root without reaching the rule, and a rename of the
  CLAUDE.md heading every skill quotes.

Nothing here skips. The rule tests build their own environments and the
repository tests hold regardless of anyone's machine, so the module
gives the same answer on a developer's box and on CI.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from management_root import (  # the single home of the resolution rule
    ManagementRootError,
    resolve_management_root,
)

_REPO = Path(__file__).resolve().parents[1]
_SECTION = "Where the session documents live"

#: Path fragments that identify a session document. Derived from the
#: CLAUDE.md enumeration; keep the two in step.
_SESSION_SHAPES = (
    "NEXT_SESSION.md",
    "handoffs/HANDOFF_",
    "plan/ITC-",
    "progress/",
    "inbox/",
    "CANDIDATE_",
    "_log.md",
)


#: The heading of the single home, as every skill quotes it.
_HEADING = re.compile(rf"(?m)^#{{1,6}}\s+{re.escape(_SECTION)}\b")

#: Machine-absolute path forms. Drive-letter (C:\WORK, C:/Users), the
#: MSYS form a bash transcript carries (/c/WORK), and a POSIX home (~/).
_ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/](?:WORK|Users|home)[\\/])"
    r"|(?:(?<![\w/])/[a-z]/(?:WORK|Users)/)"
    r"|(?:(?<![\w`])~/[A-Za-z])",
    re.IGNORECASE,
)

#: Binary-ish suffixes the machine-path sweep skips. Everything else
#: tracked is scanned, so a new text format is covered by default rather
#: than by remembering to add it.
_BINARY_SUFFIXES = {
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".svg",
    ".woff",
    ".woff2",
    ".zip",
}


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


def _flat(text: str) -> str:
    """Collapse whitespace so a citation still matches when it wraps a line.

    These files are hard-wrapped near 72 characters, so a quoted section
    title routinely straddles a newline. Matching the raw text would make
    the guard fail on reflowing rather than on a broken pointer.
    """
    return " ".join(text.split())


def _make_root(tmp_path: Path, heading: str = "# The ITACA plan ledger") -> Path:
    """Build a management root whose ledger README carries ``heading``."""
    ledger = tmp_path / "plan"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "README.md").write_text(f"{heading}\n\nBody.\n", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------
# The rule, over constructed environments.
# --------------------------------------------------------------------------


def test_a_configured_root_resolves_and_announces_its_branch(tmp_path: Path) -> None:
    """The happy path returns the root and says which branch produced it."""
    root = _make_root(tmp_path / "itaca")
    assert resolve_management_root(str(root), repo=tmp_path / "repo") == (
        root,
        "variable",
    )


def test_a_configured_root_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    """Set but absent is a configuration error, never a silent fallback."""
    with pytest.raises(ManagementRootError, match="not a directory"):
        resolve_management_root(str(tmp_path / "nope"), repo=tmp_path / "repo")


def test_a_sibling_project_root_is_refused(tmp_path: Path) -> None:
    """Existence is not identity.

    The original defect: the projects sit under one parent, so a root
    pointed one folder across satisfies "is a directory" while every
    skill writes into another project and validates its ledger.
    """
    sibling = _make_root(tmp_path / "pyflightstream", heading="# The plan ledger")
    with pytest.raises(ManagementRootError, match="not itaca's management root"):
        resolve_management_root(str(sibling), repo=tmp_path / "repo")


def test_a_root_with_no_ledger_readme_is_refused(tmp_path: Path) -> None:
    """A directory that exists but carries no ledger at all is not a root."""
    bare = tmp_path / "empty"
    bare.mkdir()
    with pytest.raises(ManagementRootError, match="not itaca's management root"):
        resolve_management_root(str(bare), repo=tmp_path / "repo")


def test_a_cross_reference_to_the_itaca_ledger_does_not_impersonate_it(
    tmp_path: Path,
) -> None:
    """The marker is anchored to the heading, not matched anywhere.

    The sister repository runs the same plan kit and its README is one
    cross-reference away from carrying this string in its body.
    """
    impostor = tmp_path / "pyflightstream"
    (impostor / "plan").mkdir(parents=True)
    (impostor / "plan" / "README.md").write_text(
        "# The plan ledger: one file per entry\n\nSame format as the ITACA "
        "plan ledger, see the sister repository.\n",
        encoding="utf-8",
    )
    with pytest.raises(ManagementRootError, match="not itaca's management root"):
        resolve_management_root(str(impostor), repo=tmp_path / "repo")


def test_unset_uses_private_while_it_still_holds_the_documents(
    tmp_path: Path,
) -> None:
    """The pre-migration layout, and any clone that configured nothing."""
    repo = tmp_path / "repo"
    (repo / "_private" / "plan").mkdir(parents=True)
    assert resolve_management_root(None, repo=repo) == (repo / "_private", "fallback")


@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("absent", lambda private: None),
        ("empty", lambda private: private.mkdir(parents=True)),
        (
            "holds only staged material",
            lambda private: (
                private.mkdir(parents=True),
                (private / "staged.csv").write_text("x\n", encoding="utf-8"),
            ),
        ),
    ],
)
def test_unset_onto_a_hollow_private_is_refused(
    tmp_path: Path, name: str, build: object
) -> None:
    """The failure this migration created, in its three shapes.

    ``_private/`` is documented as local staging as well as the fallback
    root, so a directory holding one staged file holds no session
    documents and must not resolve.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    build(repo / "_private")  # type: ignore[operator]
    with pytest.raises(ManagementRootError, match="holds no session documents"):
        resolve_management_root(None, repo=repo)


def test_every_refusal_names_object_operation_and_fix(tmp_path: Path) -> None:
    """The workspace error contract, applied to configuration errors."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cases = [
        (str(tmp_path / "nope"), repo),
        (str(_make_root(tmp_path / "sib", heading="# Other")), repo),
        (None, repo),
    ]
    for configured, where in cases:
        with pytest.raises(ManagementRootError) as caught:
            resolve_management_root(configured, repo=where)
        message = str(caught.value)
        assert "ITACA_MANAGEMENT_ROOT" in message, message
        assert ";" in message, f"no three-part structure: {message}"
        assert "set it" in message.lower() or "point it" in message.lower(), message


# --------------------------------------------------------------------------
# The repository, which holds regardless of anyone's machine.
# --------------------------------------------------------------------------


def test_no_session_document_is_tracked() -> None:
    """The "never committed" guarantee survives the location becoming a variable.

    It used to rest on one gitignore literal covering the only place the
    documents could be. With the location configurable, nothing structural
    stopped a document from being copied back in and committed, so the
    guarantee is asserted here against the index rather than the filesystem.
    """
    offenders = sorted(
        {path for path in _tracked() for shape in _SESSION_SHAPES if shape in path}
    )
    assert not offenders, (
        f"These tracked files look like session documents: {offenders}. Session "
        f"documents live under the management root and are never committed to "
        f"this repository. Remove them from the index."
    )


def test_private_stays_gitignored_by_the_committed_gitignore() -> None:
    """_private/ is the fallback root, so its exclusion is enforcement.

    Asserted against ``.gitignore`` by name, not merely against effective
    ignore status: a personal ``.git/info/exclude`` or a global
    ``core.excludesFile`` would otherwise mask the loss of the committed
    entry for every clone, which is the enforcement CLAUDE.md cites.
    """
    done = subprocess.run(
        ["git", "check-ignore", "-v", "_private/probe.md"],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (
        "_private/ is no longer git-ignored, so the fallback session-document "
        "root can be committed. Restore the _private/ entry in .gitignore."
    )
    assert done.stdout.startswith(".gitignore:"), (
        f"_private/ is ignored, but by {done.stdout.strip()!r} rather than by "
        f"the committed .gitignore, so a clone would not inherit it. Restore "
        f"the _private/ entry in .gitignore."
    )


def test_no_committed_file_carries_a_machine_absolute_path() -> None:
    """The reason this is a variable at all, asserted rather than asserted-to.

    A hard-coded personal path would publish one machine's layout into a
    public repository and be wrong on every clone. That is the stated
    rationale for all three ITACA_ variables, so a literal that reappears
    should fail here rather than ship. The sweep covers every tracked
    text file, including the SRS sources, and recognizes the drive-letter,
    MSYS and POSIX-home forms.
    """
    offenders: list[str] = []
    for path in _tracked():
        full = _REPO / path
        if full.suffix.lower() in _BINARY_SUFFIXES or not full.is_file():
            continue
        for lineno, line in enumerate(
            full.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if _ABSOLUTE_PATH.search(line):
                offenders.append(f"{path}:{lineno}")
    assert not offenders, (
        f"These committed lines carry a machine-absolute path: {offenders}. This "
        f"repository is public; locate the target through an environment "
        f"variable instead, as CLAUDE.md requires."
    )


def test_every_skill_routes_through_the_single_home() -> None:
    """A skill that reaches the root must reach the rule, not guess a path.

    Written after a review found the audit skill naming the management
    root while giving no variable and no pointer, so a session invoked as
    ``/audit`` alone had nothing to resolve from and was authorized to
    create the directory it guessed at.

    Every skill is enumerated rather than listed, and the trigger is a
    family of terms rather than one phrase, because the structural cause
    was "a skill can reach the root without reaching the rule" and a
    fixed list only closes the instances someone already knew about.
    """
    claude_md = (_REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert _HEADING.search(claude_md), (
        f"CLAUDE.md has no heading {_SECTION!r}, which every skill quotes as the "
        f"home of the resolution rule. Renaming it leaves those pointers "
        f"dangling; keep the heading or update every citation."
    )
    terms = ("management root", "session document", "NEXT_SESSION", "plan ledger")
    for skill in sorted((_REPO / ".claude" / "skills").glob("*/SKILL.md")):
        text = _flat(skill.read_text(encoding="utf-8"))
        if not any(term in text for term in terms):
            continue
        assert "ITACA_MANAGEMENT_ROOT" in text and _SECTION in text, (
            f"{skill.parent.name} reaches the session documents but does not name "
            f"ITACA_MANAGEMENT_ROOT and cite {_SECTION!r}. A skill invoked on "
            f"its own would have to guess the path. Add the pointer."
        )
