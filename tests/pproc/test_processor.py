"""Processor protocol, factory, and idempotence (REQ-45 to REQ-47, DD-16)."""

from __future__ import annotations

import re
import types
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    ItceqParseError,
    ProcessorError,
    ProcessorIdempotenceWarning,
    ProcessorNotFoundError,
    ProcessorValidationError,
    UncertaintyLineageError,
)
from itaca.core.varframe import VarFrame
from itaca.pproc import registry
from itaca.pproc.base import EquationProcessor
from itaca.pproc.equations.parser import parse_itceq
from itaca.pproc.protocol import Processor

BALANCE = """\
[meta]
name        = "Balance: power off"
version     = "2.1"
description = "test fixture"

[constants]
S_ref = 0.2

[equations]
q_inf = "0.5 * rho * V**2"
CL    = "FZ / (q_inf * S_ref)"

[corrections]
blockage = "1 + 0.005 * CL**2"
CL_corr  = "CL * blockage"
"""

# The same workflow with uncertainties declared. A SEPARATE fixture since
# FND-058: a correction that depends on the coefficient it corrects
# (blockage from CL, then CL_corr from both) is exactly the shared-ancestry
# shape, so declaring an uncertainty anywhere upstream now makes this
# workflow refuse. Splitting it keeps every test about ordering, recording,
# signing and reapplication testing what it tested, and puts the new
# uncertainty contract in one place where it is visible rather than spread
# across sixteen incidental failures.
BALANCE_UNC = BALANCE.replace(
    "[equations]",
    '[uncertainties]\nFZ  = 0.005\nrho = "0.05%"\n\n[equations]',
    1,
)

# Reads q_inf before defining it: refused in file order, fine sorted.
FORWARD = """\
[meta]
name = "forward"

[equations]
CL    = "FZ / q_inf"
q_inf = "0.5 * rho * V**2"
"""

# The same shape over a name the frame also carries, which is the case
# that would otherwise compute a wrong CL and then overwrite q_inf.
SHADOWED = """\
[meta]
name = "shadowed"

[equations]
CL    = "FZ / q_inf"
q_inf = "0.5 * rho * V**2 * 2.0"
"""

# Declares idempotence in the file, so no Python subclass is needed to
# say that reapplying this workflow is meaningful (REQ-47, REQ-48).
IDEMPOTENT = """\
[meta]
name       = "idem"
idempotent = true

[equations]
q = "0.5 * rho * V**2"
"""


@pytest.fixture
def itceq(tmp_path: Path) -> Path:
    path = tmp_path / "balance.itceq"
    path.write_text(BALANCE, encoding="utf-8")
    return path


@pytest.fixture
def db() -> VarFrame:
    alpha = np.arange(-4.0, 8.1, 2.0)
    count = alpha.size
    columns = [alpha, 40.0 + 3.2 * alpha, np.full(count, 30.0), np.full(count, 1.225)]
    names = ["alpha", "FZ", "V", "rho"]
    return itc.load(np.column_stack(columns), names=names).pivot(dims=["alpha"])


@pytest.fixture
def clean_registry() -> Iterator[None]:
    saved = dict(registry._REGISTRY)
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


# ---------------------------------------------------------------------------
# REQ-45: the protocol
# ---------------------------------------------------------------------------


def test_equation_processor_satisfies_the_protocol(itceq: Path) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    assert isinstance(processor, Processor)
    assert processor.name == "Balance: power off"
    assert processor.version == "2.1"


def test_name_and_version_fall_back_to_the_file(tmp_path: Path) -> None:
    path = tmp_path / "bare.itceq"
    path.write_text('[meta]\ndescription = "no name"\n', encoding="utf-8")
    processor = itc.processor(path)
    assert processor.name == "bare"
    assert processor.version == "0"


def test_info_prints_the_workflow(
    itceq: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert itc.processor(itceq, auto_sort=True).info() is None
    printed = capsys.readouterr().out
    assert "Balance: power off" in printed
    assert "2.1" in printed
    assert "S_ref" in printed
    assert "q_inf" in printed


def test_the_factory_does_not_shadow_the_package(itceq: Path) -> None:
    """OQ-29: itc.processor is the factory, itc.pproc stays the package.

    Binding the factory as ``itc.pproc`` would overwrite the subpackage
    attribute the import machinery sets, so ``itc.pproc.statistics(db)``
    could never resolve and ``import itaca.pproc as pp`` would silently
    hand back a function. REQ-49 to REQ-51 are written as
    ``pproc.statistics``, ``pproc.compare``, and ``pproc.report``, so
    the attribute has to stay the module for those to be reachable as
    specified. Re-exporting the factory under the package name is the
    regression this pins.
    """
    import itaca

    assert isinstance(itc.pproc, types.ModuleType), (
        f"itc.pproc is {type(itc.pproc).__name__}, not the itaca.pproc "
        "module, so something is bound at the package top level under the "
        "subpackage's own name; itc.pproc.statistics(db) can never resolve "
        "while that holds (OQ-29, DD-34)."
    )
    assert itc.pproc.__name__ == "itaca.pproc"
    assert itc.pproc.parse_itceq is parse_itceq
    assert callable(itc.processor)
    assert itc.processor(itceq).name == "Balance: power off"

    # Generalized from the pproc case to the class of it (OQ-30): any
    # top-level export whose name equals a subpackage directory shadows
    # that subpackage on the attribute. itc.surrogate is specified with
    # a surrogate/ package and will land in M3, so the guard has to
    # catch the shape rather than this one name.
    root = Path(itaca.__file__).parent
    subpackages = {
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (entry / "__init__.py").is_file()
    }
    shadowed = sorted(subpackages & set(itaca.__all__))
    assert not shadowed, (
        f"itaca.__all__ exports {shadowed}, which is also the name of a "
        "subpackage, so the export shadows the package on that attribute and "
        "itc.<name>.<member> stops resolving. Export the callable under a "
        "different name, as the processor factory is (OQ-29, OQ-30, DD-34)."
    )


# ---------------------------------------------------------------------------
# REQ-46: the factory
# ---------------------------------------------------------------------------


def test_factory_accepts_a_path_and_a_string_path(itceq: Path) -> None:
    assert itc.processor(itceq).name == "Balance: power off"
    assert itc.processor(str(itceq)).name == "Balance: power off"


def test_unknown_name_lists_the_registered_alternatives(clean_registry: None) -> None:
    registry._REGISTRY.clear()
    registry.register_processor("WT_propeller", lambda **_: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(ProcessorNotFoundError) as caught:
        itc.processor("WT_propellor")
    message = str(caught.value)
    assert "WT_propeller" in message
    assert "WT_propellor" in message


def test_unknown_name_with_an_empty_registry_says_so(clean_registry: None) -> None:
    registry._REGISTRY.clear()
    with pytest.raises(ProcessorNotFoundError, match="no processors are registered"):
        itc.processor("WT_propeller")


def test_registered_name_constructs_through_the_registry(
    itceq: Path, clean_registry: None
) -> None:
    # A builtin ships its own file and decides its own order; the
    # factory's keywords reach it, and it is free to fix auto_sort.
    def build(*, config: Any = None, auto_sort: bool = False) -> Any:
        del auto_sort
        return itc.processor(itceq, config=config, auto_sort=True)

    registry.register_processor("WT_test", build)
    assert "WT_test" in registry.registered_processors()
    assert itc.processor("WT_test").name == "Balance: power off"


def test_registering_a_duplicate_name_is_refused(clean_registry: None) -> None:
    registry.register_processor("WT_dup", lambda **_: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(ProcessorError, match="already registered"):
        registry.register_processor("WT_dup", lambda **_: None)  # type: ignore[arg-type,return-value]


def test_config_overrides_a_declared_constant(itceq: Path) -> None:
    assert itc.processor(itceq).constants["S_ref"] == 0.2
    assert itc.processor(itceq, config={"S_ref": 0.25}).constants["S_ref"] == 0.25


def test_config_key_absent_from_constants_is_refused(itceq: Path) -> None:
    with pytest.raises(ProcessorError, match="S_reff"):
        itc.processor(itceq, config={"S_reff": 0.25})


def test_config_value_must_be_numeric(itceq: Path) -> None:
    with pytest.raises(ProcessorError, match="S_ref"):
        itc.processor(itceq, config={"S_ref": "0.25"})  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# validate, and the application
# ---------------------------------------------------------------------------


def test_validate_names_every_missing_variable(itceq: Path, db: VarFrame) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    assert processor.validate(db) is None
    alpha = np.arange(-4.0, 8.1, 2.0)
    thin = itc.load(
        np.column_stack([alpha, 40.0 + 3.2 * alpha]), names=["alpha", "FZ"]
    ).pivot(dims=["alpha"])
    with pytest.raises(ProcessorValidationError) as caught:
        processor.validate(thin)
    message = str(caught.value)
    assert "V" in message and "rho" in message


def test_application_derives_every_target(itceq: Path, db: VarFrame) -> None:
    processed = itc.processor(itceq, auto_sort=True)(db)
    for target in ("q_inf", "CL", "blockage", "CL_corr"):
        assert target in processed.vars
    assert set(db.vars) < set(processed.vars)  # the input is preserved


def test_application_propagates_the_declared_uncertainty(
    tmp_path: Path, db: VarFrame
) -> None:
    # A chain whose later equations read only ROOT variables propagates
    # exactly as it always did. This is the half of the contract the
    # refusal leaves untouched, and it is the common .itceq shape.
    path = tmp_path / "roots.itceq"
    path.write_text(
        '[meta]\nname = "roots"\n\n[constants]\nS_ref = 0.2\n\n'
        '[uncertainties]\nFZ  = 0.005\nrho = "0.05%"\n\n'
        '[equations]\nq_inf = "0.5 * rho * V**2"\n'
        'CL    = "FZ / ((0.5 * rho * V**2) * S_ref)"\n',
        encoding="utf-8",
    )
    processed = itc.processor(path, auto_sort=True)(db)
    assert processed.uncertainty is not None
    systematic = processed.uncertainty.systematic
    assert systematic["FZ"][0] == pytest.approx(0.005)
    assert np.all(systematic["CL"] > 0.0)  # propagated, not assigned


def test_a_correction_reading_what_it_corrects_is_refused(
    tmp_path: Path, db: VarFrame
) -> None:
    """FND-058 reaches the processor, and it was understating.

    The processor is an ordinary sequence of ``compute`` calls, so it
    inherits the lineage loss exactly. Measured on ``dde261c``, before
    the refusal existed, over the BALANCE workflow with FZ = [100, 200,
    300], V = 50, rho = 1.225::

        processor u(CL_corr) = [0.00164167 0.00166855 0.0017128 ]
        one-expression u(CL_corr) = [0.00164342 0.00167564 0.00172907]
        ratio = [0.99893605 0.99577124 0.99058533]

    UNDERSTATED, by 0.1 to 0.9 percent and growing with CL. Understating
    is the direction that matters in a report, which is why this refuses
    rather than warns. Whether the processor should instead expand its
    equations against the root variables, which would be correct AND
    silent, is OQ-50: it changes the operations History records and
    interacts with the OQ-43 re-declaration rule, so it is not this
    lane's call.
    """
    path = tmp_path / "balance_unc.itceq"
    path.write_text(BALANCE_UNC, encoding="utf-8")
    processor = itc.processor(path, auto_sort=True)
    with pytest.raises(UncertaintyLineageError) as caught:
        processor(db)
    message = str(caught.value)
    assert "'CL' and 'blockage'" in message
    assert "CL_corr" in message


def test_constants_are_substituted_into_the_recorded_operation(
    itceq: Path, db: VarFrame
) -> None:
    # The constant is not a VarFrame variable, so what runs is the
    # expression with its numeric value; History records what ran.
    processed = itc.processor(itceq, auto_sort=True)(db)
    recorded = " ".join(entry.operation for entry in processed.history)
    assert "0.2" in recorded
    assert "S_ref" not in recorded


def test_every_step_is_recorded_and_the_application_lifts_to_a_pipeline(
    itceq: Path, db: VarFrame
) -> None:
    processed = itc.processor(itceq, auto_sort=True)(db)
    names = [entry.name for entry in processed.history]
    assert names.count("compute") == 4
    pipeline = processed.history.to_pipeline()
    assert len(pipeline) >= 4


def test_the_processor_signs_every_entry_it_records(itceq: Path, db: VarFrame) -> None:
    processed = itc.processor(itceq, auto_sort=True)(db, comment="run 12")
    comments = [entry.comment for entry in processed.history if entry.comment]
    assert comments
    assert all("Balance: power off" in comment for comment in comments)
    assert all("run 12" in comment for comment in comments)


def test_the_input_frame_is_unchanged(itceq: Path, db: VarFrame) -> None:
    before = db.state_hash
    itc.processor(itceq, auto_sort=True)(db)
    assert db.state_hash == before
    assert "CL" not in db.vars


def test_file_order_that_cannot_run_is_refused_at_parse_time(
    tmp_path: Path, db: VarFrame
) -> None:
    # A forward reference is refused when the file is read, not when it
    # runs. Accepting it has two outcomes and both are bad: compute
    # raises about a variable the file visibly defines, or the frame
    # happens to carry that name and the equation silently uses the
    # measured value, which the next line then overwrites.
    path = tmp_path / "forward.itceq"
    path.write_text(FORWARD, encoding="utf-8")
    with pytest.raises(ItceqParseError, match="defines below it"):
        itc.processor(path)
    # The same file is fine once the order is resolved.
    assert "CL" in itc.processor(path, auto_sort=True)(db).vars


def test_a_forward_reference_over_a_measured_channel_is_refused(
    tmp_path: Path, db: VarFrame
) -> None:
    # The dangerous case: the frame DOES carry q_inf, so without the
    # refusal CL would be derived from the measured value and q_inf
    # would then be overwritten, with no error anywhere.
    seeded = db.compute("q_inf = 0.5 * rho * V**2")
    path = tmp_path / "shadowed.itceq"
    path.write_text(SHADOWED, encoding="utf-8")
    with pytest.raises(ItceqParseError, match="q_inf"):
        itc.processor(path)(seeded)


def test_report_argument_defers_to_its_milestone(itceq: Path, db: VarFrame) -> None:
    with pytest.raises(ProcessorError, match=re.escape("v0.3.0")):
        itc.processor(itceq, auto_sort=True)(db, report="out.pdf")


# ---------------------------------------------------------------------------
# REQ-47 and DD-16: idempotence
# ---------------------------------------------------------------------------


def test_reapplication_is_refused_by_default(itceq: Path, db: VarFrame) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    processed = processor(db)
    with pytest.raises(ProcessorIdempotenceWarning, match="force=True"):
        processor(processed)


def test_the_refusal_is_an_itaca_error_and_a_warning(itceq: Path, db: VarFrame) -> None:
    # It is raised when refusing and passed to warnings.warn when
    # permitted, so it has to be both (REQ-47, REQ-81).
    assert issubclass(ProcessorIdempotenceWarning, itc.ITACAError)
    assert issubclass(ProcessorIdempotenceWarning, Warning)


def test_force_permits_the_rerun_and_still_warns(itceq: Path, db: VarFrame) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    processed = processor(db)
    with pytest.warns(ProcessorIdempotenceWarning):
        again = processor(processed, force=True)
    assert len(again.history) > len(processed.history)  # a distinct entry
    assert again.state_hash != processed.state_hash  # not a silent no-op


def test_a_declared_idempotent_processor_reruns_without_refusing(
    itceq: Path, db: VarFrame
) -> None:
    class Idempotent(EquationProcessor):
        idempotent = True

    processor = Idempotent(parse_itceq(itceq, auto_sort=True))
    processed = processor(db)
    with pytest.warns(ProcessorIdempotenceWarning):
        again = processor(processed)
    assert again.state_hash != processed.state_hash


def test_a_first_application_does_not_warn(itceq: Path, db: VarFrame) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        processor(db)


def test_matching_names_alone_warn_but_do_not_refuse(itceq: Path, db: VarFrame) -> None:
    """DD-35: names are not evidence of a previous run.

    A frame that arrives already carrying every target name, with no
    History record of this processor, is the first application over
    inconveniently named channels. Refusing it would teach the user to
    write force=True by reflex, which is the habit DD-16 exists to
    prevent.
    """
    processor = itc.processor(itceq, auto_sort=True)
    seeded = db
    for target in ("q_inf", "CL", "blockage", "CL_corr"):
        seeded = seeded.compute(f"{target} = 1.0")
    with pytest.warns(ProcessorIdempotenceWarning, match="does not record"):
        out = processor(seeded)
    # Applied, not merely returned: the seeded placeholder is gone and
    # the application's own entries are in History. Asserting only that
    # the name is present would be true of the input too.
    assert out.vars["CL_corr"].values.ravel()[0] != 1.0
    assert len(out.history) > len(seeded.history)


def test_a_real_reapplication_is_refused_on_the_history_evidence(
    itceq: Path, db: VarFrame
) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    processed = processor(db)
    with pytest.raises(ProcessorIdempotenceWarning, match="records this processor"):
        processor(processed)


def test_the_history_evidence_survives_a_save_and_reopen(
    itceq: Path, db: VarFrame, tmp_path: Path
) -> None:
    # History is persisted in the .itc archive, which is what makes the
    # evidence-based rule hold across a round trip (DD-35).
    processor = itc.processor(itceq, auto_sort=True)
    archive = processor(db).save(tmp_path / "run.itc")
    reopened = itc.open(archive)
    with pytest.raises(ProcessorIdempotenceWarning, match="records this processor"):
        processor(reopened)


def test_idempotent_declared_in_the_file_permits_the_rerun(
    tmp_path: Path, db: VarFrame
) -> None:
    # REQ-47 via [meta], so a file-defined processor can declare it
    # without subclassing in Python and bypassing itc.processor.
    path = tmp_path / "idem.itceq"
    path.write_text(IDEMPOTENT, encoding="utf-8")
    processor = itc.processor(path)
    processed = processor(db)
    with pytest.warns(ProcessorIdempotenceWarning):
        again = processor(processed)
    assert again.state_hash != processed.state_hash


def test_a_partial_overlap_is_not_a_reapplication(itceq: Path, db: VarFrame) -> None:
    # Only every target already present counts; one shared name is not
    # evidence the workflow ran (DD-16 protects against the double run).
    seeded = db.compute("blockage = 1.0")
    processor = itc.processor(itceq, auto_sort=True)
    assert "CL_corr" in processor(seeded).vars


def test_uncertainty_declared_on_a_derived_variable_is_applied_after(
    tmp_path: Path, db: VarFrame
) -> None:
    # q_inf does not exist when the processor starts, so its declared
    # uncertainty can only be assigned once the equation has run.
    path = tmp_path / "late.itceq"
    path.write_text(
        '[meta]\nname = "late"\n\n[uncertainties]\nq_inf = 1.5\n\n'
        '[equations]\nq_inf = "0.5 * rho * V**2"\n',
        encoding="utf-8",
    )
    processed = itc.processor(path)(db)
    assert processed.uncertainty is not None
    assert processed.uncertainty.systematic["q_inf"][0] == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# R4-ITA-003 / ITC-20260730-0105: when a declared uncertainty is applied.
#
# The rule (SRS 4.6, REQ-41, REQ-99) asks TWO questions, not one, and a name
# can answer yes to both. Does the frame CARRY it? Then the declaration is
# assigned before the first line, so every line reading the name propagates
# from the declared value. Does the FILE WRITE it? Then it is assigned again
# after the first line that writes it, since that line's propagation would
# otherwise replace it.
#
# BOTH single-question rules have shipped a wrong number, and the two are
# mirror images, which is why the tests below come in pairs.
#
#   asking only "does the frame carry it" was R4-ITA-003: with
#   `x = 1.0, y = 5.0` and `y = "2*x"` against a frame carrying y, the frame
#   shipped u(y) = 2.0 against a declared 5.0;
#
#   asking only "does the file write it" was the first repair, and three
#   reviewer passes found it regressed the mirror: with `CL = 0.01`,
#   `[equations] CD = "CL * 2"` and `[corrections] CL = "CL * 1.02"` against
#   a frame carrying a stale u(CL) = 99, u(CD) shipped as 198.0 where 0.02
#   is correct, because the declaration was withheld from the equation that
#   READ CL.
#
# In both cases the number is finite, plausible, and chosen by the shape of
# the input, which is the failure mode this library can least afford.
# ---------------------------------------------------------------------------

# A name the frame CARRIES and a `[corrections]` line rewrites, read by an
# `[equations]` line in between. This is the shape the first repair broke and
# that no test covered: `[equations]` runs before `[corrections]`, so CD is
# computed while CL still holds only whatever the frame brought.
CARRIED_AND_CORRECTED = """\
[meta]
name = "carried and corrected"

[uncertainties]
CL = 0.01

[equations]
CD = "CL * 2"

[corrections]
CL = "CL * 1.02"
"""

# A name only `[corrections]` produces, which the parser explicitly blesses
# as an input the frame must supply. Nothing may raise here: the first
# repair's obvious alternative (classify by equation targets alone) fails
# this one with an UncertaintyKeyError.
PRODUCED_BY_A_CORRECTION = """\
[meta]
name = "produced by a correction"

[uncertainties]
w = 0.5

[corrections]
w = "x * 2"
"""

# Two targets, so a frame carrying only `y` is not a full reapplication and
# the REQ-47 idempotence warning stays out of these assertions. `z` also
# makes the dependent observable: it must propagate from the DECLARED u(y),
# which is the whole reason the assignment happens mid-loop and not at the
# end.
DECLARED_ON_A_TARGET = """\
[meta]
name = "declared"

[uncertainties]
x = 1.0
y = 5.0

[equations]
y = "2*x"
z = "y + 1"
"""

# The same file with the input declaration removed, so the pre-fix symptom
# is the OTHER one: nothing propagates into `y`, so `compute` drops the
# frame's uncertainty entirely and the declaration vanishes without a trace.
DECLARED_ON_A_TARGET_ONLY = """\
[meta]
name = "declared only"

[uncertainties]
y = 5.0

[equations]
y = "2*x"
z = "y + 1"
"""

# A RELATIVE declaration, whose resolution moment is observable: 10 percent
# of what the equation wrote is [0.6, 0.8], while 10 percent of the stale
# input column below is [10.0, 10.0].
DECLARED_RELATIVE = """\
[meta]
name = "relative"

[uncertainties]
y = "10%"

[equations]
y = "2*x"
z = "y + 1"
"""


def _two_column(x: list[float], y: list[float]) -> VarFrame:
    rows = [list(pair) for pair in zip(x, y, strict=True)]
    return itc.load(np.array(rows), names=["x", "y"])


def _systematic(frame: VarFrame, name: str, why: str) -> Any:
    assert frame.uncertainty is not None, (
        f"the run shipped no UncFrame at all, so {why} (R4-ITA-003)"
    )
    table = dict(frame.uncertainty.systematic)
    assert name in table, (
        f"the run shipped an UncFrame carrying {sorted(table)} and no "
        f"u({name}), so {why} (R4-ITA-003)"
    )
    return np.asarray(table[name], dtype=float)


@pytest.mark.parametrize(
    "text",
    [DECLARED_ON_A_TARGET, DECLARED_ON_A_TARGET_ONLY],
    ids=["with-input", "alone"],
)
@pytest.mark.parametrize("shape", ["absent", "present"])
def test_a_declared_uncertainty_wins_whether_or_not_the_target_pre_exists(
    tmp_path: Path, text: str, shape: str
) -> None:
    # The load-bearing assertion of R4-ITA-003. `y` is written by the file
    # either way, so one file must give one answer against a frame that
    # happens to carry a `y` column and one that does not. Parametrized over
    # BOTH axes rather than looped, so a failure names which combination
    # broke instead of stopping at the first.
    path = tmp_path / "declared.itceq"
    path.write_text(text, encoding="utf-8")
    frame = (
        itc.load(np.array([[3.0], [4.0]]), names=["x"])
        if shape == "absent"
        else _two_column([3.0, 4.0], [6.0, 8.0])
    )
    processed = itc.processor(path)(frame)
    shipped = _systematic(
        processed, "y", f"the declared u(y) = 5.0 was dropped on the {shape} run"
    )
    assert shipped == pytest.approx(5.0), (
        f"the {shape}-target run shipped u(y) = {shipped.tolist()} where the "
        f"file declares 5.0. A declared uncertainty is not a starting point "
        f"for propagation; it is the value the file asserts (R4-ITA-003)."
    )
    # The dependent is the reason the assignment is mid-loop: z reads y
    # AFTER the declaration is in place, so u(z) follows from 5.0.
    dependent = _systematic(
        processed, "z", f"the dependent lost its uncertainty on the {shape} run"
    )
    assert dependent == pytest.approx(5.0), (
        f"the {shape}-target run shipped u(z) = {dependent.tolist()}, "
        f"propagated from something other than the declared u(y) = 5.0, so "
        f"the frame ships a dependent inconsistent with the input "
        f"uncertainty it reports"
    )


def test_a_declared_uncertainty_on_an_existing_target_is_not_silently_replaced(
    tmp_path: Path,
) -> None:
    # Named separately from the parity test above, and NOT a second
    # falsifier: `not allclose(2.0)` cannot fail unless the `approx(5.0)`
    # there fails first. It exists for its message, which names the number
    # that made R4-ITA-003 a release blocker rather than a gap. 2.0 is what
    # u(x) = 1.0 propagates to through y = 2*x, so a reader has no way to
    # tell it from a number the file asked for.
    path = tmp_path / "replaced.itceq"
    path.write_text(DECLARED_ON_A_TARGET, encoding="utf-8")
    processed = itc.processor(path)(_two_column([3.0, 4.0], [6.0, 8.0]))
    shipped = _systematic(processed, "y", "the declaration was dropped entirely")
    assert not np.allclose(shipped, 2.0), (
        f"u(y) shipped as {shipped.tolist()}, the value propagation from "
        f"u(x) = 1.0 produces, in place of the declared 5.0. R4-ITA-003: the "
        f"declaration was consumed before the equation ran and then "
        f"overwritten by the equation's own propagation."
    )


def test_a_relative_declaration_on_an_existing_target_resolves_against_the_result(
    tmp_path: Path,
) -> None:
    # A relative spec pins the assignment MOMENT and not only the winner:
    # ten percent of what the equation wrote, never of the input column.
    #
    # What the pre-fix tree actually SHIPPED here was `uncertainty is None`,
    # not a percentage of the stale column. The stale resolution, [10.0,
    # 10.0], existed only as an intermediate that the equation then
    # overwrote, so no caller ever saw it. Recorded because the first
    # version of this comment claimed otherwise, and a test whose stated
    # defect model is wrong teaches the next reader the wrong thing even
    # while it passes.
    path = tmp_path / "relative.itceq"
    path.write_text(DECLARED_RELATIVE, encoding="utf-8")
    processor = itc.processor(path)
    stale = processor(_two_column([3.0, 4.0], [100.0, 100.0]))
    fresh = processor(itc.load(np.array([[3.0], [4.0]]), names=["x"]))
    got = _systematic(stale, "y", "the declaration was lost on the stale-frame run")
    want = _systematic(fresh, "y", "the declaration was lost on the fresh run")
    assert got == pytest.approx(want), (
        f"a 10 percent declaration on an existing target resolved to "
        f"{got.tolist()} against a frame carrying y = 100, and to "
        f"{want.tolist()} against a frame that did not carry y at all. The "
        f"percentage is of what the file writes, so the input column must "
        f"not enter it (R4-ITA-003)."
    )
    assert got == pytest.approx([0.6, 0.8]), (
        f"u(y) resolved to {got.tolist()}; 10 percent of the equation's own "
        f"output [6.0, 8.0] is [0.6, 0.8]"
    )


def test_a_declared_uncertainty_on_an_input_still_precedes_every_equation(
    tmp_path: Path,
) -> None:
    # The other half of the rule, and the falsifier for moving it: `x` is
    # read and never written, so its declaration must be in place before the
    # first equation, or nothing propagates into `y` at all. A repair that
    # sent every declaration down the after-the-write path would pass every
    # test above and break this one.
    path = tmp_path / "input.itceq"
    path.write_text(
        '[meta]\nname = "input"\n\n[uncertainties]\nx = 1.0\n\n'
        '[equations]\ny = "2*x"\n',
        encoding="utf-8",
    )
    processed = itc.processor(path)(itc.load(np.array([[3.0], [4.0]]), names=["x"]))
    shipped = _systematic(
        processed, "y", "the declared u(x) was not in place when the equation read x"
    )
    assert shipped == pytest.approx(2.0)


@pytest.mark.parametrize("stale", [None, 99.0], ids=["no-stale-u", "stale-u-99"])
def test_a_declaration_reaches_the_equations_that_read_a_corrected_name(
    tmp_path: Path, stale: float | None
) -> None:
    """The mirror of R4-ITA-003, and the case the first repair regressed.

    `CL` is BOTH carried by the frame and rewritten by `[corrections]`, and
    `[equations]` runs first, so `CD = CL * 2` reads `CL` before any
    correction. The declaration must therefore already be in place, or the
    equation propagates from whatever the input frame brought.

    Measured under the first repair, which classified by what the file
    produces alone: with no stale uncertainty, `u(CD)` was ABSENT, a
    declared uncertainty silently dropped out of a derived quantity
    (REQ-98). With a stale `u(CL) = 99` that the file overrides, `u(CD)`
    shipped as 198.0 where 0.02 is correct, in a frame that simultaneously
    reported `u(CL) = 0.01`. Same class as the defect being fixed, mirrored:
    a finite, plausible number selected by the shape of the input.

    The stale parametrization is the one that makes it a WRONG number rather
    than a missing one, and it is the reason the frame's own uncertainty may
    never be read for a name the file declares.
    """
    path = tmp_path / "corrected.itceq"
    path.write_text(CARRIED_AND_CORRECTED, encoding="utf-8")
    frame = itc.load(np.array([[3.0], [4.0]]), names=["CL"])
    if stale is not None:
        frame = frame.set_uncertainty({"CL": stale})
    processed = itc.processor(path)(frame)
    derived = _systematic(
        processed,
        "CD",
        "the declaration never reached the equation that reads CL, so the "
        "derived quantity carries no uncertainty at all",
    )
    assert derived == pytest.approx(0.02), (
        f"u(CD) shipped as {derived.tolist()} where CD = CL * 2 and the file "
        f"declares u(CL) = 0.01, so 0.02 is correct. The equation read a "
        f"uncertainty other than the declared one; with a stale u(CL) in the "
        f"frame that is the frame's value, which the file overrides."
    )
    declared = _systematic(
        processed, "CL", "the correction target lost its declaration"
    )
    assert declared == pytest.approx(0.01), (
        f"u(CL) shipped as {declared.tolist()} where the file declares 0.01. "
        f"A correction is a line that writes the name, so the declaration is "
        f"reasserted after it (R4-ITA-003)."
    )


def test_a_name_only_a_correction_produces_still_gets_its_declaration(
    tmp_path: Path,
) -> None:
    """A `[corrections]`-only target the frame does not carry.

    The parser blesses this shape explicitly: a name a correction replaces
    but the file does not otherwise produce is a required input, and here it
    is produced outright. Nothing may raise. Kept as its own test because
    the obvious alternative repair (classify by `[equations]` targets alone)
    passes every other test in this block and fails this one with
    `UncertaintyKeyError: variable 'w' ... does not match any variable`.
    """
    path = tmp_path / "corr_only.itceq"
    path.write_text(PRODUCED_BY_A_CORRECTION, encoding="utf-8")
    processed = itc.processor(path)(itc.load(np.array([[3.0], [4.0]]), names=["x"]))
    shipped = _systematic(processed, "w", "a correction-produced name lost its value")
    assert shipped == pytest.approx(0.5)


def test_the_mid_loop_declaration_records_itself_in_history(tmp_path: Path) -> None:
    """REQ-18 and REQ-19 for the operation this fix moved into the loop.

    The ORDER is the assertion, not merely the presence: the declaration
    must sit between the line that writes `y` and the line that reads it,
    since that is the whole reason it is assigned mid-loop rather than at
    the end. Falsified by reordering the loop body so the assignment
    precedes its `compute`.

    ONE THING THIS DOES NOT GUARD, stated because a reviewer proposed it as
    the mutation and it is inert: passing `history=False` to that call
    changes nothing here. `VarFrame._derive` records when
    `self.mode == "production" or history`, and a frame from `itc.load` is
    in production mode, so the flag only matters for a draft frame. A
    mutation of the flag leaves the whole suite green because the behavior
    is unchanged, not because the behavior is uncovered. What IS guarded is
    the comment: dropping `comment=signature` makes the entry unattributable
    and fails the last assertion.
    """
    path = tmp_path / "history.itceq"
    path.write_text(DECLARED_ON_A_TARGET, encoding="utf-8")
    processor = itc.processor(path)
    processed = processor(_two_column([3.0, 4.0], [6.0, 8.0]))
    operations = [entry.operation for entry in processed.history]
    # MEMBERSHIP, not a prefix. The first version matched
    # startswith("set_uncertainty(vars=['y']") and so missed the pre-loop
    # entry, which lists ['x', 'y'] because this frame carries both: it then
    # asserted a count of one and passed for the wrong reason, while its own
    # message claimed something false about the frame. `y` really is assigned
    # twice here, and that is the rule, so the count asserted is two.
    assign = [
        index
        for index, text in enumerate(operations)
        if text.startswith("set_uncertainty(vars=") and "'y'" in text
    ]
    assert len(assign) == 2, (
        f"the declared u(y) is recorded {len(assign)} times in History, "
        f"expected twice for a frame that carries y AND a file that writes "
        f"it: once before the first line and once after the writing line. "
        f"Recorded operations: {operations}"
    )
    wrote = next(i for i, text in enumerate(operations) if "'y = 2*x'" in text)
    read = next(i for i, text in enumerate(operations) if "'z = y + 1'" in text)
    before, after = assign
    assert before < wrote < after < read, (
        f"the declared u(y) is recorded at positions {assign}, and the rule "
        f"requires one BEFORE the line that writes y ({wrote}) and one "
        f"between that line and the line that reads y ({read}). The second is "
        f"why the assignment is mid-loop: a dependent must propagate from the "
        f"declared value. Recorded operations: {operations}"
    )
    signed = [
        entry.comment
        for entry in processed.history
        if entry.operation.startswith("set_uncertainty(vars=")
        and "'y'" in entry.operation
    ]
    assert signed == [processor.signature, processor.signature], (
        f"the declarations carry comments {signed}, not the processor "
        f"signature {processor.signature!r} on each, so a reader landing on "
        f"either entry cannot tell which workflow wrote it (REQ-19, DD-35)"
    )


def test_a_declaration_on_a_target_alone_is_recorded_once(tmp_path: Path) -> None:
    """The single-assignment case, pinned beside the double one.

    `y` is written by the file and NOT carried by the frame, so it answers
    yes to one question only and must be recorded once. Without this beside
    the test above, the count two could be hardcoded and a rule that assigned
    everything twice would pass.
    """
    path = tmp_path / "once.itceq"
    path.write_text(DECLARED_ON_A_TARGET_ONLY, encoding="utf-8")
    processed = itc.processor(path)(itc.load(np.array([[3.0], [4.0]]), names=["x"]))
    assign = [
        entry.operation
        for entry in processed.history
        if entry.operation.startswith("set_uncertainty(vars=")
        and "'y'" in entry.operation
    ]
    assert len(assign) == 1, (
        f"the declared u(y) is recorded {len(assign)} times for a frame that "
        f"does not carry y, expected once (the frame cannot be assigned a "
        f"value for a variable it does not have). Entries: {assign}"
    )


def test_a_declaration_naming_nothing_the_file_reads_or_writes_is_refused(
    tmp_path: Path,
) -> None:
    """`validate`'s third absence check, which the whole rule rests on.

    SRS Section 4.6 says every declaration is applied at LEAST once because
    `validate` refuses a declared name that is neither carried by the frame
    nor written by the file. That claim was load-bearing and untested:
    replacing the condition with `if False` left the entire suite green.

    Both message clauses are pinned separately, because coverage showed
    every existing test reaching this refusal with BOTH clauses true, so
    neither shape was ever produced alone.

    What the caller met with the check disabled is measured in
    ``test_a_declaration_applied_nowhere_is_refused_before_anything_runs``
    below, and it is nothing: a silent drop. An earlier docstring here said
    ``UncertaintyKeyError``, which was true of a previous revision and false
    of this one.
    """
    unknown = tmp_path / "unknown.itceq"
    unknown.write_text(
        '[meta]\nname = "unknown"\n\n[uncertainties]\nw = 0.5\n\n'
        '[equations]\ny = "2*x"\n',
        encoding="utf-8",
    )
    frame = itc.load(np.array([[3.0], [4.0]]), names=["x"])
    with pytest.raises(ProcessorValidationError) as caught:
        itc.processor(unknown)(frame)
    message = str(caught.value)
    assert "[uncertainties] section names absent variable(s) ['w']" in message, message
    assert "its equations read absent variable" not in message, (
        f"the uncertainties-only refusal also reported missing equation "
        f"variables, so the two clauses are not independent: {message}"
    )

    # The mirror: equations only, so the other clause is produced alone.
    missing = tmp_path / "missing.itceq"
    missing.write_text(
        '[meta]\nname = "missing"\n\n[equations]\ny = "2*ghost"\n', encoding="utf-8"
    )
    with pytest.raises(ProcessorValidationError) as caught:
        itc.processor(missing)(frame)
    message = str(caught.value)
    assert "its equations read absent variable(s) ['ghost']" in message, message
    assert "[uncertainties]" not in message, (
        f"the equations-only refusal also reported an uncertainties clause: {message}"
    )


def test_a_declaration_does_not_touch_the_random_component(tmp_path: Path) -> None:
    """The declaration overrides the SYSTEMATIC component and only that.

    REQ-99 gives an uncertainty two components, and `set_uncertainty`
    defaults to `systematic`, which is what the `.itceq` section declares
    (SRS Chapter 8). So a frame arriving with a RANDOM component keeps it,
    and it propagates into every dependent untouched.

    Pinned because the whole new block reads only `.systematic`, so the
    random half was structurally invisible to it, and because SRS Section 4.6
    said "no uncertainty the frame arrived with is ever read for a name the
    file declares", which is false as stated: measured on this file, the
    arriving `u_random(CL) = 99.0` propagates to `u_random(CD) = 198.0`. That
    sentence is now qualified to the systematic component and this test is
    what holds it to the qualification.

    Whether a declaration SHOULD also override the random component, or a
    file be required to declare both, is a numerical-analyst question and is
    OQ-45. This test pins today's answer so the direction cannot change
    unannounced; it is not an argument that today's answer is the right one.
    """
    path = tmp_path / "components.itceq"
    path.write_text(CARRIED_AND_CORRECTED, encoding="utf-8")
    frame = itc.load(np.array([[3.0], [4.0]]), names=["CL"]).set_uncertainty(
        {"CL": 99.0}, component="random"
    )
    processed = itc.processor(path)(frame)
    assert processed.uncertainty is not None
    systematic = dict(processed.uncertainty.systematic)
    random = dict(processed.uncertainty.random)
    assert np.asarray(systematic["CL"], dtype=float) == pytest.approx(0.01), (
        f"the declaration did not win the systematic component: "
        f"{np.asarray(systematic['CL']).tolist()}"
    )
    assert np.asarray(random["CL"], dtype=float) == pytest.approx(99.0 * 1.02), (
        f"the arriving random component was altered by the declaration or "
        f"lost: u_random(CL) = {np.asarray(random['CL']).tolist()}, where "
        f"99.0 propagated through the correction CL * 1.02 is 100.98. A "
        f"declaration is a systematic-component statement (REQ-99, OQ-45)."
    )
    assert np.asarray(random["CD"], dtype=float) == pytest.approx(198.0), (
        f"u_random(CD) = {np.asarray(random['CD']).tolist()}, where "
        f"CD = CL * 2 over an arriving u_random(CL) = 99.0 gives 198.0. If "
        f"this changed, the declaration started overriding the random "
        f"component too, which is OQ-45 and not an implementation choice."
    )


def test_info_names_the_moment_each_declaration_applies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`info()` is public output (REQ-45), so its labels are asserted.

    Three cases, and the first version of this labelling got two of them
    wrong by reading `spec.targets` alone: it printed "reapplied after the
    line that writes it" for a name the file writes ONCE and never applies
    earlier, and printed only the later moment for a name applied twice,
    which reads as confirmation of the pre-fix behavior to anyone debugging
    the mirror defect.

    `info()` has no frame, but the file decides more than it looks:
    `required_variables` means the frame must carry the name, since
    `validate` refuses otherwise, so "twice" is knowable. Only
    written-and-not-required genuinely depends on the frame, and that label
    says so rather than asserting one moment.
    """
    both = tmp_path / "both.itceq"
    both.write_text(CARRIED_AND_CORRECTED, encoding="utf-8")
    itc.processor(both).info()
    printed = capsys.readouterr().out
    assert "CL = 0.01  (applied twice: before the first line, and again" in printed, (
        f"CL is read by an equation and rewritten by a correction, so it is "
        f"required AND written and is applied twice. Printed:\n{printed}"
    )

    produced = tmp_path / "produced.itceq"
    produced.write_text(PRODUCED_BY_A_CORRECTION, encoding="utf-8")
    itc.processor(produced).info()
    printed = capsys.readouterr().out
    assert "w = 0.5  (applied after the line that writes it, and also" in printed, (
        f"w is written by the file and is not a required input, so whether it "
        f"is also applied before depends on the frame and the label must say "
        f"so. Printed:\n{printed}"
    )

    inputs = tmp_path / "inputs.itceq"
    inputs.write_text(
        '[meta]\nname = "inputs"\n\n[uncertainties]\nx = 1.0\n\n'
        '[equations]\ny = "2*x"\n',
        encoding="utf-8",
    )
    itc.processor(inputs).info()
    printed = capsys.readouterr().out
    assert "x = 1.0  (applied before the first line)" in printed, (
        f"x is read and never written, so it has exactly one moment. "
        f"Printed:\n{printed}"
    )


def test_a_declaration_applied_nowhere_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    """The second line of defense, reachable and asserted.

    `validate` refuses a declaration naming neither a carried nor a written
    name, and SRS Section 4.6's "jointly exhaustive" claim rests on that
    refusal. `__call__` checks it again, because the consequence of the claim
    being false is SILENT: the declaration is applied nowhere and the frame
    ships without it.

    The first version of this guard checked the wrong set. It asserted that
    `pending` was drained AFTER the loop, and three reviewer passes measured
    that as structurally unreachable: `pending` is keyed on `spec.targets`,
    which is built from exactly the tuple the loop iterates and pops. Worse,
    the commit that added it had just made the reachable failure quieter:
    `setup` began filtering on `key in work.vars`, so an unknown name that
    the previous revision passed into `set_uncertainty` (raising
    `UncertaintyKeyError`, the wrong message but a loud one) was now dropped
    without a sound. Measured with `validate`'s clause disabled: no
    exception, `uncertainty is None`.

    So the check moved to the set that can be violated, and before the first
    `compute` rather than after the last, which is the placement `validate`'s
    own docstring argues for: a refusal arriving mid-application lands once
    earlier lines have already been written.

    Reached here through a subclass whose `validate` does nothing, which is
    the only way to reach it, and that is the honest description of the
    guard: a redundant check whose redundancy is the point. The subclass is
    also the falsifier for `validate` itself, since it measures what the
    absence of that refusal costs.
    """

    class Unvalidated(EquationProcessor):
        def validate(self, db: VarFrame) -> None:
            return None

    path = tmp_path / "nowhere.itceq"
    path.write_text(
        '[meta]\nname = "nowhere"\n\n[uncertainties]\nw = 0.5\n\n'
        '[equations]\ny = "2*x"\n',
        encoding="utf-8",
    )
    processor = Unvalidated(parse_itceq(path))
    frame = itc.load(np.array([[3.0], [4.0]]), names=["x"])
    with pytest.raises(ProcessorError) as caught:
        processor(frame)
    message = str(caught.value)
    for part in (
        f"processor '{processor.name}'",
        "declares ['w']",
        "applied nowhere",
        "remove the entry",
    ):
        assert part in message, f"the refusal does not name {part!r}: {message}"
    # And the ordinary path still refuses it earlier, so the redundancy is
    # redundancy and not a relocation.
    with pytest.raises(ProcessorValidationError):
        itc.processor(path)(frame)


def test_a_file_without_constants_runs_its_expressions_unchanged(
    tmp_path: Path, db: VarFrame
) -> None:
    path = tmp_path / "plain.itceq"
    path.write_text(
        '[meta]\nname = "plain"\n\n[equations]\nq = "0.5 * rho * V**2"\n',
        encoding="utf-8",
    )
    processed = itc.processor(path)(db)
    recorded = " ".join(entry.operation for entry in processed.history)
    assert "0.5 * rho * V**2" in recorded


def test_substitution_leaves_function_names_and_namespaces_alone(
    tmp_path: Path, db: VarFrame
) -> None:
    # A callee and the np. prefix are names in the syntax but not
    # variables, so a constant may never be substituted into them.
    path = tmp_path / "calls.itceq"
    path.write_text(
        '[meta]\nname = "calls"\n\n[constants]\nk = 2.0\n\n'
        '[equations]\nx = "sqrt(k * FZ) + np.abs(k)"\n',
        encoding="utf-8",
    )
    processed = itc.processor(path)(db)
    recorded = " ".join(entry.operation for entry in processed.history)
    assert "sqrt(2.0 * FZ)" in recorded
    assert "np.abs(2.0)" in recorded


def test_arrays_stay_read_only(itceq: Path, db: VarFrame) -> None:
    processed = itc.processor(itceq, auto_sort=True)(db)
    values: Any = processed.vars["CL"].values
    assert values.flags.writeable is False


# ---------------------------------------------------------------------------
# DD-35: what counts as this processor's signature in History
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("comment", "signs"),
    [
        ("pproc Balance: power off v2.1", True),
        ("pproc Balance: power off v2.1: run 12", True),
        (None, False),
        ("", False),
        ("smoothed before processing", False),
        # A user comment ABOUT the processor is not one written BY it.
        # REQ-19 invites free text, so containment would let a note sign
        # a frame this processor never touched.
        ("compare against pproc Balance: power off v2.1", False),
        # The version is part of the identity the signature asserts, so
        # a longer version must not be read as this one.
        ("pproc Balance: power off v2.10: run 3", False),
        # A different processor of the same family.
        ("pproc Balance: power on v2.1", False),
    ],
)
def test_only_this_processor_signature_signs(
    itceq: Path, comment: str | None, signs: bool
) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    assert isinstance(processor, EquationProcessor)
    assert processor._signs(comment) is signs


def test_the_signature_carries_the_version(itceq: Path) -> None:
    processor = itc.processor(itceq, auto_sort=True)
    assert isinstance(processor, EquationProcessor)
    assert processor.signature == "pproc Balance: power off v2.1"


def test_a_first_application_made_with_a_comment_is_still_detected(
    itceq: Path, db: VarFrame
) -> None:
    # The writer prefixes the user's comment, so the reader has to match
    # that shape too; an equality-only match would miss every run made
    # with comment= and apply the corrections twice.
    processor = itc.processor(itceq, auto_sort=True)
    processed = processor(db, comment="run 12")
    with pytest.raises(ProcessorIdempotenceWarning, match="records this processor"):
        processor(processed)


def test_a_file_that_produces_nothing_is_never_a_reapplication(
    tmp_path: Path, db: VarFrame
) -> None:
    # An empty target set is a subset of anything, so without the
    # explicit guard this would be refused vacuously on its second run,
    # the same empty-set hazard the push gate carries a guard for.
    path = tmp_path / "unc_only.itceq"
    path.write_text(
        '[meta]\nname = "unc only"\n\n[uncertainties]\nFZ = 0.005\n', encoding="utf-8"
    )
    processor = itc.processor(path)
    once = processor(db)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        twice = processor(once)
    assert twice.state_hash != once.state_hash


class TestConstantChannelCollision:
    """REV-001 ITACA-002, OQ-31 answered REFUSE by the author.

    A `[constants]` entry is substituted into every read before an
    expression evaluates, so a declared number silently beats a measured
    channel of the same name. Measured: a file declaring `rho = 1.225`
    applied to a campaign flown at `rho = 0.9` produced `q_inf` 36
    percent high, with no error, no warning, and no record of the
    substitution. History showed
    `compute('q_inf = 0.5 * 1.225 * V ** 2', ...)`, so not even the
    provenance revealed that a measurement had been discarded.

    The decision is symmetric with DD-37, which already refuses the
    HARMLESS sibling: a constant colliding with an equation target,
    where the equation's result is merely unreachable. The fix had
    landed on the safe instance and left the dangerous one.
    """

    @staticmethod
    def _collide_file(tmp_path: Path) -> Path:
        path = tmp_path / "collide.itceq"
        path.write_text(
            "[meta]\n"
            'name = "collide"\n'
            'version = "1.0"\n\n'
            "[constants]\n"
            "rho = 1.225\n\n"
            "[equations]\n"
            'q_inf = "0.5 * rho * V**2"\n',
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _campaign() -> VarFrame:
        """A frame carrying a MEASURED rho, flown at 0.9."""
        arr = np.column_stack([[0.0, 1.0], [0.9, 0.9], [30.0, 30.0]])
        return itc.load(arr, names=["alpha", "rho", "V"]).pivot(dims=["alpha"])

    def test_itaca_002_validate_refuses_a_constant_shadowing_a_channel(
        self, tmp_path: Path
    ) -> None:
        """validate is the lifecycle step that can see both sides.

        The parser cannot decide this: `parse_itceq` takes a path and
        `EquationProcessor.__init__` takes a spec, so neither has ever
        seen a frame. The same file is legal against a campaign that
        does not log rho, which is why this is not a file defect.
        """
        processor = itc.processor(self._collide_file(tmp_path))
        with pytest.raises(ProcessorValidationError) as excinfo:
            processor.validate(self._campaign())
        message = str(excinfo.value)
        assert "'rho'" in message
        # The DECLARED value is in the message, which is what lets a
        # reader see which number would have won.
        assert "1.225" in message
        assert "remove the entry from [constants]" in message

    def test_itaca_002_application_refuses_too(self, tmp_path: Path) -> None:
        """__call__ runs validate first, so one check closes both doors."""
        processor = itc.processor(self._collide_file(tmp_path))
        with pytest.raises(ProcessorValidationError):
            processor(self._campaign())

    def test_itaca_002_the_measured_value_is_never_used(self, tmp_path: Path) -> None:
        """The number the defect produced, pinned so it cannot come back.

        0.5 * 1.225 * 30**2 = 551.25 against 0.5 * 0.9 * 30**2 = 405.0,
        which is the 36 percent BRF-043 reports. If this refusal is ever
        softened without the author's decision changing, this test says
        exactly what the library would start computing again.
        """
        processor = itc.processor(self._collide_file(tmp_path))
        db = self._campaign()
        with pytest.raises(ProcessorValidationError):
            processor(db)
        assert "q_inf" not in db.vars
        declared_would_give = 0.5 * 1.225 * 30.0**2
        measured_would_give = 0.5 * 0.9 * 30.0**2
        assert declared_would_give == pytest.approx(551.25)
        assert measured_would_give == pytest.approx(405.0)

    def test_itaca_002_the_same_file_is_legal_without_the_channel(
        self, tmp_path: Path
    ) -> None:
        """The refusal is about the PAIR, not about the file.

        A campaign that does not log rho is exactly what a declared
        constant is for, and it must keep working. Without this, the fix
        would read as "constants are suspect", which is not the rule.
        """
        processor = itc.processor(self._collide_file(tmp_path))
        arr = np.column_stack([[0.0, 1.0], [30.0, 30.0]])
        db = itc.load(arr, names=["alpha", "V"]).pivot(dims=["alpha"])
        out = processor(db)
        assert out.vars["q_inf"].values == pytest.approx([551.25, 551.25])

    def test_itaca_002_a_constant_named_after_a_dimension_is_not_refused(
        self, tmp_path: Path
    ) -> None:
        """The check is scoped to db.vars, and deliberately so.

        Expressions read variables only: compute builds its environment
        from `db.vars`. A constant sharing a DIMENSION's name shadows
        nothing, so refusing it would be over-refusal. Measured: this
        case validates and applies cleanly both before and after.
        """
        path = tmp_path / "dimname.itceq"
        path.write_text(
            "[meta]\n"
            'name = "dimname"\n'
            'version = "1.0"\n\n'
            "[constants]\n"
            "alpha = 3.0\n\n"
            "[equations]\n"
            'scaled = "alpha * V"\n',
            encoding="utf-8",
        )
        processor = itc.processor(path)
        arr = np.column_stack([[0.0, 1.0], [30.0, 30.0]])
        db = itc.load(arr, names=["alpha", "V"]).pivot(dims=["alpha"])
        out = processor(db)
        assert out.vars["scaled"].values == pytest.approx([90.0, 90.0])

    def test_itaca_002_a_config_override_is_checked_on_the_resolved_value(
        self, tmp_path: Path
    ) -> None:
        """The check reads self.constants, which is what substitutes.

        A `config=` override changes the value that wins, so checking
        the resolved mapping rather than the file's own is the honest
        surface: the message must name the number that would actually
        have been used.
        """
        processor = itc.processor(self._collide_file(tmp_path), config={"rho": 1.0})
        with pytest.raises(ProcessorValidationError) as excinfo:
            processor.validate(self._campaign())
        assert "1.0" in str(excinfo.value)

    def test_itaca_002_the_collision_is_reported_before_an_absence(
        self, tmp_path: Path
    ) -> None:
        """When both conditions hold, the message is deterministic.

        The two fixes are opposites: the absence message says to load
        the missing channels, and this one says to remove a declaration.
        Folding them together would produce a message ending in the
        wrong advice.
        """
        path = tmp_path / "both.itceq"
        path.write_text(
            "[meta]\n"
            'name = "both"\n'
            'version = "1.0"\n\n'
            "[constants]\n"
            "rho = 1.225\n\n"
            "[equations]\n"
            'q_inf = "0.5 * rho * Vmissing**2"\n',
            encoding="utf-8",
        )
        processor = itc.processor(path)
        with pytest.raises(ProcessorValidationError) as excinfo:
            processor.validate(self._campaign())
        message = str(excinfo.value)
        assert "[constants]" in message
        assert "load the missing" not in message

    def test_itaca_002_a_constant_also_declared_in_uncertainties(
        self, tmp_path: Path
    ) -> None:
        """The shape the shipped fixtures actually have.

        A balance file declares `rho` in `[uncertainties]`, and a
        real-world file adds it to `[constants]` beside it. Measured
        before the fix: that parses, validate returns silently, and the
        application assigns a systematic uncertainty to the very channel
        the constant shadows, so the frame ends up carrying an
        uncertainty for a number that was never read.
        """
        path = tmp_path / "unc.itceq"
        path.write_text(
            "[meta]\n"
            'name = "unc"\n'
            'version = "1.0"\n\n'
            "[constants]\n"
            "rho = 1.225\n\n"
            "[uncertainties]\n"
            "rho = 0.01\n\n"
            "[equations]\n"
            'q_inf = "0.5 * rho * V**2"\n',
            encoding="utf-8",
        )
        processor = itc.processor(path)
        with pytest.raises(ProcessorValidationError, match=r"\[constants\]"):
            processor.validate(self._campaign())
