"""Tooling-config guard: local hooks and CI run the same ruff (REQ-96).

REQ-80 owns lint and format; REQ-96 promises the pre-commit hooks are a
local mirror of the CI lint job. Three declarations have to agree for
that to be true, and each is checked here: the ruff pinned in the
``[dev]`` extra, the ruff-pre-commit ``rev`` (whose ``vX.Y.Z`` tag
installs ``ruff==X.Y.Z``), and the ruff actually importable in the
environment running this suite. Agreeing on a version is not enough, so
both sides of the mirror are checked too: the CI lint job still runs
both ruff commands, and the hooks still declare both ruff ids with
nothing narrowing what they read. A hook that lints nothing is the same
divergence wearing a matching version number.

The two checks that read ``pyproject.toml`` need ``tomllib`` and so run
only on Python 3.11 and up. In CI that is the 3.13 test leg alone; both
3.10 legs skip them, and the lint job never runs pytest. The remaining
checks carry no such precondition and run on every supported
interpreter, including the 3.10 floor.

Markdown exclusion is a project convention, not a requirement: ``.md``
files are prose plus illustrative samples, not sources ``ruff format``
owns, and no ITACA Markdown block is collected as a doctest. The
rationale lives next to the setting in ``pyproject.toml``.
"""

import importlib.metadata
import itertools
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RUFF_REPO = "astral-sh/ruff-pre-commit"
RUFF_HOOKS = {"ruff-check", "ruff-format"}
CI_RUFF_COMMANDS = ("ruff check .", "ruff format --check .")
# An allowlist, not a denylist: any other key (args, stages, exclude,
# files, alias) narrows what the hook reads, and a hook that lints
# nothing passes just as quietly as one that is gone.
ALLOWED_KEYS = {"repo", "rev", "hooks", "id"}


def _repo_entries() -> list[str]:
    """Split the config into the items of its top-level ``repos:`` list.

    Splitting on item boundaries rather than on a ``repo:`` line keeps the
    guard indifferent to key order and to quoting inside an entry; nested
    ``- id:`` hook lines sit deeper and never start an item.
    """
    lines = PRE_COMMIT.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = {
        i: len(found.group(1))
        for i, line in enumerate(lines)
        if (found := re.match(r"( *)-\s", line))
    }
    if not starts:
        return []
    outermost = min(starts.values())
    bounds = [i for i, indent in starts.items() if indent == outermost]
    bounds.append(len(lines))
    return ["".join(lines[a:b]) for a, b in itertools.pairwise(bounds)]


def _ruff_repo_block() -> str:
    """Return the one ``repos:`` item that declares the ruff hooks."""
    owned = [entry for entry in _repo_entries() if RUFF_REPO in entry]
    assert len(owned) == 1, (
        f".pre-commit-config.yaml must declare exactly one {RUFF_REPO} repo "
        f"entry, found {len(owned)}; merge the ruff hooks into a single "
        "repos: item pinned to one rev, since that entry is the local "
        "mirror of the CI lint job (REQ-96)."
    )
    return owned[0]


def _pre_commit_ruff_rev() -> str:
    """Return the ruff version the hook installs.

    A ``pre-commit autoupdate --freeze`` rev is a commit sha carrying the
    readable tag in a trailing ``# frozen:`` comment, so that comment is
    the version source whenever it is present.
    """
    block = _ruff_repo_block()
    frozen = re.search(r"^\s*rev:.*#\s*frozen:\s*v?([0-9A-Za-z.]+)", block, flags=re.M)
    if frozen:
        return frozen.group(1)
    found = re.search(r"""^\s*rev:\s*["']?v?([0-9A-Za-z.]+)""", block, flags=re.M)
    assert found, (
        f"the {RUFF_REPO} entry in .pre-commit-config.yaml has no readable "
        "rev; give it `rev: vX.Y.Z` matching the ruff pin in the pyproject "
        "[dev] extra."
    )
    return found.group(1)


def _pyproject() -> dict[str, Any]:
    tomllib = pytest.importorskip("tomllib", reason="reading pyproject needs 3.11+")
    parsed: dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return parsed


def _dev_ruff_pin() -> str:
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    specs = [spec for spec in dev if re.match(r"ruff(?=$|[=<>~!\[; ])", spec)]
    assert len(specs) == 1, (
        f"the pyproject [dev] extra must list exactly one ruff spec, found "
        f"{specs}; write it as `ruff==X.Y.Z`."
    )
    exact = re.fullmatch(r"ruff==([0-9A-Za-z.]+)", specs[0])
    assert exact, (
        f"the pyproject [dev] ruff spec {specs[0]!r} is not an exact pin; a "
        "range lets CI install a different linter than the pre-commit hook "
        "runs (REQ-96), so write it as `ruff==X.Y.Z`."
    )
    return exact.group(1)


def test_ci_lint_job_runs_both_ruff_commands() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    missing = [cmd for cmd in CI_RUFF_COMMANDS if f"run: {cmd}" not in workflow]
    assert not missing, (
        f"the CI lint job no longer runs {missing}; restore the step, or the "
        "pre-commit hooks below mirror a job that stopped checking what they "
        "check (REQ-95, REQ-96)."
    )


def test_pre_commit_declares_both_ruff_hooks_unnarrowed() -> None:
    block = _ruff_repo_block()
    ids = set(re.findall(r"^\s*-\s+id:\s*([\w-]+)", block, flags=re.M))
    assert ids == RUFF_HOOKS, (
        f"the {RUFF_REPO} hooks are {sorted(ids)} but the CI lint job runs "
        f"{list(CI_RUFF_COMMANDS)}; declare exactly {sorted(RUFF_HOOKS)} so "
        "the local mirror covers both (REQ-96)."
    )
    keys = {
        found.group(1)
        for line in block.splitlines()
        if (found := re.match(r"\s*-?\s*([A-Za-z_]+):", line.split("#")[0]))
    }
    narrowing = sorted(keys - ALLOWED_KEYS)
    assert not narrowing, (
        f"the {RUFF_REPO} entry carries {narrowing}, which narrows what the "
        "hooks read or when they run; drop it so both hooks lint the whole "
        "tree from [tool.ruff] in pyproject.toml, as the CI job does "
        "(REQ-96)."
    )


def test_pre_commit_declares_no_global_skip() -> None:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    skipping = sorted(set(re.findall(r"^(exclude|files):", text, flags=re.M)))
    assert not skipping, (
        f".pre-commit-config.yaml sets a top-level {skipping}, which hides "
        "part of the tree from every hook while CI still lints all of it; "
        "remove it so the local mirror stays whole (REQ-96)."
    )


def test_installed_ruff_matches_the_pre_commit_rev() -> None:
    try:
        installed = importlib.metadata.version("ruff")
    except importlib.metadata.PackageNotFoundError:
        pytest.fail(
            "ruff is not installed in this environment, so the REQ-96 mirror "
            'cannot be verified; run `pip install -e ".[dev]"` before pytest.'
        )
    rev = _pre_commit_ruff_rev()
    assert installed == rev, (
        f"this environment has ruff {installed} but the pre-commit hook "
        f'installs {rev}; run `pip install -e ".[dev]"` so local runs '
        "enforce the same rule set as CI (REQ-96)."
    )


def test_dev_ruff_pin_matches_pre_commit_rev() -> None:
    dev_pin, rev = _dev_ruff_pin(), _pre_commit_ruff_rev()
    assert dev_pin == rev, (
        f"REQ-96 mirror broken: the pyproject [dev] extra installs ruff "
        f"{dev_pin} while the pre-commit hook runs ruff {rev}; move both to "
        "one version in the same commit."
    )


def test_ruff_excludes_markdown_from_the_formatter_scope() -> None:
    excluded = _pyproject()["tool"]["ruff"].get("extend-exclude", [])
    assert "*.md" in excluded, (
        "[tool.ruff] extend-exclude must list '*.md' so a later ruff release "
        "cannot extend the formatter over prose and illustrative samples; "
        f"got {excluded}. The rationale is next to the setting in pyproject."
    )
