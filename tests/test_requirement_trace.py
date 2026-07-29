"""REQ to code to test traceability, validated in CI (`ITACA-007`).

Usage example (TDD anchor)::

    trace = build_trace()
    assert trace["REQ-103"].tests

`REV-001` reported that "SRS 0.2.0" identifies neither immutable content
nor implementation state. Two halves, and this file addresses the second:
there was no REQ to code to test matrix at all, and nothing in CI checked
one. The reqbox census it measured was **97 stable, 11 draft, 0
implemented, 0 pending** against a taxonomy in `01_introduction.tex` that
defines all four plus deprecated, so `spec_status` was carrying two
different meanings at once and answering neither.

What this file does NOT do, said plainly so the guarantee is not read as
wider than it is. It does not freeze a baseline, and it does not
separate `spec_status` from `implementation_status` in the reqbox macro,
which is a LaTeX change to every requirement and is registered rather
than done here. What it does is make the trace a machine-checked fact
instead of a claim: every requirement the SRS declares is discovered,
every citation in the code and the suite is discovered, and the two are
matched so that a requirement whose implementation disappears cannot
stay silently green.

The trace is DISCOVERED, never enumerated. A hand-maintained matrix is
the same class of artifact as the hand-maintained version literal that
`ITACA-004` reports: it goes stale silently and nothing notices.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRS = ROOT / "docs" / "srs" / "chapters"
PACKAGE = ROOT / "itaca"
SUITE = ROOT / "tests"
_SELF = Path(__file__).resolve()

_REQBOX = re.compile(r"\\begin\{reqbox\}\{(REQ-\d+)\}\{\\(\w+)\}")
_CITATION = re.compile(r"\bREQ-\d+\b")


@dataclass
class Requirement:
    """One SRS requirement and where it is reached."""

    identifier: str
    status: str
    chapter: str
    code: set[str] = field(default_factory=set)
    tests: set[str] = field(default_factory=set)


def build_trace() -> dict[str, Requirement]:
    """Discover every declared requirement and every citation of it."""
    trace: dict[str, Requirement] = {}
    for path in sorted(SRS.glob("*.tex")):
        for match in _REQBOX.finditer(path.read_text(encoding="utf-8")):
            identifier, status = match.group(1), match.group(2)
            trace[identifier] = Requirement(identifier, status, path.name)

    citations: dict[str, dict[str, set[str]]] = {
        "code": defaultdict(set),
        "tests": defaultdict(set),
    }
    for root, bucket in ((PACKAGE, "code"), (SUITE, "tests")):
        for path in sorted(root.rglob("*.py")):
            if path == _SELF:
                # This module is ADMINISTRATION, not evidence. It walked
                # itself, so every id in _UNREACHED_AT_LANE_CLOSE below
                # counted as a test citation of the very requirement it
                # records as unreached, and the unreached count came out
                # 0 where the honest figure is 26. The gate was green
                # exactly because the file listing the gaps was read as
                # closing them (R3-ITA-010).
                continue
            text = path.read_text(encoding="utf-8")
            for identifier in set(_CITATION.findall(text)):
                citations[bucket][identifier].add(path.relative_to(ROOT).as_posix())
    for identifier, requirement in trace.items():
        requirement.code = citations["code"].get(identifier, set())
        requirement.tests = citations["tests"].get(identifier, set())
    return trace


#: The measured state at the ITA-1 lane close (0.2.0). These are
#: RATCHETS, not documentation: the reached set may only grow and the
#: unreached set may only shrink, so a requirement cannot quietly stop
#: being implemented and a new one cannot quietly arrive unimplemented.
#: Both are computed from the same walk the tests use, so they cannot
#: drift from what the walk can see.
_UNREACHED_AT_LANE_CLOSE: frozenset[str] = frozenset(
    {
        # Future milestones (M2 plotting, statistics, surrogate).
        "REQ-43",
        "REQ-50",
        "REQ-52",
        "REQ-56",
        "REQ-57",
        "REQ-58",
        "REQ-59",
        "REQ-60",
        "REQ-61",
        "REQ-62",
        "REQ-63",
        "REQ-64",
        "REQ-65",
        "REQ-66",
        "REQ-67",
        "REQ-68",
        "REQ-69",
        "REQ-74",
        "REQ-104",
        "REQ-108",
        # Implemented in CONFIGURATION, which this walk cannot see:
        # REQ-75 is --cov-fail-under=90, REQ-93 is the (absent)
        # commitlint job, REQ-94 the changelog rule.
        "REQ-09",
        "REQ-75",
        "REQ-87",
        "REQ-93",
        "REQ-94",
        "REQ-97",
    }
)
# REQ-78 and REQ-85 left this set when the walk stopped reading its own
# administration: both are genuinely cited outside this file, so with
# the contaminated evidence removed the honest measurement is 26
# unreached, not 28 and not the 0 the gate used to report. Taking them
# off is the deliberate, reviewable act the ratchet asks for, and it
# TIGHTENS the guard, because a requirement outside this set is one the
# reached-ratchet then protects.


def _reached_at_lane_close() -> frozenset[str]:
    """Every declared requirement except the unreached set above."""
    return frozenset(build_trace()) - _UNREACHED_AT_LANE_CLOSE


_REACHED_AT_LANE_CLOSE = _reached_at_lane_close()


def test_the_trace_is_not_empty() -> None:
    """A discovery that returns nothing would pass every check below."""
    trace = build_trace()
    assert len(trace) > 90, (
        f"the reqbox walk found only {len(trace)} requirements; it is the "
        "input to every check below, so a broken walk would pass them all "
        "while checking nothing (REQ-07, ITACA-007)."
    )


def test_itaca_007_every_requirement_declares_a_known_status() -> None:
    """The taxonomy has five states and the catalog must use them.

    `01_introduction.tex` defines stable, draft, implemented, pending and
    deprecated. Any other token is a typo that silently creates a sixth
    state nobody defined.
    """
    known = {"stable", "draft", "implemented", "pending", "deprecated"}
    trace = build_trace()
    unknown = {
        identifier: req.status
        for identifier, req in trace.items()
        if req.status not in known
    }
    assert not unknown, (
        f"requirement(s) declare a status outside the taxonomy: {unknown}. "
        f"The defined states are {sorted(known)} (ITACA-007)."
    )


def test_itaca_007_every_implemented_requirement_has_a_test() -> None:
    """A requirement the LIBRARY cites must be cited by the suite too.

    This is the actionable half of the matrix, and the one that can hold
    today. A requirement the code claims to implement while no test
    names it is verified by nothing: coverage says the LINES ran, never
    that the REQUIREMENT holds. That gap is how `ITACA-012` survived,
    where a normative document claimed a capability no symbol provided.

    The converse, a requirement nothing reaches at all, is reported
    below rather than failed, because separating spec status from
    implementation status is a change to every reqbox and is registered
    rather than done in this lane.
    """
    trace = build_trace()
    unverified = sorted(
        identifier for identifier, req in trace.items() if req.code and not req.tests
    )
    assert not unverified, (
        f"requirement(s) {unverified} are cited by the library and by no "
        "test, so nothing verifies the behavior they promise. Cite the "
        "requirement id in the test that pins it (ITACA-007)."
    )


def test_itaca_007_no_requirement_silently_stops_being_reached() -> None:
    """A ratchet, not an inventory. A reached requirement may never leave.

    The first version of this check skipped with a list and could
    therefore never fail: a requirement that IS implemented today but
    loses its citation to a refactor would silently join the unreached
    set, the count would move from 28 to 29, and the run would stay
    green. That is the self-skipping evidence this repository names for
    the plan and incident checkers, where an empty folder reports "no
    entries" and exits zero.

    The floor below is the measured state at the 0.2.0 lane close. It
    goes UP when a requirement gains an implementation and never down.
    Removing a name from it is a deliberate, reviewable act.

    Note the walk's blind spot, stated because the earlier message
    asserted the opposite: it reads only `*.py`. REQ-75 is implemented
    in `pyproject.toml` (`--cov-fail-under=90`) and REQ-78 in
    `[tool.mypy] strict`, so a requirement implemented in CONFIGURATION
    is invisible here and must not be read as unimplemented.
    """
    trace = build_trace()
    reached = {identifier for identifier, req in trace.items() if req.code or req.tests}
    lost = sorted(_REACHED_AT_LANE_CLOSE - reached)
    assert not lost, (
        f"requirement(s) {lost} were reached by the library or the suite at "
        "the 0.2.0 lane close and are not any more. An implementation or a "
        "test citation was removed; restore it, or remove the id from "
        "_REACHED_AT_LANE_CLOSE deliberately (ITACA-007)."
    )


def test_itaca_007_a_new_unreached_requirement_cannot_appear_unnoticed() -> None:
    """The other half of the ratchet.

    A requirement added to the SRS with no implementation and no test is
    a legitimate state for a future milestone, and an illegitimate one
    for a requirement someone meant to implement. The set below makes
    the difference a written act rather than a silence.
    """
    trace = build_trace()
    unreached = {
        identifier for identifier, req in trace.items() if not (req.code or req.tests)
    }
    surprises = sorted(unreached - _UNREACHED_AT_LANE_CLOSE)
    assert not surprises, (
        f"requirement(s) {surprises} are declared in the SRS and reached by "
        "nothing. Implement and cite them, or add them to "
        "_UNREACHED_AT_LANE_CLOSE with the milestone that will "
        "(ITACA-007)."
    )


def test_itaca_012_no_requirement_claims_an_absent_symbol() -> None:
    """The specific instance `REV-001` reported, pinned as a fact.

    `08_standards_alignment.tex` stated that v0.1.0 supported
    `db.export_provenance`. A grep over the package returns nothing, the
    M0 plan says it ships in v0.3.0, and the roadmap places it in M2, so
    a normative document made a false claim about a PUBLISHED release.
    This asserts the claim is gone AND that the symbol is still absent,
    so the two cannot drift apart again in either direction.
    """
    standards = (SRS / "08_standards_alignment.tex").read_text(encoding="utf-8")
    assert "v0.1.0 supports native serialization" not in standards
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in PACKAGE.rglob("*.py")
    )
    if "def export_provenance" in sources:  # pragma: no cover - future M2
        pytest.skip("export_provenance now exists; update the SRS claim with it")
    assert "is an M2 deliverable" in standards, (
        "the SRS must say PROV export is deferred while no symbol implements "
        "it (ITACA-012)."
    )
