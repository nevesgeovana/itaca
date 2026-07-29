"""Identifiers that must not travel to a user's machine, and the scan.

One rule, one implementation, two boundaries. ``tests/test_house_style.py``
scans the source tree on every run, and ``tests/test_release_integrity.py``
scans the BUILT wheel and sdist, because a source scan's notion of what
ships is a judgement while the artifact is the ground truth.

The first version of this guard scanned ``itaca/`` alone, reasoning that
the wheel is what reaches a user. An sdist built from that same commit
carried 241 entries, including ``tests/``, ``docs/``, ``.claude/`` and
``CLAUDE.md``, because setuptools-scm's file finder places every tracked
file into the sdist; the exact identifier pair the commit had just
removed from a docstring was still live three directories away, and
``pip download itaca --no-binary :all:`` would have delivered it. The
measurement beat the reasoning, which is why the artifact boundary
exists and why the source boundary no longer stops at the package.

Authorship is deliberate and is not what this forbids. The library is
published under the author's own name, so ``LICENSE``, ``CITATION.cff``,
``README.md``, ``CHANGELOG.md``, ``CLAUDE.md``, ``pyproject.toml`` and
``docs/`` carry it by decision (DD-41), and the wheel's ``METADATA``, the
sdist's ``PKG-INFO`` and the vendored license copy are derived from
those, which is why they are recognized by basename. What must not
travel is an identifier anywhere else.

This is a denylist and catches only the tokens listed. A colleague's
name, a second institution or a personal filesystem path passes; a new
identifier is a new entry, added the moment it is noticed rather than
after it ships. Two consequences worth knowing before editing it. The
institution token is assembled from code points, so this file does not
itself carry the string it forbids, and the trailing ``\\w*`` on the
names is deliberate: without it the author's own commit-trailer email
slipped through, because a word boundary does not fall between the
given name and the digits that follow it. A surname is also a citation
risk: if a docstring ever cites a paper by an author of that name, the
right move is to widen this file with the exemption stated, not to drop
the citation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# "tudelft", built from code points for the reason given above. The
# pattern below accepts the spaced and hyphenated spellings too, which
# is how it appears in prose rather than in an address.
_INSTITUTION = "".join(map(chr, (116, 117, 100, 101, 108, 102, 116)))

FORBIDDEN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgeovana\w*", re.IGNORECASE), "the author's given name"),
    (re.compile(r"\bneves\w*", re.IGNORECASE), "the author's family name"),
    (
        re.compile(rf"\b{_INSTITUTION[:2]}[ _-]?{_INSTITUTION[2:]}\b", re.IGNORECASE),
        "an institution name",
    ),
)

#: Files whose identifier is authorship, recorded by decision (DD-41).
AUTHORSHIP_PATHS = frozenset(
    {
        "LICENSE",
        "CITATION.cff",
        "README.md",
        "CHANGELOG.md",
        "CLAUDE.md",
        "pyproject.toml",
    }
)

#: This file, which must spell two of the tokens to match them. It is
#: exempt as the RULE and not as authorship, and it is the only such
#: exemption: the test module that exercises the rule builds its samples
#: from code points instead, so a mutation there cannot hide behind an
#: exemption.
RULE_PATHS = frozenset({"tests/identifiers.py"})

#: Trees whose identifier is authorship. The SRS title page and the
#: decision, question and plan logs name who decided what, which is the
#: record itself and not an incidental appearance.
AUTHORSHIP_TREES = ("docs/",)

#: Build output derives its metadata from the files above and renames it,
#: so the derived copies are recognized wherever the packaging tool puts
#: them: ``itaca-<v>.dist-info/METADATA`` in the wheel, ``PKG-INFO`` at
#: the sdist root and under ``itaca.egg-info/``, and the license copy
#: under ``.dist-info/licenses/``.
AUTHORSHIP_BASENAMES = frozenset({"METADATA", "PKG-INFO", "LICENSE"})


def is_authorship(relpath: str) -> bool:
    """Whether this path carries the author's name by deliberate decision.

    Parameters
    ----------
    relpath : str
        Path relative to the repository root or to the artifact root,
        in either separator.

    Returns
    -------
    bool
        True when the path is exempt.
    """
    posix = relpath.replace("\\", "/")
    if posix in AUTHORSHIP_PATHS or posix in RULE_PATHS:
        return True
    if posix.startswith(AUTHORSHIP_TREES):
        return True
    return posix.rsplit("/", 1)[-1] in AUTHORSHIP_BASENAMES


def offenders(items: Iterable[tuple[str, bytes]]) -> list[str]:
    """Report every forbidden identifier as ``path:line: label``.

    Takes ``(path, content)`` pairs rather than a directory, so one
    implementation serves a filesystem walk and an archive without
    either boundary re-deriving the rule.

    Parameters
    ----------
    items : iterable of (str, bytes)
        Path relative to the scanned root, and the file's bytes.

    Returns
    -------
    list of str
        One entry per offending line and label, in the order scanned.

    Examples
    --------
    >>> offenders([("itaca/core/thing.py", b"# reviewed by Geovana")])
    ["itaca/core/thing.py:1: the author's given name"]
    >>> offenders([("LICENSE", b"Copyright (c) 2026 Geovana Neves")])
    []
    """
    found: list[str] = []
    for relpath, content in items:
        if is_authorship(relpath):
            continue
        if b"\x00" in content[:8192]:
            continue  # binary; a compiled or image payload, not prose
        for lineno, line in enumerate(
            content.decode("utf-8", errors="ignore").splitlines(), start=1
        ):
            for pattern, label in FORBIDDEN:
                if pattern.search(line):
                    found.append(f"{relpath}:{lineno}: {label}")
    return found


#: The remedy, worded once so both boundaries say the same thing.
REMEDY = (
    "state the fact without the name (an SRS, DD or OQ id is what a "
    "reader can follow), and use a neutral example identity"
)
