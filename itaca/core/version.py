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
``.itc`` archives as though it were a fact.
"""

from __future__ import annotations

from itaca.core.errors import VersionResolutionError


def _resolve() -> str:
    """Return the version the build recorded, or fail loud."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("itaca")
    except PackageNotFoundError:
        pass
    try:
        # Written by setuptools-scm at build time. Reached when the
        # distribution metadata is unavailable but the tree was built.
        # Gitignored, because it is generated.
        from itaca.core._version import __version__ as built
    except ImportError:
        raise VersionResolutionError(
            "itaca.core.version",
            "the installed distribution metadata for itaca could not be "
            "read, so no version can be stamped into Provenance or a .itc "
            "archive",
            "install the package with pip install -e . so the version is "
            "derived from the repository tag; a source tree that was never "
            "installed has no version to report (REQ-92)",
        ) from None
    return str(built)


__version__ = _resolve()
