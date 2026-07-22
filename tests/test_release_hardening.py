"""Release-hardening sweep for M0 (REQ-76 rows not covered elsewhere).

Each test cites the REQ-76 edge-case row it closes; rows belonging to
v0.2.0+ features (interpolate, concat, diff, average, axes, pipeline)
ship with those features.
"""

from pathlib import Path

import numpy as np
import pytest

import itaca as itc


class TestLoadEdges:
    def test_empty_varframe_from_header_only_csv(self, tmp_path: Path) -> None:
        # REQ-76 Load: the empty VarFrame.
        path = tmp_path / "empty.csv"
        path.write_text("alpha,CT\n", encoding="utf-8")
        db = itc.load(path)
        assert db.dims["datapoint"].cardinality == 0
        assert db.vars["CT"].values.shape == (0,)
        assert db.state_hash
        report = db.diagnostics()
        assert report.coverage == 1.0


class TestReproducibility:
    def test_same_bytes_from_different_folders_hash_equal(self, tmp_path: Path) -> None:
        # REQ-103: source paths are excluded from the state hash, so
        # identical bytes loaded from different locations agree.
        content = "alpha,CT\n0.0,0.1\n2.0,0.2\n"
        first = tmp_path / "a" / "run.csv"
        second = tmp_path / "b" / "renamed.csv"
        for path in (first, second):
            path.parent.mkdir()
            path.write_text(content, encoding="utf-8")
        db1 = itc.load(first, dims=["alpha"])
        db2 = itc.load(second, dims=["alpha"])
        assert db1.state_hash == db2.state_hash
        assert db1.provenance.source_hash == db2.provenance.source_hash

    def test_operate_chain_reproducible(self, tmp_path: Path) -> None:
        # REQ-76 Reproducibility: two identical load-and-operate runs.
        path = tmp_path / "run.csv"
        path.write_text("alpha,CT\n0.0,0.1\n2.0,0.2\n", encoding="utf-8")

        def pipeline() -> str:
            db = itc.load(path, dims=["alpha"])
            db = db.set_uncertainty({"CT": 0.01}, comment="cal")
            db = db.compute("CT2 = CT * 2")
            return db.state_hash

        assert pipeline() == pipeline()


class TestPivotEdges:
    def test_auto_detect_reports_resolved_dims(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # REQ-76 Pivot: auto_detect on ambiguous candidates gives
        # feedback naming the resolved dimension list.
        arr = np.column_stack(
            [
                np.repeat([0.1, 0.2], 2),
                np.tile([0.0, 2.0], 2),
                np.array([1.0, 2.0, 3.0, 4.0]),
            ]
        )
        db = itc.load(arr, names=["mach", "alpha", "CT"])
        structured = db.pivot(auto_detect=True)
        out = capsys.readouterr().out
        assert "resolved dims" in out
        assert set(structured.dims) == {"mach", "alpha"}


class TestComputeEdges:
    def test_symbolic_and_mcm_on_same_expression(self, tmp_path: Path) -> None:
        # REQ-76 Compute: both methods on the same expression; in M0
        # the mcm branch fails loud pointing at v0.3.0 (DD-21).
        path = tmp_path / "run.csv"
        path.write_text("alpha,CT\n0.0,0.1\n", encoding="utf-8")
        db = itc.load(path, dims=["alpha"]).set_uncertainty({"CT": 0.01})
        symbolic = db.compute("f = CT * 2", method="symbolic")
        assert symbolic.uncertainty is not None
        with pytest.raises(itc.ITACAError):
            db.compute("f = CT * 2", method="mcm")
