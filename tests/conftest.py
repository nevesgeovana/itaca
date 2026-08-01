"""Shared fixtures and session-state hygiene for the ITACA test suite."""

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest

from itaca.core import provenance as provenance_module
from itaca.core.provenance import Provenance

# pytest-cov starts coverage inside any Python subprocess that inherits
# these, through its .pth hook, and the child writes to the parent's
# ABSOLUTE data file path, which is the repository root on every
# platform. A child that cannot find pyproject.toml starts without
# branch=true, and combining its statement-only data with the parent's
# branch data aborts the whole run in teardown, after every test has
# passed. That turned CI red on all three legs of commit 48009bc.
#
# Every test that spawns a Python interpreter must use child_env(), and
# `test_no_spawn_site_bypasses_child_env` in tests/test_push_gate.py
# holds that invariant. Two sites existed when this was written; only
# one had been found by looking at the failure.
COVERAGE_SUBPROCESS_VARS = (
    "COV_CORE_SOURCE",
    "COV_CORE_CONFIG",
    "COV_CORE_DATAFILE",
    "COV_CORE_BRANCH",
    "COV_CORE_CONTEXT",
    "COVERAGE_PROCESS_START",
    "COVERAGE_PROCESS_CONFIG",
)


def child_env(**overrides: str | None) -> dict[str, str]:
    """The environment a spawned Python subprocess should run in.

    Strips coverage measurement. A key whose override is ``None`` is
    removed, which is how the push gate tests drop the incident ledger
    variable to stay hermetic.

    Reached two ways, both pytest-native and neither needing ``tests``
    to be an importable package: modules beside this file import it
    (pytest puts their directory on ``sys.path``), and modules in
    subdirectories take the fixture of the same name below. An earlier
    ``from tests.conftest import`` worked locally only because of the
    editable install and broke every CI leg with ModuleNotFoundError.
    """
    env = {k: v for k, v in os.environ.items() if k not in COVERAGE_SUBPROCESS_VARS}
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


@pytest.fixture(name="child_env")
def _child_env_fixture() -> Callable[..., dict[str, str]]:
    """Expose :func:`child_env` to tests in subdirectories."""
    return child_env


@pytest.fixture(autouse=True)
def _reset_session_state() -> Iterator[None]:
    """Restore the global user and mode defaults after every test."""
    yield
    provenance_module.set_user(None)
    provenance_module.set_mode("production")


@pytest.fixture
def prov() -> Provenance:
    """A minimal production-mode Provenance record for direct construction."""
    return Provenance(
        itaca_version="0.1.0.dev0",
        user="tester@testhost",
        created_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
        source_files=(),
        source_hash="0" * 64,
        mode="production",
    )


@pytest.fixture
def draft_prov(prov: Provenance) -> Provenance:
    """A draft-mode variant of the minimal Provenance record."""
    import dataclasses

    return dataclasses.replace(prov, mode="draft")


# ---------------------------------------------------------------------------
# The commit tier stays fast BY CONSTRUCTION, not by vigilance.
#
# `.pre-commit-config.yaml` runs `pytest -m "not slow or fast"` on every
# commit (the `or fast` readmits the cheap guards a module-level marker
# swept out; see the `fast` entry in pyproject's markers), with
# a p95 budget of 30 seconds. A budget nothing enforces is a wish: unmarked
# slow tests accrete one at a time, each defensible on its own, and a year
# later the fast tier is the suite again. That is exactly how the hook NAMED
# `pytest-fast` came to run the whole suite, and a full mypy beside it,
# on every commit
# (BRF-063, measured by the coordination level on 2026-07-30).
#
# So a test that is not marked `slow` and exceeds the per-test budget below
# FAILS the run, and the remedy in the message is the honest one: mark it
# slow, which moves it to the blocking pre-push tier, or make it faster.
#
# The budget is per test and covers setup plus call plus teardown, because
# `test_push_gate.py` spent its 108 seconds almost entirely in SETUP and a
# call-only budget would have read it as fast.
#
# 3.0 s WITH THE CONDITION STATED, because the first version of this comment
# gave the number without it. The slowest unmarked test measured 1.36 s on a
# tree with a WARM mypy cache. On a cold cache, which is a fresh clone or any
# tree after `.mypy_cache` is cleared, the mypy-spawning conformance test
# measured 4.08 s and tripped this budget on the first commit. That test now
# carries the marker for that reason; the number below is honest only for the
# warm case and a reviewer measured the cold one.
#
# TWO THINGS THIS DOES NOT BOUND, both measured by reviewers rather than
# reasoned about, and both open:
#
#   1. THE TOTAL. A thousand tests at 0.02 s each is a slow tier made of fast
#      tests. `test_the_commit_tier_subset_is_actually_fast` measures the
#      aggregate, at a ceiling four times the current cost.
#   2. ONE PARAMETRIZED TEST. Four cases of 2.5 s ran 10.25 s and passed
#      unmarked, because the budget is per CASE. That is a single edit, not
#      slow drift, and it is the practical hole rather than the theoretical
#      one. Registered as ITC-20260730-2355.
_FAST_TEST_BUDGET_SECONDS = 3.0


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Accumulate the wall time of each phase, per unmarked test.

    `slow` AND NOT `fast`. A `fast` test inside a module carrying
    `pytestmark = pytest.mark.slow` still has `slow` among its keywords,
    so exempting on that word alone left the one population the `fast`
    marker creates with no per-test budget at all: the marker's whole
    purpose is to put a test INTO the commit tier, and it was putting it
    there unmeasured.

    MEASURED before the fix, with a probe module carrying a module-level
    `slow` and one `fast` test sleeping 3.5 s, run with the commit tier's
    own selection: `1 passed in 3.83s`, exit 0, no budget refusal. The
    documentation claimed the opposite, which is why this reads the
    condition it means rather than the word it used to key on.
    """
    keywords = getattr(report, "keywords", {})
    if report.when == "setup" and "slow" in keywords and "fast" not in keywords:
        _seen_slow.add(report.nodeid)
    if report.nodeid in _seen_slow:
        return
    _durations[report.nodeid] = _durations.get(report.nodeid, 0.0) + report.duration


_durations: dict[str, float] = {}
_seen_slow: set[str] = set()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Refuse a run where an unmarked test blew the commit-tier budget.

    ONLY WHEN COVERAGE IS OFF, which is the condition the commit tier
    actually runs in (`pytest -m "not slow or fast" --no-cov`). Coverage
    instrumentation inflates wall time by roughly half again on the tests
    that walk the tree, and the first version of this check did not make
    the distinction: the full suite, which runs WITH coverage, reported
    ``test_the_degraded_walk_still_reaches_the_tree_and_honors_the_exclusions``
    at 3.09 s against a 3.0 s budget, where the same test takes 1.59 s
    under the conditions the budget exists to protect.

    That false positive matters more than the seconds. Its remedy would
    have been to mark a genuinely fast contract test `slow`, moving a
    cheap tree-walking guard off the commit gate to satisfy a check that
    was measuring the wrong thing. A budget enforced under conditions the
    budgeted tier never runs in does not protect the tier; it erodes it.

    WHERE THIS ACTUALLY FIRES, stated exactly, because the first version of
    this docstring overclaimed it. Every commit runs the fast tier with
    `--no-cov`, so it fires there. It does NOT fire in CI: `ci.yml` and
    `release.yml` run bare `pytest`, which carries coverage through
    `addopts`. So the only enforcement point today is a developer machine
    that ran `pre-commit install`, and an unmarked slow test can reach main
    through a pull request with every gate green. Registered as
    ITC-20260730-2355 with the CI leg that would close it.
    """
    measuring_coverage = not getattr(session.config.option, "no_cov", True)
    if measuring_coverage:
        return
    over = sorted(
        (
            (nodeid, total)
            for nodeid, total in _durations.items()
            if total > _FAST_TEST_BUDGET_SECONDS
        ),
        key=lambda item: -item[1],
    )
    if not over:
        return
    listed = "\n".join(f"    {total:6.2f}s  {nodeid}" for nodeid, total in over)
    raise pytest.UsageError(
        f"{len(over)} test(s) exceeded the {_FAST_TEST_BUDGET_SECONDS:.1f}s "
        f"commit-tier budget without carrying the `slow` marker:\n{listed}\n"
        f'The commit tier runs `pytest -m "not slow or fast"` and is budgeted '
        f"at a p95 under 30 seconds, so an unmarked test this size makes "
        f"every commit in this repository pay for it. Either decorate that "
        f"TEST `@pytest.mark.slow` (it then runs at pre-push, where it still "
        f"blocks, and in CI), or make it faster. Use module-level "
        f"`pytestmark` only to move a whole module, and note that "
        f"tests/test_tooling_config.py refuses it on the contract modules. "
        f"A test carrying `@pytest.mark.fast` is budgeted here even inside a "
        f"module marked slow, deliberately: that marker admits a test to this "
        f"tier, so it cannot also excuse it from the tier's budget. "
        f"Do not raise the budget to make this pass."
    )
