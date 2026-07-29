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
from itaca.core.errors import DataError, DuplicateNameError


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


class TestRepeatedNamesRefused:
    """REV-001 ITACA-026: data lost at step one of the chain.

    `itc.load(array, names=["a","b","a"])` was accepted and produced two
    variables, the third column having overwritten the first. Provenance
    then documented a dataset that no longer matched the input, which is
    the one thing it exists to prevent.

    The rule is applied at every ingestion boundary rather than only at
    the one the review measured, because they share a structural cause:
    each turns a list of names into keys of a mapping, and a repeat
    collapses two sources into one key.
    """

    def test_itaca_026_duplicate_array_names_are_refused(self) -> None:
        """The reported case: the blocker, at the array boundary.

        Measured before the fix: 2 variables from a 3-column array, with
        a == [3., 6.], the third column's values under the first
        column's name.
        """
        with pytest.raises(DuplicateNameError) as excinfo:
            itc.load(
                np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]), names=["a", "b", "a"]
            )
        message = str(excinfo.value)
        assert "'a'" in message
        assert "positions 0 and 2" in message

    def test_itaca_026_the_length_check_still_runs_first(self) -> None:
        """A wrong-length names list keeps its own, more specific message."""
        with pytest.raises(DataError) as excinfo:
            itc.load(np.array([[1.0, 2.0]]), names=["a", "a", "a"])
        assert "names list of length 3" in str(excinfo.value)

    def test_itaca_026_duplicate_dims_are_refused_with_a_rank_message(self) -> None:
        """A repeated dimension is a different consequence, so a different message.

        Measured before the fix: a bare non-ITACA
        `ValueError: parameter multi_index must be a sequence of length 1`
        from deep inside numpy. A repeated dim does not discard a column,
        it makes the grid rank and the index rank disagree, so citing
        REQ-01 here would be wrong.
        """
        db = itc.load(np.array([[0.0, 1.0], [1.0, 2.0]]), names=["alpha", "CT"])
        with pytest.raises(DuplicateNameError) as excinfo:
            db.pivot(dims=["alpha", "alpha"])
        assert "dimension name 'alpha'" in str(excinfo.value)
        assert "REQ-14" in str(excinfo.value)

    def test_itaca_026_unique_names_are_untouched(self) -> None:
        """The check is scoped to repeats and refuses nothing else."""
        db = itc.load(
            np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]), names=["a", "b", "c"]
        )
        assert sorted(db.vars) == ["a", "b", "c"]

    def test_itaca_026_duplicate_dataframe_columns_are_refused(self) -> None:
        """The pandas boundary: a repeated label gives a 2-D block.

        Measured before the fix: it surfaced far downstream as
        `DataError: Variable 'a': construction with shape (2, 2) against
        dimension shape (2,)`, which names neither the duplicate nor the
        source of it.
        """
        frame = pd.DataFrame(
            np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]), columns=["a", "b", "a"]
        )
        with pytest.raises(DuplicateNameError) as excinfo:
            itc.load(frame)
        assert "the DataFrame columns" in str(excinfo.value)
