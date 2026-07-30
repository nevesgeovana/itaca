"""The SRS must describe the refusals the library actually ships.

Usage example (the contract under test)::

    provisional = srs_provisional_operations()   # parsed from REQ-98
    refusing = measured_refusing_operations()    # measured by calling them
    assert set(provisional) == set(refusing)

`ITC-20260729-1450`, a blocker on the v0.2.0 tag. The CHK-1 release
checkpoint added five public refusals to surfaces whose stable
requirement text contradicted them, and REQ-98 carried its provisional
family in four places at three different values while the normative
table still claimed that two of them propagate. Both are one defect: a
normative document holding a hand-maintained inventory that nothing
compares against the thing it inventories.

Documentation is not a guard, so the amendment is not the fix. This file
is. It reads the enumeration OUT of the SRS and measures the behavior BY
RUNNING it, so the two cannot drift apart in either direction: an
operation that starts refusing without being named fails here, and a
name in REQ-98 that stops refusing fails here too.

Three things this file does that a first version did not, each because a
reviewer measured the omission and showed the guard passing on a defect:

* Every probe builds its input OUTSIDE the ``try``, and a caught refusal
  is attributed to the module that raised it. A setup that itself raised
  ``UncertaintyError`` was otherwise credited to the operation under
  test, which was then recorded as refusing without ever being called.
* The normative table is checked in BOTH directions, per row. An
  existence check over the provisional names let the table's rows be
  swapped outright, which is the original defect with its sign flipped.
* What must be probed is derived from the table's own first column, not
  from a directory listing, so an operation living outside
  ``itaca/ops/`` cannot escape the requirement.

Every parse is asserted to have found something before it is compared. A
regex that silently matches nothing would make the assertions vacuous,
which is the shape this repository already refuses for the import policy
and for the plan and incident checkers, where an empty folder exits zero.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import UncertaintyError
from itaca.core.varframe import VarFrame

ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = ROOT / "docs" / "srs" / "chapters"

_CODE = re.compile(r"\\code\{((?:[^{}]|\{[^{}]*\})*)\}")


def _tokens(text: str) -> list[str]:
    r"""Every ``\code{}`` payload, with LaTeX escaping undone.

    ``translate\_moments`` is the operation's name in the source and
    ``translate_moments`` is its name in Python; comparing the two
    without this reported a missing probe for an operation that has one.
    """
    return [found.replace("\\_", "_") for found in _CODE.findall(text)]


#: The sentence REQ-98 declares as the single home of the list. Anchored
#: on the promise itself, so rewording the promise fails loudly here
#: rather than silently reducing the parse to nothing.
_PROVISIONAL = re.compile(
    r"operations are provisional, and this is the one place the list is\s+"
    r"given rather than restated:(.*?)\.\s",
    re.DOTALL,
)
_COUNT_WORDS = {"THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7}
#: A release-note bullet DECLARING a break, as opposed to discussing one.
_DECLARES_A_BREAK = re.compile(r"\b(?:is|are|was|were)\s+a\s+breaking\s+change\b", re.I)
_NUMBER_WORDS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
)


def reqbox(identifier: str) -> str:
    """The body of one requirement box, wherever it is declared."""
    opening = re.compile(
        r"\\begin\{reqbox\}\{"
        + re.escape(identifier)
        + r"\}\{\\\w+\}(.*?)\\end\{reqbox\}",
        re.DOTALL,
    )
    for path in sorted(CHAPTERS.glob("*.tex")):
        found = opening.search(path.read_text(encoding="utf-8"))
        if found:
            return found.group(1)
    raise AssertionError(f"{identifier} is not declared in any SRS chapter")


def srs_provisional_operations() -> set[str]:
    """The provisional family, parsed from REQ-98's single enumeration."""
    body = reqbox("REQ-98")
    found = _PROVISIONAL.search(body)
    assert found, (
        "REQ-98 no longer carries the sentence that declares itself the one "
        "place the provisional family is enumerated. Every check in this "
        "module reads the list from there, so a silent parse failure would "
        "pass them all while checking nothing (ITC-20260729-1450)."
    )
    names = set(_tokens(found.group(1)))
    assert names, "the enumeration sentence in REQ-98 names no operation"
    return names


def _table_rows() -> list[tuple[str, str]]:
    """The normative UncFrame table, as (first cell, effect cell) pairs."""
    body = reqbox("REQ-98")
    assert "tabularx" in body, "REQ-98 no longer carries its normative table"
    table = body[body.index("tabularx") :]
    rows = []
    for chunk in table.split("\\\\"):
        if "&" not in chunk or "textbf" in chunk or "midrule" in chunk:
            continue
        head, effect = chunk.split("&", 1)
        rows.append((head, effect))
    assert len(rows) >= 5, (
        f"the normative table parsed to {len(rows)} rows; the row-by-row "
        "check below would be vacuous on a broken parse"
    )
    return rows


def _row_labels(head: str) -> set[str]:
    """The operation labels a table row's first cell names.

    ``fill`` appears in two rows distinguished only by their method
    qualifier, so a bare operation name is not enough to identify what a
    row governs.
    """
    tokens = _tokens(head)
    methods = [token for token in tokens if token.startswith("method=")]
    operations = [
        token
        for token in tokens
        if not token.startswith("method=") and not token.startswith('"')
    ]
    labels: set[str] = set()
    for operation in operations:
        if operation == "fill" and methods:
            labels |= {f"fill({method})" for method in methods}
        else:
            labels.add(operation)
    return labels


def srs_table_operations() -> set[str]:
    """Every operation the normative table governs, by bare name."""
    names: set[str] = set()
    for head, _ in _table_rows():
        names |= {label.split("(")[0] for label in _row_labels(head)}
    assert len(names) >= 10, (
        f"the table's first column parsed to {len(names)} operations, which "
        "is fewer than the release ships; the coverage check would be weak"
    )
    return names


# --------------------------------------------------------------------
# Probes. One per operation the normative table governs, each applied to
# a frame that CARRIES uncertainty, so what refuses is measured and never
# declared. `setup` runs outside the try in the measurement below, so a
# refusal raised while BUILDING the input is loud instead of being
# credited to the operation under test.
# --------------------------------------------------------------------


class Probe(NamedTuple):
    """One operation, its input, and the module expected to refuse."""

    module: str
    setup: Callable[[], Any]
    call: Callable[[Any], object]


def _sweep(values: list[float] | None = None) -> VarFrame:
    """An alpha sweep carrying uncertainty on CT."""
    ct = values if values is not None else [float(a**2) for a in range(7)]
    alpha = np.arange(float(len(ct)))
    arr = np.column_stack([alpha, np.array(ct)])
    db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
    return db.set_uncertainty({"CT": 0.01})


def _gappy() -> VarFrame:
    """The same sweep with one NaN, so fill has something to do."""
    return _sweep([0.0, 1.0, float("nan"), 3.0, 4.0, 5.0, 6.0])


def _datapoint() -> VarFrame:
    """A datapoint-mode frame with uncertainty, ready for pivot."""
    arr = np.column_stack([np.arange(5.0), np.arange(5.0) ** 2])
    return itc.load(arr, names=["alpha", "CT"]).set_uncertainty({"CT": 0.01})


def _balance() -> VarFrame:
    """A one-point balance frame with force and moment groups."""
    rows = [[0.0, 0.0, 0.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0]]
    names = ["idx", "alpha", "beta", "FX", "FY", "FZ", "MX", "MY", "MZ"]
    db = itc.load(np.array(rows), names=names).pivot(dims=["idx"])
    db = db.set_metadata({"alpha": {"unit": "deg"}, "beta": {"unit": "deg"}})
    db = db.declare_vector("force", ["FX", "FY", "FZ"])
    db = db.declare_vector("moment", ["MX", "MY", "MZ"])
    return db.set_uncertainty({"FX": 0.01, "FY": 0.01, "FZ": 0.01})


def _two_sweeps() -> list[VarFrame]:
    """Two frames with disjoint coordinates, for concat."""
    low = _sweep([0.0, 1.0, 2.0])
    high = _sweep([3.0, 4.0, 5.0]).interpolate({"alpha": [3.0, 4.0, 5.0]})
    return [low, high]


def _coefficients() -> VarFrame:
    """A fitmodel output that has since been given uncertainty.

    ``fitvalue`` cannot be reached through an uncertain ``fitmodel``,
    which refuses first, so the coefficients are fitted clean and the
    uncertainty is declared on them afterwards. That is also the only
    route a user has today.
    """
    clean = itc.load(
        np.column_stack([np.arange(7.0), np.arange(7.0) ** 2]),
        names=["alpha", "CT"],
    ).pivot(dims=["alpha"])
    return clean.fitmodel(along="alpha", deg=2).set_uncertainty({"CT": 0.01})


#: label -> Probe. The label is the token REQ-98 uses, so the comparison
#: below is against the specification's own vocabulary rather than a
#: paraphrase of it.
PROBES: dict[str, Probe] = {
    "select": Probe("select", _sweep, lambda db: db.select({"alpha": [0.0, 1.0, 2.0]})),
    "at": Probe("select", _sweep, lambda db: db.at(alpha=0.0)),
    "squeeze": Probe(
        "squeeze", lambda: _sweep().select({"alpha": [0.0]}), lambda db: db.squeeze()
    ),
    "expand": Probe("expand", _sweep, lambda db: db.expand("mach", [0.5])),
    "pivot": Probe("pivot", _datapoint, lambda db: db.pivot(dims=["alpha"])),
    "concat": Probe(
        "concat", _two_sweeps, lambda pair: itc.concat(pair, along="alpha")
    ),
    "interpolate": Probe(
        "interpolate", _sweep, lambda db: db.interpolate({"alpha": [0.5, 1.5]})
    ),
    "average": Probe("average", _sweep, lambda db: db.average(along="alpha")),
    "integrate": Probe(
        "integrate", _sweep, lambda db: db.integrate("CT", over="alpha")
    ),
    "compute": Probe("compute", _sweep, lambda db: db.compute("f = CT * 2")),
    "rotate": Probe("rotate", _balance, lambda db: db.rotate("wind")),
    "translate_moments": Probe(
        "moments", _balance, lambda db: db.translate_moments(to_point=[0.1, 0.0, 0.0])
    ),
    "combine": Probe(
        "combine", _two_sweeps, lambda pair: pair[0].combine(pair[0], op="sum")
    ),
    'fill(method="linear")': Probe(
        "fill", _gappy, lambda db: db.fill(along="alpha", method="linear")
    ),
    'fill(method="polyfit")': Probe(
        "fill",
        _gappy,
        lambda db: db.fill(along="alpha", method="polyfit", deg=1, window=3),
    ),
    "smooth": Probe(
        "smooth",
        _sweep,
        lambda db: db.smooth(along="alpha", method="moving_avg", window=3),
    ),
    "diff": Probe("diff", _sweep, lambda db: db.diff(along="alpha", window=3, deg=1)),
    "fitmodel": Probe("fitmodel", _sweep, lambda db: db.fitmodel(along="alpha", deg=2)),
    "fitvalue": Probe(
        "fitmodel",
        _coefficients,
        lambda db: db.fitvalue(
            coef_dims=["alpha_coef"], at={"alpha": np.array([0.5, 1.5])}
        ),
    ),
}

#: Operations the normative table governs that the release does not ship
#: yet. The exemption is not taken on trust: the test below fails the
#: moment one of these resolves, so a shipped operation cannot keep
#: sitting here and stay unprobed.
_NOT_YET_IMPLEMENTED = frozenset({"statistics"})


def measured_refusing_operations() -> dict[str, str]:
    """Every probe that refuses, mapped to the module that raised.

    The setup runs OUTSIDE the try on purpose. A probe whose input
    construction raises ``UncertaintyError`` would otherwise be recorded
    as refusing without the operation under test ever being called, and
    the comparison would pass while measuring nothing.
    """
    refusing: dict[str, str] = {}
    for label, probe in PROBES.items():
        prepared = probe.setup()
        try:
            probe.call(prepared)
        except UncertaintyError as error:
            frames = traceback.extract_tb(error.__traceback__)
            refusing[label] = Path(frames[-1].filename).stem
    return refusing


def test_every_operation_in_the_normative_table_is_probed() -> None:
    """A new operation cannot arrive with its UncFrame effect undecided.

    The demanded set is derived from the table's own first column rather
    than from a directory listing, because REQ-98 governs operations
    wherever they live: ``pivot`` is in ``itaca/io/`` and ``combine`` in
    ``itaca/core/``, so a directory-scoped check would let either start
    refusing while the requirement's list stayed wrong and green.
    """
    declared = srs_table_operations()
    probed = {label.split("(")[0] for label in PROBES}
    missing = sorted(declared - probed - _NOT_YET_IMPLEMENTED)
    assert not missing, (
        f"the normative table governs {missing}, which no probe exercises, "
        "so whether they propagate or refuse is unmeasured and REQ-98 cannot "
        "be checked against them. Add a probe and declare the effect (DD-18)."
    )


def test_the_unimplemented_exemption_is_still_true() -> None:
    """The exemption above is a ratchet, not a permanent allowance."""
    for name in sorted(_NOT_YET_IMPLEMENTED):
        reachable = hasattr(VarFrame, name) or hasattr(itc, name)
        assert not reachable, (
            f"'{name}' is exempt from the probe requirement on the ground "
            "that it does not ship yet, and it now resolves. Write its probe "
            "and remove it from _NOT_YET_IMPLEMENTED (REQ-98, DD-18)."
        )


def test_every_operation_module_is_probed() -> None:
    """The directory half, kept as a second net under the table half.

    The table is the specification's inventory and this is the code's.
    Either can be wrong on its own; a module here that the table never
    names is a requirement gap rather than a probe gap, and it surfaces
    as this failure.
    """
    # A subpackage's operation is named by its DIRECTORY, not by the
    # `__init__` stem: filtering leading underscores discarded
    # `newfamily/__init__.py` as private, so a whole new operation family
    # could arrive unprobed while this check stayed green.
    ops = ROOT / "itaca" / "ops"
    modules = set()
    for path in ops.rglob("*.py"):
        # A flat module is named by its own stem; anything inside a
        # subpackage is named by the subpackage. `ops/__init__.py` falls
        # out of the first branch as `__init__` and is filtered as
        # private, which is what makes the second branch reachable only
        # for a genuinely new family.
        name = path.stem if path.parent == ops else path.parent.name
        if name.startswith("_"):
            continue
        modules.add(name)
    assert len(modules) >= 10, (
        f"the ops walk found {len(modules)} modules; a broken walk would "
        "pass this check while inspecting nothing"
    )
    probed = {probe.module for probe in PROBES.values()}
    missing = sorted(modules - probed)
    assert not missing, (
        f"operation module(s) {missing} have no uncertainty probe in PROBES "
        "(REQ-98, DD-18)."
    )


def test_req98_names_exactly_the_operations_that_refuse_uncertainty() -> None:
    """The specification's list and the library's behavior are one fact.

    Read from REQ-98, measured from the code. Either side moving alone
    fails, which is what makes this a guard rather than a restatement.
    """
    declared = srs_provisional_operations()
    measured = set(measured_refusing_operations())
    assert declared == measured, (
        f"REQ-98 names {sorted(declared)} as provisional while the library "
        f"actually refuses uncertainty in {sorted(measured)}. The SRS is the "
        "authoritative specification, so an operation that refuses must be "
        "named there and a name there must refuse (ITC-20260729-1450)."
    )


def test_each_refusal_is_raised_by_the_operation_under_test() -> None:
    """A refusal must come from the operation, not from its fixture.

    Without this the measurement above can be satisfied by a probe whose
    setup raised: the label is recorded, the operation is never called,
    and the guard reports agreement it never established.
    """
    for label, origin in measured_refusing_operations().items():
        expected = PROBES[label].module
        assert origin == expected, (
            f"the probe for '{label}' was recorded as refusing, but the "
            f"UncertaintyError was raised in '{origin}.py' rather than in "
            f"'{expected}.py', so the refusal belongs to another operation "
            "and this probe measured nothing (ITC-20260729-1450)."
        )


def test_req98_states_the_count_it_enumerates() -> None:
    """The written count and the written list must agree.

    The defect this file exists for was a count, not a list: REQ-98 said
    four in one sentence, three in the next, two in `CLAUDE.md`, and its
    normative table described a fifth behavior again.
    """
    # Scoped to the enumeration sentence, which is what the message below
    # claims to be talking about. Matching the whole reqbox discriminated
    # only by letter case: the body legitimately contains the lowercase
    # "four places at three different values" and "returns to four", in a
    # document that uses ALL CAPS for emphasis on nearly every page, so
    # one emphatic FOUR anywhere in the box would have failed the guard
    # for a reason unrelated to the drift it exists to catch.
    body = reqbox("REQ-98")
    found = _PROVISIONAL.search(body)
    assert found, "REQ-98 no longer carries its enumeration sentence"
    cut = body[: found.start()].rfind(".")
    sentence = body[cut + 1 : found.end()]
    words = [word for word in _COUNT_WORDS if re.search(rf"\b{word}\b", sentence)]
    assert len(words) == 1, (
        f"REQ-98 states {words or 'no'} count word(s) for its provisional "
        "family; exactly one is expected, in the sentence that enumerates it"
    )
    assert _COUNT_WORDS[words[0]] == len(srs_provisional_operations()), (
        f"REQ-98 says {words[0]} provisional operations and enumerates "
        f"{len(srs_provisional_operations())}"
    )


def test_the_normative_table_agrees_with_the_provisional_list_row_by_row() -> None:
    """Both directions, every row. Existence checking is not enough.

    Its `smooth`, `diff` row stated that they propagate through their
    kernel weights, which the implementation has never done, and a
    reader following the normative table would have written code that
    cannot run. The inverse is the same defect: a row promising a raise
    for an operation that propagates sends a user away from a result
    they could have had. Checking only that the provisional names appear
    somewhere with the word "raise" caught neither when the two `fill`
    rows were swapped outright.
    """
    provisional = srs_provisional_operations()
    covered: set[str] = set()
    for head, effect in _table_rows():
        labels = _row_labels(head)
        if not labels:
            continue
        covered |= labels
        overlap = labels & provisional
        assert overlap in (set(), labels), (
            f"the table row for {sorted(labels)} mixes provisional and "
            f"propagating operations ({sorted(overlap)} are provisional), so "
            "one normative effect is stated for two different behaviors"
        )
        claims_raise = "raise" in effect
        assert claims_raise == bool(overlap), (
            f"the normative row for {sorted(labels)} "
            f"{'claims a raise' if claims_raise else 'claims propagation'} "
            f"while REQ-98 lists {sorted(provisional)} as provisional. The "
            "table is normative, so a row that disagrees with the list IS "
            "the specification (ITC-20260729-1450)."
        )
    unrowed = sorted(provisional - covered)
    assert not unrowed, (
        f"{unrowed} are named provisional by REQ-98 and have no row in its "
        "normative table, so their UncFrame effect is undeclared (DD-18)."
    )


_OQ = re.compile(r"OQ-\d+")


def srs_row_questions() -> dict[str, str]:
    """Which open question REQ-98's prose assigns to each provisional row.

    Parsed from the "OQ-nn for <operations>" mapping that follows the
    enumeration, so the assignment is read from the requirement rather
    than restated here.
    """
    body = reqbox("REQ-98")
    found = _PROVISIONAL.search(body)
    assert found, "REQ-98 no longer carries its enumeration sentence"
    mapping: dict[str, str] = {}
    for question, operands in re.findall(
        # \s+ around "for", not a literal space: the mapping wraps mid
        # phrase ("OQ-42 for\n\code{fill(...)}"), and a space-only pattern
        # silently dropped the last assignment. The unassigned check below
        # is what caught that, which is the point of asserting coverage
        # rather than only agreement.
        r"(OQ-\d+)\s+for\s+((?:(?!OQ-)[^.])*)",
        body[found.end() :],
    ):
        for token in _tokens(operands):
            mapping[token] = question
    assert mapping, (
        "REQ-98 states no 'OQ-nn for <operations>' mapping after its "
        "enumeration, so which question lifts which row is unstated and the "
        "check below would be vacuous"
    )
    return mapping


def test_each_provisional_row_names_the_open_question_that_lifts_it() -> None:
    """One question per row, and the same assignment in prose and table.

    `fill(method="polyfit")` was routed to OQ-18 in four places. OQ-18
    asks about the sign of `smooth` and `diff` KERNEL weights and cannot
    lift the fill refusal at all: answering it in full would leave the
    operation refusing, because the fill ground is that no weights exist
    to have a sign. `docs/derivations/uncertainty_kernels.md` promised the
    opposite in its "what changes on approval" section, so the numerical
    analyst would have worked that derivation believing it released an
    operation it does not reach.

    A subset check is not enough and was measured insufficient: OQ-18 is
    legitimately cited by the `smooth`/`diff` row, so re-routing `fill`
    to OQ-18 passes any test that only asks whether the cited question
    appears somewhere in the requirement. The assignment is what must
    agree, per row.
    """
    provisional = srs_provisional_operations()
    assigned = srs_row_questions()
    unassigned = sorted(provisional - set(assigned))
    assert not unassigned, (
        f"REQ-98 names {unassigned} provisional without saying which open "
        "question lifts them, so the refusal has no stated way out (DD-18)."
    )
    for head, effect in _table_rows():
        labels = _row_labels(head) & provisional
        if not labels:
            continue
        cited = set(_OQ.findall(effect))
        assert cited, (
            f"the provisional table row for {sorted(labels)} cites no open "
            "question, so it states no condition under which the refusal is "
            "lifted (REQ-98, DD-18)."
        )
        for label in sorted(labels):
            assert assigned[label] in cited, (
                f"REQ-98's prose assigns {label} to {assigned[label]} while "
                f"its normative table row cites {sorted(cited)}. Routing a "
                "row to a question that cannot lift it is how "
                "fill(method='polyfit') came to point at OQ-18 in four "
                "places (ITC-20260729-1450, OQ-42)."
            )


#: The CHK-1 refusals, and the phrase each governing requirement must
#: carry. Every phrase was chosen by measuring it ABSENT from the
#: pre-amendment text: a phrase that already existed pins nothing, and
#: `datapoint` plus `DataError` were both present in REQ-01 before the
#: amendment, so reverting REQ-01 entirely was invisible to this check.
_CHK1_REFUSALS = (
    (
        "REQ-01",
        (
            "R3-ITA-008",
            "both a dimension and a variable",
            # The sixth CHK-1 refusal, ITC-20260729-2255, found by REV-004
            # after the first five were closed. All three phrases were
            # measured ABSENT from REQ-01 before the amendment, the way the
            # rows below were chosen: "wider" and "narrower" carry the
            # refusal and its asymmetry, and the finding id anchors it.
            "R3-ITA-009",
            "wider",
            "narrower",
        ),
        "a column named datapoint is refused, and so is a row wider than "
        "the header while a narrower one is still NaN-filled",
    ),
    ("REQ-24", ("AxesError",), "concat refuses mixed vector-group axes"),
    ("REQ-107", ("AxesError",), "the same refusal from the axis-registry side"),
    ("REQ-39", ("FINITE", "5.1.2"), "a non-finite magnitude is refused"),
    ("REQ-44", ("shadow", "DD-42"), "a constant may not shadow a channel"),
    ("REQ-45", ("three things", "DD-42"), "validate refuses three things, not two"),
)


@pytest.mark.parametrize(
    ("identifier", "phrases", "what"),
    _CHK1_REFUSALS,
    ids=[entry[0] for entry in _CHK1_REFUSALS],
)
def test_each_chk1_refusal_is_described_by_its_requirement(
    identifier: str, phrases: tuple[str, ...], what: str
) -> None:
    """Every refusal CHK-1 added must be visible in its own requirement.

    Each of these contradicted the text of a STABLE requirement rather
    than merely extending it, which is why the V&V pass rated the gap
    severe: the SRS declares itself authoritative and says that on a
    discrepancy the code is corrected, not the document. Here the code
    was right five times over.
    """
    body = reqbox(identifier)
    missing = [phrase for phrase in phrases if phrase not in body]
    assert not missing, (
        f"{identifier} does not mention {missing}, so the SRS does not "
        f"describe that {what} (ITC-20260729-1450)."
    )


def test_the_release_notes_name_the_same_provisional_family_as_req98() -> None:
    """The one restatement kept on purpose, and now the only guarded one.

    REQ-98 says it is the single place the list is given, and the release
    notes give it again, deliberately: a user hitting the refusal reads
    `CHANGELOG.md`, not the SRS. A duplicate aimed at a reader is worth
    keeping; a duplicate nothing compares is what this whole lane is
    about. So it is compared.
    """
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index("Read this first")
    section = text[start : text.index("### Changed", start)]
    declared = srs_provisional_operations()
    listed = {
        name.split("(")[0]
        for name in re.findall(r"`db\.(\w+)[^`]*`", section)
        if name not in {"d", "load"}
    }
    expected = {name.split("(")[0] for name in declared}
    missing = sorted(expected - listed)
    assert not missing, (
        f"the release notes' provisional list omits {missing}, which REQ-98 "
        "names. A user who hits the refusal reads this section, so an "
        "omission here is the drift with the highest cost "
        "(ITC-20260729-1450)."
    )


def _carve_out() -> str:
    """REQ-92's major-version-zero paragraph, where the list used to be."""
    body = reqbox("REQ-92")
    start = body.index("Major version zero")
    end = body.index("Every breaking change")
    return body[start:end]


def test_req92_does_not_enumerate_the_breaking_changes() -> None:
    """The removal is the fix; a corrected count would go stale again.

    REQ-92 named three breaking changes and shipped more. The remedy was
    not to recount: `CHANGELOG.md` is where the requirement's own next
    paragraph already mandates the list, and a duplicate inventory in a
    normative document goes stale independently of its original. A bare
    count is that same artifact with its evidence removed, so the
    property asserted here is that the carve-out states NO number, not
    merely that one dead phrase is gone.
    """
    carve = _carve_out()
    assert "does NOT enumerate" in carve, (
        "REQ-92's carve-out must say that it does not enumerate the breaking "
        "changes, so a reader knows the omission is deliberate"
    )
    # Scoped to sentences that talk about breaking changes, because
    # "one" is an ordinary English word ("the one it duplicates") and a
    # blanket ban would fail on prose that counts nothing.
    about_breaks = [
        sentence
        for sentence in re.split(r"(?<=\.)\s", carve)
        if re.search(r"\bbreak", sentence, re.I)
    ]
    assert about_breaks, (
        "REQ-92's carve-out no longer discusses breaking changes at all; "
        "the check below would pass vacuously"
    )
    counted = sorted(
        {
            word
            for sentence in about_breaks
            for word in _NUMBER_WORDS
            if re.search(rf"\b{word}\b", sentence, re.I)
        }
    )
    assert not counted, (
        f"REQ-92's carve-out counts breaking changes: {counted}. The "
        "enumeration and the count both belong in CHANGELOG.md alone, which "
        "is what the requirement's next paragraph already mandates. A bare "
        "count is the removed inventory with its evidence stripped off, and "
        "goes stale the same way (ITC-20260729-1450)."
    )


def test_req92_still_requires_the_marker_that_replaced_the_enumeration() -> None:
    """What REQ-92 rests on after the removal must still be stated."""
    body = reqbox("REQ-92")
    assert "CHANGELOG.md" in body and "BREAKING" in body, (
        "REQ-92 must still require every breaking change to be marked "
        "BREAKING in CHANGELOG.md; that obligation is what replaces the "
        "version bump while the major version is zero, and after the "
        "enumeration was removed it carries the whole weight."
    )


def test_every_breaking_change_in_the_release_notes_carries_the_marker() -> None:
    """REQ-92's obligation, measured against the file it names.

    The enumeration was removed from the requirement on the ground that
    `CHANGELOG.md` is the single authority. That made the authority load
    bearing, and it did not hold: four entries declared a break in prose
    or in mixed case, so a reader grepping for the marker the
    requirement names would have found five of nine.
    """
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    headings = [index for index, line in enumerate(lines) if line.startswith("## [")]
    assert len(headings) >= 2, (
        f"CHANGELOG.md has {len(headings)} version heading(s); the release "
        "section could not be delimited and this check would inspect the "
        "wrong text"
    )
    section = lines[headings[0] : headings[1]]
    assert any("**BREAKING" in line for line in section), (
        "no breaking change is marked in the release notes; this check "
        "would pass vacuously on a section it failed to find"
    )
    unmarked = [
        f"{index + 1}: {line.strip()[:70]}"
        for index, line in enumerate(section)
        if "**Breaking" in line and "**BREAKING" not in line
    ]
    # The mixed-case marker was three of the four original instances. The
    # fourth carried no bold marker at all: the Python-floor entry bolded
    # its headline and put "This is a breaking change for anyone on 3.10"
    # in plain prose on the next line. A guard that only sees the
    # mixed-case shape does not block the original failure when re-run,
    # which this repository's incident rule requires, so bullets are
    # walked too. Scoped to bullet starts so it cannot fire on the
    # requirement-quoting prose elsewhere in the section.
    bullets: list[tuple[int, list[str]]] = []
    for index, line in enumerate(section):
        if line.startswith("* "):
            bullets.append((index, [line]))
        elif bullets and line.startswith("  ") and line.strip():
            bullets[-1][1].append(line)
    # Matched on DECLARATIVE phrasing only, and the narrowness is the
    # point rather than a shortcut. A bare "break" fires on bullets that
    # merely discuss breakage: the keyword-only deprecation entry says
    # "Breaking it outright would have been worse than the finding", and
    # the REQ-92 entry quotes the requirement's own obligation. Both are
    # correct as unmarked. What the original defect looked like is a
    # declaration: "This is a breaking change for anyone on 3.10".
    prose_only = [
        f"{index + 1}: {body[0].strip()[:70]}"
        for index, body in bullets
        if _DECLARES_A_BREAK.search(" ".join(body))
        and not any("**BREAKING" in line for line in body)
    ]
    assert not unmarked and not prose_only, (
        f"release-note entr(ies) {unmarked + prose_only} declare a breaking "
        "change without the literal BREAKING marker REQ-92 requires. REQ-92 "
        "no longer enumerates the breaks, so this file is the only inventory "
        "and grepping the marker has to find all of them."
    )
