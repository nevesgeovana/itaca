"""Identifiers that must not travel to a user's machine, and the scan.

The rule, its authority and the measurement that shaped it are recorded
in DD-41; this module is its implementation and carries only the notes
an editor of this file needs.

One rule, one implementation, two boundaries: ``tests/test_house_style``
scans the repository, and ``tests/test_release_integrity`` scans the
built wheel and sdist. Both import this module by bare name, which works
for the same reason ``from conftest import child_env`` does: pytest's
default prepend import mode puts ``tests/`` on ``sys.path``. A module in
a subdirectory must take a fixture instead, as ``conftest`` provides for
``child_env``.

Three notes on the patterns, each of which cost a measurement:

* Every token is assembled from code points, so this file does not carry
  any of the strings it forbids. An earlier version spelled two of them
  and exempted itself, which made the rule file the one file in the
  repository able to defeat the rule, and put both names into every
  sdist. There is now no exemption for this file and none is needed.
* The trailing ``\\w*`` on the names is deliberate: without it the
  author's own commit-trailer email slipped through, because no word
  boundary falls between the given name and the characters that follow
  it in an email local part. The LEADING side is deliberately NOT
  widened: a leading ``\\w*`` would match the surname inside ordinary
  words, and the measured need was the trailing side alone. A login
  formed from an initial followed by the surname is therefore missed,
  and widening the token set is the author's call rather than this
  file's.
* An email-SHAPED rule was measured and rejected. The package documents
  its default identity as ``user@hostname`` in three places and uses
  ``u@h`` in an example, so shape matching false-positives; and the
  occurrence that started this had no dot in its domain, so the usual
  pattern would have missed the very case it was written for.

This is a denylist and catches only the tokens listed. A colleague's
name, a second institution or a personal filesystem path passes; a new
identifier is a new entry, added the moment it is noticed rather than
after it ships. A surname is also a citation risk: if a docstring ever
cites a paper by an author of that name, the right move is to widen this
file with the exemption stated, not to drop the citation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Assembled from code points for the reason given above. In order: the
# author's given name, her family name, and the institution, whose
# pattern accepts the spaced and hyphenated spellings that appear in
# prose as well as the run-together form that appears in an address.
_GIVEN = "".join(map(chr, (103, 101, 111, 118, 97, 110, 97)))
_FAMILY = "".join(map(chr, (110, 101, 118, 101, 115)))
_INSTITUTION = "".join(map(chr, (116, 117, 100, 101, 108, 102, 116)))

FORBIDDEN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"\b{_GIVEN}\w*", re.IGNORECASE), "the author's given name"),
    (re.compile(rf"\b{_FAMILY}\w*", re.IGNORECASE), "the author's family name"),
    (
        re.compile(rf"\b{_INSTITUTION[:2]}[ _-]?{_INSTITUTION[2:]}\b", re.IGNORECASE),
        "an institution name",
    ),
)

#: Files whose identifier is authorship, recorded by decision (DD-41).
#: This is the whole exemption set, together with the derived metadata
#: below; there is no other way for a path to be exempt.
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

#: Trees whose content is the decision record itself: the SRS, the
#: decision log, the question log and the execution plans all name who
#: decided what, which is what they are for.
AUTHORSHIP_TREES = ("docs/",)

#: Build output derives its metadata from the files above and renames
#: it. Matched by SHAPE rather than by basename, so that a stray
#: ``itaca/core/LICENSE`` or ``tests/data/PKG-INFO`` is guarded like any
#: other file instead of being exempted by its name alone.
_DERIVED_METADATA = (
    re.compile(r"PKG-INFO"),
    re.compile(r"[^/]+\.egg-info/PKG-INFO"),
    re.compile(r"[^/]+\.dist-info/METADATA"),
    re.compile(r"[^/]+\.dist-info/licenses/.+"),
)


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

    Examples
    --------
    >>> is_authorship("LICENSE"), is_authorship("docs/DECISIONS.md")
    (True, True)
    >>> is_authorship("itaca-0.2.0.dist-info/METADATA")
    True
    >>> is_authorship("itaca/core/LICENSE")
    False
    """
    posix = relpath.replace("\\", "/")
    if posix in AUTHORSHIP_PATHS or posix.startswith(AUTHORSHIP_TREES):
        return True
    return any(pattern.fullmatch(posix) for pattern in _DERIVED_METADATA)


def offenders(items: Iterable[tuple[str, bytes]]) -> list[str]:
    """Report every forbidden identifier as ``path:line: label``.

    Takes ``(path, content)`` pairs rather than a directory, so one
    implementation serves a filesystem walk and an archive without
    either boundary re-deriving the rule.

    A payload holding a NUL byte early is skipped as binary. That is a
    known limit rather than an oversight: ``.itc`` is a ZIP and carries
    a user identity by design, so a committed archive fixture would pass
    both boundaries. Nothing tracked is in that shape today.

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
    >>> offenders([("itaca/core/thing.py", b"# an author call at B1")])
    []
    >>> offenders([("itaca/core/thing.py", b"# see Section 4.5")])
    []
    """
    found: list[str] = []
    for relpath, content in items:
        if is_authorship(relpath):
            continue
        if b"\x00" in content[:8192]:
            continue
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
