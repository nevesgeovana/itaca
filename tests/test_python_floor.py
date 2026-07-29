"""Guard test for the Python version floor (REQ-83).

REQ-83 carries the language baseline in its dependency table, and four
declarations have to agree for that baseline to mean anything: the
``requires-python`` specifier, the ``Programming Language :: Python ::
X.Y`` classifiers, the ruff ``target-version``, and the lowest leg of
the CI test matrix. Nothing tied them together before, so the floor was
guarded only by accident: the REQ-105 sentinel test happened to follow
imports into the package on the oldest leg, and a refactor that stopped
importing through it would have removed the guard silently.

This module makes the floor a declared fact with one source and checks
every restatement against it. It also binds the floor to what the
library actually needs: a module that imports ``tomllib`` cannot run
below 3.11, so the floor may never drop under a version the code
already depends on.

Reading ``pyproject.toml`` needs ``tomllib``, which is exactly what the
floor now guarantees, so these checks run on every supported
interpreter with no skip.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

import itaca

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Standard-library names whose availability starts at a given minor, as
# whole modules and as symbols within a module. The floor may never fall
# below something the library already imports. Symbols matter as much as
# modules: `datetime` has existed forever and `datetime.UTC` is 3.11, so
# a module-granular map would report this library as 3.10-safe while it
# fails at import on 3.10.
STDLIB_SINCE = {
    "tomllib": (3, 11),
    "datetime.UTC": (3, 11),
    "typing.Self": (3, 11),
    "itertools.batched": (3, 12),
}


def _pyproject() -> dict[str, Any]:
    parsed: dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return parsed


def _version_range() -> tuple[tuple[int, int], tuple[int, int]]:
    """Return the (floor, exclusive ceiling) minors of ``requires-python``."""
    spec = _pyproject()["project"]["requires-python"]
    found = re.fullmatch(r">=(\d+)\.(\d+),<(\d+)\.(\d+)", spec.strip())
    assert found, (
        f"pyproject requires-python is {spec!r}, which this guard cannot read; "
        "write it as '>=MAJOR.MINOR,<MAJOR.MINOR' so the floor stays a single "
        "declared fact the classifiers, ruff target-version, and CI matrix can "
        "be checked against (REQ-83)."
    )
    low = (int(found.group(1)), int(found.group(2)))
    high = (int(found.group(3)), int(found.group(4)))
    return low, high


def _supported_minors() -> list[tuple[int, int]]:
    (major, low), (ceil_major, ceil_minor) = _version_range()
    assert major == ceil_major, (
        "pyproject requires-python spans a major version boundary; this guard "
        "enumerates minors within one major, so widen it deliberately (REQ-83)."
    )
    return [(major, minor) for minor in range(low, ceil_minor)]


def _ci_matrix_versions() -> list[tuple[int, int]]:
    """Every interpreter the CI matrix actually runs a gate on.

    Read from the parsed YAML rather than by regex over the text. CI
    calls the vendored reusable release gate, which takes ONE
    ``python-version``, so the breadth lives in a ``strategy.matrix``
    on the CALLING job and reaches the gate through ``with:``. A regex
    for an inline ``python-version: [...]`` list read the previous
    shape and saw nothing in this one, which would have removed the
    floor guard silently: exactly the accidental-guard failure this
    module's docstring exists to prevent.

    The walk is deliberately shape-agnostic. It collects every
    ``python-version`` under any ``matrix`` mapping at any depth, so a
    future move back to an inline list, or to a differently named job,
    keeps the floor guarded without another silent gap.
    """
    workflow: Any = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    found: list[str] = []

    def walk(node: Any, *, in_matrix: bool) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "python-version" and in_matrix:
                    if isinstance(value, str):
                        found.append(value)
                    elif isinstance(value, list):
                        found.extend(str(entry) for entry in value)
                walk(value, in_matrix=in_matrix or key == "matrix")
        elif isinstance(node, list):
            for entry in node:
                walk(entry, in_matrix=in_matrix)

    walk(workflow, in_matrix=False)
    assert found, (
        "the CI workflow declares no python-version anywhere under a "
        "strategy.matrix; this guard reads it to confirm the floor is "
        "actually exercised. Keep the interpreter breadth in a matrix on "
        "the job that calls the release gate (REQ-83, REQ-95)."
    )
    versions = re.findall(r"(\d+)\.(\d+)", " ".join(found))
    return [(int(major), int(minor)) for major, minor in versions]


def _library_stdlib_imports() -> dict[str, str]:
    """Map each floor-sensitive stdlib name to a file that imports it.

    Both shapes are read: ``import tomllib`` names a module, and
    ``from datetime import UTC`` names a symbol whose availability is
    later than its module's.
    """
    root = Path(itaca.__file__).parent
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        where = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                module = node.module.split(".")[0]
                names = [module]
                names.extend(f"{module}.{alias.name}" for alias in node.names)
            for name in names:
                if name in STDLIB_SINCE:
                    found.setdefault(name, where)
    return found


def test_classifiers_list_exactly_the_supported_minors() -> None:
    classifiers = _pyproject()["project"]["classifiers"]
    prefix = "Programming Language :: Python :: "
    declared = {
        tuple(int(part) for part in suffix.split("."))
        for entry in classifiers
        if (suffix := entry.removeprefix(prefix)) != entry and "." in suffix
    }
    expected = set(_supported_minors())
    assert declared == expected, (
        f"the pyproject classifiers advertise Python {sorted(declared)} while "
        f"requires-python supports {sorted(expected)}; PyPI shows the "
        "classifiers, so a stale one tells users an unsupported interpreter "
        "will work (REQ-83)."
    )


def test_ruff_target_version_matches_the_floor() -> None:
    (major, minor), _ = _version_range()
    target = _pyproject()["tool"]["ruff"]["target-version"]
    expected = f"py{major}{minor}"
    assert target == expected, (
        f"[tool.ruff] target-version is {target!r} but the requires-python "
        f"floor is {major}.{minor}, so pyupgrade rewrites and syntax checks "
        f"run against the wrong baseline; set it to {expected!r} (REQ-80, "
        "REQ-83)."
    )


def test_ci_matrix_exercises_the_floor_and_nothing_below_it() -> None:
    floor, _ = _version_range()
    supported = set(_supported_minors())
    matrix = _ci_matrix_versions()
    assert floor in matrix, (
        f"the CI test matrix runs {matrix} and never {floor[0]}.{floor[1]}, "
        "the declared floor; the oldest supported interpreter is the one that "
        "breaks on new syntax, so it is the leg that must run (REQ-83, "
        "REQ-95)."
    )
    outside = sorted(version for version in matrix if version not in supported)
    assert not outside, (
        f"the CI test matrix runs {outside}, which requires-python does not "
        "support; a green leg on an unsupported interpreter is not evidence "
        "about anything the package promises (REQ-83)."
    )


def test_floor_covers_every_stdlib_name_the_library_imports() -> None:
    floor, _ = _version_range()
    found = _library_stdlib_imports()
    assert found, (
        "the stdlib import walk found nothing, so the check below cannot "
        "fail; the library imports at least tomllib and datetime.UTC "
        "(REQ-83)."
    )
    offenders = [
        f"{name} (first shipped in {since[0]}.{since[1]}, imported by {where})"
        for name, where in sorted(found.items())
        if (since := STDLIB_SINCE[name]) > floor
    ]
    assert not offenders, (
        f"the requires-python floor is {floor[0]}.{floor[1]} but library code "
        f"imports {offenders}; the package would install on an interpreter "
        "where it cannot import, so raise the floor or drop the import "
        "(REQ-83)."
    )
