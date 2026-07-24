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
from itaca.core.errors import DataError, DraftModeExportError, HashMismatchError
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

    def test_a_schema_1_archive_still_opens(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The CHANGELOG promises it; nothing proved it.

        A v0.1.0 archive has no per-entry 'step' and no 'steps_hash'.
        Downgrading a schema-2 archive reproduces exactly that shape, so
        the compatibility claim is tested rather than asserted.
        """
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        legacy = tmp_path / "legacy.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(legacy, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "metadata.json":
                    metadata = json.loads(data)
                    metadata["schema"] = "itaca-itc/1"
                    metadata.pop("steps_hash", None)
                    data = json.dumps(metadata).encode()
                elif item == "history.json":
                    entries = json.loads(data)
                    for entry in entries:
                        entry.pop("step", None)
                    data = json.dumps(entries).encode()
                out.writestr(item, data)
        reopened = itc.open(legacy)
        assert reopened.state_hash == rich_db.state_hash

    def test_an_archive_with_no_state_hash_is_named_not_a_key_error(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """A truncated metadata block must not surface as KeyError."""
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        broken = tmp_path / "broken.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "metadata.json":
                    metadata = json.loads(data)
                    metadata.pop("state_hash")
                    data = json.dumps(metadata).encode()
                out.writestr(item, data)
        with pytest.raises(DataError, match="no 'state_hash'"):
            itc.open(broken)

    def test_a_schema_downgrade_cannot_disable_the_steps_check(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The schema string is not covered by any digest, so it cannot gate one.

        Rewriting metadata.json's schema to 1 while keeping the poisoned
        step members skipped the recipe digest entirely, and the state
        hash still matched because steps are deliberately outside it.
        The tampered recipe then loaded and would steer the next replay.
        Three review passes found this independently.
        """
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        forged = tmp_path / "forged.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(forged, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "metadata.json":
                    metadata = json.loads(data)
                    metadata["schema"] = "itaca-itc/1"
                    metadata.pop("steps_hash", None)
                    data = json.dumps(metadata).encode()
                out.writestr(item, data)
        with pytest.raises(DataError, match="carries replay steps"):
            itc.open(forged)

    def test_a_missing_steps_hash_is_refused(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The schema 2 digest must be present, not merely checked when there."""
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        broken = tmp_path / "nodigest.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "metadata.json":
                    metadata = json.loads(data)
                    metadata.pop("steps_hash")
                    data = json.dumps(metadata).encode()
                out.writestr(item, data)
        with pytest.raises(DataError, match="no 'steps_hash'"):
            itc.open(broken)

    def test_an_edited_replay_step_is_detected(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The digest exists for exactly this, and nothing exercised it."""
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        poisoned = tmp_path / "poisoned.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(poisoned, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "history.json":
                    entries = json.loads(data)
                    for entry in entries:
                        step = entry.get("step")
                        if step and step.get("call") == "compute":
                            step["kwargs"]["expression"] = "CT2 = CT * 1000"
                    data = json.dumps(entries).encode()
                out.writestr(item, data)
        with pytest.raises(HashMismatchError, match="recipe"):
            itc.open(poisoned)

    def test_a_non_finite_replay_argument_is_named_at_save(
        self, tmp_path: Path
    ) -> None:
        """db.save must not raise a bare ValueError on a legal fill (REQ-35)."""
        csv = tmp_path / "run.csv"
        csv.write_text("alpha,CT\n0.0,1.0\n2.0,3.0\n", encoding="utf-8")
        db = itc.load(csv, dims=["alpha"])
        db = db.compute("CT2 = CT * 2", where="CT > 2", fill=float("inf"))
        with pytest.raises(DataError, match="no RFC 8259 JSON representation"):
            db.save(tmp_path / "campaign.itc")

    def test_an_unknown_schema_is_refused_before_anything_is_rebuilt(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The guard this commit moved had no test, so it was deletable.

        An archive from a future build must be named as such, not
        reconstructed under this build's assumptions and then rejected
        for whatever happens to break first.
        """
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        future = tmp_path / "future.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(future, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "metadata.json":
                    metadata = json.loads(data)
                    metadata["schema"] = "itaca-itc/3"
                    data = json.dumps(metadata).encode()
                elif item == "history.json":
                    entries = json.loads(data)
                    for entry in entries:
                        if entry.get("step"):
                            entry["step"]["call"] = "not_a_real_operation"
                    data = json.dumps(entries).encode()
                out.writestr(item, data)
        # Both defects are present; the schema answer must win, because a
        # reader cannot act on a replay-step complaint about a format
        # their build was never able to read.
        with pytest.raises(DataError, match=r"unknown \.itc schema"):
            itc.open(future)

    def test_a_schema_2_archive_without_steps_is_named_correctly(
        self, tmp_path: Path
    ) -> None:
        """The refusal must not assert something the archive does not do."""
        csv = tmp_path / "run.csv"
        csv.write_text("alpha,CT\n0.0,1.0\n2.0,3.0\n", encoding="utf-8")
        db = itc.load(csv, dims=["alpha"])
        target = tmp_path / "plain.itc"
        db.save(target)
        stripped = tmp_path / "stripped.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(stripped, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "metadata.json":
                    metadata = json.loads(data)
                    metadata.pop("steps_hash")
                    data = json.dumps(metadata).encode()
                out.writestr(item, data)
        with pytest.raises(DataError, match="declares schema") as excinfo:
            itc.open(stripped)
        assert "carries replay steps" not in excinfo.value.operation

    def test_a_non_finite_argument_in_a_read_archive_is_worded_for_reading(
        self, tmp_path: Path
    ) -> None:
        """json.loads accepts Infinity, so the read path reaches the digest.

        Telling a user who opened a file to "pass a finite number for
        that argument" names an operation they never attempted.
        """
        csv = tmp_path / "run.csv"
        csv.write_text("alpha,CT\n0.0,1.0\n2.0,3.0\n", encoding="utf-8")
        db = itc.load(csv, dims=["alpha"]).compute("CT2 = CT * 2")
        target = tmp_path / "campaign.itc"
        db.save(target)
        edited = tmp_path / "edited.itc"
        with (
            zipfile.ZipFile(target) as source,
            zipfile.ZipFile(edited, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            for item in source.namelist():
                data = source.read(item)
                if item == "history.json":
                    text = data.decode()
                    entries = json.loads(text)
                    for entry in entries:
                        if entry.get("step"):
                            entry["step"]["kwargs"]["fill"] = float("inf")
                    data = json.dumps(entries).encode()
                out.writestr(item, data)
        with pytest.raises(DataError) as excinfo:
            itc.open(edited)
        assert "cannot be written" not in excinfo.value.operation
        assert "re-export" in excinfo.value.fix

    def test_the_save_refusal_names_the_offending_step(self, tmp_path: Path) -> None:
        """ "That argument" is unactionable across forty history entries."""
        csv = tmp_path / "run.csv"
        csv.write_text("alpha,CT\n0.0,1.0\n2.0,3.0\n", encoding="utf-8")
        db = itc.load(csv, dims=["alpha"])
        db = db.compute("CT2 = CT * 2", where="CT > 2", fill=float("inf"))
        with pytest.raises(DataError) as excinfo:
            db.save(tmp_path / "campaign.itc")
        assert "fill" in excinfo.value.obj
        assert "compute" in excinfo.value.obj


class TestSchemaLiterals:
    """Pin the schema strings by parsing, not by reading them.

    Twice in one session a review pass reported one of these literals as
    containing a backslash escape (`itaca-itc\1`, an octal escape for
    U+0001) and concluded the schema 1 read path was dead code. The byte
    is a forward slash; the search tool renders it both ways on Windows.
    Acting on that finding would have introduced the defect it
    described.

    A charter note telling reviewers to check bytes is documentation,
    not a guard. This is the guard: the claim is now mechanically
    refutable, because a build where it were true is a build where this
    test is already red.
    """

    def test_every_schema_literal_is_exactly_as_written(self) -> None:
        import ast

        source = Path(itc.io.formats.itc.__file__).read_text(encoding="utf-8")
        literals = {
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("itaca-itc")
        }
        assert literals == {"itaca-itc/1", "itaca-itc/2"}, literals
        assert all("\\" not in value and "\x01" not in value for value in literals)
