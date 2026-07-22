"""Tests for the export family (REQ-70 to REQ-72) and the draft guard
(REQ-11, OQ-22).
"""

import json
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DraftModeExportError
from itaca.core.varframe import VarFrame


@pytest.fixture
def db() -> VarFrame:
    arr = np.array(
        [
            [0.1, 0.0, 0.10],
            [0.1, 2.0, 0.12],
            [0.2, 0.0, 0.20],
            [0.2, 2.0, 0.22],
        ]
    )
    return itc.load(arr, names=["mach", "alpha", "CT"]).pivot(dims=["mach", "alpha"])


class TestCsv:
    def test_flat_csv_with_provenance_header(
        self, db: VarFrame, tmp_path: Path
    ) -> None:
        out = db.to_csv(tmp_path / "out.csv")
        text = Path(out).read_text(encoding="utf-8")
        assert text.startswith("# ITACA export")  # REQ-71
        assert "# history[1]:" in text
        body = [line for line in text.splitlines() if not line.startswith("#")]
        assert body[0] == "mach,alpha,CT"
        assert body[1].startswith("0.1,0.0,")

    def test_split_by(self, db: VarFrame, tmp_path: Path) -> None:
        # REQ-72: one CSV per coordinate of the split dimension.
        files = db.to_csv(tmp_path, split_by="mach")
        assert len(files) == 2
        for written in files:
            assert Path(written).is_file()

    def test_draft_guard(self, db: VarFrame, tmp_path: Path) -> None:
        draft = db.demote()
        with pytest.raises(DraftModeExportError):
            draft.to_csv(tmp_path / "out.csv")
        out = draft.to_csv(tmp_path / "out.csv", allow_draft=True)
        assert "DRAFT" in Path(out).read_text(encoding="utf-8")


class TestJson:
    def test_provenance_and_history_keys(self, db: VarFrame, tmp_path: Path) -> None:
        out = db.to_json(tmp_path / "out.json")
        payload = json.loads(Path(out).read_text(encoding="utf-8"))
        assert "provenance" in payload  # REQ-71
        assert "history" in payload
        assert payload["provenance"]["mode"] == "production"
        assert payload["dims"]["mach"]["coords"] == [0.1, 0.2]
        assert payload["variables"]["CT"]["values"][0][0] == pytest.approx(0.1)

    def test_uncertainty_included_when_present(
        self, db: VarFrame, tmp_path: Path
    ) -> None:
        with_unc = db.set_uncertainty({"CT": 0.01})
        payload = json.loads(
            Path(with_unc.to_json(tmp_path / "u.json")).read_text(encoding="utf-8")
        )
        assert "uncertainty" in payload
        assert "CT" in payload["uncertainty"]["systematic"]


class TestPandasNumpy:
    def test_to_pandas_flat(self, db: VarFrame) -> None:
        frame = db.to_pandas()
        assert list(frame.columns) == ["mach", "alpha", "CT"]
        assert len(frame) == 4

    def test_to_numpy_read_only_views(self, db: VarFrame) -> None:
        # REQ-102: read-only by default, copy=True for writable.
        arrays = db.to_numpy()
        with pytest.raises(ValueError, match="read-only"):
            arrays["CT"][0, 0] = 9.9
        writable = db.to_numpy(copy=True)
        writable["CT"][0, 0] = 9.9
        assert db.vars["CT"].values[0, 0] == pytest.approx(0.1)

    def test_to_numpy_return_dims(self, db: VarFrame) -> None:
        arrays, dims = db.to_numpy(return_dims=True)
        assert np.allclose(dims["alpha"], [0.0, 2.0])
        assert arrays["CT"].shape == (2, 2)

    def test_draft_guard_on_all_exports(self, db: VarFrame) -> None:
        draft = db.demote()
        with pytest.raises(DraftModeExportError):
            draft.to_pandas()
        with pytest.raises(DraftModeExportError):
            draft.to_numpy()
