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
from itaca.core.varframe import VarFrame


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
        # REQ-89: summary reports the in-memory footprint.
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
        # REQ-90 names the sparse strategy these diagnostics point at.
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


class TestDiagnosticsNonFinite:
    """FND-083: a variable with no usable value produced no warning.

    The report already COUNTED infinities, into `non_finite`, and then
    said nothing about them: an all-infinity variable came back with
    `coverage = 1.0` and an empty `warnings` tuple, while the all-NaN
    control through the same call warned twice. A count nobody is told
    to read is not a data-quality report.

    Whether an infinity should also lower COVERAGE is not decided here.
    OQ-49 carries that question, together with the reduction half.
    """

    @staticmethod
    def _var(values: list[float]) -> VarFrame:
        return itc.load(np.array(values).reshape(-1, 1), names=["CT"])

    @staticmethod
    def _infinity_warnings(report: object) -> list[str]:
        """The warnings about infinities, and no others.

        `any("CT" in w)` would be satisfied by the all-NaN branch's
        "variable 'CT' has no finite values", which fires for a
        different reason and existed before this fix. Selecting on the
        word the new warning owns is what makes these assertions
        falsifiable.
        """
        return [w for w in report.warnings if "infinite value" in w]  # type: ignore[attr-defined]

    def test_an_all_infinity_variable_is_warned_about(self) -> None:
        report = self._var([np.inf, np.inf]).diagnostics()
        matching = self._infinity_warnings(report)
        assert len(matching) == 1
        assert "'CT'" in matching[0]
        assert "2" in matching[0]

    def test_one_infinity_among_finite_values_is_warned_about(self) -> None:
        """Not only the degenerate case. One bad cell is the one a
        reader is least likely to notice unaided."""
        report = self._var([1.0, 2.0, np.inf]).diagnostics()
        matching = self._infinity_warnings(report)
        assert len(matching) == 1
        assert "'CT'" in matching[0]

    def test_a_variable_carrying_both_nan_and_infinity_warns_about_both(
        self,
    ) -> None:
        """The two counts are separate and neither absorbs the other.

        `missing` and `non_finite` partition differently, and a cell of
        each must show in both the counts and the warnings.
        """
        report = self._var([1.0, np.nan, np.inf]).diagnostics()
        assert report.missing["CT"] == 1
        assert report.non_finite["CT"] == 1
        assert len(self._infinity_warnings(report)) == 1
        assert report.partial_vars == ("CT",)

    def test_the_warning_names_the_count_and_reaches_the_printed_report(
        self,
        capsys,  # type: ignore[no-untyped-def]
    ) -> None:
        report = self._var([1.0, -np.inf, np.inf]).diagnostics()
        matching = [w for w in report.warnings if "CT" in w]
        assert len(matching) == 1
        assert "2" in matching[0]
        assert matching[0] in capsys.readouterr().out

    def test_finite_data_still_warns_about_nothing(self) -> None:
        report = self._var([1.0, 2.0]).diagnostics()
        assert not [w for w in report.warnings if "CT" in w]

    def test_the_counts_and_coverage_are_untouched(self) -> None:
        """The fix adds a warning and changes no number.

        Stated as a test rather than as a claim, because changing
        `coverage` here is exactly the tempting half OQ-49 reserves for
        the numerical-analyst seat.
        """
        report = self._var([1.0, np.inf]).diagnostics()
        assert report.coverage == 1.0
        assert report.non_finite["CT"] == 1
        assert report.missing["CT"] == 0


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
