"""The round trip and the error boundary: part two of the ITA-2E lane.

Nine findings from BRF-059, writing into the schema part one defined.
The theme is narrower than part one's and just as concrete: what ITACA
writes, ITACA must be able to read, and what leaves a public boundary
must be an ``ITACAError``.

Reproduction, the shortest call that exhibited the round-trip defect
before the fix existed::

    db.to_csv(path)
    itc.load(path, dims=[...])
    # DataError: row 3 of source file roundtrip.csv: it has 2 fields
    # against a header of 1 (['# ITACA export | version: ...'])

Findings: FND-060, FND-019, FND-084, FND-059, FND-031, FND-086,
FND-087, FND-085, FND-062.
"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DataError, ITACAError
from itaca.core.varframe import VarFrame
from itaca.pproc.equations.parser import parse_itceq


@pytest.fixture
def db(tmp_path: Path) -> VarFrame:
    source = tmp_path / "run.csv"
    source.write_text("alpha,CT\n0.0,1.0\n2.0,3.0\n", encoding="utf-8")
    return itc.load(source, dims=["alpha"], comment="load")


class TestWhatItacaWritesItacaReads:
    """FND-060 and FND-019. A file produced by ``to_csv`` was not
    accepted by ``itc.load``: the provenance preamble became the header
    and ``splitlines`` broke quoted newlines."""

    def test_a_to_csv_file_loads_back(self, db: VarFrame, tmp_path: Path) -> None:
        exported = tmp_path / "roundtrip.csv"
        db.to_csv(exported)
        reloaded = itc.load(exported, dims=["alpha"])
        assert list(reloaded.dims) == ["alpha"]
        assert np.allclose(reloaded.dims["alpha"].coords, [0.0, 2.0])
        assert np.allclose(reloaded.vars["CT"].values, [1.0, 3.0])

    def test_a_quoted_newline_survives(self, tmp_path: Path) -> None:
        """The exporter emits it; the reader deleted it silently.

        Measured before the fix: a coordinate written as
        ``"front\\nrear"`` came back as ``frontrear``, because the
        reader split the text on lines before the CSV parser could see
        the quoting.
        """
        source = tmp_path / "multiline.csv"
        with open(source, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["station", "CT"])
            writer.writerow(["front\nrear", "1.0"])
            writer.writerow(["aft", "2.0"])
        loaded = itc.load(source, dims=["station"])
        assert sorted(loaded.dims["station"].coords) == ["aft", "front\nrear"]

    def test_a_quoted_cell_keeps_its_whitespace(self, tmp_path: Path) -> None:
        """FND-062's parser half. A quoted cell was stripped."""
        source = tmp_path / "padded.csv"
        with open(source, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["label", "CT"])
            writer.writerow([" padded label ", "1.0"])
            writer.writerow(["plain", "2.0"])
        loaded = itc.load(source, dims=["label"])
        assert " padded label " in list(loaded.dims["label"].coords)

    def test_an_unquoted_numeric_cell_still_tolerates_spaces(
        self, tmp_path: Path
    ) -> None:
        """Inert control: not stripping must not stop numbers parsing."""
        source = tmp_path / "spaced.csv"
        source.write_text("alpha, CT\n0.0, 1.0\n2.0, 3.0\n", encoding="utf-8")
        loaded = itc.load(source, dims=["alpha"])
        assert np.allclose(loaded.vars["CT"].values, [1.0, 3.0])

    def test_a_file_with_no_preamble_is_unaffected(self, tmp_path: Path) -> None:
        """Inert control: the skip stops at the first non-comment line."""
        source = tmp_path / "plain.csv"
        source.write_text("alpha,CT\n0.0,1.0\n", encoding="utf-8")
        assert list(itc.load(source, dims=["alpha"]).vars) == ["CT"]

    def test_the_uncertainty_survives_a_json_round_trip_of_its_own_export(
        self, db: VarFrame, tmp_path: Path
    ) -> None:
        """The export must at least be readable as strict JSON."""
        target = tmp_path / "out.json"
        db.to_json(target)
        json.loads(target.read_text(encoding="utf-8"))


class TestTheManifestIsRealCsv:
    """FND-084. The manifest was concatenated with ``','.join`` and no
    RFC 4180 escaping, so a source path containing a comma corrupted the
    row cardinality."""

    def test_a_comma_in_a_source_path_does_not_add_a_column(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "source,comma.csv"
        source.write_text("alpha,CT\n0.0,1.0\n", encoding="utf-8")
        db = itc.load({(0.5,): source}, dims=["mach"])
        target = tmp_path / "manifest.csv"
        db.manifest(target)
        with open(target, newline="", encoding="utf-8") as handle:
            rows = [row for row in csv.reader(handle) if row]
        assert len({len(row) for row in rows}) == 1


class TestSplitByCannotOverwriteASlice:
    """FND-059. The filename stem collided for distinct textual
    coordinates, and the second slice silently overwrote the first."""

    def test_colliding_stems_are_refused(self, tmp_path: Path) -> None:
        source = tmp_path / "runs.csv"
        source.write_text("s,CT\na.b,10.0\napb,20.0\n", encoding="utf-8")
        db = itc.load(source, dims=["s"])
        target = tmp_path / "split"
        with pytest.raises(DataError) as caught:
            db.to_csv(target, split_by="s")
        assert "a.b" in str(caught.value)
        assert "apb" in str(caught.value)

    def test_nothing_is_written_when_the_split_is_refused(self, tmp_path: Path) -> None:
        """A refused export must not leave half a directory behind."""
        source = tmp_path / "runs.csv"
        source.write_text("s,CT\na.b,10.0\napb,20.0\n", encoding="utf-8")
        db = itc.load(source, dims=["s"])
        target = tmp_path / "split"
        with pytest.raises(DataError):
            db.to_csv(target, split_by="s")
        assert list(target.glob("*.csv")) == []

    def test_a_non_colliding_split_is_unchanged(self, tmp_path: Path) -> None:
        """Inert control, and it pins the filenames the fix must not move."""
        source = tmp_path / "runs.csv"
        source.write_text("s,CT\n1.5,10.0\n15.0,20.0\n", encoding="utf-8")
        db = itc.load(source, dims=["s"])
        target = tmp_path / "split"
        written = db.to_csv(target, split_by="s")
        assert isinstance(written, list)
        assert sorted(path.name for path in written) == ["s_15p0.csv", "s_1p5.csv"]


class TestPublicBoundariesRaiseItacaErrors:
    """FND-031. ``itc.open`` leaked ``JSONDecodeError`` on an invalid
    JSON member and ``ValueError`` on a malformed NPZ; a plugin
    constructor returning a bad object leaked ``AttributeError``."""

    @staticmethod
    def _corrupt(archive: Path, member: str, payload: bytes) -> None:
        with zipfile.ZipFile(archive) as source:
            names = source.namelist()
            contents = {name: source.read(name) for name in names}
        contents[member] = payload
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                out.writestr(name, contents[name])

    def test_an_invalid_json_member_raises_an_itaca_error(
        self, db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "broken.itc"
        db.save(target)
        self._corrupt(target, "metadata.json", b"{not json")
        with pytest.raises(ITACAError):
            itc.open(target)

    def test_a_malformed_npz_member_raises_an_itaca_error(
        self, db: VarFrame, tmp_path: Path
    ) -> None:
        target = tmp_path / "badnpz.itc"
        db.save(target)
        self._corrupt(target, "varframe.npz", b"not an npz at all")
        with pytest.raises(ITACAError):
            itc.open(target)

    def test_a_plugin_returning_a_bad_object_raises_an_itaca_error(self) -> None:
        from itaca.pproc.registry import _REGISTRY

        _REGISTRY["ita2e_bad_plugin"] = lambda **_: None  # type: ignore[return-value]
        try:
            with pytest.raises(ITACAError):
                itc.processor("ita2e_bad_plugin")
        finally:
            del _REGISTRY["ita2e_bad_plugin"]


class TestItceqRefusesAtParseTime:
    """FND-086 and FND-087. A non-finite constant passed validation, and
    a disallowed operator was refused only when applied."""

    @staticmethod
    def _write(path: Path, body: str) -> Path:
        path.write_text(body, encoding="utf-8")
        return path

    @pytest.mark.parametrize("literal", ["nan", "inf", "-inf"])
    def test_a_non_finite_constant_is_refused(
        self, tmp_path: Path, literal: str
    ) -> None:
        source = self._write(
            tmp_path / "c.itceq",
            f'[meta]\nname = "c"\nversion = "1.0"\n\n'
            f"[constants]\nk = {literal}\n\n"
            f'[equations]\ny = "x * k"\n',
        )
        with pytest.raises(ITACAError):
            parse_itceq(source)

    def test_a_finite_constant_is_accepted(self, tmp_path: Path) -> None:
        """Inert control: the finiteness check must not refuse numbers."""
        source = self._write(
            tmp_path / "ok.itceq",
            '[meta]\nname = "ok"\nversion = "1.0"\n\n'
            "[constants]\nk = 0.1963\n\n"
            '[equations]\ny = "x * k"\n',
        )
        assert parse_itceq(source).constants["k"] == pytest.approx(0.1963)

    def test_a_disallowed_operator_is_refused_at_parse(self, tmp_path: Path) -> None:
        source = self._write(
            tmp_path / "op.itceq",
            '[meta]\nname = "op"\nversion = "1.0"\n\n[equations]\ny = "x // 2"\n',
        )
        with pytest.raises(ITACAError) as caught:
            parse_itceq(source)
        assert "//" in str(caught.value) or "FloorDiv" in str(caught.value)

    def test_an_allowed_operator_still_parses(self, tmp_path: Path) -> None:
        """Inert control, including a forward reference between equations.

        Parse-time validation must NOT resolve names: an equation may
        legitimately reference a variable an earlier equation produces,
        or one the VarFrame supplies at application time.
        """
        source = self._write(
            tmp_path / "fine.itceq",
            '[meta]\nname = "fine"\nversion = "1.0"\n\n'
            '[equations]\nq = "0.5 * rho * V**2"\nCL = "FZ / q"\n',
        )
        spec = parse_itceq(source)
        assert [equation.target for equation in spec.equations] == ["q", "CL"]


class TestJsonSaysWhichKindOfNonFinite:
    """FND-085, the author's decided call. NaN and the infinities all
    exported as ``null``, so a point never measured stopped arriving
    distinguishable from a computation that diverged."""

    def test_nan_and_the_infinities_are_told_apart(self, tmp_path: Path) -> None:
        values = np.array([[np.nan, np.inf], [-np.inf, 1.5]])
        db = itc.load(values, names=["x", "y"])
        target = tmp_path / "out.json"
        db.to_json(target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["variables"]["x"]["values"] == [None, "-Infinity"]
        assert payload["variables"]["y"]["values"] == ["Infinity", 1.5]

    def test_the_file_is_still_strict_json(self, tmp_path: Path) -> None:
        """Inert control: the tokens must be STRINGS, not bare literals.

        Writing the bare tokens would make the file something a strict
        parser refuses, which is the interoperability break the nullify
        rule was introduced to fix in the first place.
        """
        db = itc.load(np.array([[np.inf, 1.0]]), names=["x", "y"])
        target = tmp_path / "out.json"
        db.to_json(target)
        raw = target.read_text(encoding="utf-8")
        assert '"Infinity"' in raw
        json.loads(raw)  # strict by default: bare Infinity would raise


class TestJsonCarriesTheCombinedUncertainty:
    """FND-062, the author's decided call. The export omitted the
    combined uncertainty the API computes, so a consumer reimplements
    the rule and may ignore correlation."""

    def test_combined_is_exported_beside_its_components(
        self, db: VarFrame, tmp_path: Path
    ) -> None:
        frame = db.set_uncertainty({"CT": 0.1}).set_uncertainty(
            {"CT": 0.2}, component="random"
        )
        target = tmp_path / "unc.json"
        frame.to_json(target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        block = payload["uncertainty"]
        assert set(block) >= {"systematic", "random", "combined"}
        assert block["combined"]["CT"] == pytest.approx([np.sqrt(0.05), np.sqrt(0.05)])

    def test_the_composition_method_is_named(
        self, db: VarFrame, tmp_path: Path
    ) -> None:
        """A number a consumer cannot interpret is a number they will
        reimplement, which is the finding."""
        frame = db.set_uncertainty({"CT": 0.1})
        target = tmp_path / "unc.json"
        frame.to_json(target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert "combination" in payload["uncertainty"]
        assert "RSS" in payload["uncertainty"]["combination"]
