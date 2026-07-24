"""Reusable pipelines: extraction, replay, and persistence (REQ-53..55).

Usage example (TDD anchor)::

    processed = db.smooth(along="x", method="moving_avg", window=3)
    processed = processed.compute("w = y + z")
    pipe = processed.history.to_pipeline()
    same = pipe.apply(other_run)
    reloaded = itc.load_pipeline(pipe.save(path))

The contract under test: a contiguous range of History entries lifts
into a Pipeline that reproduces the recorded processing on a new
VarFrame, and survives a round trip through a ``.itc_pipe`` file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.axes import Axis
from itaca.core.errors import DataError, HashMismatchError, PipelineCompatibilityError
from itaca.core.history import History
from itaca.core.pipeline import (
    PIPELINE_SCHEMA,
    REPLAYABLE_CALLS,
    Pipeline,
    PipelineStep,
    _to_jsonable,
)
from itaca.core.varframe import VarFrame

_Call = Callable[[VarFrame], VarFrame]


def _frame(seed: int = 0) -> VarFrame:
    """A pivoted frame with a swept dimension and two variables."""
    rng = np.random.default_rng(seed)
    x = np.arange(0.0, 10.0, 1.0)
    y = 2.0 * x + 1.0 + rng.normal(0.0, 0.01, x.size)
    z = x**2 + 1.0 + float(seed)
    arr = np.column_stack([x, y, z])
    return itc.load(arr, names=["x", "y", "z"]).pivot(dims=["x"])


def _force_frame(extra_group: bool = False) -> VarFrame:
    """A frame carrying force and moment components.

    Vector groups are auto-detected from the naming convention, so
    ``extra_group`` adds a third convention-named triple that the plain
    frame does not have. Replaying onto it discriminates a step that
    recorded the source-resolved group list instead of the caller's
    argument: the caller's ``None`` must re-resolve on the target and
    pick the extra group up.
    """
    names = ["alpha", "FX", "FY", "FZ", "MX", "MY", "MZ"]
    columns = [
        [0.0, 10.0],
        [1.0, 1.5],
        [2.0, 2.5],
        [3.0, 3.5],
        [0.4, 0.7],
        [0.5, 0.8],
        [0.6, 0.9],
    ]
    if extra_group:
        names += ["VX", "VY", "VZ"]
        columns += [[5.0, 5.5], [6.0, 6.5], [7.0, 7.5]]
    rows = np.column_stack([np.asarray(c, dtype=float) for c in columns])
    db = itc.load(rows, names=names).pivot(dims=["alpha"])
    if extra_group:
        # Only (FX,FY,FZ) and (MX,MY,MZ) are auto-detected, so a third
        # group has to be declared for the target to differ.
        db = db.declare_vector("velocity", ["VX", "VY", "VZ"])
    return db


def _tilt() -> Axis:
    return Axis(
        name="tilt",
        rotation_matrix=np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]),
        description="fixed quarter turn about z",
    )


# ---------------------------------------------------------------------------
# REQ-53: extraction by index range
# ---------------------------------------------------------------------------


def test_to_pipeline_skips_only_the_construction_prefix() -> None:
    """load and pivot build the input; they are never replayed."""
    db = _frame()
    assert [e.name for e in db.history] == ["load", "pivot"]
    assert not any(e.replayable for e in db.history)
    lifted = db.compute("w = y + z").history.to_pipeline()
    assert [s.call for s in lifted] == ["compute"]


def test_to_pipeline_collects_in_recorded_order() -> None:
    processed = _frame().smooth(along="x", method="moving_avg", window=3)
    processed = processed.compute("w = y + z")
    assert [s.call for s in processed.history.to_pipeline()] == ["smooth", "compute"]


def test_to_pipeline_honors_an_explicit_range() -> None:
    """start and end are 1-based inclusive history indices (REQ-53)."""
    processed = _frame().smooth(along="x", method="moving_avg", window=3)
    processed = processed.compute("w = y + z")
    # History: [1] load, [2] pivot, [3] smooth, [4] compute.
    assert len(processed.history) == 4
    assert [s.call for s in processed.history.to_pipeline(start=3, end=3)] == ["smooth"]
    assert [s.call for s in processed.history.to_pipeline(start=4)] == ["compute"]
    assert processed.history.to_pipeline(start=3).history_start == 3


@pytest.mark.parametrize(("start", "end"), [(0, 2), (1, 99), (3, 2), (-1, None)])
def test_to_pipeline_rejects_an_out_of_range_slice(start: int, end: int | None) -> None:
    db = _frame().compute("w = y + z")
    with pytest.raises(DataError, match="outside"):
        db.history.to_pipeline(start=start, end=end)


def test_to_pipeline_raises_on_a_range_with_no_replayable_step() -> None:
    """An empty pipeline would apply as a silent no-op, so refuse it."""
    db = _frame()
    with pytest.raises(PipelineCompatibilityError, match="silent no-op"):
        db.history.to_pipeline(start=1, end=2)


def test_to_pipeline_in_draft_mode_refuses_rather_than_returning_a_no_op() -> None:
    """Draft frames record only with history=True (REQ-10)."""
    itc.set_mode("draft")
    try:
        db = _frame()
        processed = db.smooth(along="x", method="moving_avg", window=3)
        processed = processed.compute("w = y + z")
        with pytest.raises(PipelineCompatibilityError, match="silent no-op"):
            processed.history.to_pipeline()
    finally:
        itc.set_mode("production")


def test_draft_mode_with_history_true_is_extractable() -> None:
    itc.set_mode("draft")
    try:
        processed = _frame().compute("w = y + z", history=True)
        assert [s.call for s in processed.history.to_pipeline()] == ["compute"]
    finally:
        itc.set_mode("production")


def test_a_merge_after_processing_is_not_replayable() -> None:
    """concat references other frames, so the sequence cannot reproduce."""
    left = _frame().compute("w = y + z")
    right = itc.load(
        np.column_stack([np.arange(10.0, 15.0), np.zeros(5), np.zeros(5), np.zeros(5)]),
        names=["x", "y", "z", "w"],
    ).pivot(dims=["x"])
    merged = itc.concat([left, right], along="x")
    assert merged.history.entries[-1].step is None
    with pytest.raises(PipelineCompatibilityError, match="records no replayable step"):
        merged.history.to_pipeline()


def test_to_pipeline_on_an_empty_history_names_the_real_cause() -> None:
    """Blaming the caller's indices for an absent history is unhelpful."""
    with pytest.raises(DataError, match="no recorded operations"):
        History().to_pipeline()


def test_uncertainty_setup_is_captured_not_silently_dropped() -> None:
    """set_uncertainty is part of the recipe (it used to be skipped)."""
    processed = _frame().set_uncertainty({"y": 0.1}).compute("w = y + z")
    assert [s.call for s in processed.history.to_pipeline()] == [
        "set_uncertainty",
        "compute",
    ]


# ---------------------------------------------------------------------------
# REQ-54: replay onto a new VarFrame
# ---------------------------------------------------------------------------


def test_replay_on_the_same_frame_reproduces_the_state_hash() -> None:
    db = _frame()
    processed = db.smooth(along="x", method="moving_avg", window=3)
    processed = processed.compute("w = y + z")
    assert processed.history.to_pipeline().apply(db).state_hash == processed.state_hash


def test_replay_preserves_the_history_comment() -> None:
    """REQ-19: the comment survives into pipeline exports and replay."""
    db = _frame()
    processed = db.compute("w = y + z", comment="lift ratio")
    step = processed.history.entries[-1].step
    assert step is not None
    assert step.comment == "lift ratio"
    replayed = processed.history.to_pipeline().apply(db)
    assert replayed.history.entries[-1].comment == "lift ratio"
    assert replayed.state_hash == processed.state_hash


def test_replay_carries_uncertainty_and_correlation() -> None:
    db = _frame()
    processed = db.set_uncertainty({"y": 0.1, "z": 0.2})
    processed = processed.set_uncertainty({"y": 0.05}, component="random")
    processed = processed.set_correlation({("y", "z"): 0.3})
    processed = processed.compute("w = y * z")
    replayed = processed.history.to_pipeline().apply(db)
    assert replayed.state_hash == processed.state_hash
    assert replayed.uncertainty is not None
    assert processed.uncertainty is not None
    assert np.allclose(
        replayed.uncertainty.systematic["w"], processed.uncertainty.systematic["w"]
    )
    assert np.allclose(
        replayed.uncertainty.random["w"], processed.uncertainty.random["w"]
    )
    assert replayed.correlation is not None


def test_apply_on_an_incompatible_frame_raises_with_all_three_parts() -> None:
    recipe = _frame().compute("w = y + z").history.to_pipeline()
    other = itc.load(
        np.column_stack([np.arange(5.0), np.arange(5.0)]), names=["x", "q"]
    ).pivot(dims=["x"])
    with pytest.raises(PipelineCompatibilityError) as excinfo:
        recipe.apply(other)
    error = excinfo.value
    assert "pipeline step 1 (compute)" in error.obj
    assert "variable 'y'" in error.obj  # the inner error's object survives
    assert "incompatible" in error.operation
    assert "available variables" in error.fix  # the inner fix survives


def test_apply_wraps_non_data_errors_too() -> None:
    """An axes failure is an incompatibility, not an escaping error."""
    source = _force_frame().register_axis(_tilt())
    source = source.declare_vector("force", ["FX", "FY", "FZ"]).rotate("tilt")
    last = len(source.history)
    recipe = source.history.to_pipeline(start=last, end=last)
    with pytest.raises(PipelineCompatibilityError, match="pipeline step 1"):
        recipe.apply(_force_frame())


def test_an_empty_pipeline_cannot_be_constructed() -> None:
    """Extraction refuses to produce one, so construction must too.

    This test previously pinned the opposite, that the empty pipeline
    was the identity. ``History.to_pipeline`` raises on an empty range
    precisely to stop a pipeline that would apply as a silent no-op, so
    letting one in through the constructor and through the file reader
    left the producer strict and the two consumers permissive.
    """
    with pytest.raises(DataError, match="no steps"):
        Pipeline(steps=())


def test_replay_rejects_a_call_outside_the_allowlist() -> None:
    step = PipelineStep(call="save", kwargs={"path": "x.itc"})
    with pytest.raises(PipelineCompatibilityError, match="not a replayable"):
        Pipeline(steps=(step,)).apply(_frame())


# ---------------------------------------------------------------------------
# REQ-55 and the .itc_pipe section of SRS Chapter 4: serialization
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    db = _frame()
    processed = db.smooth(along="x", method="moving_avg", window=3).compute("w = y + z")
    original = processed.history.to_pipeline()
    reloaded = itc.load_pipeline(original.save(tmp_path / "recipe.itc_pipe"))
    assert [s.call for s in reloaded] == [s.call for s in original]
    assert [dict(s.kwargs) for s in reloaded] == [dict(s.kwargs) for s in original]
    assert reloaded.apply(db).state_hash == processed.state_hash


def test_the_saved_file_carries_every_srs_field(tmp_path: Path) -> None:
    """Every field the .itc_pipe section of SRS Chapter 4 requires."""
    db = _frame().smooth(along="x", method="moving_avg", window=3, comment="drift fix")
    path = db.history.to_pipeline().save(tmp_path / "recipe.itc_pipe")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    assert payload["schema"] == PIPELINE_SCHEMA
    assert payload["itaca_version"] == itc.__version__
    assert payload["history_start"] == 1
    assert payload["history_end"] == 3
    assert payload["content_hash"].startswith("sha256:")
    step = payload["steps"][0]
    assert step["call"] == "smooth"
    assert step["comment"] == "drift fix"
    assert step["kwargs"]["window"] == 3


def test_save_is_atomic_leaving_no_temp_file(tmp_path: Path) -> None:
    _frame().compute("w = y + z").history.to_pipeline().save(
        tmp_path / "recipe.itc_pipe"
    )
    assert [p.name for p in tmp_path.iterdir()] == ["recipe.itc_pipe"]


def test_an_edited_file_fails_its_content_hash(tmp_path: Path) -> None:
    pipeline = _frame().compute("w = y + z").history.to_pipeline()
    path = pipeline.save(tmp_path / "recipe.itc_pipe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["steps"][0]["kwargs"]["equation"] = "w = y * 1000"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HashMismatchError, match="modified after it was written"):
        itc.load_pipeline(path)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ([1, 2, 3], "not a JSON object"),
        ({"schema": "other/9", "steps": []}, "unknown .itc_pipe schema"),
        ({"schema": PIPELINE_SCHEMA}, "'steps' is missing or not a list"),
        ({"schema": PIPELINE_SCHEMA, "steps": {}}, "'steps' is missing or not a list"),
        ({"schema": PIPELINE_SCHEMA, "steps": [1]}, "not a JSON object"),
        ({"schema": PIPELINE_SCHEMA, "steps": [{}]}, "without a string 'call'"),
        (
            {"schema": PIPELINE_SCHEMA, "steps": [{"call": "save", "kwargs": {}}]},
            "not replayable",
        ),
        (
            {"schema": PIPELINE_SCHEMA, "steps": [{"call": "smooth", "kwargs": []}]},
            "'kwargs' is not a JSON object",
        ),
    ],
)
def test_load_pipeline_rejects_malformed_payloads(
    tmp_path: Path, payload: object, match: str
) -> None:
    path = tmp_path / "bad.itc_pipe"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DataError, match=re.escape(match)):
        itc.load_pipeline(path)


def test_load_pipeline_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.itc_pipe"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DataError, match="could not parse"):
        itc.load_pipeline(path)


def test_a_pipeline_survives_the_itc_archive(tmp_path: Path) -> None:
    """A reopened archive can still lift its recipe (.itc schema 2)."""
    db = _frame()
    processed = db.smooth(along="x", method="moving_avg", window=3).compute("w = y + z")
    reopened = itc.open(processed.save(tmp_path / "campaign.itc"))
    pipeline = reopened.history.to_pipeline()
    assert [s.call for s in pipeline] == ["smooth", "compute"]
    assert pipeline.apply(db).state_hash == processed.state_hash


# ---------------------------------------------------------------------------
# Replay fidelity across the operation set, on the source and a new frame
# ---------------------------------------------------------------------------

_CASES: list[tuple[str, _Call]] = [
    ("smooth", lambda db: db.smooth(along="x", method="moving_avg", window=3)),
    ("diff", lambda db: db.diff(along="x", window=5, deg=2)),
    ("compute", lambda db: db.compute("w = y * 2")),
    ("compute_where", lambda db: db.compute("w = y * 2", where="y > 5")),
    ("compute_fill_none", lambda db: db.compute("w = y * 2", where="y > 5", fill=None)),
    ("average", lambda db: db.average(along="x")),
    ("integrate", lambda db: db.integrate("y", over="x")),
    ("fill", lambda db: db.fill(along="x", method="linear")),
    ("fitmodel", lambda db: db.fitmodel(along="x", deg=2)),
    ("select", lambda db: db.select({"x": [1.0, 2.0, 3.0]})),
    ("at", lambda db: db.at(x=2.0)),
    ("expand", lambda db: db.expand("mach", [0.2, 0.4])),
    ("interpolate", lambda db: db.interpolate({"x": [1.5, 2.5, 3.5]})),
    (
        "interpolate_axis_translation",
        lambda db: db.interpolate(axisTranslation={"from": "x", "to": "y"}),
    ),
    (
        "interpolate_axis_translation_grid",
        lambda db: db.interpolate(
            axisTranslation={"from": "x", "to": "y"}, mapping={"y": [3.0, 5.0, 7.0]}
        ),
    ),
    ("set_uncertainty", lambda db: db.set_uncertainty({"y": 0.1})),
    ("set_correlation", lambda db: db.set_correlation({("y", "z"): 0.3})),
]


@pytest.mark.parametrize(("label", "call"), _CASES)
def test_each_operation_replays_on_its_source_frame(label: str, call: _Call) -> None:
    db = _frame()
    processed = call(db)
    pipeline = processed.history.to_pipeline()
    assert len(pipeline) == 1, f"{label} recorded no replayable step"
    assert pipeline.apply(db).state_hash == processed.state_hash


@pytest.mark.parametrize(("label", "call"), _CASES)
def test_each_operation_replays_on_a_different_frame(label: str, call: _Call) -> None:
    """Cross-frame replay. A step that captured a value derived from the
    source frame rather than from the call is only visible here.
    """
    recipe = call(_frame(seed=1)).history.to_pipeline()
    target = _frame(seed=2)
    assert recipe.apply(target).state_hash == call(target).state_hash, label


def test_fitvalue_replays() -> None:
    db = _frame()
    fitted = db.fitmodel(along="x", deg=2)
    processed = fitted.fitvalue(coef_dims=["x_coef"], at={"x": [1.0, 2.0]})
    pipeline = processed.history.to_pipeline(start=len(fitted.history) + 1)
    assert [s.call for s in pipeline] == ["fitvalue"]
    assert pipeline.apply(fitted).state_hash == processed.state_hash


def test_the_axes_journey_replays_end_to_end() -> None:
    """register_axis, declare_vector and rotate compose in a pipeline."""
    base = _force_frame()
    processed = base.register_axis(_tilt())
    processed = processed.declare_vector("force", ["FX", "FY", "FZ"]).rotate("tilt")
    pipeline = processed.history.to_pipeline()
    assert [s.call for s in pipeline] == ["register_axis", "declare_vector", "rotate"]
    assert pipeline.apply(base).state_hash == processed.state_hash


def test_translate_moments_replays() -> None:
    rows = np.array([[0.0, 1.0, 2.0, 3.0, 0.1, 0.2, 0.3]])
    db = itc.load(rows, names=["alpha", "FX", "FY", "FZ", "MX", "MY", "MZ"]).pivot(
        dims=["alpha"]
    )
    processed = db.translate_moments(to_point=[1.0, 0.0, 0.0])
    pipeline = processed.history.to_pipeline()
    assert [s.call for s in pipeline] == ["translate_moments"]
    assert pipeline.apply(db).state_hash == processed.state_hash


def test_a_multi_step_pipeline_replays_in_order() -> None:
    db = _frame()
    processed = (
        db.smooth(along="x", method="moving_avg", window=3)
        .compute("w = y + z")
        .diff(along="x", window=5, deg=2)
    )
    pipeline = processed.history.to_pipeline()
    assert len(pipeline) == 3
    assert pipeline.apply(db).state_hash == processed.state_hash


# ---------------------------------------------------------------------------
# Immutability, hashing, and serialization helpers
# ---------------------------------------------------------------------------


def test_recorded_step_kwargs_cannot_be_mutated() -> None:
    """Provenance is append-only; the step hangs off a frozen entry."""
    processed = _frame().smooth(along="x", method="moving_avg", window=3)
    step = processed.history.entries[-1].step
    assert step is not None
    with pytest.raises(TypeError):
        step.kwargs["window"] = 99  # type: ignore[index]


def test_a_step_is_hashable_so_history_stays_a_value_object() -> None:
    processed = _frame().compute("w = y + z")
    entry = processed.history.entries[-1]
    assert isinstance(hash(entry.step), int)
    assert isinstance(hash(entry), int)


def test_pipeline_step_is_frozen() -> None:
    step = PipelineStep(call="smooth", kwargs={"along": "x"})
    with pytest.raises(AttributeError):
        step.call = "diff"  # type: ignore[misc]


def test_pipeline_repr_lists_its_steps() -> None:
    processed = _frame().compute("w = y + z", comment="ratio")
    text = repr(processed.history.to_pipeline())
    assert "Pipeline(1 step," in text
    assert "compute" in text
    assert "ratio" in text


def test_steps_serialize_numpy_values_as_json_natives() -> None:
    processed = _frame().expand("mach", np.array([0.2, 0.4]))
    step = processed.history.entries[-1].step
    assert step is not None
    payload = step._payload()
    json.dumps(payload)  # must not raise
    # Frozen deeply in the record, JSON-native lists on the way out.
    assert step.kwargs["values"] == (0.2, 0.4)
    assert payload["kwargs"]["values"] == [0.2, 0.4]


def test_every_replayable_call_is_a_varframe_method() -> None:
    """The allowlist cannot drift from the actual public surface."""
    for call in REPLAYABLE_CALLS:
        assert callable(getattr(VarFrame, call, None)), call


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (np.array([1.0, 2.0]), [1.0, 2.0]),
        (np.float64(3.5), 3.5),
        (np.int64(7), 7),
        ((1, 2), [1, 2]),
        ({"a": np.int64(1)}, {"a": 1}),
        ("plain", "plain"),
        (True, True),
        (None, None),
    ],
)
def test_to_jsonable_normalizes(value: object, expected: object) -> None:
    assert _to_jsonable(value) == expected


def test_a_non_finite_argument_is_refused_at_save_not_at_record_time(
    tmp_path: Path,
) -> None:
    """REQ-35 admits any scalar fill; only persisting it can fail."""
    processed = _frame().compute("w = y * 2", where="y > 5", fill=float("inf"))
    pipeline = processed.history.to_pipeline()
    with pytest.raises(DataError, match="no RFC 8259 JSON representation"):
        pipeline.save(tmp_path / "recipe.itc_pipe")


def test_to_jsonable_normalizes_nested_numpy() -> None:
    assert _to_jsonable({"a": [np.int64(1), (np.float64(2.0),)]}) == {"a": [1, [2.0]]}


# ---------------------------------------------------------------------------
# Integrity: the reproduced tamper paths stay closed
# ---------------------------------------------------------------------------


def test_a_recipe_without_a_content_hash_is_refused(tmp_path: Path) -> None:
    """Deleting the hash must not silently opt out of verification."""
    pipeline = _frame().compute("w = y + z").history.to_pipeline()
    path = pipeline.save(tmp_path / "recipe.itc_pipe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["steps"][0]["kwargs"]["equation"] = "w = y * 1000"
    del payload["content_hash"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DataError, match="integrity cannot be verified"):
        itc.load_pipeline(path)


def test_the_content_hash_is_formatting_independent(tmp_path: Path) -> None:
    """It must detect edits, not reformatting."""
    pipeline = _frame().compute("w = y + z").history.to_pipeline()
    path = pipeline.save(tmp_path / "recipe.itc_pipe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(payload, indent=8, sort_keys=True), encoding="utf-8")
    assert len(itc.load_pipeline(path)) == 1


@pytest.mark.parametrize(
    ("call", "kwargs"),
    [
        ("set_correlation", {"spec": [[1, 2]]}),
        ("register_axis", {"axis": {"name": "a"}}),
        ("smooth", {"bogus": 1}),
        ("compute", {"equation": "w = y + z", "nope": 2}),
    ],
)
def test_malformed_step_kwargs_stay_inside_the_error_hierarchy(
    call: str, kwargs: dict[str, object]
) -> None:
    """A hand-edited recipe must not raise a bare TypeError or KeyError."""
    pipeline = Pipeline(steps=(PipelineStep(call=call, kwargs=kwargs),))
    with pytest.raises(PipelineCompatibilityError):
        pipeline.apply(_frame())


@pytest.mark.parametrize("path_keys", [["mapping", "x"], ["filters", "x"]])
def test_nested_replay_arguments_cannot_be_mutated(path_keys: list[str]) -> None:
    """A shallow freeze would leave recorded provenance writable."""
    db = _frame()
    processed = (
        db.interpolate({"x": [1.0, 2.0]})
        if path_keys[0] == "mapping"
        else db.select({"x": [1.0, 2.0]})
    )
    step = processed.history.entries[-1].step
    assert step is not None
    nested = step.kwargs[path_keys[0]][path_keys[1]]
    with pytest.raises(AttributeError):
        nested.append(99.0)  # type: ignore[union-attr]


def test_the_axes_journey_replays_onto_a_frame_with_different_groups() -> None:
    """Cross-frame replay for rotate, which records a caller argument.

    The recipe records ``vector_groups=None``, meaning "resolve on
    whatever frame this runs against". Recording the source-resolved
    list instead would rotate the wrong subset here, since the target
    carries a third vector group the source does not.
    """
    source = _force_frame().register_axis(_tilt())
    source = source.declare_vector("force", ["FX", "FY", "FZ"]).rotate("tilt")
    recipe = source.history.to_pipeline()
    target = _force_frame(extra_group=True)
    expected = (
        target.register_axis(_tilt())
        .declare_vector("force", ["FX", "FY", "FZ"])
        .rotate("tilt")
    )
    replayed = recipe.apply(target)
    # The extra group must have been rotated too.
    assert not np.allclose(replayed.vars["VX"].values, target.vars["VX"].values)
    assert replayed.state_hash == expected.state_hash


def test_translate_moments_replays_on_a_different_frame() -> None:
    source = _force_frame().translate_moments(to_point=[1.0, 0.0, 0.0])
    recipe = source.history.to_pipeline()
    target = _force_frame(extra_group=True)
    assert recipe.apply(target).state_hash == (
        target.translate_moments(to_point=[1.0, 0.0, 0.0]).state_hash
    )


# ---------------------------------------------------------------------------
# The library never lets a stdlib exception reach the user (REQ-81)
# ---------------------------------------------------------------------------


def test_load_pipeline_names_a_missing_file(tmp_path: Path) -> None:
    """The likeliest first-try mistake must not surface as FileNotFoundError."""
    with pytest.raises(DataError, match="could not find") as excinfo:
        itc.load_pipeline(tmp_path / "absent.itc_pipe")
    # A typo wants "check the path", not advice about the other reader.
    assert "check the path" in excinfo.value.fix
    assert "itc.open" not in excinfo.value.fix


def test_load_pipeline_names_a_binary_file(tmp_path: Path) -> None:
    """Pointing it at a sibling .itc archive decodes as bytes, not as text."""
    archive = tmp_path / "campaign.itc"
    archive.write_bytes(b"PK\x03\x04\x00\xff\xfe binary")
    with pytest.raises(DataError, match="could not read") as excinfo:
        itc.load_pipeline(archive)
    # The suffix is a free, certain signal about which reader was wanted.
    assert "itc.open" in excinfo.value.fix


def test_apply_to_a_non_varframe_says_what_to_pass() -> None:
    """``apply`` reads as if it might take a path; it does not."""
    pipeline = _frame().compute("w = y * 2").history.to_pipeline()
    with pytest.raises(PipelineCompatibilityError, match="expects a VarFrame"):
        pipeline.apply("run2.itc")  # type: ignore[arg-type]


def test_content_hash_refuses_a_non_finite_argument_the_same_way_save_does() -> None:
    """A public property must not raise a bare ValueError (REQ-81)."""
    processed = _frame().compute("w = y * 2", where="y > 5", fill=float("inf"))
    pipeline = processed.history.to_pipeline()
    with pytest.raises(DataError, match="no RFC 8259 JSON representation"):
        _ = pipeline.content_hash


def test_a_pipeline_with_no_steps_is_refused_at_both_ends(tmp_path: Path) -> None:
    """``to_pipeline`` refuses to build a silent no-op; so must the reader."""
    with pytest.raises(DataError, match="no steps"):
        Pipeline(steps=(), history_start=0, history_end=0, itaca_version="0.2.0")
    target = tmp_path / "empty.itc_pipe"
    target.write_text(
        json.dumps(
            {
                "schema": PIPELINE_SCHEMA,
                "itaca_version": "0.2.0",
                "history_start": 0,
                "history_end": 0,
                "steps": [],
                "content_hash": "sha256:0",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(DataError, match="silent no-op") as excinfo:
        itc.load_pipeline(target)
    # The reader's own guard must fire, naming the file. Without it the
    # constructor still raises "no steps", so matching that phrase alone
    # could not tell the two ends apart.
    assert str(target) in excinfo.value.obj
