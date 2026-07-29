"""CHK-1: the defects measured OPEN at the 0.2.0 release checkpoint.

Every test here was reproduced by a probe during the CHK-1 release
checkpoint against `730649f`, and each is named for the finding it comes
from. The probe is the source; this file is the asset.

Two kinds of test live here, and the difference is deliberate.

A test marked ``xfail(strict=True)`` pins a defect that is OPEN. It fails
today, which is why it is marked, and the marker is a RATCHET rather
than a excuse: the moment the defect is fixed the test passes, strict
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
from itaca.core.errors import ITACAError

ROOT = Path(__file__).resolve().parents[1]


def _frame(names, rows, dims):
    loaded = itc.load(np.array(rows, dtype=float), names=list(names))
    return loaded.pivot(dims=list(dims))


# ---------------------------------------------------------------------------
# Wrong numbers, produced silently. These are the release-critical ones.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="CHK1-001: open at 730649f")
def test_chk1_001_builtin_constant_does_not_shadow_a_measured_channel() -> None:
    """A frame variable named ``e`` must not lose to Euler's number.

    ``e`` is the Oswald span efficiency factor, so this is the most
    likely name collision in the library's own target domain. The
    library already refuses the same collision for an ``.itceq``
    ``[constants]`` name against a measured channel (DD-39, OQ-31); the
    built-in expression constants got no such check.
    """
    db = itc.load(np.array([[1.0, 8.0, 0.5]]), names=["CL", "AR", "e"])
    out = db.compute("CDi = CL**2 / (pi * AR * e)")
    obtained = float(np.asarray(out.vars["CDi"].values).ravel()[0])
    assert obtained == pytest.approx(1.0**2 / (np.pi * 8.0 * 0.5))


@pytest.mark.xfail(strict=True, reason="CHK1-002: open at 730649f")
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


@pytest.mark.xfail(strict=True, reason="CHK1-003: open at 730649f")
def test_chk1_003_concat_refuses_to_mix_vector_groups_from_different_axes() -> None:
    """Concatenating a body-axis frame with a wind-axis frame must refuse.

    ``concat`` keeps only the first frame's AxisRegistry, so the merged
    frame claims every row is in the first frame's axis. The next
    ``rotate`` then transforms the already-rotated rows a second time.
    REQ-107 makes the recorded source axis the thing that keeps a second
    rotation an identity; this defeats it.
    """

    def build(k: float) -> object:
        rows = [[k, 90.0, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["k", "alpha", "FX", "FY", "FZ"]).pivot(
            dims=["k"]
        )
        return db.set_metadata({"alpha": {"unit": "deg"}}).declare_vector(
            "force", ["FX", "FY", "FZ"]
        )

    body = build(0.0)
    wind = build(1.0).rotate("wind")
    assert body.axes.group_axis("force") != wind.axes.group_axis("force")
    with pytest.raises(ITACAError):
        itc.concat([body, wind], along="k")


@pytest.mark.xfail(strict=True, reason="R3-ITA-002: open at 730649f")
def test_r3_ita_002_combine_jacobians_do_not_inherit_an_integer_dtype() -> None:
    """The mean jacobian must stay 0.5, not truncate to 0 on an int array.

    ``np.full_like(a, 0.5)`` inherits ``a``'s dtype. Not reachable
    through ``itc.load``, which casts to float64, so the frame is built
    directly here; the defect is latent behind that cast rather than
    absent.
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


@pytest.mark.xfail(strict=True, reason="R3-ITA-006: open at 730649f")
def test_r3_ita_006_processor_applies_declared_uncertainty_to_an_existing_target(
    tmp_path: Path,
) -> None:
    """The same ``.itceq`` must give the same uncertainty either way.

    ``[uncertainties] y = 5.0`` is dropped from the pending set when the
    frame already carries ``y``, and ``compute`` then clears the
    overwritten target's uncertainty, so nothing reinstates it.
    """
    path = tmp_path / "corr.itceq"
    path.write_text(
        '[meta]\nname = "corr"\nversion = "1.0"\n\n'
        "[uncertainties]\ny = 5.0\n\n"
        '[equations]\ny = "2*x"\n',
        encoding="utf-8",
    )
    proc = itc.processor(str(path))
    absent = itc.load(np.array([[3.0], [4.0]]), names=["x"])
    present = itc.load(np.array([[3.0, 99.0], [4.0, 99.0]]), names=["x", "y"])
    ua = dict(proc(absent).uncertainty.systematic)["y"]
    assert proc(present).uncertainty is not None
    ub = dict(proc(present).uncertainty.systematic)["y"]
    assert np.asarray(ub) == pytest.approx(np.asarray(ua))


# ---------------------------------------------------------------------------
# Silent data loss and invalid input accepted at a public boundary.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="R3-ITA-007: open at 730649f")
@pytest.mark.parametrize("value", [float("nan"), float("inf"), "nan%", "inf%"])
def test_r3_ita_007_set_uncertainty_refuses_a_non_finite_value(value: object) -> None:
    """A non-finite standard uncertainty is not a standard uncertainty.

    ``UncFrame`` already refuses a negative one with a GUM citation; the
    finiteness half of the same rule is missing, so NaN enters the state
    and propagates into every derived quantity.
    """
    db = itc.load(np.array([[1.0], [2.0]]), names=["x"])
    with pytest.raises(ITACAError):
        db.set_uncertainty({"x": value})


@pytest.mark.xfail(strict=True, reason="R3-ITA-009: open at 730649f")
def test_r3_ita_009_csv_row_wider_than_the_header_is_refused(tmp_path: Path) -> None:
    """A cell past the header width must not vanish.

    ``_read_csv`` iterates the header and indexes into the row, so the
    third cell is dropped with no signal, while Provenance still hashes
    the complete file bytes: the source hash certifies bytes the frame
    does not represent.
    """
    path = tmp_path / "ragged.csv"
    path.write_text("a,b\n1,2,3\n4,5\n", encoding="utf-8")
    with pytest.raises(ITACAError):
        itc.load(path)


@pytest.mark.xfail(strict=True, reason="R3-ITA-008: open at 730649f")
def test_r3_ita_008_a_variable_cannot_collide_with_the_synthetic_dimension() -> None:
    """``dims`` and ``vars`` must not intersect.

    Datapoint mode always creates the synthetic ``datapoint`` dimension
    and also accepts a column of that name, so one frame carries both.
    ``select`` then resolves the dimension, and ``to_pandas`` loses one
    of the two columns to a dict-key overwrite.
    """
    db = itc.load(np.array([[10.0, 1.0], [20.0, 2.0]]), names=["datapoint", "a"])
    assert set(db.dims).isdisjoint(set(db.vars))


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


@pytest.mark.xfail(strict=True, reason="ITACA-031: open at 730649f")
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


@pytest.mark.xfail(strict=True, reason="ITACA-012: residual at 730649f")
def test_itaca_012_no_chapter_claims_an_absent_export_symbol() -> None:
    """The ITACA-012 scan must cover every chapter, not the cited one.

    Chapter 8 was corrected and now retracts the claim in place. REQ-70
    in chapter 6 still lists ``db.export_provenance`` among the export
    formats, and the guard test reads only chapter 8, so it cannot see
    it.
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


@pytest.mark.xfail(strict=True, reason="R3-ITA-010: open at 730649f")
def test_r3_ita_010_the_trace_does_not_count_its_own_inventory_as_evidence() -> None:
    """A requirement id listed as unreached must not thereby be reached.

    ``build_trace`` walks the whole suite including the module that
    declares ``_UNREACHED_AT_LANE_CLOSE``, so all 28 ids in that
    inventory register as test citations of themselves. Excluding the
    file moves the unreached count from 0 to 25.
    """
    from tests.test_requirement_trace import build_trace

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
