"""CHK-1: the defects measured OPEN at the 0.2.0 release checkpoint.

Every test here was reproduced by a probe during the CHK-1 release
checkpoint against `730649f`, and each is named for the finding it comes
from. The probe is the source; this file is the asset.

Two kinds of test live here, and the difference is deliberate.

A test marked ``xfail(strict=True)`` pins a defect that is OPEN. It fails
today, which is why it is marked, and the marker is a RATCHET rather
than an excuse: the moment the defect is fixed the test passes, strict
xfail turns an unexpected pass into a failure, and whoever fixed it must
come here and remove the marker. An open defect recorded only in prose
is invisible to CI; recorded this way it cannot be forgotten and it
cannot be silently re-broken later.

An unmarked test pins behavior that is already CORRECT and was not
otherwise covered, so a regression would be caught.

Ids beginning ``ITACA-`` are REV-001 findings that survived the ITA-1
remediation. Ids beginning ``R3-ITA-`` are REV-003 findings. Ids
beginning ``CHK1-`` were found by CHK-1's own independent pass.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.coords import Cartesian, Polar
from itaca.core.errors import AxesError, DataError, ITACAError

ROOT = Path(__file__).resolve().parents[1]


def _frame(names, rows, dims):
    loaded = itc.load(np.array(rows, dtype=float), names=list(names))
    return loaded.pivot(dims=list(dims))


# ---------------------------------------------------------------------------
# Wrong numbers, produced silently. These are the release-critical ones.
# ---------------------------------------------------------------------------


def test_chk1_001_builtin_constant_does_not_shadow_a_measured_channel() -> None:
    """A frame variable named ``e`` must not lose to Euler's number.

    ``e`` is the Oswald span efficiency factor, so this is the most
    likely name collision in the library's own target domain. Measured
    before the fix: ``CDi`` came out ``0.01463746``, the value for
    Euler's number, where ``0.07957747`` is correct for ``e = 0.5``, and
    neither the result nor History said so.

    Two remedies were open, the frame winning or the collision being
    refused, and refusing is the one taken: it is symmetric with DD-39,
    which already refuses an ``.itceq`` ``[constants]`` name against a
    measured channel, and REQ-44 names ``pi`` and ``e`` without saying
    which wins, so silently choosing either would be a new rule invented
    at the point of a wrong answer. The refusal must name the collision.
    """
    db = itc.load(np.array([[1.0, 8.0, 0.5]]), names=["CL", "AR", "e"])
    with pytest.raises(ITACAError) as raised:
        db.compute("CDi = CL**2 / (pi * AR * e)")
    assert "'e'" in str(raised.value)
    # pi is still a constant on a frame that does not carry the name
    plain = itc.load(np.array([[1.0, 8.0]]), names=["CL", "AR"])
    out = plain.compute("half = pi / 2.0")
    assert float(np.asarray(out.vars["half"].values).ravel()[0]) == pytest.approx(
        np.pi / 2.0
    )


@pytest.mark.parametrize("name", ["pi", "e"])
def test_chk1_001_the_rule_covers_every_builtin_constant(name: str) -> None:
    """Neither constant is exempt, and this is why the case is parametrized.

    The rule is about a MEASURED channel becoming unreadable, which is
    true of any name the expression language also supplies. A narrowing
    to one of the two would leave the other silently returning the
    constant while the surrounding comment still stated the general rule,
    so the guard needs a guard: this test fails the moment the condition
    stops covering both names, whatever the reason.
    """
    db = itc.load(np.array([[2.0, 3.0]]), names=[name, "other"])
    with pytest.raises(ITACAError) as raised:
        db.compute(f"y = {name} * other")
    assert name in str(raised.value)


def test_chk1_002_negative_itceq_constant_keeps_its_sign_under_a_power(
    tmp_path: Path,
) -> None:
    """``x_ref = -0.25`` with ``x_ref ** 2`` must give ``+0.0625``.

    Constant substitution rewrites the AST and round-trips through
    ``ast.unparse``, which emits ``-0.25`` as a bare token. Re-parsed in
    the base of a power that binds as ``-(0.25 ** 2)``. History then
    records the substituted expression, so the provenance record is
    self-consistent and wrong.
    """
    path = tmp_path / "moment.itceq"
    path.write_text(
        '[meta]\nname = "Moment"\nversion = "1.0"\n\n'
        "[constants]\nx_ref = -0.25\n\n"
        '[equations]\nCm = "x_ref ** 2 * CN"\n',
        encoding="utf-8",
    )
    db = itc.load(np.array([[2.0]]), names=["CN"])
    out = itc.processor(str(path))(db)
    obtained = float(np.asarray(out.vars["Cm"].values).ravel()[0])
    assert obtained == pytest.approx((-0.25) ** 2 * 2.0)
    # The sharper half: History recorded `Cm = -0.25 ** 2 * CN`, an
    # expression that is not equivalent to the file's, so the provenance
    # record was self-consistent and wrong. It must round-trip.
    recorded = out.history.entries[-1].operation
    assert "(-0.25) ** 2" in recorded, recorded


def test_chk1_001_a_processor_refuses_a_shadowed_channel_at_validate(
    tmp_path: Path,
) -> None:
    """The refusal must land at ``validate``, not mid-application.

    ``_dependencies`` subtracts ``pi`` and ``e`` unconditionally, so the
    name never reached ``required_variables`` and ``validate`` certified
    a frame the equations could not actually read. REQ-45 makes
    ``validate`` the step that answers whether this frame can feed this
    processor, so that is where the collision has to surface.
    """
    path = tmp_path / "drag.itceq"
    path.write_text(
        '[meta]\nname = "drag"\nversion = "1.0"\n\n'
        '[equations]\nCDi = "CL ** 2 / (pi * AR * e)"\n',
        encoding="utf-8",
    )
    proc = itc.processor(str(path))
    carries_e = itc.load(np.array([[1.0, 8.0, 0.5]]), names=["CL", "AR", "e"])
    with pytest.raises(ITACAError) as raised:
        proc.validate(carries_e)
    assert "e" in str(raised.value)


def test_chk1_003_concat_refuses_to_mix_vector_groups_from_different_axes() -> None:
    """Concatenating a body-axis frame with a wind-axis frame must refuse.

    ``concat`` keeps only the first frame's AxisRegistry, so the merged
    frame claims every row is in the first frame's axis. The next
    ``rotate`` then transforms the already-rotated rows a second time.
    REQ-107 makes the recorded source axis the thing that keeps a second
    rotation an identity; this defeats it.
    """

    def build(k: float) -> object:
        rows = [[k, 90.0, 0.0, 1.0, 0.0, 0.0]]
        names = ["k", "alpha", "beta", "FX", "FY", "FZ"]
        db = itc.load(np.array(rows), names=names).pivot(dims=["k"])
        db = db.set_metadata({"alpha": {"unit": "deg"}, "beta": {"unit": "deg"}})
        return db.declare_vector("force", ["FX", "FY", "FZ"])

    body = build(0.0)
    wind = build(1.0).rotate("wind")
    assert body.axes.group_axis("force") == "body"
    assert wind.axes.group_axis("force") == "wind"
    with pytest.raises(AxesError, match="different axis systems"):
        itc.concat([body, wind], along="k")
    # Two inputs agreeing on the axis still concatenate.
    joined = itc.concat([body, build(1.0)], along="k")
    assert joined.axes.group_axis("force") == "body"


@pytest.mark.parametrize("reversed_order", [False, True])
def test_chk1_003_the_axis_check_covers_the_undeclared_input(
    reversed_order: bool,
) -> None:
    """The commonest shape of all: nobody called ``declare_vector``.

    ``rotate`` registers a group only when it rotates it, so a raw frame
    carries FX/FY/FZ with NO entry in ``vector_groups`` while
    ``group_axis`` answers ``"body"`` for it by design. A check driven by
    what each frame declares saw one axis, passed, and left the double
    rotation reachable through the path where the user never declared
    anything. Driving it from the union of names closes that, and both
    argument orders are wrong in their own direction, so both are pinned.
    """
    rows = [[0.0, 90.0, 0.0, 1.0, 0.0, 0.0]]
    names = ["k", "alpha", "beta", "FX", "FY", "FZ"]

    def build(k: float) -> object:
        db = itc.load(np.array([[k, *rows[0][1:]]]), names=names).pivot(dims=["k"])
        return db.set_metadata({"alpha": {"unit": "deg"}, "beta": {"unit": "deg"}})

    raw = build(0.0)
    rotated = build(1.0).declare_vector("force", ["FX", "FY", "FZ"]).rotate("wind")
    assert "force" not in raw.axes.vector_groups
    assert rotated.axes.group_axis("force") == "wind"
    inputs = [rotated, raw] if reversed_order else [raw, rotated]
    with pytest.raises(AxesError, match="different axis systems"):
        itc.concat(inputs, along="k")


def test_chk1_001_a_correction_reading_a_shadowed_channel_is_refused_at_validate(
    tmp_path: Path,
) -> None:
    """``__call__`` runs corrections too, so ``validate`` must see them.

    Scanning only ``[equations]`` let a correction reading ``e`` pass
    validation and then fail inside ``compute`` partway through the
    application, after ``set_uncertainty`` had run and after earlier
    equations had already been written. The check reads the spec
    property, which is computed over both sections.
    """
    path = tmp_path / "corr.itceq"
    path.write_text(
        '[meta]\nname = "corr"\nversion = "1.0"\n\n'
        '[equations]\nCL = "FZ / q"\n\n'
        '[corrections]\nCL = "CL * e"\n',
        encoding="utf-8",
    )
    proc = itc.processor(str(path))
    assert proc.spec.builtin_constants == ("e",)
    carries_e = itc.load(np.array([[1.0, 2.0, 0.5]]), names=["FZ", "q", "e"])
    with pytest.raises(ITACAError) as raised:
        proc.validate(carries_e)
    assert "e" in str(raised.value)


def test_r3_ita_002_combine_jacobians_do_not_inherit_an_integer_dtype() -> None:
    """The mean jacobian must stay 0.5, not truncate to 0 on an int array.

    ``np.full_like(a, 0.5)`` inherits ``a``'s dtype. Not reachable
    through ``itc.load``, which casts to float64, so the frame is built
    directly here; the defect is latent behind that cast rather than
    absent.

    FIXED, and the marker removed with the fix (FND-035). Measured on the
    base with ``--runxfail``: ``[0., 0.]`` against ``2.5 +/- 2.5e-06``.
    The partials of ``mean`` and ``weighted_mean`` are now built with
    ``np.full`` on the operand's shape. The behavior itself is covered in
    ``tests/core/test_combine.py::TestCombineJacobianDtype``, which states
    the invariant over every operation of the REQ-37 table rather than
    over this one.
    """
    base = _frame(["i", "F"], [[0, 10], [1, 20]], ["i"])
    ints = np.array([10, 20], dtype=np.int64)
    ints.setflags(write=False)

    def as_int(db: object, u: float) -> object:
        db = db.set_uncertainty({"F": u})
        return dataclasses.replace(
            db, vars={"F": dataclasses.replace(db.vars["F"], values=ints)}
        )

    out = as_int(base, 3.0).combine(as_int(base, 4.0), op="mean")
    u = np.asarray(dict(out.uncertainty.systematic)["F"], dtype=float)
    assert u == pytest.approx(2.5)


def test_r3_ita_006_processor_applies_declared_uncertainty_to_an_existing_target(
    tmp_path: Path,
) -> None:
    """The same ``.itceq`` must give the same uncertainty either way.

    FIXED, and the marker removed with the fix. ``itaca/pproc/base.py``
    sorted the ``[uncertainties]`` declarations by whether the incoming
    frame already carried the name, when the rule is whether the FILE
    PRODUCES it: a target the frame carried was assigned before the loop
    and then overwritten by its own equation's propagation.

    Measured before the fix, on the two files below. With ``y = 5.0``
    alone, the present-target run shipped ``uncertainty is None``: the
    declaration vanished. With ``x = 1.0`` beside it, the SAME run shipped
    ``u(y) = [2.0, 2.0]``, which is what ``u(x) = 1.0`` propagates to
    through ``y = 2*x``, where the file declares ``5.0``.

    The second file is ``R4-ITA-003`` (``ITC-20260730-0105``) and is why
    this finding was reopened as a release blocker rather than closed as a
    lost declaration. A missing uncertainty is a visible gap. A DIFFERENT
    one, finite and plausible and selected by whether the input frame
    happened to carry a column, is a wrong number a reader cannot detect.
    Both branches are pinned here, and the behavior itself is covered in
    ``tests/pproc/test_processor.py`` where it belongs.
    """
    absent = itc.load(np.array([[3.0], [4.0]]), names=["x"])
    present = itc.load(np.array([[3.0, 99.0], [4.0, 99.0]]), names=["x", "y"])
    for label, declarations in (
        ("dropped", "y = 5.0\n"),
        ("replaced by 2.0", "x = 1.0\ny = 5.0\n"),
    ):
        path = tmp_path / f"corr_{label.split()[0]}.itceq"
        path.write_text(
            '[meta]\nname = "corr"\nversion = "1.0"\n\n'
            f"[uncertainties]\n{declarations}\n"
            '[equations]\ny = "2*x"\n',
            encoding="utf-8",
        )
        proc = itc.processor(str(path))
        ua = dict(proc(absent).uncertainty.systematic)["y"]
        result = proc(present)
        assert result.uncertainty is not None, (
            f"the {label} branch shipped no uncertainty at all (R3-ITA-006)"
        )
        ub = dict(result.uncertainty.systematic)["y"]
        assert np.asarray(ub) == pytest.approx(np.asarray(ua)), (
            f"the {label} branch shipped u(y) = {np.asarray(ub).tolist()} "
            f"against a frame carrying y, and {np.asarray(ua).tolist()} "
            f"against one that did not, from one file"
        )
        assert np.asarray(ub) == pytest.approx(5.0), (
            f"the {label} branch shipped u(y) = {np.asarray(ub).tolist()} "
            f"where the file declares 5.0 (R4-ITA-003)"
        )


# ---------------------------------------------------------------------------
# Silent data loss and invalid input accepted at a public boundary.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        "nan%",
        "inf%",
        # The malformed-percentage cases. Without these the ValueError
        # arm of the parse is caught by nothing: every value above is
        # accepted by float() and lands in the finiteness branch, so
        # narrowing the except clause to TypeError left the suite green.
        "abc%",
        "5.0.0%",
        object(),
    ],
)
def test_r3_ita_007_set_uncertainty_refuses_a_non_finite_value(value: object) -> None:
    """A non-finite standard uncertainty is not a standard uncertainty.

    ``UncFrame`` already refuses a negative one with a GUM citation; the
    finiteness half of the same rule is missing, so NaN enters the state
    and propagates into every derived quantity.
    """
    db = itc.load(np.array([[1.0], [2.0]]), names=["x"])
    with pytest.raises(ITACAError):
        db.set_uncertainty({"x": value})


@pytest.mark.xfail(strict=True, reason="R3-ITA-007 structural half: OQ-40")
def test_r3_ita_007_a_relative_spec_cannot_inherit_a_non_finite_value() -> None:
    """The half of R3-ITA-007 the declared-magnitude check does not reach.

    ``"5%"`` is a valid spec and ``_resolve_value`` resolves it against
    the data, so a variable carrying NaN yields a NaN standard
    uncertainty with nothing refused. The structural fix is a finiteness
    rule on the assembled array in ``UncFrame``, beside the negativity
    rule; it was attempted and reverted because ``compute(where=)`` and
    both ``fill`` uncertainty paths write NaN deliberately for cells they
    did not touch, so that array carries two meanings of NaN and
    separating them is the numerical analyst's call (OQ-40).

    Pinned here rather than left in prose, so the remaining hole is
    visible to CI and this ratchet turns the moment OQ-40 is answered.
    """
    db = itc.load(np.array([[1.0], [np.nan]]), names=["x"])
    with pytest.raises(ITACAError):
        db.set_uncertainty({"x": "5%"})


def test_r3_ita_009_csv_row_wider_than_the_header_is_refused(tmp_path: Path) -> None:
    """A cell past the header width must not vanish.

    ``_read_csv`` iterates the header and indexes into the row, so the
    third cell is dropped with no signal, while Provenance still hashes
    the complete file bytes: the source hash certifies bytes the frame
    does not represent.
    """
    path = tmp_path / "ragged.csv"
    path.write_text("a,b\n1,2,3\n4,5\n", encoding="utf-8")
    with pytest.raises(DataError, match="fields against a header"):
        itc.load(path)


def test_r3_ita_009_the_refusal_message_names_every_part_req01_promises(
    tmp_path: Path,
) -> None:
    """REQ-01 describes this message in detail, so all of it is pinned.

    The requirement (SRS 0.2.3) says the refusal names the row, its field
    count, the header, the cells that would have been discarded, and the
    suggested fix. Only the third of those was asserted before, by a
    ``match=`` on one phrase, so dropping ``row[len(header):]`` from the
    message would have kept the suite green and made REQ-01 false.
    """
    path = tmp_path / "wide.csv"
    path.write_text("alpha,CT\n0.0,0.1\n2.0,0.2,9.9\n", encoding="utf-8")
    with pytest.raises(DataError) as caught:
        itc.load(path)
    message = str(caught.value)
    for part in (
        "row 3",  # the row
        "3 fields",  # its field count
        "['alpha', 'CT']",  # the header
        "['9.9']",  # the cells that would have been discarded
        "Suggested fix",  # REQ-81's three-part contract
        "quote the field",  # the fix itself
    ):
        assert part in message, (
            f"the refusal message omits {part!r}, which REQ-01 states it "
            f"names. Message: {message!r}"
        )


def test_r3_ita_009_a_row_narrower_than_the_header_is_still_nan_filled(
    tmp_path: Path,
) -> None:
    """The lenient half of the asymmetry REQ-01 states, and it had no test.

    REQ-01 says a row NARROWER than its header is not refused and its absent
    trailing cells are NaN-filled. Nothing asserted it: the only ragged
    fixture in the suite raises on its wide row before any narrow row is
    parsed, and the empty-cell test uses a full-width row. So generalizing
    ``len(row) > len(header)`` to ``!=``, which is the natural "ragged is
    malformed" reading, would have left the whole suite green while
    contradicting the requirement.
    """
    path = tmp_path / "narrow.csv"
    path.write_text("a,b\n1\n4,5\n", encoding="utf-8")
    db = itc.load(path)
    values, _dims = db.to_numpy(return_dims=True)
    assert np.isnan(values["b"][0]), (
        f"a row narrower than its header must NaN-fill its absent trailing "
        f"cells, per REQ-01. Got {values['b']!r}"
    )
    assert values["a"][0] == 1.0
    assert values["b"][1] == 5.0


def test_r3_ita_008_a_variable_cannot_collide_with_the_synthetic_dimension() -> None:
    """``dims`` and ``vars`` must not intersect.

    Datapoint mode always creates the synthetic ``datapoint`` dimension
    and also accepts a column of that name, so one frame carries both.
    ``select`` then resolves the dimension, and ``to_pandas`` loses one
    of the two columns to a dict-key overwrite.
    """
    with pytest.raises(DataError, match="BOTH a dimension and a variable"):
        itc.load(np.array([[10.0, 1.0], [20.0, 2.0]]), names=["datapoint", "a"])
    # The invariant is on the CONSTRUCTOR, so an operation cannot build
    # one either. Asserted by driving one rather than by restating the
    # claim: `expand` adds a dimension, and it must refuse a name the
    # frame already carries as a variable.
    ordinary = itc.load(np.array([[0.0, 1.0], [1.0, 2.0]]), names=["i", "a"]).pivot(
        dims=["i"]
    )
    with pytest.raises(ITACAError):
        ordinary.expand("a", [0.0, 1.0])


@pytest.mark.xfail(strict=True, reason="R3-ITA-013: open at 730649f")
@pytest.mark.parametrize("method", ["linear", "cubic"])
def test_r3_ita_013_interpolation_from_one_point_fails_loud(method: str) -> None:
    """One source point must refuse, not return infinity.

    The kernels assume at least two points; the degenerate case returns
    ``inf`` behind a bare RuntimeWarning.
    """
    db = _frame(["x", "y"], [[0.0, 2.0]], ["x"])
    with pytest.raises(ITACAError):
        db.interpolate({"x": [1.0]}, method=method)


@pytest.mark.xfail(strict=True, reason="R3-ITA-014: open at 730649f")
def test_r3_ita_014_average_does_not_treat_infinity_as_missing() -> None:
    """REQ-27 says the mean skips NaN, not every non-finite value.

    ``average`` filters with ``np.isfinite``, so a genuine infinity is
    dropped and a misleadingly finite mean is reported.
    """
    db = _frame(["i", "v"], [[0.0, 1.0], [1.0, np.inf]], ["i"])
    out = db.average(along="i")
    assert not np.isfinite(np.asarray(out.vars["v"].values).ravel()[0])


# ---------------------------------------------------------------------------
# Identity, persistence and the audit trail.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="R3-ITA-004: open at 730649f")
def test_r3_ita_004_coord_system_is_part_of_the_state() -> None:
    """Two frames that integrate differently must not share a hash.

    ``CoordSystem`` is read by ``integrate`` only through its own
    argument, is excluded from the state hash, and is not written to
    ``.itc``. OQ-39 records the loss and says it should not survive.
    """
    r = np.linspace(0.0, 1.0, 3)
    rows = [[ri, ti, 1.0] for ri in r for ti in r]
    db = itc.load(np.array(rows), names=["r", "theta", "v"]).pivot(dims=["r", "theta"])
    assert (
        dataclasses.replace(db, coords=Cartesian()).state_hash
        != dataclasses.replace(db, coords=Polar()).state_hash
    )


@pytest.mark.xfail(strict=True, reason="R3-ITA-004: open at 730649f")
def test_r3_ita_004_coord_system_survives_an_itc_round_trip(tmp_path: Path) -> None:
    """A Polar frame must not come back Cartesian."""
    db = _frame(["r", "v"], [[0.0, 1.0], [1.0, 1.0]], ["r"])
    polar = dataclasses.replace(db, coords=Polar())
    path = polar.save(tmp_path / "x.itc", allow_draft=True)
    assert isinstance(itc.open(path).coords, Polar)


@pytest.mark.xfail(strict=True, reason="R3-ITA-005: open at 730649f")
def test_r3_ita_005_itc_rejects_a_tampered_last_history_hash(tmp_path: Path) -> None:
    """A forged state hash in History must be detected.

    ``steps_hash`` covers replay steps and the manifest compares the
    current state, but the individual ``HistoryEntry.state_hash`` values
    are reconstructed unauthenticated, so the audit trail can carry a
    false declaration while the current state stays intact.
    """
    db = _frame(["i", "a"], [[0.0, 1.0], [1.0, 2.0]], ["i"]).compute(
        "b = a * 2", history=True
    )
    path = db.save(tmp_path / "x.itc", allow_draft=True)
    with zipfile.ZipFile(path) as archive:
        blobs = {name: archive.read(name) for name in archive.namelist()}
    name = next(n for n in blobs if "history" in n)
    payload = json.loads(blobs[name])
    entries = payload["entries"] if isinstance(payload, dict) else payload
    key = next(k for k in entries[-1] if "hash" in k)
    entries[-1][key] = "0" * 64
    blobs[name] = json.dumps(payload).encode()
    forged = tmp_path / "forged.itc"
    with zipfile.ZipFile(forged, "w") as archive:
        for member, blob in blobs.items():
            archive.writestr(member, blob)
    with pytest.raises(ITACAError):
        itc.open(forged)


@pytest.mark.xfail(strict=True, reason="R3-ITA-003: open at 730649f")
def test_r3_ita_003_state_hash_separates_a_missing_comment_from_an_empty_one() -> None:
    """``comment=None`` and ``comment=""`` are different states.

    History frames its fields with a bare ``0x1f`` separator and
    ``(comment or "")``, with no length prefix, so the two collapse and
    a comment containing the separator can cross a field boundary.
    """
    db = _frame(["i", "a"], [[0.0, 1.0], [1.0, 2.0]], ["i"])
    absent = db.compute("b = a * 2", history=True, comment=None)
    empty = db.compute("b = a * 2", history=True, comment="")
    assert absent.state_hash != empty.state_hash


@pytest.mark.xfail(strict=True, reason="R3-ITA-019: open at 730649f")
def test_r3_ita_019_metadata_field_order_does_not_change_the_hash() -> None:
    """The same final metadata must hash the same however it was given.

    ``set_metadata`` sorts the outer mapping but preserves the inner
    field order in the History string, so an incidental construction
    detail becomes part of the identity.
    """
    db = _frame(["alpha", "FX"], [[0.0, 1.0], [1.0, 2.0]], ["alpha"])
    a = db.set_metadata({"alpha": {"unit": "deg", "description": "angle"}})
    b = db.set_metadata({"alpha": {"description": "angle", "unit": "deg"}})
    assert a.dims["alpha"].unit == b.dims["alpha"].unit
    assert a.state_hash == b.state_hash


@pytest.mark.xfail(strict=True, reason="R3-ITA-015: open at 730649f")
def test_r3_ita_015_a_malformed_itc_raises_an_itaca_error(tmp_path: Path) -> None:
    """A corrupt member must not leak ``json.JSONDecodeError``."""
    db = _frame(["i", "a"], [[0.0, 1.0], [1.0, 2.0]], ["i"])
    path = db.save(tmp_path / "x.itc", allow_draft=True)
    with zipfile.ZipFile(path) as archive:
        blobs = {name: archive.read(name) for name in archive.namelist()}
    blobs[next(n for n in blobs if "metadata" in n)] = b"{not json"
    broken = tmp_path / "broken.itc"
    with zipfile.ZipFile(broken, "w") as archive:
        for member, blob in blobs.items():
            archive.writestr(member, blob)
    with pytest.raises(ITACAError):
        itc.open(broken)


# ---------------------------------------------------------------------------
# The error hierarchy, still open at three sites (ITACA-031).
# ---------------------------------------------------------------------------


def test_itaca_031_set_uncertainty_wraps_a_bad_value_type() -> None:
    """``set_uncertainty({"x": object()})`` must raise an ``ITACAError``."""
    db = _frame(["i", "x"], [[0.0, 1.0], [1.0, 2.0]], ["i"])
    with pytest.raises(ITACAError):
        db.set_uncertainty({"x": object()})


@pytest.mark.xfail(strict=True, reason="ITACA-031: open at 730649f")
def test_itaca_031_a_broken_processor_constructor_raises_an_itaca_error() -> None:
    """The one place third-party code plugs in must not leak."""
    from itaca.pproc.registry import register_processor

    register_processor("chk1_none", lambda **_: None)
    with pytest.raises(ITACAError):
        _ = itc.processor("chk1_none").name


@pytest.mark.xfail(strict=True, reason="ITACA-030: open at 730649f")
def test_itaca_030_combine_refuses_incompatible_units() -> None:
    """Newtons and pounds-force must not be summed silently.

    The four numeric halves of ITACA-030 were closed; the units half was
    not, and the result takes the left operand's label.
    """
    a = _frame(["i", "F"], [[0.0, 1.0], [1.0, 2.0]], ["i"]).set_metadata(
        {"F": {"unit": "N"}}
    )
    b = _frame(["i", "F"], [[0.0, 1.0], [1.0, 2.0]], ["i"]).set_metadata(
        {"F": {"unit": "lbf"}}
    )
    with pytest.raises(ITACAError):
        a.combine(b, op="sum")


# ---------------------------------------------------------------------------
# Claims the repository makes about itself.
# ---------------------------------------------------------------------------


def test_itaca_012_no_chapter_claims_an_absent_export_symbol() -> None:
    """The ITACA-012 scan must cover every chapter, not the cited one.

    FIXED before the v0.2.0 tag, and the marker is gone because the ratchet
    forced it: this passed, and strict xfail turns a pass into a failure.

    Chapter 8 was corrected when ITACA-012 was first closed, and REQ-70 in
    chapter 6 went on listing ``db.export_provenance`` among the export
    formats with no qualifier, because the guard written for the finding
    read chapter 8 alone. So a stable requirement promised a method that
    exists nowhere, in a document the sdist now publishes. The release
    review found it; REQ-70 now marks it an M2 deliverable and NOT
    IMPLEMENTED.

    This test is the widened form and it stays: it walks EVERY chapter, so
    the next claim of an absent symbol cannot hide in the one file the
    original guard did not read. The skip below is the forward path, for
    when M2 actually ships the method.
    """
    package = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "itaca").rglob("*.py"))
    )
    if "def export_provenance" in package:  # pragma: no cover - future M2
        pytest.skip("export_provenance now exists; the claim is no longer false")
    claiming = []
    for path in sorted((ROOT / "docs/srs/chapters").glob("*.tex")):
        flat = path.read_text(encoding="utf-8").replace("\\_", "_")
        lines = flat.splitlines()
        for number, line in enumerate(lines, 1):
            if "export_provenance" not in line:
                continue
            window = "\n".join(lines[max(0, number - 12) : number + 12])
            if not re.search(r"not implemented|M2 deliverable|v0\.3\.0", window, re.I):
                claiming.append(f"{path.name}:{number}")
    assert not claiming, f"chapters claiming an absent symbol: {claiming}"


def test_r3_ita_010_the_trace_does_not_count_its_own_inventory_as_evidence() -> None:
    """A requirement id listed as unreached must not thereby be reached.

    ``build_trace`` WALKED the whole suite including the module that
    declares ``_UNREACHED_AT_LANE_CLOSE``, so the 28 ids the inventory
    then carried registered as test citations of themselves and the gate
    reported zero unreached. Excluding the file restores the honest
    count, whose single home is ``_UNREACHED_AT_LANE_CLOSE`` itself;
    it is deliberately not restated here, because a number with two
    homes is what the sibling defect ``ITACA-012`` is made of.
    """
    # Bare name, not `tests.`: this suite has no package __init__, and
    # pytest's prepend import mode puts `tests/` on sys.path, which is
    # the same reason `from conftest import child_env` works. The dotted
    # form resolved on one machine and raised ModuleNotFoundError in CI.
    from test_requirement_trace import build_trace

    contaminated = {
        identifier
        for identifier, requirement in build_trace().items()
        if not requirement.code
        and requirement.tests == {"tests/test_requirement_trace.py"}
    }
    assert not contaminated, (
        f"reached only by the inventory itself: {sorted(contaminated)}"
    )


# ---------------------------------------------------------------------------
# Behavior that is CORRECT and was not otherwise pinned.
# ---------------------------------------------------------------------------


def test_itaca_021_angle_only_uncertainty_matches_the_chain_rule_oracle() -> None:
    """A rotation driven by a measured angle propagates that angle.

    Locked here because CHK-1 measured it against the analytic oracle
    rather than against the previous behavior: with an exact unit vector
    along x and ``u(alpha) = 1 deg`` at ``alpha = 30 deg``, the rotated
    components carry ``|sin a| da`` and ``|cos a| da``.
    """
    from itaca.core.axes import Axis

    rows = [[0.0, 30.0, 1.0, 0.0, 0.0], [1.0, 30.0, 1.0, 0.0, 0.0]]
    db = itc.load(np.array(rows), names=["i", "alpha", "FX", "FY", "FZ"]).pivot(
        dims=["i"]
    )
    db = db.set_metadata({"alpha": {"unit": "deg"}})
    db = db.declare_vector("force", ["FX", "FY", "FZ"]).set_uncertainty({"alpha": 1.0})
    rotated = db.register_axis(
        Axis(name="measured_wind", angles_from=("alpha",), convention="stability")
    ).rotate("measured_wind")
    systematic = dict(rotated.uncertainty.systematic)
    radians = np.deg2rad(1.0)
    assert np.asarray(systematic["FX"])[0] == pytest.approx(
        abs(np.sin(np.deg2rad(30.0))) * radians
    )
    assert np.asarray(systematic["FZ"])[0] == pytest.approx(
        abs(np.cos(np.deg2rad(30.0))) * radians
    )


def test_itaca_019_csv_round_trips_a_name_carrying_the_delimiter(
    tmp_path: Path,
) -> None:
    """A variable named ``a,b`` must not change the column count."""
    db = _frame(["i", "a,b"], [[0.0, 1.0], [1.0, 2.0]], ["i"])
    path = db.to_csv(tmp_path / "x.csv", allow_draft=True)
    rows = [
        row
        for row in csv.reader(
            line
            for line in Path(str(path)).read_text(encoding="utf-8").splitlines()
            if not line.startswith("#")
        )
        if row
    ]
    assert rows[0] == ["i", "a,b"]
    assert len({len(row) for row in rows}) == 1
