"""Round-trip tests for the .itc native format (REQ-70, REQ-103).

Write, read, revalidate: the reopened VarFrame must reproduce the
state hash exactly, and tampered archives must fail loud with
HashMismatchError.
"""

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DraftModeExportError, HashMismatchError
from itaca.core.varframe import VarFrame


@pytest.fixture
def rich_db(tmp_path: Path) -> VarFrame:
    csv = tmp_path / "run.csv"
    csv.write_text("alpha,CT\n0.0,1.0\n2.0,\n4.0,5.0\n", encoding="utf-8")
    db = itc.load(csv, dims=["alpha"], version="v1.0-raw", comment="load")
    db = db.set_uncertainty({"CT": 0.1}, comment="cal")
    db = db.set_uncertainty({"CT": 0.05}, component="random")
    db = db.compute("CT2 = CT * 2")
    db = db.set_correlation({("CT", "CT2"): 0.5})
    return db.fill(along="alpha", method="nearest", comment="gap at 2 deg")


class TestRoundTrip:
    def test_state_hash_survives(self, rich_db: VarFrame, tmp_path: Path) -> None:
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        reopened = itc.open(target)
        assert reopened.state_hash == rich_db.state_hash

    def test_content_survives(self, rich_db: VarFrame, tmp_path: Path) -> None:
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        reopened = itc.open(target)
        assert list(reopened.dims) == ["alpha"]
        assert np.allclose(reopened.vars["CT"].values, rich_db.vars["CT"].values)
        assert reopened.uncertainty is not None
        assert np.allclose(reopened.uncertainty.systematic["CT"], 0.1)
        assert np.allclose(reopened.uncertainty.random["CT"], 0.05)
        assert reopened.correlation is not None
        assert reopened.correlation.get("CT", "CT2") == 0.5
        assert reopened.tags is not None
        assert list(reopened.tags.tags["CT"]) == [0, 1, 0]

    def test_history_and_comments_survive(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        # REQ-76 History edge: comment preserved through .itc round trip.
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        reopened = itc.open(target)
        assert len(reopened.history) == len(rich_db.history)
        assert reopened.history[0].comment == "load"
        assert reopened.history.last is not None
        assert reopened.history.last.comment == "gap at 2 deg"

    def test_provenance_survives(self, rich_db: VarFrame, tmp_path: Path) -> None:
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        reopened = itc.open(target)
        assert reopened.provenance.version_tag == "v1.0-raw"
        assert reopened.provenance.user == rich_db.provenance.user
        assert reopened.provenance.source_hash == rich_db.provenance.source_hash
        assert reopened.provenance.source_coords is not None

    def test_non_numeric_dimension_survives(self, tmp_path: Path) -> None:
        a = tmp_path / "a.csv"
        b = tmp_path / "b.csv"
        a.write_text("CT\n1.0\n", encoding="utf-8")
        b.write_text("CT\n2.0\n", encoding="utf-8")
        db = itc.load({("A",): a, ("B",): b}, dims=["blade"])
        target = tmp_path / "blades.itc"
        db.save(target)
        reopened = itc.open(target)
        assert not reopened.dims["blade"].is_numeric
        assert list(reopened.dims["blade"].coords) == ["A", "B"]
        assert reopened.state_hash == db.state_hash


class TestGuards:
    def test_draft_save_blocked(self, rich_db: VarFrame, tmp_path: Path) -> None:
        draft = rich_db.demote()
        with pytest.raises(DraftModeExportError):
            draft.save(tmp_path / "draft.itc")

    def test_allow_draft_embeds_warning(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "draft.itc"
        rich_db.demote().save(target, allow_draft=True)
        with zipfile.ZipFile(target) as archive:
            provenance = json.loads(archive.read("provenance.json"))
        assert "DRAFT" in provenance["warning"]

    def test_tampered_archive_rejected(self, rich_db: VarFrame, tmp_path: Path) -> None:
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        tampered = tmp_path / "tampered.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(tampered, "w") as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "history.json":
                    entries = json.loads(data)
                    entries[0]["operation"] = "load(FORGED)"
                    data = json.dumps(entries).encode()
                out.writestr(item, data)
        with pytest.raises(HashMismatchError):
            itc.open(tampered)

    def test_metadata_schema_present(self, rich_db: VarFrame, tmp_path: Path) -> None:
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        with zipfile.ZipFile(target) as archive:
            metadata = json.loads(archive.read("metadata.json"))
        # Schema 2 adds the per-entry replay step to history.json (REQ-54).
        assert metadata["schema"] == "itaca-itc/2"
        assert metadata["state_hash"] == rich_db.state_hash
