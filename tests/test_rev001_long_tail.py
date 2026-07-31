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
        # The fixture must CONTAIN the delimiter, or the test passes
        # against the pre-fix code: with no comma in any name or value,
        # ",".join produces exactly as many fields as csv.writer does.
        # Measured on the old code with this fixture: header 3 fields,
        # data 2 fields.
        db = itc.load(np.array([[1.0], [2.0]]), names=["odd,name"])
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
        strict parser refuses, so the format chosen for
        interoperability was not interoperable.

        This test used to assert that the SUBSTRING "Infinity" was
        absent, which was a stricter claim than the invariant and it
        stopped being true at FND-085: the infinities now export as the
        quoted strings "Infinity" and "-Infinity", so that a point never
        measured stays distinguishable from a computation that
        diverged. What matters is that no BARE token reaches the file,
        and `parse_constant` is what measures that, since it fires for
        the bare tokens and never for a string.
        """
        db = itc.load(np.array([[1.0], [np.nan], [np.inf], [-np.inf]]), names=["CT"])
        target = tmp_path / "out.json"
        db.to_json(target)
        text = target.read_text(encoding="utf-8")

        # Strict parse: parse_constant fires only for the bare tokens.
        def _refuse(token: str) -> None:
            raise AssertionError(f"non-JSON token {token!r} in the output")

        payload = json.loads(text, parse_constant=_refuse)
        values = payload["variables"]["CT"]["values"]
        assert values == [1.0, None, "Infinity", "-Infinity"]


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


class TestMetadataIsSettableAndRecorded:
    """The API-designer blocker: a refusal named an action that did not exist.

    `rotate` refuses a condition-dependent rotation with "set the
    Dimension or Variable unit to 'deg' or 'rad'". There was no
    `set_unit`, no `units=` on `itc.load` or `db.pivot`, and neither
    `Dimension` nor `Variable` is exported, so the only route was
    `dataclasses.replace` on a frozen object through a private module
    path. The library's own `rotate` docstring taught exactly that, and
    it bypasses `_derive`: no History entry, no re-derived state hash.

    DD-40 made the unit part of the hash, and REQ-101 makes it decide
    physics, so it is the one field that most needs a traceable setter.
    """

    @staticmethod
    def _angle_frame() -> VarFrame:
        arr = np.column_stack([[0.0, 90.0], [1.0, 1.0], [0.0, 0.0], [0.0, 0.0]])
        return itc.load(arr, names=["alpha", "FX", "FY", "FZ"]).pivot(dims=["alpha"])

    def test_the_rotate_refusal_names_a_reachable_action(self) -> None:
        """Refuse, set the unit through the public API, succeed.

        This is the whole finding in one test: the message says to set
        a unit, and the test does it the way a user can.
        """
        db = self._angle_frame()
        with pytest.raises(DataError, match="without a unit"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")

        out = (
            db.set_metadata({"alpha": {"unit": "deg"}})
            .declare_vector("force", ["FX", "FY", "FZ"])
            .rotate("stability")
        )
        # Ry(90 deg) @ (1,0,0) = (0, 0, -1).
        assert out.vars["FZ"].values[1] == pytest.approx(-1.0)

    def test_set_metadata_is_recorded_and_moves_the_hash(self) -> None:
        """It goes through `_derive`, which is the point of adding it.

        `dataclasses.replace` changed the unit and left History and the
        state hash describing the frame before the change, so the unit
        that decides the physics was invisible to provenance.
        """
        db = self._angle_frame()
        out = db.set_metadata({"alpha": {"unit": "deg"}})
        assert out.dims["alpha"].unit == "deg"
        assert "set_metadata" in out.history[-1].operation
        assert out.state_hash != db.state_hash
        assert db.dims["alpha"].unit is None  # the original is untouched

    def test_set_metadata_refuses_a_field_the_target_does_not_carry(self) -> None:
        """A Dimension has no long name, and saying so beats ignoring it."""
        db = self._angle_frame()
        with pytest.raises(DataError, match="long_name"):
            db.set_metadata({"alpha": {"long_name": "angle of attack"}})
        with pytest.raises(DataError, match="neither a dimension nor a variable"):
            db.set_metadata({"ghost": {"unit": "deg"}})

    def test_set_metadata_reaches_variables_too(self) -> None:
        """Including `long_name`, which only a variable carries."""
        out = self._angle_frame().set_metadata(
            {"FX": {"unit": "N", "long_name": "axial force"}}
        )
        assert out.vars["FX"].unit == "N"
        assert out.vars["FX"].long_name == "axial force"


class TestCorrelationIsWithdrawable:
    """The other API-designer blocker: three refusals prescribed dropping
    a declaration, and `set_correlation` merges and can only add."""

    def test_drop_correlation_removes_pairs_naming_a_variable(self) -> None:
        arr = np.column_stack([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        db = itc.load(arr, names=["FX", "FY", "q"])
        db = db.set_correlation({("FX", "FY"): 0.5, ("FX", "q"): 0.3})
        out = db.drop_correlation(["q"])
        assert sorted(out.correlation.pairs) == [("FX", "FY")]
        assert "drop_correlation" in out.history[-1].operation
        # The original is untouched (REQ-18).
        assert sorted(db.correlation.pairs) == [("FX", "FY"), ("FX", "q")]

    def test_drop_correlation_with_no_names_drops_everything(self) -> None:
        arr = np.column_stack([[1.0, 2.0], [3.0, 4.0]])
        db = itc.load(arr, names=["FX", "FY"]).set_correlation({("FX", "FY"): 0.5})
        assert db.drop_correlation().correlation is None

    def test_drop_correlation_on_a_frame_that_declared_none_is_a_no_op(self) -> None:
        db = itc.load(np.column_stack([[1.0, 2.0]]), names=["FX"])
        assert db.drop_correlation().correlation is None
