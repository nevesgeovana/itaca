"""Guard test for the NumPy-only rule (REQ-82, DD-02).

The library packages import only NumPy and the standard library.
xarray, dask, and pandas are barred, at module level and inside
functions alike, everywhere except ``io/`` and ``utils/``, which may
use pandas lazily (REQ-05, REQ-84). This test complements the ruff
TID251 rule so the policy holds even if the lint configuration
regresses.

Packages are discovered by walking, not enumerated. They used to be
listed in two literal tuples, which meant a package added later was
named in neither and the AST guard silently stopped covering the newest
part of the library, in exactly the case its own docstring says it
exists for. Discovery removes that: a new package is restricted by
default on both sides, the ruff half because the ban is repository-wide
with per-file exemptions, and this half because the walk finds it.

The two exemption declarations are checked against each other rather
than retyped, so a package exempted in one and not the other goes red.
They are compared on library package keys only: ``per-file-ignores``
also exempts ``tests/**``, which is not a package this guard walks, so
plain set equality would fail on a correct configuration.
"""

import ast
import tomllib
from pathlib import Path

import itaca

# The NumPy-only rule bars xarray/dask/pandas from library code. scipy
# and uncertainties are dev-only test oracles (DD-25, DD-26): barred
# from ALL library code, allowed only under tests/oracle/.
ALWAYS_BANNED = {"xarray", "dask"}
"""Barred from EVERY library package, with no exception anywhere."""

PANDAS = {"pandas"}
ORACLE_ONLY = {"scipy", "uncertainties"}

PANDAS_EXEMPT_PACKAGES = frozenset({"io", "utils"})
"""Packages REQ-82 licenses to import pandas LAZILY (REQ-05, REQ-84).

The xarray and dask ban is not narrowed by this set. Exempting these
packages from the whole banned list was measured to let `import xarray`
and `import dask` through both enforcement layers (ITACA-013), which is
broader than the licence REQ-82 actually grants.
"""

# Packages known to exist. Not the list the guards walk: it is a floor
# under the walk, so a discovery that silently returns nothing fails
# instead of passing every check vacuously.
KNOWN_PACKAGES = frozenset({"core", "io", "ops", "pproc", "uncertainty", "utils"})

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
TID251 = "TID251"


def library_packages() -> tuple[str, ...]:
    """Every package under ``itaca/``, discovered by walking."""
    root = Path(itaca.__file__).parent
    return tuple(
        sorted(
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and (entry / "__init__.py").is_file()
        )
    )


def restricted_packages() -> tuple[str, ...]:
    """The discovered packages the PANDAS exemption does not cover."""
    return tuple(
        name for name in library_packages() if name not in PANDAS_EXEMPT_PACKAGES
    )


def _exempt_packages_in_pyproject() -> set[str]:
    """Library packages ``per-file-ignores`` exempts from TID251.

    Keys outside ``itaca/`` are not packages this guard walks and are
    excluded here rather than compared: ``tests/**`` is exempt in ruff
    and has no counterpart on this side.
    """
    parsed = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    ignores = parsed["tool"]["ruff"]["lint"]["per-file-ignores"]
    exempt = set()
    for pattern, rules in ignores.items():
        parts = pattern.split("/")
        if parts[0] == "itaca" and len(parts) > 1 and TID251 in rules:
            exempt.add(parts[1])
    return exempt


def _imported_top_level_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _sources(packages: tuple[str, ...]) -> list[Path]:
    """Every module the given packages cover, plus the package root.

    Modules sitting directly under ``itaca/`` belong to no subpackage
    and were covered by neither half of this guard while the ruff ban
    (repository-wide) covered them. Composing paths from a package list
    alone reproduced in miniature the enumeration defect the walk was
    written to remove, so the root is walked as its own unit and is
    never exempt: it is the package's own namespace.
    """
    root = Path(itaca.__file__).parent
    found = list(root.glob("*.py"))
    found.extend(
        path for package in packages for path in (root / package).rglob("*.py")
    )
    return sorted(found)


def _offenders(packages: tuple[str, ...], banned: set[str]) -> list[str]:
    root = Path(itaca.__file__).parent
    offenders: list[str] = []
    for path in _sources(packages):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = _imported_top_level_names(tree) & banned
        offenders.extend(
            f"{path.relative_to(root).as_posix()}: {name}" for name in sorted(hits)
        )
    return offenders


def test_discovery_finds_every_known_package() -> None:
    discovered = set(library_packages())
    missing = sorted(KNOWN_PACKAGES - discovered)
    assert not missing, (
        f"the package walk found {sorted(discovered)} and missed {missing}; "
        "the guards below walk what it returns, so a broken walk would pass "
        "them all while checking nothing (REQ-82)."
    )


def test_itaca_013_no_library_package_is_exempt_wholesale() -> None:
    """The ruff exemption may no longer be granted per package.

    A package-wide TID251 exemption licenses every banned import in that
    package, not only the one REQ-82 allows. Measured before the fix, by
    mutation: `import xarray` and `import dask` added to `itaca/io/`
    passed ruff AND passed the AST guard below, because both layers
    exempted the PACKAGE rather than the import (ITACA-013).
    """
    declared = _exempt_packages_in_pyproject()
    assert not declared, (
        f"pyproject per-file-ignores exempts the itaca package(s) "
        f"{sorted(declared)} from {TID251} wholesale. REQ-82 licenses "
        "pandas lazily in io/ and utils/; it licenses nothing else, and no "
        "package is exempt from the xarray and dask ban. Grant the "
        "exemption at the import site with a targeted `# noqa: TID251` "
        "instead (REQ-82, DD-02, DD-33)."
    )


def test_every_exempt_package_exists() -> None:
    unknown = sorted(PANDAS_EXEMPT_PACKAGES - set(library_packages()))
    assert not unknown, (
        f"the NumPy-only exemption names package(s) {unknown} that do not "
        "exist under itaca/; an exemption for a package that was renamed or "
        "removed silently exempts nothing and hides the rename (REQ-82)."
    )


def test_itaca_013_xarray_and_dask_are_barred_from_every_package() -> None:
    """No package, not even io/ or utils/, may import xarray or dask.

    This is the half the wholesale exemption opened. REQ-82's exception
    clause licenses pandas and nothing else, so this ban is walked over
    EVERY discovered package rather than over the restricted subset.
    """
    offenders = _offenders(library_packages(), ALWAYS_BANNED)
    assert not offenders, (
        f"xarray or dask imported by library code (REQ-82, DD-33): "
        f"{offenders}. The pandas exception does not extend to them in "
        "any package."
    )


def test_numpy_only_rule() -> None:
    offenders = _offenders(restricted_packages(), PANDAS)
    assert not offenders, (
        f"pandas imported outside {sorted(PANDAS_EXEMPT_PACKAGES)} "
        f"(REQ-82) in {restricted_packages()}: {offenders}"
    )


def test_dev_only_oracles_barred_from_library() -> None:
    # scipy and uncertainties are dev-only test oracles (DD-25, DD-26):
    # never imported by any library package, including io/ and utils/.
    offenders = _offenders(library_packages(), ORACLE_ONLY)
    assert not offenders, f"dev-only oracle imported by library (DD-25/26): {offenders}"
