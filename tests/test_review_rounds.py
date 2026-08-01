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

WHAT THIS MODULE DOES NOT PROVE, said first because a reviewer measured
that the paragraph below reads as if it did. Nothing in this repository
applies the cap to a real ledger from a hook or from CI, and these tests
would all pass if it were never applied at all. What DOES apply it is the
`role-review` skill, which records a lane's round ledger under the
resolved management root and runs this checker against it before the
review closes. That is an INSTRUCTION and this repository's own rule says
documentation is not a guard, so the honest description is: vendored,
mutation-proven, and applied by a skill rather than by a mechanism.

Whether it SHOULD be mechanical is `OQ-54`, raised by this lane. What is
missing is not a locator: `ITACA_MANAGEMENT_ROOT` already names where the
ledger lives and the checker takes a plain `--ledger <path>`. It is a
LANE IDENTITY at hook time, so an invoker could know which ledger belongs
to the work in front of it, and a decision about what an absent root
means at a GATE, since that variable's unset branch substitutes a
location rather than denying. An earlier version of this docstring said a
fourth locator was needed and attributed the question to `OQ-53`; both
were measured false by reviewers, OQ-53 being the vendored-kit currency
question.

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

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

_ROOT = Path(__file__).resolve().parents[1]
_KIT = _ROOT / ".claude" / "kit"
_ROUNDS_CHECK = _KIT / "check_review_rounds.py"
_ROUNDS_MUTATIONS = _KIT / "check_review_rounds_mutations.py"


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
    assert "all 12 mutants are denied" in done.stdout, (
        f"the round-cap mutation companion did not report all 12 mutants "
        f"denied. Two opposite remedies: if a re-vendor changed the count, "
        f"move it here and in tests/test_kit_drift.py's manifest note "
        f"together; if it did not, a mutant SURVIVED and the checker no "
        f"longer refuses what it claims to. Output:\n{done.stdout}"
    )
    assert "All 21 cases hold" in done.stdout, (
        f"the round-cap mutation companion did not report 21 cases. The "
        f"mutants can be denied by a shrunken case list, so this count is "
        f"what catches a re-vendor that quietly dropped cases. If the kit "
        f"really changed it, move the pin; do not delete it. "
        f"Output:\n{done.stdout}"
    )
