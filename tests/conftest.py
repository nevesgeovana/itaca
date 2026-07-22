"""Shared fixtures and session-state hygiene for the ITACA test suite."""

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest

from itaca.core import provenance as provenance_module
from itaca.core.provenance import Provenance


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
