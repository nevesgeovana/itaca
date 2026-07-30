"""CLAUDE.md's session-document root resolution, as code, in one home.

This is the rule in CLAUDE.md, "Where the session documents live", and
nothing else. It lives in a plain helper module rather than inside
``tests/test_management_root.py`` because two test modules need the answer,
and a test module imported as a library makes another module's NAME part of
the suite's internal API: renaming or splitting the guard file would then
break an unrelated test. ``tests/identifiers.py`` is the precedent, extracted
for the same reason.

The alternative, letting each caller re-derive the root, is the one thing
that must not happen. A second copy of a resolution rule is how the two
drift, and the rule has three branches whose differences are the whole
point: unset falls back, set-but-invalid stops, and only one of the two
"nothing is configured" readings is legitimate.
"""

from __future__ import annotations

from pathlib import Path

#: Subdirectories or files whose presence means ``_private/`` still holds the
#: session documents, so the unset fallback is the pre-migration layout
#: rather than a hollow tree.
ROOT_MARKERS = ("plan", "handoffs", "inbox", "NEXT_SESSION.md")


class ManagementRootError(RuntimeError):
    """A configuration error in locating the session-document root."""


def is_itacas(root: Path) -> bool:
    """Whether a directory is itaca's management root, not a sibling's.

    Existence is not identity: the sibling projects sit under one parent,
    so the marker is the ledger README's own heading, anchored rather than
    matched anywhere in the file, since a sister README could mention the
    ITACA ledger in a cross-reference.
    """
    marker = root / "plan" / "README.md"
    if not marker.is_file():
        return False
    for line in marker.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            return "ITACA plan ledger" in line
    return False


def holds_documents(fallback: Path) -> bool:
    """Whether ``_private/`` still holds session documents.

    Not "is non-empty": ``_private/`` is also documented as local staging for
    proprietary material, so one staged file must not be mistaken for the
    pre-migration layout.
    """
    return fallback.is_dir() and any((fallback / m).exists() for m in ROOT_MARKERS)


def resolve_management_root(configured: str | None, *, repo: Path) -> tuple[Path, str]:
    """Resolve the management root, or raise with a three-part message.

    Returns the root and which branch produced it, ``"variable"`` or
    ``"fallback"``, because a resolution that is never announced cannot be
    noticed when it is wrong.

    Parameters
    ----------
    configured
        The value of ``ITACA_MANAGEMENT_ROOT``, or None when unset.
    repo
        The repository root, holding the ``_private/`` fallback.

    Returns
    -------
    tuple of (Path, str)
        The resolved root, and the branch that produced it.

    Raises
    ------
    ManagementRootError
        When the configured root does not exist, is not itaca's, or when the
        variable is unset and the fallback holds no session documents.

    Examples
    --------
    >>> resolve_management_root(None, repo=Path("/nowhere"))
    Traceback (most recent call last):
    ManagementRootError: ...
    """
    if configured:
        root = Path(configured)
        if not root.is_dir():
            raise ManagementRootError(
                f"ITACA_MANAGEMENT_ROOT is set to {root}, which is not a "
                f"directory; session documents cannot be written; set it to "
                f"the itaca management root, or unset it to use _private/."
            )
        if not is_itacas(root):
            raise ManagementRootError(
                f"ITACA_MANAGEMENT_ROOT is set to {root}, whose plan/README.md "
                f"is missing or does not name the ITACA plan ledger, so it is "
                f"not itaca's management root; session documents would go to "
                f"another project; point it at the itaca management root, or "
                f"restore that README's heading if it was retitled."
            )
        return root, "variable"

    fallback = repo / "_private"
    if not holds_documents(fallback):
        raise ManagementRootError(
            f"ITACA_MANAGEMENT_ROOT is unset and {fallback} holds no session "
            f"documents; writing them there would put them where nobody reads "
            f"them; set ITACA_MANAGEMENT_ROOT to the management root."
        )
    return fallback, "fallback"
