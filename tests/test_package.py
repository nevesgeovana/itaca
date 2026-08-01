"""Phase 0 usage example and package skeleton tests (M0, SRS Chapter 10).

Usage example (the contract under test)::

    import itaca as itc

    print(itc.__version__)
"""

import re

import itaca as itc


def test_import_convention() -> None:
    assert itc.__name__ == "itaca"


def test_axis_is_top_level() -> None:
    # Q-013.1: itc.Axis is exported so register_axis has a reachable type.
    assert "Axis" in itc.__all__
    assert itc.Axis is not None


def test_version_is_semver() -> None:
    # REQ-92: semantic versioning; dev suffix allowed before release.
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+)?", itc.__version__)


def _is_a_source_checkout() -> bool:
    """Whether `itaca` is imported from the repository rather than an install."""
    from pathlib import Path

    return (Path(itc.__file__).resolve().parents[1] / "pyproject.toml").is_file()


def test_itaca_004_the_version_is_the_one_the_build_wrote() -> None:
    """`ITACA-004`: the code's version is what a BUILD recorded, not a literal.

    This asserts the IDENTITY, not a literal. A literal is what the
    finding was: `version.py` pinned `0.1.0` while the tree carried the
    whole M1 seam, so an sdist built from it was named
    `itaca-0.1.0.tar.gz` and Provenance recorded a false statement about
    which implementation produced a result. Pinning another literal here
    would reintroduce exactly the hand-maintained fact that went stale.

    It used to say `itc.__version__ == importlib.metadata.version(...)`,
    and that was FND-046's fourth face, found when the resolver stopped
    reading the metadata first (DD-48). Both sides are written by a
    build, but by DIFFERENT builds: the version file by every build of
    this tree, the distribution metadata only by `pip install -e .`. In
    an editable checkout they drift apart by construction, so that
    equality made the commit gate go red on a correct tree, which is the
    same tax FND-046 charged the push gate one tier up.

    So the equality is asserted against whichever generated source the
    resolver actually consults, and the cross-source agreement is
    asserted only where one build wrote both, which is any install that
    is not a source checkout. Where it is relaxed, it is relaxed because
    DD-48 names that drift as the residual it did not close, not because
    the assertion was inconvenient.

    Whether the derived version correctly identifies the COMMIT is a
    different question, and it is answered by the vendored
    `check_version_identity.py` in the release gate's identity job,
    which runs against full history. This test runs in the gates job,
    whose checkout is shallow and carries no tags, so it deliberately
    asserts only what is true there.
    """
    from importlib.metadata import version

    try:
        from itaca.core._version import __version__ as written
    except ImportError:
        written = None

    if written is not None:
        assert itc.__version__ == written, (
            f"itc.__version__ is {itc.__version__} and the generated version "
            f"file says {written}; the resolver reads that file first (DD-48), "
            f"so these cannot differ unless something else is answering."
        )
    else:
        assert itc.__version__ == version("itaca")

    if not _is_a_source_checkout():
        assert written is None or written == version("itaca"), (
            f"this is an installed distribution, so one build wrote both the "
            f"version file ({written}) and the distribution metadata "
            f"({version('itaca')}), and they disagree."
        )


def test_itaca_004_the_version_is_not_a_literal_in_the_source() -> None:
    """The structural half: nothing may hand-write a version string.

    A guard rather than a behavior test. The defect recurs the moment
    someone restores a literal, and detection after the fact is what
    DD-38 rejected in favor of derivation.
    """
    import ast
    from pathlib import Path

    import itaca

    # The AST, not the text: this module's own docstring quotes the old
    # `__version__ = "0.1.0"` line to explain the defect, and a
    # substring search would read that prose as the defect returning.
    source = (Path(itaca.__file__).parent / "core" / "version.py").read_text(
        encoding="utf-8"
    )
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "__version__" in names and isinstance(node.value, ast.Constant):
            raise AssertionError(
                f"itaca/core/version.py assigns the literal "
                f"{node.value.value!r} to __version__ again. The version is "
                f"derived from the repository by setuptools-scm (DD-38); a "
                f"literal cannot be bumped without a window in which the "
                f"tree is wrong, which is ITACA-004."
            )


def test_subpackages_importable() -> None:
    # Discovered, not enumerated: a package added later was named in no
    # list and this check silently stopped covering it (DD-33).
    import importlib
    from pathlib import Path

    import itaca

    root = Path(itaca.__file__).parent
    names = sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (entry / "__init__.py").is_file()
    )
    assert {"core", "io", "ops", "pproc", "uncertainty", "utils"} <= set(names), (
        f"the subpackage walk found {names}; it is the input to this check, "
        "so an empty or broken walk would pass it while importing nothing."
    )
    for pkg in (importlib.import_module(f"itaca.{name}") for name in names):
        assert pkg.__doc__, f"{pkg.__name__} must carry a module docstring"
