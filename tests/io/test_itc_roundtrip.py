"""Round-trip tests for the .itc native format (REQ-70, REQ-103).

Write, read, revalidate: the reopened VarFrame must reproduce the
state hash exactly, and tampered archives must fail loud with
HashMismatchError.
"""

import json
import zipfile
from pathlib import Path
from typing import Any

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


def rewrite(
    source: Path, destination: Path, edits: dict[str, object], *, reseal: bool
) -> None:
    """Copy an archive with members replaced, optionally resealing it.

    ``reseal=False`` is the ordinary tamper: the member manifest still
    describes the members as written, so ``itc.open`` refuses at the
    manifest. ``reseal=True`` recomputes ``members`` so the edit gets
    PAST the manifest and reaches the steps and state digests, which is
    the only way those two layers can be shown not to be dead code
    (DD-47).
    """
    import hashlib

    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        payloads = {name: archive.read(name) for name in names}
    for name, replacement in edits.items():
        payloads[name] = (
            replacement
            if isinstance(replacement, bytes)
            else json.dumps(replacement).encode()
        )
    if reseal:
        metadata = json.loads(payloads["metadata.json"])
        metadata["members"] = {
            name: "sha256:" + hashlib.sha256(payload).hexdigest()
            for name, payload in payloads.items()
            if name != "metadata.json"
        }
        payloads["metadata.json"] = json.dumps(metadata).encode()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            out.writestr(name, payloads[name])


def member(archive: Path, name: str) -> Any:
    with zipfile.ZipFile(archive) as source:
        return json.loads(source.read(name))


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
        # Schema 3 is the authenticated canonical payload (DD-47).
        assert metadata["schema"] == "itaca-itc/3"
        assert metadata["state_hash"] == rich_db.state_hash
        assert set(metadata["members"]) == set(archive.namelist()) - {"metadata.json"}

    @pytest.mark.parametrize("superseded", ["itaca-itc/1", "itaca-itc/2"])
    def test_a_superseded_archive_is_refused_and_names_its_migration(
        self, rich_db: VarFrame, tmp_path: Path, superseded: str
    ) -> None:
        """The acceptance criterion for the schema break (DD-47).

        Schema 1 and 2 archives used to open. They no longer do, and the
        refusal has to NAME the migration rather than fail on whatever
        happens to break first, because a user whose file stopped
        opening needs to be told what to do, not what went wrong.

        The alternative, reading them, is refused for the reason the
        schema exists: neither records a coordinate system, so a polar
        frame would come back cartesian and integrate against the wrong
        area element. That is the defect, and it must not be its own
        remedy.
        """
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        legacy = tmp_path / "legacy.itc"
        metadata = member(target, "metadata.json")
        metadata["schema"] = superseded
        rewrite(target, legacy, {"metadata.json": metadata}, reseal=False)
        with pytest.raises(DataError) as caught:
            itc.open(legacy)
        assert superseded in caught.value.obj
        assert "coordinate system" in caught.value.operation
        assert "re-export" in caught.value.fix

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

    def test_a_schema_downgrade_cannot_disable_any_check(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The schema string could gate a digest, and no longer gates one.

        Rewriting metadata.json's schema to 1 while keeping the poisoned
        step members used to skip the recipe digest entirely, because
        the check was gated on the schema and the schema is ordinary
        metadata. Three review passes found that independently.

        The gate is gone: schema 1 is not readable at all, and the steps
        digest is now unconditional. The downgrade is refused for being
        a superseded schema, and it reaches no reconstruction either
        way, which is the property the original test was defending.
        """
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        forged = tmp_path / "forged.itc"
        metadata = member(target, "metadata.json")
        metadata["schema"] = "itaca-itc/1"
        metadata.pop("steps_hash", None)
        rewrite(target, forged, {"metadata.json": metadata}, reseal=False)
        with pytest.raises(DataError) as caught:
            itc.open(forged)
        assert "itaca-itc/1" in caught.value.obj

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

    @staticmethod
    def _poison(target: Path) -> list[dict[str, Any]]:
        entries = member(target, "history.json")
        for entry in entries:
            step = entry.get("step")
            if step and step.get("call") == "compute":
                step["kwargs"]["expression"] = "CT2 = CT * 1000"
        return entries  # type: ignore[no-any-return]

    def test_an_edited_replay_step_is_caught_by_the_member_manifest(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The outer layer, and the one an ordinary edit meets first.

        The manifest is checked before any member is interpreted, so a
        poisoned recipe is refused by NAME of the member that drifted,
        which is more specific than the recipe digest's own message.
        """
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        poisoned = tmp_path / "poisoned.itc"
        rewrite(target, poisoned, {"history.json": self._poison(target)}, reseal=False)
        with pytest.raises(HashMismatchError, match=r"history\.json"):
            itc.open(poisoned)

    def test_an_edited_replay_step_is_detected_even_when_resealed(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The inner layer, and the proof it is not dead code.

        An editor who updates the member manifest but not 'steps_hash'
        gets past the manifest. The recipe digest is what catches that,
        and this is the only way to reach it now, so without this test
        the whole DD-30 guard would be unreachable and nobody would
        notice if it were deleted.
        """
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        poisoned = tmp_path / "resealed.itc"
        rewrite(target, poisoned, {"history.json": self._poison(target)}, reseal=True)
        with pytest.raises(HashMismatchError, match="recipe"):
            itc.open(poisoned)

    def test_an_edited_operation_is_detected_even_when_resealed(
        self, rich_db: VarFrame, tmp_path: Path
    ) -> None:
        """The state hash, reached the same way, for the same reason."""
        target = tmp_path / "campaign.itc"
        rich_db.save(target)
        entries = member(target, "history.json")
        entries[0]["operation"] = "load(FORGED)"
        forged = tmp_path / "forged_op.itc"
        rewrite(target, forged, {"history.json": entries}, reseal=True)
        with pytest.raises(HashMismatchError, match="state-hash drift"):
            itc.open(forged)

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
        metadata = member(target, "metadata.json")
        metadata["schema"] = "itaca-itc/4"
        entries = member(target, "history.json")
        for entry in entries:
            if entry.get("step"):
                entry["step"]["call"] = "not_a_real_operation"
        rewrite(
            target,
            future,
            {"metadata.json": metadata, "history.json": entries},
            reseal=False,
        )
        # Both defects are present; the schema answer must win, because a
        # reader cannot act on a replay-step complaint about a format
        # their build was never able to read.
        with pytest.raises(DataError, match=r"unknown \.itc schema"):
            itc.open(future)

    def test_the_migration_refusal_claims_nothing_about_replay_steps(
        self, tmp_path: Path
    ) -> None:
        """The refusal must not assert something the archive does not do.

        The predecessor of this test guarded a message that had to
        choose between two reasons and could name the wrong one. That
        branch is gone with the schema gate, and what replaces it is a
        migration message that could drift into naming the recipe, which
        has nothing to do with why the archive is refused.
        """
        csv = tmp_path / "run.csv"
        csv.write_text("alpha,CT\n0.0,1.0\n2.0,3.0\n", encoding="utf-8")
        db = itc.load(csv, dims=["alpha"])
        target = tmp_path / "plain.itc"
        db.save(target)
        stripped = tmp_path / "stripped.itc"
        metadata = member(target, "metadata.json")
        metadata["schema"] = "itaca-itc/2"
        rewrite(target, stripped, {"metadata.json": metadata}, reseal=False)
        with pytest.raises(DataError) as excinfo:
            itc.open(stripped)
        assert "replay step" not in excinfo.value.operation
        assert "coordinate system" in excinfo.value.operation

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
        entries = member(target, "history.json")
        for entry in entries:
            if entry.get("step"):
                entry["step"]["kwargs"]["fill"] = float("inf")
        # Resealed: the member manifest would otherwise refuse this
        # first, and the wording under test belongs to the READ path of
        # the steps digest, which is behind it.
        rewrite(target, edited, {"history.json": entries}, reseal=True)
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
        assert literals == {"itaca-itc/1", "itaca-itc/2", "itaca-itc/3"}, literals
        assert all("\\" not in value and "\x01" not in value for value in literals)
