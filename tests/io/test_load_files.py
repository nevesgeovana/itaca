"""Tests for itc.load file modes: single file, folder, dict.

REQ-01, REQ-02 (pattern), REQ-03 (dict mode), REQ-06 (NaN fill),
REQ-07 (provenance and history at load time).

Usage example (the contract under test)::

    db = itc.load(
        {(0.1,): folder / "m01.csv", (0.2,): folder / "m02.csv"},
        dims=["mach"],
    )
"""

from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    DataError,
    LoadCoordinateError,
    PivotDuplicateError,
)


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> Path:
    lines = [",".join(header)]
    lines.extend(",".join(str(cell) for cell in row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def sweep_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "campaign"
    folder.mkdir()
    write_csv(
        folder / "run_m01.csv",
        ["alpha", "CT"],
        [[0.0, 0.10], [2.0, 0.12]],
    )
    write_csv(
        folder / "run_m02.csv",
        ["alpha", "CT"],
        [[0.0, 0.20], [2.0, 0.22]],
    )
    return folder


class TestSingleFile:
    def test_datapoint_mode(self, tmp_path: Path) -> None:
        path = write_csv(
            tmp_path / "run.csv", ["alpha", "CT"], [[0.0, 0.1], [2.0, 0.2]]
        )
        db = itc.load(path)
        assert list(db.dims) == ["datapoint"]
        assert np.array_equal(db.vars["alpha"].values, [0.0, 2.0])
        assert db.provenance.source_files == (path,)

    def test_structured_with_dims(self, tmp_path: Path) -> None:
        path = write_csv(
            tmp_path / "run.csv", ["alpha", "CT"], [[0.0, 0.1], [2.0, 0.2]]
        )
        db = itc.load(path, dims=["alpha"])
        assert list(db.dims) == ["alpha"]
        assert np.array_equal(db.dims["alpha"].coords, [0.0, 2.0])
        assert np.array_equal(db.vars["CT"].values, [0.1, 0.2])

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DataError):
            itc.load(tmp_path / "absent.csv")

    def test_empty_cell_becomes_nan(self, tmp_path: Path) -> None:
        path = tmp_path / "run.csv"
        path.write_text("alpha,CT\n0.0,0.1\n2.0,\n", encoding="utf-8")
        db = itc.load(path)
        assert np.isnan(db.vars["CT"].values[1])

    def test_reproducibility_invariant(self, tmp_path: Path) -> None:
        # REQ-76: identical load runs yield identical state hashes,
        # invariant to user identity.
        path = write_csv(tmp_path / "run.csv", ["CT"], [[0.1]])
        db1 = itc.load(path)
        itc.set_user("someone-else@other")
        db2 = itc.load(path)
        assert db1.state_hash == db2.state_hash


class TestFolder:
    def test_loads_all_csv_files(self, sweep_folder: Path) -> None:
        db = itc.load(sweep_folder)
        assert db.dims["datapoint"].cardinality == 4
        assert len(db.provenance.source_files) == 2

    def test_glob_pattern(self, sweep_folder: Path) -> None:
        db = itc.load(sweep_folder, pattern="run_m01*.csv")
        assert db.dims["datapoint"].cardinality == 2

    def test_regex_pattern(self, sweep_folder: Path) -> None:
        # REQ-02: regular expressions are accepted too.
        db = itc.load(sweep_folder, pattern=r"run_m\d+\.csv")
        assert db.dims["datapoint"].cardinality == 4

    def test_empty_folder_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DataError):
            itc.load(tmp_path)

    def test_pattern_without_match_rejected(self, sweep_folder: Path) -> None:
        with pytest.raises(DataError):
            itc.load(sweep_folder, pattern="nothing_*.csv")


class TestDictMode:
    def test_structured_grid(self, sweep_folder: Path) -> None:
        db = itc.load(
            {
                (0.1, "*"): sweep_folder / "run_m01.csv",
                (0.2, "*"): sweep_folder / "run_m02.csv",
            },
            dims=["mach", "alpha"],
        )
        assert list(db.dims) == ["mach", "alpha"]
        assert db.shape == (2, 2)
        assert np.array_equal(db.dims["mach"].coords, [0.1, 0.2])
        assert db.vars["CT"].values[1, 1] == pytest.approx(0.22)

    def test_missing_combination_is_nan(self, tmp_path: Path) -> None:
        # REQ-06: sparse test matrices load with NaN, no error.
        a = write_csv(tmp_path / "a.csv", ["CT"], [[0.1]])
        b = write_csv(tmp_path / "b.csv", ["CT"], [[0.2]])
        db = itc.load({(0.1, 0.0): a, (0.2, 2.0): b}, dims=["mach", "alpha"])
        assert db.shape == (2, 2)
        assert np.isnan(db.vars["CT"].values[0, 1])
        assert db.vars["CT"].values[1, 1] == pytest.approx(0.2)

    def test_tuple_length_mismatch_rejected(self, tmp_path: Path) -> None:
        # REQ-03: tuple length must match dims.
        path = write_csv(tmp_path / "a.csv", ["CT"], [[0.1]])
        with pytest.raises(LoadCoordinateError):
            itc.load({(0.1, 0.0): path}, dims=["mach"])

    def test_dims_required(self, tmp_path: Path) -> None:
        path = write_csv(tmp_path / "a.csv", ["CT"], [[0.1]])
        with pytest.raises(DataError):
            itc.load({(0.1,): path})

    def test_string_coordinates(self, tmp_path: Path) -> None:
        a = write_csv(tmp_path / "a.csv", ["CT"], [[0.1]])
        b = write_csv(tmp_path / "b.csv", ["CT"], [[0.2]])
        db = itc.load({("A",): a, ("B",): b}, dims=["blade_type"])
        assert not db.dims["blade_type"].is_numeric
        assert list(db.dims["blade_type"].coords) == ["A", "B"]

    def test_duplicate_coordinates_rejected(self, tmp_path: Path) -> None:
        path = write_csv(tmp_path / "a.csv", ["CT"], [[0.1], [0.2]])
        with pytest.raises(PivotDuplicateError):
            itc.load({(0.1,): path}, dims=["mach"])

    def test_swept_dim_missing_column_rejected(self, tmp_path: Path) -> None:
        path = write_csv(tmp_path / "a.csv", ["CT"], [[0.1]])
        with pytest.raises(DataError):
            itc.load({("*",): path}, dims=["alpha"])
