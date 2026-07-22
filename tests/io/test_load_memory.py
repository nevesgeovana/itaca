"""Tests for itc.load memory modes: NumPy array and pandas DataFrame.

REQ-01 (datapoint mode), REQ-04 (NumPy), REQ-05 (pandas), REQ-07
(provenance at load time).

Usage example (the contract under test)::

    import numpy as np
    import itaca as itc

    db = itc.load(np.array([[0.0, 1.0], [2.0, 3.0]]), names=["alpha", "CT"])
    assert "datapoint" in db.dims
"""

import numpy as np
import pandas as pd
import pytest

import itaca as itc
from itaca.core.errors import DataError


class TestNumpyMode:
    def test_datapoint_mode(self) -> None:
        arr = np.array([[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]])
        db = itc.load(arr, names=["alpha", "CT"])
        assert list(db.dims) == ["datapoint"]
        assert db.dims["datapoint"].cardinality == 3
        assert list(db.vars) == ["alpha", "CT"]
        assert np.array_equal(db.vars["CT"].values, [1.0, 3.0, 5.0])

    def test_history_starts_at_load(self) -> None:
        # REQ-07: the load operation is History index 1.
        db = itc.load(np.zeros((2, 1)), names=["CT"])
        assert len(db.history) == 1
        assert db.history[0].index == 1
        assert db.history[0].operation.startswith("load(")

    def test_provenance_recorded(self) -> None:
        itc.set_user("tester@host")
        db = itc.load(np.zeros((2, 1)), names=["CT"], version="v1.0-raw")
        assert db.provenance.user == "tester@host"
        assert db.provenance.mode == "production"
        assert db.provenance.version_tag == "v1.0-raw"
        assert db.provenance.source_files == ()
        assert len(db.provenance.source_hash) == 64

    def test_names_length_mismatch_rejected(self) -> None:
        # REQ-76 Load edge: NumPy array with mismatched names.
        with pytest.raises(DataError):
            itc.load(np.zeros((2, 2)), names=["only_one"])

    def test_non_2d_rejected(self) -> None:
        with pytest.raises(DataError):
            itc.load(np.zeros(3), names=["CT"])

    def test_names_required(self) -> None:
        with pytest.raises(DataError):
            itc.load(np.zeros((2, 2)))

    def test_dims_not_supported_for_arrays(self) -> None:
        # REQ-04: array mode is datapoint mode, ready for db.pivot.
        with pytest.raises(DataError):
            itc.load(np.zeros((2, 2)), names=["alpha", "CT"], dims=["alpha"])

    def test_mode_argument(self) -> None:
        db = itc.load(np.zeros((1, 1)), names=["CT"], mode="draft")
        assert db.mode == "draft"


class TestPandasMode:
    def test_datapoint_mode_from_dataframe(self) -> None:
        df = pd.DataFrame({"alpha": [0.0, 2.0], "CT": [0.1, 0.2]})
        db = itc.load(df)
        assert list(db.dims) == ["datapoint"]
        assert list(db.vars) == ["alpha", "CT"]
        assert np.array_equal(db.vars["alpha"].values, [0.0, 2.0])

    def test_non_string_column_names_rejected(self) -> None:
        # REQ-76 Load edge: non-string column names fail loud.
        df = pd.DataFrame({0: [1.0], "CT": [0.2]})
        with pytest.raises(DataError):
            itc.load(df)

    def test_reproducible_hash(self) -> None:
        df = pd.DataFrame({"CT": [0.1, 0.2]})
        db1 = itc.load(df)
        itc.set_user("someone-else@other")
        db2 = itc.load(df)
        assert db1.state_hash == db2.state_hash
