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
BANNED_TOP_LEVEL = {"xarray", "dask", "pandas"}
ORACLE_ONLY = {"scipy", "uncertainties"}

EXEMPT_PACKAGES = frozenset({"io", "utils"})
"""Library packages the NumPy-only ban does not cover (REQ-05, REQ-84)."""

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
    """The discovered packages the NumPy-only ban covers."""
    return tuple(name for name in library_packages() if name not in EXEMPT_PACKAGES)


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


def test_the_two_exemption_declarations_agree() -> None:
    declared = _exempt_packages_in_pyproject()
    assert declared == set(EXEMPT_PACKAGES), (
        f"the ruff per-file-ignores exempt the itaca package(s) "
        f"{sorted(declared)} from {TID251} while this guard exempts "
        f"{sorted(EXEMPT_PACKAGES)}. Only library package keys are compared: "
        "per-file-ignores also exempts tests/**, which is not a package this "
        "guard walks, so that key is excluded rather than counted as a "
        "disagreement. Move both sides together, or the belt and the braces "
        "stop covering the same packages (REQ-82, DD-02)."
    )


def test_every_exempt_package_exists() -> None:
    unknown = sorted(EXEMPT_PACKAGES - set(library_packages()))
    assert not unknown, (
        f"the NumPy-only exemption names package(s) {unknown} that do not "
        "exist under itaca/; an exemption for a package that was renamed or "
        "removed silently exempts nothing and hides the rename (REQ-82)."
    )


def test_numpy_only_rule() -> None:
    offenders = _offenders(restricted_packages(), BANNED_TOP_LEVEL)
    assert not offenders, (
        f"NumPy-only rule violated (REQ-82) in {restricted_packages()}: {offenders}"
    )


def test_dev_only_oracles_barred_from_library() -> None:
    # scipy and uncertainties are dev-only test oracles (DD-25, DD-26):
    # never imported by any library package, including io/ and utils/.
    offenders = _offenders(library_packages(), ORACLE_ONLY)
    assert not offenders, f"dev-only oracle imported by library (DD-25/26): {offenders}"
