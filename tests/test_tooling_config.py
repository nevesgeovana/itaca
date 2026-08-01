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

The two checks that read ``pyproject.toml`` need ``tomllib``. That used
to make them conditional: against the former 3.10 floor they ran on the
3.13 leg alone and both 3.10 legs skipped them, so the mirror was
verified on one interpreter out of three. The 3.11 floor (REQ-83) puts
``tomllib`` in the standard library on every supported interpreter, so
they now run on every leg with no skip, like the rest of this module.

Markdown exclusion is a project convention, not a requirement: ``.md``
files are prose plus illustrative samples, not sources ``ruff format``
owns, and no ITACA Markdown block is collected as a doctest. The
rationale lives next to the setting in ``pyproject.toml``.
"""

import importlib.metadata
import itertools
import json
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from hook_entry import assert_is_the_vendored_receipt, split_wrapper

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


def _ci_gate_commands() -> list[str]:
    """Every command CI's release-gate call actually runs.

    CI no longer spells its checks as `run:` steps: it calls the
    vendored reusable release gate and passes the gate set as a JSON
    array. Reading the parsed gate entries is a STRONGER check than the
    previous text search, because it confirms the command is a gate the
    workflow will execute rather than a string that happens to appear
    somewhere in the file.
    """
    workflow: Any = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    commands: list[str] = []
    for job in workflow.get("jobs", {}).values():
        gates = job.get("with", {}).get("gates")
        if not gates:
            continue
        for entry in json.loads(gates):
            if "run" in entry:
                commands.append(entry["run"])
    assert commands, (
        "the CI workflow passes no `gates` to the release gate, so this "
        "guard has nothing to read and the lint commands below would be "
        "unchecked (REQ-95, REQ-96)."
    )
    return commands


def test_ci_lint_job_runs_both_ruff_commands() -> None:
    commands = " && ".join(_ci_gate_commands())
    missing = [cmd for cmd in CI_RUFF_COMMANDS if cmd not in commands]
    assert not missing, (
        f"the CI gate set no longer runs {missing}; restore it in the `gates` "
        "input, or the pre-commit hooks below mirror a job that stopped "
        "checking what they check (REQ-95, REQ-96)."
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


# The contract modules the COMMIT tier must keep. Marking one of these
# `slow` would buy seconds by moving the repository's own invariants off
# the gate a developer actually feels, which is the trade this list exists
# to refuse. Each pins something that is cheap to check and expensive to
# discover late: the NumPy-only import policy, the vendored kit bodies, the
# house style and identifier rules, the locator family's resolution, and
# this file, which pins the tiers themselves.
_COMMIT_TIER_CONTRACT_MODULES = (
    "tests/test_import_policy.py",
    "tests/test_kit_drift.py",
    "tests/test_house_style.py",
    "tests/test_management_root.py",
    "tests/test_tooling_config.py",
    "tests/test_review_gate.py",
    "tests/test_side_effect_guard.py",
)


def _local_hook_stages() -> dict[str, list[str]]:
    """Every local hook id mapped to the stages it declares."""
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    stages: dict[str, list[str]] = {}
    for repo in config["repos"]:
        if repo.get("repo") != "local":
            continue
        for hook in repo["hooks"]:
            stages[hook["id"]] = hook.get("stages", [])
    return stages


def test_the_commit_tier_runs_only_the_fast_subset() -> None:
    """The commit hook must select, or it is the whole suite again.

    BRF-063's diagnosis, and the reason this guard is worth more than the
    config line it checks: the hook was NAMED `pytest-fast` and ran the
    entire suite plus a full `mypy --strict` on every commit, because its
    entry carried no selection at all. A name is not a mechanism, and
    nothing failed when the two disagreed.
    """
    stages = _local_hook_stages()
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entries = {
        hook["id"]: hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
    }
    assert "pytest-fast" in entries, (
        "the commit tier has no pytest hook, so a commit runs no tests at "
        "all. Restore `pytest-fast` with the `not slow` selection."
    )
    entry = entries["pytest-fast"]
    assert "not slow" in entry, (
        f"the commit hook runs {entry!r}, with no marker selection, so it "
        f"runs the FULL suite on every commit. That is the exact defect "
        f"BRF-063 measured: a hook named fast that was not. Select the "
        f'subset with -m "not slow".'
    )
    assert "--no-cov" in entry, (
        f"the commit hook runs {entry!r} with coverage on. Coverage is the "
        f"pre-push tier's job; at commit time it buys nothing and costs "
        f"every commit."
    )
    assert stages.get("pytest-fast") == ["pre-commit"], (
        f"the commit hook declares stages {stages.get('pytest-fast')!r}. Pin "
        f"it to pre-commit so it cannot silently become the push tier too."
    )


def test_the_push_tier_runs_the_whole_suite_and_blocks() -> None:
    """Marking a test `slow` must move it, never excuse it.

    This is the load-bearing half of the tier split. `slow` is only
    legitimate because everything it removes from the commit gate still
    runs, with coverage, at a gate that blocks. If the pre-push hook were
    deleted, `slow` would silently become "does not run locally at all",
    and the marker would be an exemption rather than a routing decision.
    """
    stages = _local_hook_stages()
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entries = {
        hook["id"]: hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
    }
    assert "pytest-full" in entries, (
        "there is no pre-push pytest hook, so nothing local runs the tests "
        "the `slow` marker removed from the commit tier. Either restore it "
        "or stop marking tests slow; a marker with no blocking tier behind "
        "it is an exemption."
    )
    assert stages.get("pytest-full") == ["pre-push"], (
        f"the full-suite hook declares stages {stages.get('pytest-full')!r}; "
        f"it must be pre-push, or it is back on every commit."
    )
    # Kit 0.2.15 lets this entry be WRAPPED in the pre-push receipt, which
    # skips a command already passed on an identical tree and environment.
    # Everything below is a claim about WHAT ACTUALLY RUNS, so it reads the
    # PARSED command and not the entry string. The first repair here split
    # on `" -- "` and searched substrings, and a reviewer measured that a
    # wrapper carrying the receipt's name inside a quoted argument passed
    # every assertion while running another program entirely.
    wrapper, argv = split_wrapper(entries["pytest-full"])
    if wrapper is not None:
        assert_is_the_vendored_receipt(wrapper)
    # EQUALITY, not a list of refusals. The first repair here refused `-m`
    # and `--deselect`, and a reviewer measured that `pytest --co` passes
    # it: the tier would collect and run nothing while a guard whose whole
    # purpose is "the blocking tier runs the WHOLE suite" stayed green.
    # Enumerating the ways to run less is a denylist, and this file already
    # states one level up why an allowlist is the only safe shape. Coverage
    # and marker selection are covered by this too, since neither
    # `--no-cov` nor `-m` can appear in a command that is exactly `pytest`.
    #
    # An addition here is not forbidden, it is a DECISION: change this
    # literal and say in the same edit why the addition does not reduce
    # what the blocking tier sees.
    assert argv == ["pytest"], (
        f"the pre-push hook's effective command is {argv!r} and not exactly "
        f"['pytest']. This is the only local gate that sees the slow tests "
        f"and the only one that enforces the 90 percent floor (REQ-75), so "
        f"it runs the whole suite with nothing added: no marker selection, "
        f"no -k, no -x, no --co, no --no-cov. If an argument is genuinely "
        f"needed, add it here with the reason it does not narrow the run."
    )


@pytest.mark.parametrize(
    "entry,expected",
    [
        (
            "python .claude/kit/other_wrapper.py --note "
            '".claude/kit/prepush_receipt.py guard --label pytest-full" '
            "-- pytest",
            "which resolves to",
        ),
        (
            "python .claude/kit/prepush_receipt.py status --label pytest-full "
            "-- pytest",
            "subcommand",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard -- pytest",
            "carries no --label",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard --label -- pytest",
            "and no value",
        ),
        (
            "sh -c .claude/kit/prepush_receipt.py guard --label x -- pytest",
            "not a Python interpreter",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard --label pytest-full "
            "--repo /tmp/elsewhere -- pytest",
            "which is not this repository",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard --label pytest-full "
            "--quiet -- pytest",
            "Only --label and --repo are allowed",
        ),
    ],
    ids=[
        "quoted-name",
        "status",
        "no-label",
        "empty-label",
        "not-python",
        "other-repo",
        "unknown-option",
    ],
)
def test_a_wrapper_that_is_not_the_receipt_is_refused(
    entry: str, expected: str
) -> None:
    """Prove the wrapper check can still fail, on the shapes that defeated it.

    The first version of the check above searched the entry STRING, and a
    reviewer measured that the first case here satisfied all seven of its
    assertions across two modules while the program actually executed was
    `other_wrapper.py`. A guard that cannot refuse the thing it names is
    the failure class this repository registers most, so the refusal is
    asserted rather than assumed.

    EACH CASE ASSERTS ITS OWN MESSAGE, and that is not decoration. A bare
    `pytest.raises(AssertionError)` says only that SOMETHING refused, so
    every case would keep passing if one early assertion started catching
    all of them, with the ids still claiming seven distinct reasons. A
    reviewer traced the ordering by hand and found it correct today; this
    is what keeps it correct after the next edit.

    Every case is a wrapper that a reader would plausibly write and that
    must not stand in front of the blocking suite.
    """
    wrapper, argv = split_wrapper(entry)
    assert wrapper is not None, f"the fixture {entry!r} is not even wrapped"
    assert argv[:1] == ["pytest"], "every fixture wraps the real suite"
    with pytest.raises(AssertionError, match=re.escape(expected)):
        assert_is_the_vendored_receipt(wrapper)


def test_an_unwrapped_entry_parses_as_unwrapped() -> None:
    """The branch nothing else reaches, and inverting it hides the check.

    Every caller guards the wrapper assertions with `if wrapper is not
    None`, so a `split_wrapper` that returned a wrapper for an unwrapped
    entry, or None for a wrapped one, would silently skip the whole
    receipt check while every other test stayed green. A reviewer
    measured that no test exercised this branch: the module's doctests do
    not run, since the suite collects no `--doctest-modules`.
    """
    assert split_wrapper("pytest") == (None, ["pytest"])
    assert split_wrapper("mypy") == (None, ["mypy"])
    # A `--` that is part of an option, not a separator, does not split.
    assert split_wrapper("pytest --no-cov") == (None, ["pytest", "--no-cov"])
    # The wrapped form, so this test measures the DISTINCTION and not just
    # one side of it.
    assert split_wrapper("python r.py guard --label x -- pytest") == (
        ["python", "r.py", "guard", "--label", "x"],
        ["pytest"],
    )


def test_the_real_entry_passes_the_same_check() -> None:
    """The control: the refusals above are not refusing everything.

    A parametrized refusal test passes just as happily when the assertion
    it calls rejects every input, including the correct one, so the live
    entry is driven through the same function as the positive case.
    """
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entry = next(
        hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
        if hook["id"] == "pytest-full"
    )
    wrapper, argv = split_wrapper(entry)
    assert wrapper is not None, (
        f"the pre-push entry {entry!r} is not wrapped at all, so this control "
        f"is measuring nothing. If the wrapper was deliberately removed, "
        f"remove this test with it."
    )
    assert argv[:1] == ["pytest"], (
        f"the live entry wraps {argv!r}, so the refusals above and this "
        f"control are not comparing the same shape."
    )
    assert_is_the_vendored_receipt(wrapper)


def test_the_coverage_floor_is_declared_with_its_value() -> None:
    """REQ-75: the 90 percent floor, asserted on the CARRIER not the mention.

    THREE REVIEWERS INDEPENDENTLY CAUGHT THE ABSENCE OF THIS TEST, and one
    proved it by mutation: with `--cov-fail-under=90` deleted from
    `addopts`, every guard in this repository stayed green while the
    requirement trace reported REQ-75 as reached. It read as reached only
    because the string `REQ-75` had appeared in an assertion MESSAGE, which
    is the trace's whole notion of reached, so the ratchet did not notice an
    improvement; it reacted to a comment.

    REQ-75 names a THRESHOLD, so the value is asserted and not merely the
    flag. The pre-push tier check beside this one asserts the floor is not
    disabled there; this asserts it exists at all.
    """
    addopts = _pyproject()["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--cov-fail-under=90" in addopts, (
        f"pyproject's pytest addopts is {addopts!r}, which does not carry "
        f"`--cov-fail-under=90`. REQ-75 is the 90 percent coverage floor and "
        f"this is the only place it exists; without it the suite reports "
        f"coverage and enforces nothing, and the requirement trace still "
        f"lists REQ-75 as reached."
    )


def test_the_contract_modules_stay_in_the_commit_tier() -> None:
    """A cheap invariant must not be moved off the gate developers feel.

    The `slow` marker is a routing decision and it is available to any
    module, which makes it available as a way to make a red commit green.
    These modules are the ones where that trade is refused: each is under
    four seconds and each pins something the repository cannot afford to
    discover at push time.
    """
    # ONE collection for all of them. Seven subprocesses cost 4.36 s and
    # tripped this repository's own commit-tier budget, which then failed the
    # aggregate test that runs the subset: the guard was paying more than the
    # thing it guards. Collecting once and reading the node ids is the same
    # question asked once.
    argv = [
        sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-cov",
        "-m", "not slow", "-p", "no:cacheprovider", "tests",
    ]  # fmt: skip
    done = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(ROOT), env=child_env()
    )
    assert done.returncode == 0, (
        f"collecting the commit tier's own selection failed, so this guard "
        f"cannot say which modules run there:\n{done.stdout[-2000:]}"
    )
    collected = done.stdout.replace("\\", "/")
    for relative in _COMMIT_TIER_CONTRACT_MODULES:
        assert (ROOT / relative).is_file(), (
            f"{relative} is named as a commit-tier contract module but does "
            f"not exist; either it was renamed, in which case update this "
            f"list deliberately, or a guard was deleted."
        )
        # MEASURE THE SELECTION, never the source. Two earlier versions read
        # the file: the first matched `pytest.mark.slow` as a substring and
        # failed against its own assertion text, and the second matched a
        # `pytestmark` line, which a reviewer defeated six ways. Two of the
        # six need nobody to do anything wrong: `ruff format` produces a
        # multiline list the moment a second marker joins `slow`, and a
        # marker applied in `pytest_collection_modifyitems` never appears in
        # the module at all. Asking pytest what the tier would collect is
        # immune to all six, because it is the question the tier asks.
        assert f"{relative}::" in collected, (
            f"{relative} contributes NO test to the commit tier: everything "
            f"in it is marked slow, however that marking is spelled. It is "
            f"on the contract list precisely because it is cheap and "
            f"load-bearing. If it became genuinely slow, that is the "
            f"finding: make it fast again, or take it off this list "
            f"deliberately and say why. Marking one test inside it slow is "
            f"fine and is not what this refuses."
        )


@pytest.mark.slow
def test_the_commit_tier_subset_is_actually_fast() -> None:
    """Measure the aggregate, because no per-test rule can see it.

    `tests/conftest.py` bounds each unmarked test at three seconds, which
    stops one slow test from landing unmarked. It cannot see a thousand
    fast tests adding up to a slow tier, and that is the shape this budget
    would actually drift into.

    So this runs the real commit-tier selection in a subprocess and
    measures it. It is itself marked `slow`, for two reasons: it costs
    about what the subset costs, and a fast-tier test that runs the fast
    tier would recurse.

    The budget here is the WALL time of one run against the p95 target of
    30 seconds. A single sample is not a p95, and this test does not
    pretend otherwise: it is a ceiling that catches drift, and the p95 is
    measured deliberately when the tiers change. The margin is generous
    for that reason.
    """
    # `child_env()` strips the COV_CORE_* variables. Without it the nested
    # run inherits the parent's coverage subprocess hooks, which is how a
    # spawned pytest has aborted here AFTER every test passed; the whole
    # suite is under coverage when this test runs, and this is the one
    # test in the file that spawns pytest rather than a checker.
    # The argument list is built FIRST so that `env=` sits within a few
    # lines of `subprocess.run(`. That is not cosmetic:
    # `test_push_gate.py::test_no_spawn_site_bypasses_child_env` scans a
    # 14-line window from each spawn site and reported this call as
    # bypassing the helper when the arguments were inlined, because
    # `env=child_env()` fell outside the window. The guard was right to be
    # tight and the call is what moved; widening its window to fit this
    # code would have loosened the check that caught it.
    argv = [
        sys.executable, "-m", "pytest",
        "-m", "not slow", "-q", "--no-cov", "-p", "no:cacheprovider",
    ]  # fmt: skip
    started = time.monotonic()
    done = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(ROOT), env=child_env()
    )
    elapsed = time.monotonic() - started
    assert done.returncode == 0, (
        f"the commit-tier subset does not pass on its own:\n{done.stdout[-3000:]}"
    )
    assert elapsed < 60.0, (
        f"the commit-tier subset took {elapsed:.1f}s in this run, against a "
        f"p95 target of 30 s and a drift ceiling of 60 s. The subset has "
        f"grown into the tier it was split out of. Find what got slow "
        f'(pytest --durations=25 -m "not slow") and mark it or fix it; '
        f"do not raise this ceiling."
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


def test_the_mypy_missing_import_exemption_stays_scoped_to_generated_modules() -> None:
    """`ignore_missing_imports` may not widen past the modules that earn it.

    Two overrides carry it, for two different and narrow reasons:
    `pandas` is an optional lazily imported bridge whose stubs are not a
    dependency (REQ-84), and `itaca.core._version` is GENERATED by
    setuptools-scm and gitignored, so it is absent from any tree that
    has not been built.

    The second is the one that needs a guard. Without the override,
    `mypy --strict` fails on a fresh clone or a detached worktree for a
    reason the developer did not cause, and the obvious remedy for that
    noise is a blanket `ignore_missing_imports` at `[tool.mypy]` or a
    wildcard over `itaca.*`. Either would silently exempt the whole
    package from the gate REQ-78 states, and nothing else would notice.
    So the exemption is pinned to exactly the modules that justify it,
    and this fails if it ever grows or moves to the top level.
    """
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy = config["tool"]["mypy"]

    # The gate itself, first. Pinning the exemption while `strict` or
    # `files` can move is guarding the lock and not the door.
    assert mypy.get("strict") is True, (
        "pyproject.toml no longer sets strict = true under [tool.mypy]; "
        "REQ-78 states mypy --strict on the public API."
    )
    assert mypy.get("files") == ["itaca"], (
        f"[tool.mypy] files is {mypy.get('files')!r}, not ['itaca']; "
        f"narrowing it removes packages from the gate without removing the "
        f"gate."
    )

    # Every knob that can suppress an error, not just the one this
    # repository happens to use. An override reaching the same weakening
    # by `follow_imports = "skip"` or `ignore_errors` over `itaca.*`
    # would leave the exemption set below untouched while mypy stopped
    # seeing most of the package.
    suppressors = ("ignore_missing_imports", "ignore_errors", "follow_imports")
    for knob in suppressors:
        assert knob not in mypy, (
            f"pyproject.toml sets {knob} at [tool.mypy], which applies it to "
            f"EVERY module in the package and turns the REQ-78 gate off "
            f"wholesale. Scope it to the module that needs it instead."
        )
    assert "disable_error_code" not in mypy, (
        "pyproject.toml disables error codes at [tool.mypy], repository-wide."
    )

    suppressing: set[tuple[str, str]] = set()
    for override in mypy.get("overrides", []):
        used = tuple(knob for knob in suppressors if override.get(knob))
        if not used and not override.get("disable_error_code"):
            continue
        for module in override["module"]:
            for knob in used:
                suppressing.add((module, knob))
            if override.get("disable_error_code"):
                suppressing.add((module, "disable_error_code"))

    assert suppressing == {
        ("pandas", "ignore_missing_imports"),
        ("pandas.*", "ignore_missing_imports"),
        ("itaca.core._version", "ignore_missing_imports"),
    }, (
        f"the mypy error suppression covers {sorted(suppressing)}. It is "
        f"allowed for the optional pandas bridge (REQ-84) and for the "
        f"generated, gitignored itaca/core/_version.py, by missing-import "
        f"only, and for nothing else. A wildcard over itaca.* by any knob "
        f"would turn the strict gate off for the package it exists to check."
    )


# The suite spawns interpreters to exercise tools it cannot import: mypy
# on a snippet, and `build` on the repository. Those tools have to be in
# the extra the contributing guide and CI install, or the test errors on
# every machine but the author's. That is ITACA-015's defect class, whose
# fix added one package and no guard, so it recurred the moment a test
# spawned `build`. Discovering the spawn sites is what makes the rule
# survive the next tool.
_SPAWNED_MODULE = re.compile(r'sys\.executable,\s*"-m",\s*"([a-zA-Z_][\w.]*)"')
_STDLIB_SPAWNS = frozenset({"pytest", "pip", "venv", "json.tool"})


def _requirement_names(requirements: list[str]) -> set[str]:
    return {
        re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower() for line in requirements
    }


def test_every_module_the_suite_spawns_is_declared_in_the_dev_extra() -> None:
    """A tool the suite runs but nobody installs is a test that only passes here.

    `pytest` and `pip` are exempt because whatever ran this file already
    provides them.
    """
    declared = _requirement_names(
        _pyproject()["project"]["optional-dependencies"]["dev"]
    )
    spawned: dict[str, str] = {}
    for path in sorted((ROOT / "tests").rglob("*.py")):
        for module in _SPAWNED_MODULE.findall(path.read_text(encoding="utf-8")):
            spawned.setdefault(module, path.relative_to(ROOT).as_posix())
    # Pinned as a SET, not a floor. The pattern recognizes one syntactic
    # shape, so a tool spawned as a console script or through a variable
    # is invisible to it while the floor stays satisfied by the two sites
    # already here. A difference either way is a deliberate edit.
    # `pytest` joined the set on 2026-07-30 with the tier split: the
    # aggregate commit-tier measurement in this file spawns the fast subset
    # in a subprocess, because wall time is the thing it exists to measure
    # and it cannot measure that from inside the same run. It is the
    # deliberate edit this assertion's own message asks for, not a
    # widening: the docstring above already exempted pytest from the
    # installation half, since whatever ran this file provides it.
    assert set(spawned) == {"mypy", "build", "pytest"}, (
        f"the spawn-site scan found {spawned}; if a tool was added, declare "
        "it in the [dev] extra and add it here, and if one moved out of the "
        "recognized shape, widen the pattern rather than the exemption"
    )
    missing = {
        module: site
        for module, site in spawned.items()
        if module not in _STDLIB_SPAWNS and module not in declared
    }
    assert not missing, (
        f"the suite spawns {missing} (module: spawn site) but the [dev] extra "
        f"declares {sorted(declared)}; a tool the tests run must be installed "
        'by `pip install -e ".[dev]"`, or the test errors wherever the author '
        "did not already have it (ITACA-015's class)."
    )
