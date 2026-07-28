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


def test_m0_target_version() -> None:
    # DD-21: M0 ships as v0.1.0.
    assert itc.__version__.startswith("0.1.0")


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
