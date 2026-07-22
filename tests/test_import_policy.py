"""Guard test for the NumPy-only rule (REQ-82, DD-02).

core/, ops/, and uncertainty/ import only NumPy and the standard
library. xarray, dask, and pandas are barred, at module level and
inside functions alike. This test complements the ruff TID251 rule so
the policy holds even if the lint configuration regresses.
"""

import ast
from pathlib import Path

import itaca

BANNED_TOP_LEVEL = {"xarray", "dask", "pandas"}
RESTRICTED_PACKAGES = ("core", "ops", "uncertainty")


def _imported_top_level_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_restricted_packages_exist() -> None:
    root = Path(itaca.__file__).parent
    for pkg in RESTRICTED_PACKAGES:
        assert (root / pkg / "__init__.py").is_file(), f"missing package: {pkg}"


def test_numpy_only_rule() -> None:
    root = Path(itaca.__file__).parent
    offenders: list[str] = []
    for pkg in RESTRICTED_PACKAGES:
        for path in sorted((root / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            banned = _imported_top_level_names(tree) & BANNED_TOP_LEVEL
            offenders.extend(f"{path.name}: {name}" for name in sorted(banned))
    assert not offenders, f"NumPy-only rule violated (REQ-82): {offenders}"
