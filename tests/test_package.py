"""Phase 0 usage example and package skeleton tests (M0, SRS Chapter 10).

Usage example (the contract under test)::

    import itaca as itc

    print(itc.__version__)
"""

import re

import itaca as itc


def test_import_convention() -> None:
    assert itc.__name__ == "itaca"


def test_version_is_semver() -> None:
    # REQ-92: semantic versioning; dev suffix allowed before release.
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+)?", itc.__version__)


def test_m0_target_version() -> None:
    # DD-21: M0 ships as v0.1.0.
    assert itc.__version__.startswith("0.1.0")


def test_subpackages_importable() -> None:
    import itaca.core
    import itaca.io
    import itaca.ops
    import itaca.uncertainty
    import itaca.utils

    for pkg in (itaca.core, itaca.io, itaca.ops, itaca.uncertainty, itaca.utils):
        assert pkg.__doc__, f"{pkg.__name__} must carry a module docstring"
