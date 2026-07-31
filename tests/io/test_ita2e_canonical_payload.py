"""The authenticated canonical payload: part one of the ITA-2E lane.

Ten findings from BRF-059, one design: everything that decides how a
``.itc`` behaves when reopened is inside a digest, and every byte of the
archive is covered by a manifest.

The tampering cases are proved BY TAMPERING. Each rewrites one member of
a written archive, reopens it, and asserts the refusal. Asserting that
the manifest covers the member would test the manifest, not the guard.

Reproduction, the shortest call that exhibited the critical defect
before the fix existed::

    db = itc.load(csv, dims=["alpha"]).demote()
    db.save(target, allow_draft=True)
    # edit only provenance.json inside the ZIP, draft -> production
    itc.open(target)          # ACCEPTED, hash still valid
    itc.open(target).to_json(out)   # ALLOWED, no allow_draft needed

Findings: FND-089, FND-037, FND-038, FND-036, FND-049, FND-047,
FND-048, FND-071, FND-091, FND-063.
"""

from __future__ import annotations

import dataclasses
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import itaca as itc
from itaca.core.coords import Cartesian, Polar
from itaca.core.dimension import Dimension
from itaca.core.errors import DataError, HashMismatchError
from itaca.core.history import compute_state_hash
from itaca.core.pipeline import Pipeline, PipelineStep
from itaca.core.provenance import Provenance
from itaca.core.varframe import VarFrame


def rewrite_member(archive: Path, member: str, payload: bytes) -> None:
    """Replace one member of a ZIP, leaving every other byte alone.

    This is the tampering machinery the acceptance criterion asks for:
    the refusal has to be produced by an edited file, not asserted from
    the manifest's existence.
    """
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        contents = {name: source.read(name) for name in names}
    contents[member] = payload
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as target:
        for name in names:
            target.writestr(name, contents[name])


def drop_member(archive: Path, member: str) -> None:
    with zipfile.ZipFile(archive) as source:
        names = [name for name in source.namelist() if name != member]
        contents = {name: source.read(name) for name in names}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as target:
        for name in names:
            target.writestr(name, contents[name])


def add_member(archive: Path, member: str, payload: bytes) -> None:
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        contents = {name: source.read(name) for name in names}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as target:
        for name in names:
            target.writestr(name, contents[name])
        target.writestr(member, payload)


@pytest.fixture
def simple_db(tmp_path: Path) -> VarFrame:
    csv = tmp_path / "run.csv"
    csv.write_text("alpha,CT\n0.0,1.0\n2.0,3.0\n", encoding="utf-8")
    return itc.load(csv, dims=["alpha"], comment="load")


class TestModeIsAuthenticated:
    """FND-089, the critical one.

    ``Provenance.mode`` sat outside the authenticated state, so editing
    one JSON string inside the ZIP turned a draft file into production
    and it reopened with a valid state hash.
    """

    def test_editing_only_the_mode_member_is_refused(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        draft = simple_db.demote()
        target = tmp_path / "draft.itc"
        draft.save(target, allow_draft=True)
        payload = json.loads(
            zipfile.ZipFile(target).read("provenance.json").decode("utf-8")
        )
        payload["mode"] = "production"
        payload.pop("warning", None)
        rewrite_member(target, "provenance.json", json.dumps(payload).encode())
        with pytest.raises(HashMismatchError):
            itc.open(target)

    def test_mode_participates_in_the_state_hash(self, simple_db: VarFrame) -> None:
        draft = dataclasses.replace(
            simple_db,
            provenance=dataclasses.replace(simple_db.provenance, mode="draft"),
        )
        assert draft.state_hash != simple_db.state_hash


class TestCoordSystemIsStateAndSurvives:
    """FND-037. Cartesian and Polar shared a hash and a Polar frame
    reopened Cartesian."""

    def test_cartesian_and_polar_do_not_share_a_state_hash(
        self, simple_db: VarFrame
    ) -> None:
        polar = dataclasses.replace(simple_db, coords=Polar())
        assert simple_db.state_hash != polar.state_hash

    def test_a_polar_frame_reopens_polar(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        polar = dataclasses.replace(simple_db, coords=Polar())
        target = tmp_path / "polar.itc"
        polar.save(target)
        assert isinstance(itc.open(target).coords, Polar)

    def test_a_cartesian_frame_reopens_cartesian(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "cart.itc"
        simple_db.save(target)
        assert isinstance(itc.open(target).coords, Cartesian)


class TestEveryMemberIsCovered:
    """FND-038 and what completes FND-089: only the final state hash and
    the replay-steps digest were authenticated."""

    def test_a_forged_history_entry_hash_is_refused(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "forged.itc"
        simple_db.save(target)
        entries = json.loads(
            zipfile.ZipFile(target).read("history.json").decode("utf-8")
        )
        entries[-1]["state_hash"] = "0" * 64
        rewrite_member(target, "history.json", json.dumps(entries).encode())
        with pytest.raises(HashMismatchError):
            itc.open(target)

    def test_an_edited_variable_metadata_member_is_refused(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "meta.itc"
        simple_db.save(target)
        payload = json.loads(
            zipfile.ZipFile(target).read("vars_meta.json").decode("utf-8")
        )
        payload["CT"]["unit"] = "smoot"
        rewrite_member(target, "vars_meta.json", json.dumps(payload).encode())
        with pytest.raises(HashMismatchError):
            itc.open(target)

    def test_a_removed_member_is_refused(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "short.itc"
        simple_db.save(target)
        drop_member(target, "vars_meta.json")
        with pytest.raises((DataError, HashMismatchError)):
            itc.open(target)

    def test_an_added_member_is_refused(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "extra.itc"
        simple_db.save(target)
        add_member(target, "smuggled.json", b"{}")
        with pytest.raises((DataError, HashMismatchError)):
            itc.open(target)

    def test_an_intact_archive_still_opens(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        """The inert control: the guard must refuse tampering, not files."""
        target = tmp_path / "intact.itc"
        simple_db.save(target)
        assert itc.open(target).state_hash == simple_db.state_hash


class TestCanonicalFraming:
    """FND-036. A bare separator with ``(comment or '')`` collided a
    missing comment with an empty one, and content carrying the
    separator crossed field boundaries."""

    @staticmethod
    def _base() -> dict[str, Any]:
        return {
            "dims": {"x": Dimension(name="x", coords=np.array([0.0, 1.0]))},
            "variables": {},
            "coords": Cartesian(),
            "mode": "production",
        }

    def test_a_missing_comment_is_not_an_empty_one(self) -> None:
        absent = compute_state_hash(operations=(("op", None),), **self._base())
        empty = compute_state_hash(operations=(("op", ""),), **self._base())
        assert absent != empty

    def test_content_cannot_cross_a_field_boundary(self) -> None:
        left = compute_state_hash(operations=(("op1\x1fx", "y"),), **self._base())
        right = compute_state_hash(operations=(("op1", "x\x1fy"),), **self._base())
        assert left != right

    def test_a_comment_still_enters_the_hash(self) -> None:
        """Inert control: framing must not stop the field mattering."""
        one = compute_state_hash(operations=(("op", "a"),), **self._base())
        two = compute_state_hash(operations=(("op", "b"),), **self._base())
        assert one != two


class TestMetadataOrderIsNotIdentity:
    """FND-049. ``set_metadata`` sorted the outer mapping and embedded
    the inner one in insertion order."""

    def test_inner_field_order_does_not_change_the_state_hash(
        self, simple_db: VarFrame
    ) -> None:
        unit_first = simple_db.set_metadata(
            {"CT": {"unit": "deg", "description": "angle"}}
        )
        description_first = simple_db.set_metadata(
            {"CT": {"description": "angle", "unit": "deg"}}
        )
        assert unit_first.state_hash == description_first.state_hash

    def test_a_changed_value_still_changes_the_hash(self, simple_db: VarFrame) -> None:
        """Inert control: order-insensitivity must not become blindness."""
        degrees = simple_db.set_metadata({"CT": {"unit": "deg"}})
        radians = simple_db.set_metadata({"CT": {"unit": "rad"}})
        assert degrees.state_hash != radians.state_hash


class TestSourceHashIsCanonical:
    """FND-047. Names were comma-joined without framing and raw array
    bytes carried no dtype."""

    def test_variable_names_cannot_collide_across_the_delimiter(self) -> None:
        values = np.array([[1.0, 2.0], [3.0, 4.0]])
        left = itc.load(values, names=["a,b", "c"])
        right = itc.load(values, names=["a", "b,c"])
        assert left.provenance.source_hash != right.provenance.source_hash

    def test_equivalent_loads_agree(self) -> None:
        """Two loads that produce the identical frame must agree.

        The columns are cast to float either way, so an integer source
        and a float source give the same values and the same dtype; the
        digest read the raw input bytes instead and diverged.
        """
        integers = itc.load(np.array([[1, 2], [3, 4]]), names=["a", "b"])
        floats = itc.load(np.array([[1.0, 2.0], [3.0, 4.0]]), names=["a", "b"])
        assert np.array_equal(integers.vars["a"].values, floats.vars["a"].values)
        assert integers.vars["a"].values.dtype == floats.vars["a"].values.dtype
        assert integers.provenance.source_hash == floats.provenance.source_hash

    def test_different_data_still_gives_a_different_hash(self) -> None:
        """Inert control: canonical framing must not flatten the digest."""
        one = itc.load(np.array([[1.0, 2.0]]), names=["a", "b"])
        two = itc.load(np.array([[1.0, 9.0]]), names=["a", "b"])
        assert one.provenance.source_hash != two.provenance.source_hash


class TestFrozenObjectsOwnTheirContainers:
    """FND-048. ``Pipeline(steps=<list>)`` and
    ``Provenance(source_files=<list>)`` stayed bound to the caller's
    list, so an external mutation changed a frozen object."""

    def test_a_pipeline_does_not_observe_an_external_append(self) -> None:
        steps = [PipelineStep(call="smooth", kwargs={"along": "x"})]
        pipeline = Pipeline(steps=steps)  # type: ignore[arg-type]
        before = len(pipeline)
        steps.append(PipelineStep(call="diff", kwargs={"along": "x"}))
        assert len(pipeline) == before

    def test_provenance_does_not_observe_an_external_append(self) -> None:
        files = [Path("a.csv")]
        provenance = Provenance(
            itaca_version="0.0.0",
            user="tester@host",
            created_at=itc.load(np.array([[1.0]]), names=["a"]).provenance.created_at,
            source_files=files,  # type: ignore[arg-type]
            source_hash="0" * 64,
            mode="production",
        )
        before = len(provenance.source_files)
        files.append(Path("b.csv"))
        assert len(provenance.source_files) == before


class TestReadOnlyArraysCannotBeReopened:
    """FND-071. ``setflags(write=True)`` re-enabled writes on a public
    array, mutating state with a changed hash and no History entry."""

    def test_a_variable_array_refuses_to_become_writeable(
        self, simple_db: VarFrame
    ) -> None:
        values = simple_db.vars["CT"].values
        with pytest.raises(ValueError):
            values.setflags(write=True)

    def test_a_dimension_array_refuses_to_become_writeable(
        self, simple_db: VarFrame
    ) -> None:
        coords = simple_db.dims["alpha"].coords
        with pytest.raises(ValueError):
            coords.setflags(write=True)

    def test_an_uncertainty_array_refuses_to_become_writeable(
        self, simple_db: VarFrame
    ) -> None:
        db = simple_db.set_uncertainty({"CT": 0.1})
        assert db.uncertainty is not None
        with pytest.raises(ValueError):
            db.uncertainty.systematic["CT"].setflags(write=True)

    def test_a_copy_is_still_writeable(self, simple_db: VarFrame) -> None:
        """Inert control: the guard protects the frame, not the caller."""
        assert simple_db.vars["CT"].values.copy().flags.writeable


class TestCoordinateDtypeSurvives:
    """FND-091. Coordinates were serialized by ``tolist()`` with no
    dtype and rebuilt as float64, so an INTACT float32 archive raised
    HashMismatchError on reopen."""

    @pytest.mark.parametrize(
        ("dtype", "values"),
        [
            ("float32", [0.5, 0.8]),
            ("float64", [0.5, 0.8]),
            # Integer coordinates need integer VALUES: [0.5, 0.8] cast to
            # int32 is [0, 0], which expand refuses as duplicates long
            # before the dtype could reach the archive.
            ("int32", [1, 2]),
            ("int64", [1, 2]),
        ],
    )
    def test_an_intact_archive_reopens_with_its_dtype(
        self, simple_db: VarFrame, tmp_path: Path, dtype: str, values: list[float]
    ) -> None:
        expanded = simple_db.expand("mach", np.array(values, dtype=dtype))
        target = tmp_path / f"{dtype}.itc"
        expanded.save(target)
        reopened = itc.open(target)
        assert reopened.dims["mach"].coords.dtype == np.dtype(dtype)
        assert reopened.state_hash == expanded.state_hash

    def test_string_coordinates_survive(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        expanded = simple_db.expand("blade", np.array(["a", "bb"]))
        target = tmp_path / "text.itc"
        expanded.save(target)
        reopened = itc.open(target)
        assert list(reopened.dims["blade"].coords) == ["a", "bb"]
        assert reopened.state_hash == expanded.state_hash


class TestHistoryRecordsWhatWasDecided:
    """FND-063. A resolved axis was omitted and a no-op was unrecorded,
    while the same call that removed nothing WAS recorded."""

    def test_drop_correlation_records_a_no_op(self, simple_db: VarFrame) -> None:
        assert simple_db.correlation is None
        dropped = simple_db.drop_correlation()
        assert len(dropped.history) == len(simple_db.history) + 1
        assert dropped.history.last is not None
        assert dropped.history.last.name == "drop_correlation"


class TestTheMigrationIsNamed:
    """The acceptance criterion: an archive written by the previous
    version either still opens or is refused with a message naming the
    migration. Silent reinterpretation is FND-037 and must not be its
    remedy."""

    def test_a_schema_two_archive_is_refused_by_name(
        self, simple_db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "old.itc"
        simple_db.save(target)
        metadata = json.loads(
            zipfile.ZipFile(target).read("metadata.json").decode("utf-8")
        )
        metadata["schema"] = "itaca-itc/2"
        rewrite_member(target, "metadata.json", json.dumps(metadata).encode())
        with pytest.raises(DataError) as caught:
            itc.open(target)
        message = str(caught.value)
        assert "itaca-itc/2" in message
        assert "re-export" in message
