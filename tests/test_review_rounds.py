"""The two-round review cap's checker, and the evidence it can still fail.

Usage example (TDD anchor)::

    done = subprocess.run(
        [sys.executable, str(_ROUNDS_MUTATIONS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr

`review-policy.md` has capped reviews at two rounds since kit 0.2.7 and
nothing enforced it. Kit 0.2.15 vendors the mechanism, and the rule it
mechanises is not the count. Lane ITA-4 is why: its round-one FIXES were
themselves defective, six guards did not guard, one false-fired on
correct code, and it introduced a fresh defect in the same commit that
added the guard against the old one. Only round two saw any of it. Under
a flat "two rounds, then register whatever is left" every one of those
would have shipped, documented as known.

So the checker refuses a ledger that REGISTERS a finding about a previous
round's fix (that finding is the fix not being done, and it is fixed in
the round that found it), refuses a third round with no named authority,
and refuses a ledger that certifies nothing.

WHAT THIS MODULE DID NOT PROVE UNTIL KIT 0.2.16, and the paragraph is
kept rather than deleted because it is what changed. Nothing in this
repository applied the cap to a real ledger from a hook or from CI, and
every test here would have passed if it were never applied at all. What
applied it was the `role-review` skill, which is an INSTRUCTION, and this
repository's own rule says documentation is not a guard. That is the
whole of `ITC-20260802-0120`.

0.2.16 adds the locator the kit owed, and this module now uses it:

    <root>/<lane>_rounds.ledger

resolved by `--root <dir> --lane <id>`. The convention is the one lane
ITA-11 used unprompted, recorded rather than invented. NO ENVIRONMENT
VARIABLE JOINS THE FAMILY: the caller passes the root, and what an absent
root means at a gate is each repository's charter call. itaca's is in
CLAUDE.md and is a SKIP THAT MUST BE ANNOUNCED, on the same rule
`tests/test_kit_drift.py` applies to every env-located artifact, and
never a denial. The denial branch belongs to `COORD_INCIDENT_LEDGER`
alone.

WHAT IS STILL NOT MECHANICAL, so the improvement is not read as wider
than it is. `--root <root> --all` is NOT wired, and the reason is
measured. Run against the real root on 2026-08-02, before this lane's own
ledger existed, `--root "$ITACA_MANAGEMENT_ROOT" --all` reported 2 ledgers
checked and 2 refused, 22 violations each, EVERY ONE of them the new rule
8, with 22 `fixed` rows in each. Both are lane ITA-11's WORK, and only one
says so in its `lane:` field: the other declares `lane: ITC-20260802-0330`,
the plan item it reviews, so the filename convention and the `lane:` field
are not the same thing. Both were written before `property=` existed.

They are NOT retrofitted, because writing the sentence after the fix is
not the mechanism and the whole value of the field is at the moment of
writing; they stay as closed historical records. So this module checks the
LANE form against a ledger written under rule 8 from its first line, and
wiring `--all` waits on those two being resolved, which is the author's
call over another lane's closed record (`ITC-20260802-1715`). The same
invocation now reports 3 ledgers checked and 2 refused: this lane's own
ledger is the difference, and it VERIFIES.

The rest of `OQ-54` is unchanged: a LANE IDENTITY at hook time, so an
invoker could know which ledger belongs to the work in front of it. The
constant below is this module standing in for that, deliberately and
visibly. An earlier version of this docstring said a fourth locator was
needed and attributed the question to `OQ-53`; both were measured false
by reviewers, OQ-53 being the vendored-kit currency question.

WHY THE COMPANION RUNS HERE rather than sitting beside the checker
unexecuted. A checker in `.claude/kit` that nothing calls is the same
shape as the defect it exists to catch, which this repository already
names for `ITACA-006`. Running the companion answers DRIFT, not
enforcement, and the two are not the same claim. It is also the drift
lane ITA-4 measured directly:
the deployed plan checker had been upgraded to 0.2.10 while the mutation
companion proving it can still fail sat at 0.2.3, both internally
consistent and no test able to see it. A companion that runs in tier 1
cannot fall behind its checker silently, because a mismatched pair stops
being green.

The counts are pinned for the reason the release-gate companion's are:
the body-sha256 pin in `tests/test_kit_drift.py` fails first on any byte
change, so these literals are defense in depth for one specific path, a
re-vendor where the hash is updated mechanically and a shrunken case list
goes unnoticed.

The ledger FORMAT this checker reads is PROPOSED and not settled, on the
precedent `check_probe_closure.py` set. This lane recorded its own round
ledger in that format as the first consumer use of it. A lane that finds
the format wrong corrects it by kit promotion, never by hand-editing the
vendored copy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from management_root import (  # the single home of the resolution rule
    ManagementRootError,
    resolve_management_root,
)

_ROOT = Path(__file__).resolve().parents[1]
_KIT = _ROOT / ".claude" / "kit"
_ROUNDS_CHECK = _KIT / "check_review_rounds.py"
_ROUNDS_MUTATIONS = _KIT / "check_review_rounds_mutations.py"

#: The lane whose round ledger this suite certifies. It is a CONSTANT and
#: not a discovery, and that is the honest shape of what is missing: there
#: is no lane identity available at test time, which is the open half of
#: `OQ-54`. A new lane moves this line, and the `role-review` skill is
#: what writes the ledger it names. Checking every ledger under the root
#: instead is what `--all` is for, and the module docstring says why that
#: is not wired here yet.
#:
#: THE DANGEROUS DIRECTION IS A STALE VALUE, not an absent ledger, and it
#: was named by three reviewer lenses at once. An absent ledger is loud. A
#: constant left behind is SILENT: the previous lane's ledger is still
#: there and still clean, so the suite certifies a closed historical record
#: while the current lane's ledger is never read, and nothing says so.
#: `test_the_certified_ledger_is_not_older_than_another_lane_s` below is
#: what makes that direction loud too. It is a floor and not a mechanism:
#: a lane that writes NO ledger and moves nothing is still not caught,
#: which is `ITC-20260802-1715` and is stated rather than papered over.
#: MOVED FROM `ITA-12` BY LANE ITA-2D, and the move was not remembered:
#: `test_the_certified_ledger_is_not_older_than_another_lane_s` FAILED in
#: ITA-2D's own pre-commit run, naming `ITA-2D_rounds.ledger` as strictly
#: newer than the `ITA-12` ledger this constant still pointed at. The
#: silent direction it was written for was silent for exactly one lane,
#: which is the shortest useful life a guard can have and is the evidence
#: that the floor is worth its cost.
#: MOVED FROM `ITA-2D` BY LANE ITA-15, and this time the move was made
#: BEFORE the guard fired, because the previous entry said it would. That
#: is the whole return on writing the failure down: the constant is now a
#: known step of closing a lane rather than a surprise in a pre-commit run.
#: MOVED AGAIN TO `ITA-17`, before the guard fired for the second lane
#: running. Two consecutive lanes have now paid nothing for it, which is
#: what a known step looks like once it is written down.
_LANE = "ITA-17"

#: The convention the kit writes down at 0.2.16. ONE copy of the fact:
#: both the glob and the per-lane filename derive from it, because two
#: copies of a kit convention drift apart on a kit rename and the glob's
#: failure is the misleading one (it matches nothing and the error blames
#: the root).
_LEDGER_SUFFIX = "_rounds.ledger"
_LEDGER_GLOB = f"*{_LEDGER_SUFFIX}"

#: A minimal ledger that certifies one round with one fixed finding, used
#: by the hermetic locator cases. It carries `property=` because rule 8
#: requires one on every `fixed` row.
_VALID_LEDGER = """\
lane: PROBE
rounds: 1

finding: P1 | round=1 | ground=new | fixed | \
property=the probe ledger resolves from a root and a lane id
"""


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=str(_ROOT),
    )


def test_the_vendored_round_cap_checker_is_present() -> None:
    """A checker loaded by path fails loudly if it is missing.

    Without this a rename would remove the whole check while the suite
    stayed green, which is the self-skipping evidence the kit exists to
    replace.
    """
    for checker in (_ROUNDS_CHECK, _ROUNDS_MUTATIONS):
        assert checker.is_file(), f"vendored kit checker missing at {checker}"


def test_the_round_cap_checker_refuses_a_bad_invocation() -> None:
    """A CONFIG error exits 2 and is never reported as a clean ledger.

    The cheapest possible proof that the vendored copy RUNS at all. It is
    not redundant with the companion below: a copy whose header was
    corrupted on vendoring parses as a SyntaxError, the body hash is
    untouched because the marker splits header from body, and
    `tests/test_kit_drift.py` stays green. That happened in this very
    lane, on the first vendoring pass, and it is why a checker is
    EXECUTED here and not only hashed.
    """
    done = _run(str(_ROUNDS_CHECK))
    assert done.returncode == 2, (
        f"expected exit 2 (CONFIG) from a bare invocation, got "
        f"{done.returncode}.\n{done.stdout}{done.stderr}"
    )
    assert "usage:" in (done.stdout + done.stderr).lower(), (
        f"the checker refused without saying how to invoke it, which is the "
        f"three-part error rule broken.\n{done.stdout}{done.stderr}"
    )


@pytest.mark.slow
@pytest.mark.guardproof
def test_the_round_cap_checker_can_still_fail() -> None:
    """The mutation companion proves the round-cap rules still bite.

    MEASURED 3.17 s, over the commit tier's 3.0 s budget, so it carries
    the marker: it spawns the checker once per case and once per case per
    mutant. The marker moves WHERE it runs and never WHETHER: the pre-push
    tier and CI both run it, and both block. The two tests above stay in
    the commit tier, so a vendored copy that does not even parse is caught
    at the cheapest gate.

    Its case 1 and case 2 are the two REAL shapes rather than
    reconstructions: lane ITA-4's round two as it actually happened, and
    the same round two as a flat two-rounds-then-register cap would have
    recorded it. If case 2 ever stops being refused, this checker has
    stopped being able to tell the rule from the count.

    The companion also reports how many mutants were denied BY A CRASH
    rather than by a changed verdict. That number is stated by the tool
    and is not asserted here: a crash proves the line is load-bearing and
    does not prove the check produced the refusal, so it is a fact to read
    rather than a threshold to pin.
    """
    done = _run(str(_ROUNDS_MUTATIONS))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "all 16 mutants are denied" in done.stdout, (
        f"the round-cap mutation companion did not report all 16 mutants "
        f"denied. Two opposite remedies: if a re-vendor changed the count, "
        f"move it here and in tests/test_kit_drift.py's manifest note "
        f"together; if it did not, a mutant SURVIVED and the checker no "
        f"longer refuses what it claims to. Output:\n{done.stdout}"
    )
    assert "All 30 ledger cases and 7 locator checks hold" in done.stdout, (
        f"the round-cap mutation companion did not report 30 ledger cases "
        f"and 7 locator checks. The mutants can be denied by a shrunken "
        f"case list, so these counts are what catches a re-vendor that "
        f"quietly dropped cases. The 21 pre-existing cases hold in verdict "
        f"inside the 30; the locator checks are new at kit 0.2.16. If the "
        f"kit really changed the counts, move the pin; do not delete it. "
        f"Output:\n{done.stdout}"
    )


def test_the_locator_resolves_a_ledger_from_a_root_and_a_lane(
    tmp_path: Path,
) -> None:
    """The locator's two verdicts, hermetically, on a tree this test builds.

    This case does not depend on how any machine is configured, which is
    the half `test_the_lane_ledger_this_repository_certifies_is_clean`
    below cannot offer: that one reads a ledger outside this repository
    and skips where it is absent. A mechanism proven only where the real
    root exists is a mechanism unproven in CI, and CI is where a broken
    locator would otherwise go unnoticed.

    Both directions are asserted, because only the pair is a guard. A
    resolver that always exits 0 passes the first and fails the second; a
    resolver that always exits 2 does the reverse.
    """
    (tmp_path / f"PROBE{_LEDGER_SUFFIX}").write_text(_VALID_LEDGER, encoding="utf-8")

    found = _run(str(_ROUNDS_CHECK), "--root", str(tmp_path), "--lane", "PROBE")
    assert found.returncode == 0, (
        f"the locator did not resolve {tmp_path}/PROBE_rounds.ledger from "
        f"--root and --lane, or refused a ledger that satisfies every rule "
        f"including the new rule 8.\n{found.stdout}{found.stderr}"
    )

    absent = _run(str(_ROUNDS_CHECK), "--root", str(tmp_path), "--lane", "NOSUCH")
    assert absent.returncode == 2, (
        f"a root holding no ledger for the named lane exited "
        f"{absent.returncode}, not 2. 'I could not find the thing I was "
        f"asked to check' is a CONFIGURATION error and never a pass; a "
        f"checker that reports clean over nothing is the failure this kit "
        f"registers most often.\n{absent.stdout}{absent.stderr}"
    )
    assert f"NOSUCH{_LEDGER_SUFFIX}" in (absent.stdout + absent.stderr), (
        f"the refusal did not name the path it looked for, so an operator "
        f"cannot tell a wrong root from a wrong lane.\n"
        f"{absent.stdout}{absent.stderr}"
    )


def _resolved_root() -> Path:
    """The management root, or a skip naming why the cap went unchecked.

    ONLY the resolution itself may skip here, and that is the charter
    branch written in CLAUDE.md: at THIS gate an unresolvable
    `ITACA_MANAGEMENT_ROOT` is a skip that must be ANNOUNCED, never a
    denial, so a clone that configured nothing still runs a green suite
    and the run says what went unread. Unresolvable covers unset, absent
    and set-but-invalid alike, because `resolve_management_root` refuses
    all three the same way.

    A MISSING LEDGER IS NOT A CONFIGURATION FACT and must not share that
    branch. Stacking a second skip behind the first was this module's own
    round-one defect: "the skill never wrote one" then read exactly like
    "the clone is not configured", and the claim that the cap is applied
    stayed true-sounding while nothing applied it.
    """
    try:
        root, _branch = resolve_management_root(
            os.environ.get("ITACA_MANAGEMENT_ROOT"), repo=_ROOT
        )
    except ManagementRootError as error:
        pytest.skip(
            f"the management root does not resolve ({error}), so lane "
            f"{_LANE}'s round ledger cannot be located. The two-round cap is "
            f"UNCHECKED here, not satisfied."
        )
    return root


def test_the_lane_ledger_this_repository_certifies_is_clean() -> None:
    """Run the checker against a REAL ledger, which is the whole point.

    `ITC-20260802-0120` is not that the cap lacked a mechanism; it is that
    nothing ever applied the mechanism to a ledger. This is what applies
    it, and it FAILS rather than skips when the ledger is absent: a
    configured root with no ledger for the lane means the review did not
    write one, which is work not done and not a configuration state.
    """
    root = _resolved_root()
    ledger = root / f"{_LANE}{_LEDGER_SUFFIX}"
    assert ledger.is_file(), (
        f"no round ledger for lane {_LANE} at {ledger}, although the "
        f"management root resolved. The role-review skill writes it as the "
        f"review closes, one line per finding, with `property=` on every "
        f"`fixed` row. Write it, or move `_LANE` in this module to the lane "
        f"whose ledger this suite should certify."
    )
    done = _run(str(_ROUNDS_CHECK), "--root", str(root), "--lane", _LANE)
    assert done.returncode == 0, (
        f"lane {_LANE}'s round ledger at {ledger} is REFUSED by the two-round "
        f"cap. Read which rule: a finding about a previous round's fix that "
        f"was registered rather than fixed, a third round with no named "
        f"authority, a ledger certifying nothing, or a `fixed` row with no "
        f"`property=` sentence.\n{done.stdout}{done.stderr}"
    )


def test_the_certified_ledger_is_not_older_than_another_lane_s() -> None:
    """A newer lane ledger must not sit unchecked behind a stale constant.

    The silent direction of `_LANE`. Once a ledger exists for it the test
    above goes green and STAYS green for every later lane, certifying a
    closed historical record while the current lane's ledger is never
    read. Three reviewer lenses found that independently in this module's
    own round one.

    IT COMPARES MTIME, which is metadata on a tree outside this
    repository, and that is the weakest part of this guard. It is chosen
    because the ledger format carries no date field to compare instead:
    the alternative is asking git in the other tree, which makes a
    commit-tier test depend on another repository's history being
    readable. The direction is right and the anchor is soft, so the
    failure message names all three causes rather than asserting the one
    the test was written for.

    Ties PASS. The stated reason used to be that a fresh clone gives every
    file the same checkout time; round two measured that `st_mtime` is a
    float with sub-second resolution, so ties are nearly unreachable and
    the concession buys almost nothing. It is kept because it can only
    ever make this guard quieter, never louder, and a guard that can false
    fire on a tie would be worse than one that misses it.
    """
    root = _resolved_root()
    ledgers = sorted(root.glob(_LEDGER_GLOB))
    assert ledgers, (
        f"the resolved management root {root} holds no {_LEDGER_GLOB} at "
        f"all. Every reviewed lane writes one, so a root holding none is "
        f"either the wrong root or a review process that has stopped "
        f"recording; it is not a clean run."
    )
    certified = root / f"{_LANE}{_LEDGER_SUFFIX}"
    if not certified.is_file():
        # ANNOUNCED, not a bare return. The sibling test above owns that
        # failure, but "owns it" holds only while both are selected: a
        # `-k` run, a marker change or a future split would turn a silent
        # return into a silent pass, in the one module whose whole thesis
        # is that an unannounced skip is the defect.
        pytest.skip(
            f"no ledger for lane {_LANE} at {certified}; "
            f"test_the_lane_ledger_this_repository_certifies_is_clean owns "
            f"that failure and this staleness check has nothing to compare"
        )
    newer = [
        path.name
        for path in ledgers
        if path.stat().st_mtime > certified.stat().st_mtime
    ]
    assert not newer, (
        f"{newer} are newer by mtime than the ledger this suite certifies "
        f"({certified.name}). THREE causes, and the remedy differs: a later "
        f"lane wrote a round ledger and `_LANE` was never moved, in which "
        f"case move `_LANE`; an OLDER ledger was edited after this one was "
        f"written, a typo repair or a reformat, in which case read `lane:` "
        f"in the named files and change nothing here; or `--root <root> "
        f"--all` should be wired now that the pre-rule-8 ledgers are "
        f"resolved (`ITC-20260802-1715`), which retires this check. This "
        f"guard compares FILE MTIME on a tree outside this repository, "
        f"because the ledger format carries no date to compare instead."
    )
