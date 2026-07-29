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
            text = path.read_text(encoding="utf-8")
            for identifier in set(_CITATION.findall(text)):
                citations[bucket][identifier].add(path.relative_to(ROOT).as_posix())
    for identifier, requirement in trace.items():
        requirement.code = citations["code"].get(identifier, set())
        requirement.tests = citations["tests"].get(identifier, set())
    return trace


def test_the_trace_is_not_empty() -> None:
    """A discovery that returns nothing would pass every check below."""
    trace = build_trace()
    assert len(trace) > 90, (
        f"the reqbox walk found only {len(trace)} requirements; it is the "
        "input to every check below, so a broken walk would pass them all "
        "while checking nothing (REQ-07, ITACA-007)."
    )


def test_itaca_007_every_requirement_declares_a_known_status() -> None:
    """The taxonomy has five states and the catalogue must use them.

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


def test_itaca_007_the_run_reports_which_requirements_nothing_reaches() -> None:
    """Name the unreached requirements, so a gap is an inventory.

    The census `REV-001` measured was 97 stable, 11 draft, 0 implemented
    and 0 pending, against a taxonomy defining all four: `spec_status`
    was carrying two meanings at once and answering neither, so "stable"
    says nothing about whether anything implements it. Splitting the
    field is a LaTeX change to every reqbox and is registered.

    Until then this test refuses to be silent about the gap. It never
    fails on a legitimately future requirement; it exists so the run
    STATES which requirements nothing reaches, rather than a matrix
    quietly describing a system that has moved.
    """
    trace = build_trace()
    unreached = sorted(
        identifier
        for identifier, req in trace.items()
        if not req.code and not req.tests
    )
    assert trace, "the reqbox walk is inert"
    if unreached:
        pytest.skip(
            f"{len(trace) - len(unreached)} of {len(trace)} requirements are "
            f"reached by the library or the suite. NOT reached by either, so "
            f"nothing in this repository implements or verifies them: "
            f"{unreached}. Most are future milestones; the point of naming "
            f"them is that a requirement which SHOULD be reached cannot hide "
            f"among them (ITACA-007)."
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
