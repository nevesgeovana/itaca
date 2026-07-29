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


def test_itaca_004_the_version_is_the_installed_distribution_version() -> None:
    """`ITACA-004`: the code's version and the artifact's must be one fact.

    This asserts the IDENTITY, not a literal. A literal is what the
    finding was: `version.py` pinned `0.1.0` while the tree carried the
    whole M1 seam, so an sdist built from it was named
    `itaca-0.1.0.tar.gz` and Provenance recorded a false statement about
    which implementation produced a result. Pinning another literal here
    would reintroduce exactly the hand-maintained fact that went stale.

    Whether the derived version correctly identifies the COMMIT is a
    different question, and it is answered by the vendored
    `check_version_identity.py` in the release gate's identity job,
    which runs against full history. This test runs in the gates job,
    whose checkout is shallow and carries no tags, so it deliberately
    asserts only what is true there.
    """
    from importlib.metadata import version

    assert itc.__version__ == version("itaca")


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
