"""Reusable pipelines: extraction, replay, and persistence (REQ-53..55).

The contract under test: a contiguous range of History entries lifts
into a Pipeline that reproduces the recorded processing on a new
VarFrame, and survives a round trip through a ``.itc_pipe`` file.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import DataError, PipelineCompatibilityError
from itaca.core.pipeline import PIPELINE_SCHEMA, Pipeline, PipelineStep, to_jsonable
from itaca.core.varframe import VarFrame


def _frame(seed: int = 0) -> VarFrame:
    """A pivoted frame with a swept dimension and two variables."""
    rng = np.random.default_rng(seed)
    x = np.arange(0.0, 10.0, 1.0)
    y = 2.0 * x + 1.0 + rng.normal(0.0, 0.01, x.size)
    z = x**2 + 1.0
    arr = np.column_stack([x, y, z])
    return itc.load(arr, names=["x", "y", "z"]).pivot(dims=["x"])


# ---------------------------------------------------------------------------
# REQ-53: extraction by index range
# ---------------------------------------------------------------------------


def test_to_pipeline_skips_the_construction_prefix() -> None:
    """load and pivot are input construction, not replayable steps."""
    db = _frame()
    assert [entry.step for entry in db.history] == [None, None]
    processed = db.compute("w = y + z")
    pipeline = processed.history.to_pipeline()
    assert len(pipeline) == 1
    assert pipeline.steps[0].method == "compute"


def test_to_pipeline_collects_in_recorded_order() -> None:
    processed = _frame().smooth(along="x", method="moving_avg", window=3)
    processed = processed.compute("w = y + z")
    pipeline = processed.history.to_pipeline()
    assert [step.method for step in pipeline] == ["smooth", "compute"]


def test_to_pipeline_honors_an_explicit_range() -> None:
    """start and end are 1-based inclusive history indices (REQ-53)."""
    processed = _frame().smooth(along="x", method="moving_avg", window=3)
    processed = processed.compute("w = y + z")
    # History: [1] load, [2] pivot, [3] smooth, [4] compute.
    assert len(processed.history) == 4
    assert [s.method for s in processed.history.to_pipeline(start=3, end=3)] == [
        "smooth"
    ]
    assert [s.method for s in processed.history.to_pipeline(start=4)] == ["compute"]


@pytest.mark.parametrize(
    ("start", "end"),
    [(0, 2), (1, 99), (3, 2), (-1, None)],
)
def test_to_pipeline_rejects_an_out_of_range_slice(start: int, end: int | None) -> None:
    db = _frame().compute("w = y + z")
    with pytest.raises(DataError, match="outside"):
        db.history.to_pipeline(start=start, end=end)


def test_to_pipeline_raises_on_a_non_replayable_operation_after_a_step() -> None:
    """A state-only entry mid-processing cannot be reproduced (REQ-54)."""
    processed = _frame().compute("w = y + z")
    processed = processed.set_uncertainty({"w": 0.1})
    processed = processed.compute("v = w * 2")
    with pytest.raises(PipelineCompatibilityError, match="cannot be replayed"):
        processed.history.to_pipeline()


def test_leading_state_only_entries_are_treated_as_input_preparation() -> None:
    """Setup before any transform is the caller's job on the new frame."""
    db = _frame().set_uncertainty({"y": 0.1})
    processed = db.compute("w = y + z")
    pipeline = processed.history.to_pipeline()
    assert [step.method for step in pipeline] == ["compute"]


def test_concat_is_not_replayable() -> None:
    """concat references other frames, so it records no step (REQ-54)."""
    left = _frame()
    right = itc.load(
        np.column_stack([np.arange(10.0, 15.0), np.zeros(5), np.zeros(5)]),
        names=["x", "y", "z"],
    ).pivot(dims=["x"])
    merged = itc.concat([left, right], along="x")
    assert merged.history.entries[-1].step is None
    processed = merged.compute("w = y + z")
    # The concat sits before the first replayable step, so it is prefix.
    assert len(processed.history.to_pipeline()) == 1


# ---------------------------------------------------------------------------
# REQ-54: replay onto a new VarFrame
# ---------------------------------------------------------------------------


def test_replay_on_the_same_frame_reproduces_the_state_hash() -> None:
    """The strongest check: replay is the recorded computation."""
    db = _frame()
    processed = db.smooth(along="x", method="moving_avg", window=3)
    processed = processed.compute("w = y + z")
    replayed = processed.history.to_pipeline().apply(db)
    assert replayed.state_hash == processed.state_hash


def test_replay_on_new_data_applies_the_same_processing() -> None:
    recipe = _frame(seed=1).compute("w = y + z").history.to_pipeline()
    fresh = _frame(seed=2)
    out = recipe.apply(fresh)
    assert "w" in out.vars
    assert np.allclose(
        out.vars["w"].values,
        fresh.vars["y"].values + fresh.vars["z"].values,
    )


def test_replay_records_its_own_history_entries() -> None:
    """A replayed operation is recorded like any other (REQ-18)."""
    db = _frame()
    recipe = db.compute("w = y + z").history.to_pipeline()
    out = recipe.apply(db)
    assert out.history.entries[-1].operation.startswith("compute(")
    assert len(out.history) == len(db.history) + 1


def test_apply_on_an_incompatible_frame_raises() -> None:
    """Missing variables raise PipelineCompatibilityError (REQ-54)."""
    recipe = _frame().compute("w = y + z").history.to_pipeline()
    other = itc.load(
        np.column_stack([np.arange(5.0), np.arange(5.0)]), names=["x", "q"]
    ).pivot(dims=["x"])
    with pytest.raises(PipelineCompatibilityError, match="incompatible"):
        recipe.apply(other)


def test_apply_reports_which_step_failed() -> None:
    db = _frame()
    recipe = db.compute("w = y + z").history.to_pipeline()
    other = itc.load(
        np.column_stack([np.arange(5.0), np.arange(5.0)]), names=["x", "q"]
    ).pivot(dims=["x"])
    with pytest.raises(PipelineCompatibilityError) as excinfo:
        recipe.apply(other)
    assert "pipeline step 1" in str(excinfo.value)
    assert "compute" in str(excinfo.value)


def test_an_empty_pipeline_is_the_identity() -> None:
    db = _frame()
    assert Pipeline(steps=()).apply(db).state_hash == db.state_hash


# ---------------------------------------------------------------------------
# REQ-55: serialization
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = _frame()
    processed = db.smooth(along="x", method="moving_avg", window=3).compute("w = y + z")
    original = processed.history.to_pipeline()
    path = original.save(tmp_path / "recipe.itc_pipe")
    reloaded = itc.load_pipeline(path)
    assert [s.method for s in reloaded] == [s.method for s in original]
    assert [dict(s.kwargs) for s in reloaded] == [dict(s.kwargs) for s in original]
    assert reloaded.apply(db).state_hash == processed.state_hash


def test_the_saved_file_is_human_readable_json(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = _frame().smooth(along="x", method="moving_avg", window=3)
    path = db.history.to_pipeline().save(tmp_path / "recipe.itc_pipe")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    assert payload["schema"] == PIPELINE_SCHEMA
    assert payload["steps"][0]["method"] == "smooth"
    assert payload["steps"][0]["kwargs"]["window"] == 3


def test_save_is_atomic_leaving_no_temp_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = _frame().compute("w = y + z")
    db.history.to_pipeline().save(tmp_path / "recipe.itc_pipe")
    assert [p.name for p in tmp_path.iterdir()] == ["recipe.itc_pipe"]


def test_load_pipeline_rejects_an_unknown_schema(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "bad.itc_pipe"
    path.write_text(json.dumps({"schema": "other/9", "steps": []}), encoding="utf-8")
    with pytest.raises(DataError, match=r"unknown \.itc_pipe schema"):
        itc.load_pipeline(path)


def test_load_pipeline_rejects_malformed_json(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "bad.itc_pipe"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DataError, match="could not parse"):
        itc.load_pipeline(path)


# ---------------------------------------------------------------------------
# Replay fidelity across the operation set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "call"),
    [
        ("smooth", lambda db: db.smooth(along="x", method="moving_avg", window=3)),
        ("diff", lambda db: db.diff(along="x", window=5, deg=2)),
        ("compute", lambda db: db.compute("w = y * 2")),
        ("compute_where", lambda db: db.compute("w = y * 2", where="y > 5")),
        ("average", lambda db: db.average(along="x")),
        ("integrate", lambda db: db.integrate("y", over="x")),
        ("fill", lambda db: db.fill(along="x", method="linear")),
        ("fitmodel", lambda db: db.fitmodel(along="x", deg=2)),
        ("select", lambda db: db.select({"x": [1.0, 2.0, 3.0]})),
        ("expand", lambda db: db.expand("mach", [0.2, 0.4])),
        (
            "interpolate",
            lambda db: db.interpolate({"x": [1.5, 2.5, 3.5]}),
        ),
    ],
)
def test_every_replayable_op_reproduces_its_state_hash(
    label: str,
    call,  # type: ignore[no-untyped-def]
) -> None:
    """Each wired operation replays to a byte-identical state (REQ-54)."""
    db = _frame()
    processed = call(db)
    pipeline = processed.history.to_pipeline()
    assert len(pipeline) == 1, f"{label} recorded no replayable step"
    assert pipeline.apply(db).state_hash == processed.state_hash


@pytest.mark.parametrize(
    ("label", "call"),
    [
        ("squeeze", lambda db: db.squeeze()),
    ],
)
def test_squeeze_replays(label: str, call) -> None:  # type: ignore[no-untyped-def]
    base = _frame()
    db = base.select({"x": [1.0]})
    processed = call(db)
    # select is itself replayable, so the pipeline is select + squeeze
    # and replays from the untouched base frame.
    pipeline = processed.history.to_pipeline()
    assert [s.method for s in pipeline] == ["select", "squeeze"]
    assert pipeline.apply(base).state_hash == processed.state_hash


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
# Step and serialization helpers
# ---------------------------------------------------------------------------


def test_steps_serialize_numpy_values_as_json_natives() -> None:
    """expand receives arrays; the step must stay JSON-native (REQ-55)."""
    db = _frame()
    processed = db.expand("mach", np.array([0.2, 0.4]))
    step = processed.history.entries[-1].step
    assert step is not None
    json.dumps(step.kwargs)  # must not raise
    assert step.kwargs["values"] == [0.2, 0.4]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (np.array([1.0, 2.0]), [1.0, 2.0]),
        (np.float64(3.5), 3.5),
        (np.int64(7), 7),
        ((1, 2), [1, 2]),
        ({"a": np.int64(1)}, {"a": 1}),
        ("plain", "plain"),
        (None, None),
    ],
)
def test_to_jsonable_normalizes(value: object, expected: object) -> None:
    assert to_jsonable(value) == expected


def test_pipeline_step_is_frozen() -> None:
    step = PipelineStep(method="smooth", kwargs={"along": "x"})
    with pytest.raises(AttributeError):
        step.method = "diff"  # type: ignore[misc]
