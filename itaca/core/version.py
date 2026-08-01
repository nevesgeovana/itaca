"""Version identity for ITACA (REQ-92, DD-21, DD-38).

The version is DERIVED FROM THE REPOSITORY, not written here. A commit
carrying the release tag ``vX.Y.Z`` builds as exactly ``X.Y.Z``; every
other commit builds as ``X.Y.Z.devN``, naming the release being worked
toward, with ``N`` the number of commits since the last release tag.
``setuptools-scm`` computes it at build time and this module reads it
back from the installed distribution.

Why it is no longer a literal. Until 0.2.0 this module held
``__version__ = "0.1.0"`` and every M1 commit inherited it, so an sdist
built from the seam was named ``itaca-0.1.0.tar.gz`` while containing
``Pipeline`` and the whole ``pproc`` package, and Provenance recorded a
false statement about which implementation produced a result
(``ITACA-004``). A hand-maintained literal also cannot be bumped
without a window in which the tree is wrong: the version-bump commit
must be pushed before its tag, and a final version on an untagged
commit is refused, so the branch would go red between the two pushes.
Deriving from the repository removes both, structurally.

There is no third fallback. A version that cannot be resolved is not
guessed, because the guess would be stamped into Provenance and into
``.itc`` archives as though it were a fact. A NULL is not a permitted
answer either, and for the same reason: it is not even wrong.

Why the version file is read before the distribution metadata (FND-046).
``importlib.metadata`` locates a distribution by scanning ``sys.path``
for ``*.egg-info`` and ``*.dist-info`` directories, and the working
directory is on ``sys.path``. Every in-tree build writes an
``itaca.egg-info/`` into the repository root, so the same interpreter at
the same commit reported ``9.9.9.dev99`` from one directory and
``0.3.0.dev24`` from another: a build artifact was deciding what the
library says about itself. ``itaca/core/_version.py`` is
``setuptools-scm``'s ``version_file``; it is written by the same build
that writes the distribution metadata, it ships INSIDE the built wheel,
and it is found by IMPORT rather than by a path scan, so there is
exactly one of it and the working directory cannot choose between
copies.

What this does not change is staleness. In an editable checkout the
version file is as old as the last build of that checkout. That is a
stale but VALID version, which is the distinction that matters: a stale
version is a true statement about an earlier tree. Resolving from git at
import time was measured and rejected (DD-48).
"""

from __future__ import annotations

from itaca.core.errors import VersionResolutionError


def _from_version_file() -> str | None:
    """Return the version ``setuptools-scm`` wrote into the package.

    Gitignored, because it is generated, so a clone that has never been
    built does not have it and this returns ``None``.
    """
    try:
        from itaca.core._version import __version__ as built
    except ImportError:
        return None
    return str(built) or None


def _from_distribution_metadata() -> str | None:
    """Return the installed distribution's version, if one can be read.

    Returns ``None`` rather than raising for BOTH ways this can fail:
    no distribution at all, and a distribution whose metadata parses and
    carries no ``Version:`` field. The second returns ``None`` from
    ``version()`` at runtime while typeshed declares ``str``, so
    ``mypy --strict`` cannot see it and only this guard can.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        found: str | None = version("itaca")
    except PackageNotFoundError:
        return None
    return found or None


def _resolve() -> str:
    """Return the version the build recorded, or fail loud."""
    resolved = _from_version_file() or _from_distribution_metadata()
    if resolved is None:
        raise VersionResolutionError(
            "itaca.core.version",
            "neither the generated version file nor the installed "
            "distribution metadata for itaca yielded a version, so nothing "
            "can be stamped into Provenance or a .itc archive",
            "install the package with pip install -e . so the version is "
            "derived from the repository tag; a source tree that was never "
            "installed has no version to report (REQ-92)",
        )
    return resolved


__version__ = _resolve()
