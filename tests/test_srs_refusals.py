"""The SRS must describe the refusals the library actually ships.

Usage example (the contract under test)::

    provisional = srs_provisional_operations()   # parsed from REQ-98
    refusing = measured_refusing_operations()    # measured by calling them
    assert provisional == refusing

`ITC-20260729-1450`, a blocker on the v0.2.0 tag. The CHK-1 release
checkpoint added five public refusals to surfaces whose stable
requirement text contradicted them, and REQ-98 carried the count of its
own provisional family in four places at three different values while
the normative table still claimed that two of them propagate. Both are
one defect: a normative document holding a hand-maintained inventory
that nothing compares against the thing it inventories.

Documentation is not a guard, so the amendment is not the fix. This file
is. It reads the enumeration OUT of the SRS and measures the behavior BY
RUNNING it, so the two cannot drift apart in either direction: an
operation that starts refusing without being named fails here, and a
name in REQ-98 that stops refusing fails here too.

The parse is asserted to have found something before it is compared. A
regex that silently matches nothing would make every assertion below
vacuous, which is the shape this repository already refuses for the
import policy and for the plan and incident checkers, where an empty
folder exits zero.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import UncertaintyError
from itaca.core.varframe import VarFrame

SRS = Path(__file__).resolve().parents[1] / "docs" / "srs"
CHAPTERS = SRS / "chapters"

_CODE = re.compile(r"\\code\{((?:[^{}]|\{[^{}]*\})*)\}")
#: The sentence REQ-98 declares as the single home of the list. Anchored
#: on the promise itself, so rewording the promise fails loudly here
#: rather than silently reducing the parse to nothing.
_PROVISIONAL = re.compile(
    r"operations are provisional, and this is the one place the list is\s+"
    r"given rather than restated:(.*?)\.\s",
    re.DOTALL,
)
_COUNT_WORDS = {"THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7}


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
    names = set(_CODE.findall(found.group(1)))
    assert names, "the enumeration sentence in REQ-98 names no operation"
    return names


# --------------------------------------------------------------------
# Probes. One per operation the library exposes, each applied to a frame
# that CARRIES uncertainty, so what refuses is measured and never
# declared. The coverage assertion below requires one for every module
# in `itaca/ops/`, which is what stops a new operation from arriving
# with its UncFrame effect undecided (DD-18, REQ-98).
# --------------------------------------------------------------------


def _sweep(values: list[float] | None = None) -> VarFrame:
    """An alpha sweep carrying uncertainty on CT."""
    ct = values if values is not None else [float(a**2) for a in range(7)]
    alpha = np.arange(float(len(ct)))
    arr = np.column_stack([alpha, np.array(ct)])
    db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
    return db.set_uncertainty({"CT": 0.01})


def _balance() -> VarFrame:
    """A one-point balance frame with force and moment groups."""
    rows = [[0.0, 0.0, 0.0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0]]
    names = ["idx", "alpha", "beta", "FX", "FY", "FZ", "MX", "MY", "MZ"]
    db = itc.load(np.array(rows), names=names).pivot(dims=["idx"])
    db = db.set_metadata({"alpha": {"unit": "deg"}, "beta": {"unit": "deg"}})
    db = db.declare_vector("force", ["FX", "FY", "FZ"])
    db = db.declare_vector("moment", ["MX", "MY", "MZ"])
    return db.set_uncertainty({"FX": 0.01, "FY": 0.01, "FZ": 0.01})


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
    fitted = clean.fitmodel(along="alpha", deg=2)
    return fitted.set_uncertainty({"CT": 0.01})


#: label -> (ops module it belongs to, the call). The label is the token
#: REQ-98 uses, so the comparison below is against the specification's
#: own vocabulary rather than a paraphrase of it.
PROBES: dict[str, tuple[str, Callable[[], object]]] = {
    "select": ("select", lambda: _sweep().select({"alpha": [0.0, 1.0, 2.0]})),
    "squeeze": (
        "squeeze",
        lambda: _sweep().select({"alpha": [0.0]}).squeeze(),
    ),
    "expand": ("expand", lambda: _sweep().expand("mach", [0.5])),
    "concat": (
        "concat",
        lambda: itc.concat(
            [
                _sweep([0.0, 1.0, 2.0]),
                _sweep([3.0, 4.0, 5.0]).interpolate({"alpha": [3.0, 4.0, 5.0]}),
            ],
            along="alpha",
        ),
    ),
    "interpolate": (
        "interpolate",
        lambda: _sweep().interpolate({"alpha": [0.5, 1.5]}),
    ),
    "average": ("average", lambda: _sweep().average(along="alpha")),
    "integrate": (
        "integrate",
        lambda: _sweep().integrate("CT", over="alpha"),
    ),
    "compute": ("compute", lambda: _sweep().compute("f = CT * 2")),
    "rotate": ("rotate", lambda: _balance().rotate("wind")),
    "translate_moments": (
        "moments",
        lambda: _balance().translate_moments(to_point=[0.1, 0.0, 0.0]),
    ),
    'fill(method="linear")': (
        "fill",
        lambda: _sweep([0.0, 1.0, float("nan"), 3.0, 4.0, 5.0, 6.0]).fill(
            along="alpha", method="linear"
        ),
    ),
    'fill(method="polyfit")': (
        "fill",
        lambda: _sweep([0.0, 1.0, float("nan"), 3.0, 4.0, 5.0, 6.0]).fill(
            along="alpha", method="polyfit", deg=1, window=3
        ),
    ),
    "smooth": (
        "smooth",
        lambda: _sweep().smooth(along="alpha", method="moving_avg", window=3),
    ),
    "diff": ("diff", lambda: _sweep().diff(along="alpha", window=3, deg=1)),
    "fitmodel": ("fitmodel", lambda: _sweep().fitmodel(along="alpha", deg=2)),
    "fitvalue": (
        "fitmodel",
        lambda: _coefficients().fitvalue(
            coef_dims=["alpha_coef"], at={"alpha": np.array([0.5, 1.5])}
        ),
    ),
}


def measured_refusing_operations() -> set[str]:
    """Every probe that raises ``UncertaintyError``, measured by calling."""
    refusing: set[str] = set()
    for label, (_, call) in PROBES.items():
        try:
            call()
        except UncertaintyError:
            refusing.add(label)
    return refusing


def test_every_operation_module_is_probed() -> None:
    """A new operation cannot arrive with its UncFrame effect undecided.

    Without this, the comparison below stays green for any operation
    nobody thought to add a probe for, which is the same self-skipping
    shape the enumeration defect had: the check would be measuring a
    subset it also defines.
    """
    modules = {
        path.stem
        for path in (Path(__file__).resolve().parents[1] / "itaca" / "ops").glob("*.py")
        if not path.stem.startswith("_")
    }
    probed = {module for module, _ in PROBES.values()}
    missing = sorted(modules - probed)
    assert not missing, (
        f"operation module(s) {missing} have no uncertainty probe in PROBES, "
        "so whether they propagate or refuse is unmeasured and REQ-98 cannot "
        "be checked against them. Add a probe and declare the effect (DD-18)."
    )


def test_req98_names_exactly_the_operations_that_refuse_uncertainty() -> None:
    """The specification's list and the library's behavior are one fact.

    Read from REQ-98, measured from the code. Either side moving alone
    fails, which is what makes this a guard rather than a restatement.
    """
    declared = srs_provisional_operations()
    measured = measured_refusing_operations()
    assert declared == measured, (
        f"REQ-98 names {sorted(declared)} as provisional while the library "
        f"actually refuses uncertainty in {sorted(measured)}. The SRS is the "
        "authoritative specification, so an operation that refuses must be "
        "named there and a name there must refuse (ITC-20260729-1450)."
    )


def test_req98_states_the_count_it_enumerates() -> None:
    """The written count and the written list must agree.

    The defect this file exists for was a count, not a list: REQ-98 said
    four in one sentence, three in the next, two in `CLAUDE.md`, and its
    normative table described a fifth behavior again.
    """
    body = reqbox("REQ-98")
    words = [word for word in _COUNT_WORDS if word in body]
    assert len(words) == 1, (
        f"REQ-98 states {words or 'no'} count word(s) for its provisional "
        "family; exactly one is expected, in the sentence that enumerates it"
    )
    assert _COUNT_WORDS[words[0]] == len(srs_provisional_operations()), (
        f"REQ-98 says {words[0]} provisional operations and enumerates "
        f"{len(srs_provisional_operations())}"
    )


def test_the_normative_table_gives_every_provisional_row_as_raising() -> None:
    """The table is normative, so a row claiming propagation is the spec.

    Its `smooth`, `diff` row stated that they propagate through their
    kernel weights, which the implementation has never done. A reader
    following the normative table would have written code that cannot
    run.
    """
    body = reqbox("REQ-98")
    table = body[body.index("tabularx") :]
    rows = [row for row in table.split("\\\\") if "&" in row]
    for name in sorted(srs_provisional_operations()):
        bare = name.split("(")[0]
        owning = [row for row in rows if f"\\code{{{bare}}}" in row.split("&")[0]]
        assert owning, f"no normative table row names {bare}"
        assert any("raise" in row for row in owning), (
            f"the normative UncFrame row for {bare} does not say it raises, "
            f"while REQ-98 names it provisional and the code refuses. Row(s): "
            f"{[row.strip()[:80] for row in owning]}"
        )


#: The CHK-1 refusals, and the phrase each governing requirement must
#: carry. Deliberately the ERROR CLASS or the refused condition, never a
#: whole sentence: this pins that the text describes the behavior, and
#: leaves the author free to word it.
_CHK1_REFUSALS = (
    ("REQ-01", ("datapoint", "DataError"), "a column named datapoint is refused"),
    ("REQ-24", ("AxesError",), "concat refuses mixed vector-group axes"),
    ("REQ-107", ("AxesError",), "the same refusal from the axis-registry side"),
    ("REQ-39", ("FINITE", "UncertaintyError"), "a non-finite magnitude is refused"),
    ("REQ-44", ("shadow", "DataError"), "a constant may not shadow a channel"),
    ("REQ-45", ("three things",), "validate refuses three things, not two"),
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


def test_req92_does_not_enumerate_the_breaking_changes() -> None:
    """The removal is the fix; a corrected count would go stale again.

    REQ-92 named three breaking changes and shipped nine. The remedy was
    not to recount: `CHANGELOG.md` is where the requirement's own next
    paragraph already mandates the list, and a duplicate inventory in a
    normative document goes stale independently of its original. This
    pins that the duplicate does not come back, and that the obligation
    which replaces it is still stated.
    """
    body = reqbox("REQ-92")
    assert "ships three" not in body, (
        "REQ-92 enumerates the breaking changes again. The enumeration "
        "belongs in CHANGELOG.md alone (ITC-20260729-1450)."
    )
    assert "CHANGELOG.md" in body and "BREAKING" in body, (
        "REQ-92 must still require every breaking change to be marked "
        "BREAKING in CHANGELOG.md; that obligation is what replaces the "
        "version bump while the major version is zero."
    )
