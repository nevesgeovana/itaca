"""Named regression tests for the confirmed REV-001 findings that do
not belong to one of the five fix groups.

Usage example (TDD anchor)::

    with pytest.raises(RotationMatrixError, match="built-in"):
        AxisRegistry().with_axis(Axis(name="body", rotation_matrix=np.eye(3)))

The definition of done for lane `ITA-1` is that every confirmed finding
becomes a permanent named regression test in this repository's own
suite, cited by its finding id. The blockers are pinned beside the code
they touch; these are the ones whose natural home is a cross-cutting
file, because the finding is about a boundary rather than an operation.

The probe is the source, the test is the asset: a check that lives only
in a reviewer's document is only as durable as the reviewer.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.axes import Axis, AxisRegistry
from itaca.core.errors import (
    CorrelationMatrixError,
    DataError,
    DraftModeExportWarning,
    RotationMatrixError,
    VectorGroupError,
)
from itaca.core.varframe import VarFrame


def _frame(names: list[str], rows: list[list[float]]) -> VarFrame:
    return itc.load(np.array(rows), names=names)


class TestAxisRegistryAmbiguity:
    """`ITACA-029`: the registry accepted destructive ambiguity."""

    def test_itaca_029_a_builtin_axis_name_is_reserved(self) -> None:
        """Registering over `body` silently replaced the canonical frame.

        Measured before the fix: a VarFrame's default registry is EMPTY
        and `resolve` falls back to the built-ins, so
        `register_axis(Axis(name="body", ...))` was ACCEPTED and
        `resolve('body')` then returned the user's matrix for that frame
        and everything downstream of it. Only a registry already
        populated by `with_builtins()` refused, which is not the path a
        user takes.
        """
        flipped = np.diag([1.0, -1.0, -1.0])
        with pytest.raises(RotationMatrixError, match="built-in") as excinfo:
            AxisRegistry().with_axis(Axis(name="body", rotation_matrix=flipped))
        assert "silently replace" in str(excinfo.value)

    def test_itaca_029_a_group_must_have_distinct_components(self) -> None:
        """`("FX", "FX", "FZ")` was accepted as a vector triplet."""
        with pytest.raises(VectorGroupError, match="more than once"):
            AxisRegistry().with_vector_group("force", ["FX", "FX", "FZ"])

    def test_itaca_029_two_groups_may_not_claim_the_same_component(self) -> None:
        """Overlapping groups rotate the same variables twice in one call.

        The same shape as `ITACA-020b`, which the rotate sweep found:
        two declarations over one triplet made a single `rotate` apply
        the transform twice.
        """
        registry = AxisRegistry().with_vector_group("force", ["FX", "FY", "FZ"])
        with pytest.raises(VectorGroupError, match="twice") as excinfo:
            registry.with_vector_group("aero", ["FX", "FY", "FZ"])
        assert "'FX'" in str(excinfo.value)

    def test_itaca_029_a_distinct_group_is_still_accepted(self) -> None:
        """The checks refuse ambiguity and nothing else."""
        registry = AxisRegistry().with_vector_group("force", ["FX", "FY", "FZ"])
        widened = registry.with_vector_group("moment", ["MX", "MY", "MZ"])
        assert sorted(widened.vector_groups) == ["force", "moment"]


class TestCombineValidation:
    """`ITACA-030`: combine accepted numerically invalid input four ways."""

    @staticmethod
    def _pair() -> tuple[VarFrame, VarFrame]:
        left = _frame(["CT"], [[1.0], [2.0]]).set_uncertainty({"CT": 0.1})
        right = _frame(["CT"], [[3.0], [4.0]]).set_uncertainty({"CT": 0.2})
        return left, right

    @pytest.mark.parametrize("coefficient", [5.0, float("nan"), float("inf")])
    def test_itaca_030_cross_correlation_must_be_finite_and_in_range(
        self, coefficient: float
    ) -> None:
        """Measured: 5.0 gave u = 0.346 and NaN gave u = NaN, both accepted."""
        left, right = self._pair()
        with pytest.raises(CorrelationMatrixError, match="finite"):
            left.combine(right, op="sum", cross_correlation=coefficient)

    def test_itaca_030_weights_summing_to_zero_are_refused(self) -> None:
        """Measured: (1.0, -1.0) reached a bare ZeroDivisionError."""
        left, right = self._pair()
        with pytest.raises(DataError, match="summing to zero"):
            left.combine(right, op="weighted_mean", weights=(1.0, -1.0))

    def test_itaca_030_non_finite_weights_are_refused(self) -> None:
        """Measured: (nan, 1.0) was accepted and every value came back NaN."""
        left, right = self._pair()
        with pytest.raises(DataError, match="non-finite weight"):
            left.combine(right, op="weighted_mean", weights=(float("nan"), 1.0))

    def test_itaca_030_valid_weights_still_combine(self) -> None:
        """The guard refuses the invalid cases and nothing else."""
        left, right = self._pair()
        out = left.combine(right, op="weighted_mean", weights=(1.0, 3.0))
        assert out.vars["CT"].values[0] == pytest.approx((1.0 + 3.0 * 3.0) / 4.0)


class TestSerializationHardening:
    """`ITACA-019`: CSV and JSON were written by hand."""

    def test_itaca_019_csv_quotes_a_value_containing_the_delimiter(
        self, tmp_path: Path
    ) -> None:
        """Every data row must carry exactly as many fields as the header.

        `','.join` wrote whatever `str()` produced, so a value or a name
        containing the delimiter added a field to its row and the file
        parsed as a different table than the one exported. The invariant
        holds for any content once the writer owns the quoting.
        """
        db = itc.load(np.array([[1.0], [2.0]]), names=["CT"])
        target = tmp_path / "out.csv"
        db.to_csv(target)

        import csv as _csv

        with open(target, newline="", encoding="utf-8") as handle:
            body = [
                row for row in _csv.reader(handle) if row and not row[0].startswith("#")
            ]
        header, *data = body
        for row in data:
            assert len(row) == len(header), (
                f"row {row} has {len(row)} fields against {len(header)} in the "
                "header; the writer must quote, not join"
            )

    def test_itaca_019_csv_round_trips_a_delimiter_in_a_name(
        self, tmp_path: Path
    ) -> None:
        """The load side must read back exactly what the export wrote."""
        import csv as _csv

        target = tmp_path / "quoted.csv"
        with open(target, "w", newline="", encoding="utf-8") as handle:
            writer = _csv.writer(handle, lineterminator="\n")
            writer.writerow(["alpha", "odd,name"])
            writer.writerow(["0.0", "1.0"])
            writer.writerow(["1.0", "2.0"])
        db = itc.load(target)
        assert "odd,name" in db.vars

    def test_itaca_019_json_is_strict_json(self, tmp_path: Path) -> None:
        """NaN, Infinity and -Infinity are not JSON (RFC 8259).

        Measured before the fix: the file carried bare `NaN` and
        `Infinity` tokens, which `json.loads` accepts by extension but a
        strict parser refuses, so the format chosen for interoperability
        was not interoperable.
        """
        db = itc.load(np.array([[1.0], [np.nan]]), names=["CT"])
        target = tmp_path / "out.json"
        db.to_json(target)
        text = target.read_text(encoding="utf-8")
        assert "NaN" not in text
        assert "Infinity" not in text

        # Strict parse: parse_constant fires only for the bare tokens.
        def _refuse(token: str) -> None:
            raise AssertionError(f"non-JSON token {token!r} in the output")

        payload = json.loads(text, parse_constant=_refuse)
        assert payload["variables"]["CT"]["values"][1] is None


class TestLossyExportsWarn:
    """`ITACA-005`: the draft banner never reached to_pandas or to_numpy."""

    def test_itaca_005_to_numpy_warns_on_a_forced_draft_export(self) -> None:
        """Measured before the fix: warnings emitted was an empty list.

        `guard_draft` only raised or returned, and the banner lives in
        `_header_lines`, which the CSV, JSON and `.itc` paths use and
        these do not. A caller who passed `allow_draft=True` received
        draft data with nothing marking it, which is the half of REQ-11
        that is a safety property rather than a provenance one.
        """
        itc.set_mode("draft")
        try:
            db = itc.load(np.array([[1.0], [2.0]]), names=["CT"])
            with pytest.warns(DraftModeExportWarning, match="draft-mode banner"):
                db.to_numpy(allow_draft=True)
        finally:
            itc.set_mode("production")

    def test_itaca_005_a_production_export_warns_about_nothing(self) -> None:
        """The warning is scoped to draft mode."""
        db = itc.load(np.array([[1.0], [2.0]]), names=["CT"])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            db.to_numpy()
