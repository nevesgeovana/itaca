"""Tests for Provenance and the operating-mode session state (REQ-07, REQ-08).

Usage example (the contract under test)::

    import itaca as itc

    itc.set_user("geovana@tudelft")
    itc.set_mode("draft")
"""

import dataclasses
import re

import pytest

import itaca as itc
from itaca.core import provenance
from itaca.core.errors import ProvenanceError
from itaca.core.provenance import Provenance


class TestSessionState:
    def test_default_user_is_user_at_hostname(self) -> None:
        # REQ-07: getpass.getuser() + "@" + socket.gethostname().
        assert re.fullmatch(r"[^@]+@[^@]+", provenance.current_user())

    def test_set_user_overrides_and_resets(self) -> None:
        default = provenance.current_user()
        itc.set_user("geovana@tudelft")
        assert provenance.current_user() == "geovana@tudelft"
        itc.set_user(None)
        assert provenance.current_user() == default

    def test_set_user_rejects_empty(self) -> None:
        with pytest.raises(ProvenanceError):
            itc.set_user("")

    def test_default_mode_is_production(self) -> None:
        # REQ-08: mode="production" is the default.
        assert provenance.current_mode() == "production"

    def test_set_mode(self) -> None:
        itc.set_mode("draft")
        assert provenance.current_mode() == "draft"

    def test_set_mode_rejects_unknown(self) -> None:
        with pytest.raises(ProvenanceError):
            itc.set_mode("experimental")

    def test_top_level_exports(self) -> None:
        assert itc.set_user is provenance.set_user
        assert itc.set_mode is provenance.set_mode


class TestProvenance:
    def test_fields(self, prov: Provenance) -> None:
        assert prov.mode == "production"
        assert prov.source_files == ()
        assert prov.version_tag is None
        assert prov.created_at.tzinfo is not None

    def test_frozen(self, prov: Provenance) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            prov.mode = "draft"  # type: ignore[misc]

    def test_invalid_mode_rejected(self, prov: Provenance) -> None:
        with pytest.raises(ProvenanceError):
            dataclasses.replace(prov, mode="experimental")
