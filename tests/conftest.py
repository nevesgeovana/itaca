"""Shared fixtures and session-state hygiene for the ITACA test suite."""

import os
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

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
        created_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc),
        source_files=(),
        source_hash="0" * 64,
        mode="production",
    )


@pytest.fixture
def draft_prov(prov: Provenance) -> Provenance:
    """A draft-mode variant of the minimal Provenance record."""
    import dataclasses

    return dataclasses.replace(prov, mode="draft")
