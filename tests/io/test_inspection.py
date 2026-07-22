"""Tests for db.inspect, db.summary, db.diagnostics, db.manifest.

REQ-13 (inspect), REQ-15 (manifest with the "*" convention), REQ-16
(summary), REQ-17 (diagnostics print-and-return with log=).
"""

import json
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DataError


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    lines = [",".join(header)]
    lines.extend(",".join(str(cell) for cell in row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def datapoint_db() -> object:
    arr = np.array(
        [
            [0.1, 0.0, 0.10],
            [0.1, 2.0, 0.12],
            [0.2, 0.0, 0.20],
            [0.2, 2.0, np.nan],
        ]
    )
    return itc.load(arr, names=["mach", "alpha", "CT"])


class TestInspect:
    def test_reports_candidacy(self, datapoint_db, capsys) -> None:  # type: ignore[no-untyped-def]
        result = datapoint_db.inspect()
        out = capsys.readouterr().out
        assert result is None
        assert "mach" in out and "alpha" in out and "CT" in out
        assert "dimension candidate" in out
        assert "coverage" in out.lower()

    def test_noop_on_structured(self, datapoint_db, capsys) -> None:  # type: ignore[no-untyped-def]
        structured = datapoint_db.pivot(dims=["mach", "alpha"])
        structured.inspect()
        out = capsys.readouterr().out
        assert "structured" in out.lower()


class TestSummary:
    def test_returns_and_prints(self, datapoint_db, capsys) -> None:  # type: ignore[no-untyped-def]
        summary = datapoint_db.summary()
        out = capsys.readouterr().out
        assert "production" in out
        assert "CT" in out
        assert summary.mode == "production"
        assert summary.history_index == 1
        assert summary.ram_bytes > 0
        assert dict(summary.dims) == {"datapoint": 4}
        assert "CT" in summary.variables

    def test_stats_ignore_non_finite(self, datapoint_db) -> None:  # type: ignore[no-untyped-def]
        summary = datapoint_db.summary()
        low, high, mean = summary.stats["CT"]
        assert low == pytest.approx(0.10)
        assert high == pytest.approx(0.20)
        assert mean == pytest.approx(0.14)


class TestDiagnostics:
    def test_report_attributes(self, datapoint_db, capsys) -> None:  # type: ignore[no-untyped-def]
        report = datapoint_db.diagnostics()
        out = capsys.readouterr().out
        assert "CT" in out
        assert report.missing["CT"] == 1
        assert report.n_missing == 1
        assert "CT" in report.partial_vars
        assert 0.0 < report.coverage < 1.0
        assert report.non_finite["CT"] == 0

    def test_full_coverage_frame(self) -> None:
        # REQ-76 Diagnostics edge: 100 percent coverage VarFrame.
        db = itc.load(np.array([[1.0], [2.0]]), names=["CT"])
        report = db.diagnostics()
        assert report.coverage == 1.0
        assert report.n_missing == 0
        assert report.partial_vars == ()

    def test_all_nan_variable_warns(self) -> None:
        # REQ-76 Diagnostics edge: all-NaN slice.
        arr = np.array([[1.0, np.nan], [2.0, np.nan]])
        db = itc.load(arr, names=["alpha", "CT"])
        report = db.diagnostics()
        assert any("CT" in warning for warning in report.warnings)

    def test_single_point_dimension_warns(self, tmp_path: Path) -> None:
        # REQ-76 Diagnostics edge: single-point dimension.
        path = write_csv(tmp_path / "a.csv", ["alpha", "CT"], [[0.0, 0.1]])
        db = itc.load(path, dims=["alpha"])
        report = db.diagnostics()
        assert any("alpha" in warning for warning in report.warnings)

    def test_log_file(self, datapoint_db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        log = tmp_path / "diag.log"
        datapoint_db.diagnostics(log=log)
        assert log.is_file()
        assert "CT" in log.read_text(encoding="utf-8")

    def test_to_csv_and_json(self, datapoint_db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        report = datapoint_db.diagnostics()
        csv_path = report.to_csv(tmp_path / "diag.csv")
        json_path = report.to_json(tmp_path / "diag.json")
        assert "CT" in csv_path.read_text(encoding="utf-8")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["missing"]["CT"] == 1


class TestManifest:
    def test_csv_with_swept_marker(self, tmp_path: Path) -> None:
        a = write_csv(tmp_path / "a.csv", ["alpha", "CT"], [[0.0, 0.1], [2.0, 0.2]])
        b = write_csv(tmp_path / "b.csv", ["alpha", "CT"], [[0.0, 0.3], [2.0, 0.4]])
        db = itc.load({(0.1, "*"): a, (0.2, "*"): b}, dims=["mach", "alpha"])
        out = db.manifest(tmp_path / "manifest.csv")
        text = out.read_text(encoding="utf-8")
        assert "file,mach,alpha" in text.replace(" ", "")
        assert "*" in text
        assert "a.csv" in text

    def test_json(self, tmp_path: Path) -> None:
        a = write_csv(tmp_path / "a.csv", ["CT"], [[0.1]])
        db = itc.load({(0.1,): a}, dims=["mach"])
        out = db.manifest(tmp_path / "manifest.json")
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload[0]["coords"]["mach"] == 0.1

    def test_memory_source_rejected(self, tmp_path: Path) -> None:
        db = itc.load(np.zeros((1, 1)), names=["CT"])
        with pytest.raises(DataError):
            db.manifest(tmp_path / "manifest.csv")

    def test_unknown_format_rejected(self, tmp_path: Path) -> None:
        a = write_csv(tmp_path / "a.csv", ["CT"], [[0.1]])
        db = itc.load({(0.1,): a}, dims=["mach"])
        with pytest.raises(DataError):
            db.manifest(tmp_path / "manifest.xlsx")
