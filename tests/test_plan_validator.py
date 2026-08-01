"""Keep the plan-ledger checker proven, the way the incident gate is.

Usage example (TDD anchor)::

    checker, companion = _resolve()  # from ITACA_PLAN_VALIDATOR
    assert checker.name == "check_plan_kit.py" or checker.suffix == ".py"

The plan ledger is validated by the shared-kit checker ``check_plan_kit.py``
(Option C: the strict guards of the old ``check_plan_entries.py`` plus the
union vocabulary), resolved from the ``ITACA_PLAN_VALIDATOR`` environment
variable exactly as the incident checker is resolved from
``COORD_INCIDENT_LEDGER``. A validator that cannot fail the case it exists
to catch manufactures confidence, so its mutation companion runs here.

Resolution mirrors the plan skill and the incident-ledger philosophy:

- unset -> skip (a clone that never configured the validator still runs a
  green suite);
- set but the checker (or its mutation companion) is unreadable -> a
  configuration error, so this fails rather than passing silently. The
  skill's own contract makes the same promise, and asserting only the
  companion would let a mis-pointed ``ITACA_PLAN_VALIDATOR`` (for example
  one still naming the retired ``check_plan_entries.py``) green the suite;
- set but resolving to a file that is not ``check_plan_kit.py`` -> also a
  configuration error, since the directory beside it holds the sister
  repository's ``check_plan.py`` and one typo reaches it;
- resolving correctly but validating NOTHING -> a failure here whatever the
  exit code was, because a run against the wrong path would otherwise read
  as a pass.

That last one is kept as a check on itaca's own CONSUMPTION even though the
checker itself now refuses the case (kit 0.2.10: ``CANNOT VERIFY``, exit
2). Two reasons it is not redundant. ``classify`` below also catches a
checker whose output wording changed, which is a way for this guard to go
blind that no exit code reports. And the two live at different levels: the
kit decides what an empty walk means to a checker, and this decides what
validating nothing means to itaca, which would still be a silent pass if
some future caller here read the exit code alone.

As of kit 0.2.2 the companion resolves the checker as a sibling
(``Path(__file__).resolve().parent / "check_plan_kit.py"``) instead of
the old hardcoded coordination path, so it now proves the DEPLOYED copy
beside it, not the coordination master. That closes the coupling this
test previously had to disclose (routed item ITC-20260724-1715), which is
why the mutation companion can finally be wired as a tier-1 test here.
The deployed pair is at kit 0.2.10, and it got there in two steps a
couple of days apart, which is worth stating because the gap was the
defect. The CHECKER moved to 0.2.10 on 2026-07-30. Its mutation
COMPANION stayed at 0.2.3 until 2026-08-01, so for that window the
artifact proving this checker can still fail was seven versions behind
the checker, and nothing could see it: each half was self-consistent
with its own pin in ``tests/test_kit_drift.py``. Both are now at 0.2.10
together with their pins, and the companion reports ``0 check(s) could
not fail`` with an empty-plan-directory case it did not have before.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from management_root import (  # the single home of the resolution rule
    ManagementRootError,
    resolve_management_root,
)

_CHECKER_NAME = "check_plan_kit.py"
_COMPANION_NAME = "check_plan_kit_mutations.py"
_REPO = Path(__file__).resolve().parents[1]


def _ledger_dir() -> tuple[Path, str] | None:
    """The resolved plan ledger and the branch that resolved it, or None.

    Resolution goes through ``resolve_management_root`` in
    ``tests/management_root.py``, the single home of the rule in CLAUDE.md,
    "Where the session documents live". Reusing it rather than re-deriving
    the root here is deliberate: a second copy of a resolution rule is how
    the two drift apart, and this file only needs the answer.

    ``None`` means one thing only: the variable is UNSET and the ``_private/``
    fallback holds no session documents. CLAUDE.md's locator table makes that
    a legitimate skip, because it is the state of any clone that configured
    nothing.

    A variable that is SET but invalid is a configuration error and is NOT
    converted to a skip. The exception propagates, carrying the resolver's own
    three-part message. Collapsing the two branches was the first version of
    this helper and it was wrong in the way this whole file exists to catch: a
    misconfigured root would have read as "not configured", so a run against a
    sibling project's ledger, or against nothing at all, would have skipped
    green while announcing a cause that had not occurred. The branch is
    returned rather than discarded for the same reason CLAUDE.md requires it to
    be announced: a resolution nobody states cannot be noticed when it is
    wrong.
    """
    configured = os.environ.get("ITACA_MANAGEMENT_ROOT")
    try:
        root, branch = resolve_management_root(configured, repo=_REPO)
    except ManagementRootError:
        if configured:
            raise
        return None
    ledger = root / "plan"
    return (ledger, branch) if ledger.is_dir() else None


def _resolve() -> tuple[Path, Path] | None:
    """(checker, mutation companion) for the configured validator, or None.

    ``ITACA_PLAN_VALIDATOR`` may name the checker file itself or the
    directory holding it; the companion sits beside the checker in either
    case. Returns None only when the variable is unset.
    """
    configured = os.environ.get("ITACA_PLAN_VALIDATOR")
    if not configured:
        return None
    target = Path(configured)
    if target.suffix == ".py":
        checker, directory = target, target.parent
    else:
        checker, directory = target / _CHECKER_NAME, target
    return checker, directory / _COMPANION_NAME


def test_the_plan_checker_is_readable_when_configured() -> None:
    """A set ITACA_PLAN_VALIDATOR must name a checker that actually exists.

    The plan skill runs exactly this checker; a variable pointing at a
    missing or retired file (the skill's own "set but unreadable is a
    configuration error") must surface here, not green silently.
    """
    resolved = _resolve()
    if resolved is None:
        pytest.skip("ITACA_PLAN_VALIDATOR is unset; plan checker not configured here")
    checker, _ = resolved
    assert checker.is_file(), (
        f"ITACA_PLAN_VALIDATOR resolves to a checker that is not readable at "
        f"{checker}. This is a configuration error, not a skip: the plan skill "
        f"runs this path, so a missing or retired target must fail loudly."
    )
    # A real-but-wrong basename in the direct-file form (the directory also
    # holds the sister repo's check_plan.py) would otherwise green while the
    # skill runs the wrong checker, so require the kit checker by name.
    assert checker.name == _CHECKER_NAME, (
        f"ITACA_PLAN_VALIDATOR must resolve to {_CHECKER_NAME}, not "
        f"{checker.name}. The plan ledger is validated only by the shared-kit "
        f"checker; a different file in the same directory is a misconfiguration."
    )


def test_the_plan_checker_can_still_fail() -> None:
    """Run the kit plan checker's mutation companion when it is configured."""
    resolved = _resolve()
    if resolved is None:
        pytest.skip("ITACA_PLAN_VALIDATOR is unset; plan checker not configured here")
    _, companion = resolved
    assert companion.is_file(), (
        f"ITACA_PLAN_VALIDATOR is set but the mutation companion is missing at "
        f"{companion}. This is a configuration error, not a skip: the plan "
        f"checker cannot be proven, so it must not read as clean."
    )
    done = subprocess.run(
        [sys.executable, str(companion)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr


def _entry_count(output: str) -> int | None:
    """The count from a ``N entries checked (...)`` line, or None."""
    match = re.search(r"(\d+) entries checked", output)
    return int(match.group(1)) if match else None


def classify(returncode: int, output: str) -> tuple[str, str]:
    """What a plan-checker run actually says, and the fix each answer wants.

    Extracted from the assertion it serves so every branch can be exercised
    over synthetic shapes rather than only through whichever shape the
    deployed checker happens to produce today. Two branches were otherwise
    unreachable and one fired with the wrong explanation.

    Diagnosis is by output SHAPE first and exit code second. Reading the code
    alone was the defect: kit 0.2.10's exit 2 covers three different causes
    (an empty walk, an unreadable ``legacy_ids.txt``, and a usage error), and
    exit 1 covers two (bad entries, and a path that is not a directory), so a
    message keyed on a code names one cause and sends the reader elsewhere for
    the others. And a checker regressed to the pre-0.2.10 shape prints
    ``no entries`` while exiting ZERO, which must be reported as an empty
    ledger and not as a wording change.

    Returns ``("validated", "")`` only when a positive entry count was read
    and the run did not refuse.
    """
    lowered = output.lower()
    # A crash first, because a traceback carries no recognizable shape and
    # would otherwise be reported as wording drift, sending the reader to
    # edit this guard. Same hole the missing-directory assertion below
    # already closes for itself.
    if "traceback (most recent call last)" in lowered:
        return (
            "checker-crashed",
            "the checker raised rather than reporting; nothing was validated "
            "and the traceback names the cause. Fix the checker or the input "
            "it choked on, not this guard",
        )
    if "config error" in lowered or "legacy_ids.txt" in lowered:
        return (
            "config-error",
            "the checker refused because something it needs could not be read, "
            "and its output names the file; fix that file rather than the "
            "ledger path",
        )
    if "usage:" in lowered and returncode == 2:
        return (
            "bad-invocation",
            "the checker rejected the invocation itself, so no path was walked",
        )
    if "not a directory" in lowered:
        return (
            "no-such-directory",
            "the resolved ledger path is not a directory; check ITACA_MANAGEMENT_ROOT",
        )
    if "cannot verify" in lowered or "no entries" in lowered:
        return (
            "empty",
            "the checker found no entries, so nothing was validated; either "
            "the resolved path is wrong or the ledger is genuinely empty. "
            "Check ITACA_MANAGEMENT_ROOT and that the tree is synced. Note "
            "that a checker older than kit 0.2.10 reports this while exiting "
            "ZERO, which is why the wording is read and not the code",
        )
    count = _entry_count(output)
    if count is None:
        return (
            "unreadable-report",
            "no '<N> entries checked' line and no recognized refusal, so the "
            "checker's output format has moved under this guard; re-read "
            "check_plan_kit.py and update _entry_count and classify",
        )
    if count == 0:
        return (
            "zero-count",
            "the checker reported zero entries WITHOUT refusing, which reads "
            "as a pass while nothing was validated",
        )
    if returncode != 0:
        return (
            "bad-entries",
            f"{count} entries were read and the checker rejected some of them; "
            f"its output names each file and the failing check",
        )
    return "validated", ""


def test_a_zero_entry_ledger_report_is_a_failure_here() -> None:
    """Read the checker's entry COUNT, not only its exit code.

    ``ITC-20260727-1612``. ``check_plan_kit.py`` used to exit ZERO on an
    empty ledger folder, printing ``no entries in <dir>``, while a MISSING
    folder was refused loudly with ``not a directory`` and exit 1. So the
    loud case was handled and the empty one was not, and a run pointed at
    the wrong path reported success. Kit 0.2.10 refuses it with exit 2, and
    that fix is adopted here.

    ``CLAUDE.md`` already told the reader to read the entry count rather
    than the exit code. That is documentation, and this repository's own
    incident rule says documentation is not a guard. This test is that
    instruction expressed as a mechanism: whatever the exit code was, a
    report covering zero entries fails here.

    It survives the kit fix because it guards a different thing. The kit
    decides what an empty walk means to a CHECKER; this decides what a
    zero-entry report means to ITACA, which would still be a silent pass if
    some caller here read the exit code alone. It also catches a checker
    whose output wording drifts, which no exit code reports.

    The diagnosis lives in ``classify`` beside this test, not inline, and it
    keys on the output SHAPE rather than the exit code. Two rounds of review
    landed there. Once the kit refused the empty case, an empty ledger
    stopped printing a count line, so an inline "no count line" branch fired
    with the message "the output format changed" for a run where nothing had
    changed. Keying on the code instead was no better: kit 0.2.10 exits 2 for
    three different causes and 1 for two, so any message tied to a code names
    one and misdirects the rest. Extracting it also made the zero-count
    branch, which the deployed checker can no longer produce, reachable by a
    test rather than only by a mutation.
    """
    resolved = _resolve()
    if resolved is None:
        pytest.skip("ITACA_PLAN_VALIDATOR is unset; plan checker not configured here")
    checker, _ = resolved
    found = _ledger_dir()
    if found is None:
        pytest.skip(
            "ITACA_MANAGEMENT_ROOT is unset and the _private/ fallback holds no "
            "session documents, so no plan ledger is resolvable here and there "
            "is nothing to validate. A root that is SET but invalid does not "
            "reach this skip; it raises."
        )
    ledger, branch = found
    done = subprocess.run(
        [sys.executable, str(checker), str(ledger)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    output = done.stdout + done.stderr
    where = f"{ledger} (resolved by the {branch} branch), exit {done.returncode}"
    outcome, detail = classify(done.returncode, output)
    assert outcome == "validated", (
        f"the plan ledger at {where} was not validated: {detail} "
        f"(ITC-20260727-1612). Output: {output.strip()!r}"
    )


def test_the_plan_checker_refuses_an_empty_ledger_folder(tmp_path: Path) -> None:
    """The kit-side half of ``ITC-20260727-1612``. FIXED; the marker is gone.

    The defect was that an empty ledger folder printed ``no entries`` and
    exited ZERO, so a checker aimed at the wrong path, at an unsynced tree,
    or at a directory naming nothing was indistinguishable from a ledger
    with no defects. Kit 0.2.10 refuses it: ``CANNOT VERIFY`` on stderr and
    exit 2. Adopted here by re-vendoring the DEPLOYED copy together with its
    pin in ``tests/test_kit_drift.py``, since the copy lives outside this
    repository under the directory ``ITACA_PLAN_VALIDATOR`` names.

    This test carried ``xfail(strict=True)`` until then, and the ratchet did
    its work: adopting the fix made it XPASS, which strict xfail turns into
    a failure, so the marker could not be left behind.

    It stays here, unmarked, as the falsifier, and that is load-bearing
    rather than tidy. The kit's own mutation companion is at 0.2.3 and has
    no empty-walk case, so ``0 check(s) could not fail`` is true of every
    guard it covers and says nothing about this one. Until the kit adds it
    (``ITC-20260730-0205``), this is the only place the 0.2.10 refusal is
    proven, on the copy this repository actually runs.

    WHY THE ASSERTION IS SPECIFIC AND NOT MERELY ``returncode != 0``. A
    reviewer measured the first version XPASSING for the wrong reason twice:
    pointed at a checker that does not exist, and at one that raises on
    startup, a bare nonzero exit read as "the kit was fixed". A reader
    following the reason string would then remove the marker and ship a
    repository whose plan validation cannot run at all. So the test first
    proves the checker WORKS on a known-good one-entry ledger, and then
    requires the empty-folder refusal to name the empty case. A crash now
    fails as a crash instead of passing as a fix.

    The exit CODE is pinned too, and separately from the refusal, because
    the kit distinguishes 1 (the entries were read and some were bad) from
    2 (cannot verify). An empty walk is the second. A checker that started
    reporting it as 1 would still refuse, so the refusal assertion alone
    would not notice, while a caller treating any nonzero as "the ledger is
    dirty" would report a configuration error as a content error.
    """
    resolved = _resolve()
    if resolved is None:
        pytest.skip("ITACA_PLAN_VALIDATOR is unset; plan checker not configured here")
    checker, _ = resolved
    # Precondition: the checker runs and accepts a valid ledger. Without this,
    # every failure mode of the checker looks like the fix this test waits for.
    good = tmp_path / "good"
    good.mkdir()
    (good / "ITC-20260101-0000-a-known-good-entry.md").write_text(
        "---\n"
        "id: ITC-20260101-0000-a-known-good-entry\n"
        "milestone: M1\n"
        "priority: P2\n"
        "status: open\n"
        "ref: this test\n"
        "---\n\n"
        "A synthetic entry, so the checker is proven to run before the "
        "empty-folder case below is interpreted.\n",
        encoding="utf-8",
    )
    control = subprocess.run(
        [sys.executable, str(checker), str(good)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    control_output = control.stdout + control.stderr
    assert control.returncode == 0 and _entry_count(control_output) == 1, (
        f"the plan checker could not validate a known-good one-entry ledger, "
        f"so this test cannot tell a kit fix from a broken checker. Exit "
        f"{control.returncode}, output {control_output.strip()!r}. Fix the "
        f"checker or ITACA_PLAN_VALIDATOR before reading the result below."
    )

    empty = tmp_path / "plan"
    empty.mkdir()
    done = subprocess.run(
        [sys.executable, str(checker), str(empty)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    output = done.stdout + done.stderr
    assert done.returncode != 0 and (
        "no entries" in output.lower() or "empty" in output.lower()
    ), (
        f"an empty ledger folder exited {done.returncode} without refusing it, "
        f"so a run against the wrong path looks like a pass. Output: "
        f"{output.strip()!r}"
    )
    # The refusal and its KIND are asserted separately. A checker that
    # refused with 1 would satisfy the assertion above while telling a
    # caller the ledger's contents are bad, when nothing was read at all.
    assert done.returncode == 2, (
        f"an empty ledger folder exited {done.returncode}, and the kit reserves "
        f"2 for CANNOT VERIFY, meaning nothing was validated. An empty walk is "
        f"that. Exit 1 covers a path the checker refused with a cause: bad "
        f"entries, or a path that is not a directory. Output: {output.strip()!r}"
    )
    # And a MISSING directory keeps its own answer, so the fix widened the
    # refusal rather than collapsing two different configuration errors into
    # one code. This half was always correct and is pinned so it stays so.
    absent = subprocess.run(
        [sys.executable, str(checker), str(tmp_path / "not-created")],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    absent_output = (absent.stdout + absent.stderr).strip()
    # The message as well as the code: a checker that exited 1 from an
    # uncaught exception on this path would satisfy the code alone, and this
    # test would then report a crash as the behavior it pins.
    assert absent.returncode == 1 and "not a directory" in absent_output.lower(), (
        f"a missing plan directory exited {absent.returncode} with "
        f"{absent_output!r}, where it has always exited 1 naming 'not a "
        f"directory'. A bare exit 1 is also what a crash on this path would "
        f"give, so the message is required too."
    )


# (returncode, output) -> the outcome `classify` must report. Every branch is
# here, including the ones the deployed checker can no longer produce, so
# deleting any of them fails rather than going unnoticed.
#
# EACH DISJUNCT GETS ITS OWN ROW. A reviewer measured that four sub-branch
# deletions survived an earlier version of this table, because the synthetic
# output for the empty walk matched BOTH halves of that branch and the config
# output matched both halves of its own. A branch tested only through an
# input that satisfies every disjunct at once is a branch whose disjuncts are
# untested.
_SHAPES = [
    ("kit 0.2.10 empty walk", 2, "CANNOT VERIFY C:/x/plan: holds no entries", "empty"),
    # The refusal wording without the count wording, and vice versa.
    ("cannot verify alone", 2, "CANNOT VERIFY C:/x/plan: refusing", "empty"),
    ("pre-0.2.10 empty walk", 0, "no entries in C:/x/plan", "empty"),
    ("missing directory", 1, "not a directory: C:/x/plan", "no-such-directory"),
    (
        "unreadable legacy_ids.txt",
        2,
        "CONFIG ERROR: legacy_ids.txt exists at C:/x/plan/legacy_ids.txt but "
        "could not be read (UnicodeDecodeError: ...)",
        "config-error",
    ),
    # The two halves of the config branch, each alone.
    ("config error not naming the file", 2, "CONFIG ERROR: unreadable", "config-error"),
    (
        "legacy ids named without the CONFIG ERROR prefix",
        2,
        "cannot read legacy_ids.txt at C:/x/plan",
        "config-error",
    ),
    ("usage error", 2, "usage: check_plan_kit.py <plan-directory>", "bad-invocation"),
    # A usage line with a code OTHER than 2 must not be read as the usage
    # branch, which is what the returncode conjunct is for.
    (
        "usage wording with a different code",
        0,
        "usage: check_plan_kit.py <plan-directory>",
        "unreadable-report",
    ),
    (
        "a crashed checker",
        1,
        "Traceback (most recent call last):\n  KeyError: 'id'",
        "checker-crashed",
    ),
    ("wording drift", 0, "validated 12 files, all good", "unreadable-report"),
    ("zero count reported as a pass", 0, "0 entries checked (), 0 bad", "zero-count"),
    ("bad entries", 1, "12 entries checked (open: 12), 3 bad", "bad-entries"),
    ("a clean ledger", 0, "144 entries checked (open: 112), 0 bad", "validated"),
]


@pytest.mark.parametrize(
    ("label", "returncode", "output", "expected"),
    _SHAPES,
    ids=[shape[0].replace(" ", "-") for shape in _SHAPES],
)
def test_the_classifier_names_every_shape_a_plan_run_can_take(
    label: str, returncode: int, output: str, expected: str
) -> None:
    """``ITC-20260727-1612``. Each outcome wants a different fix, so each
    must be distinguishable, including the two the deployed checker cannot
    produce today.

    ``pre-0.2.10 empty walk`` is the row that matters most: a checker
    regressed to printing ``no entries`` and exiting ZERO must be reported as
    an EMPTY ledger, not as a wording change, which is what an exit-code-first
    reading did. ``zero count reported as a pass`` is unreachable through the
    current checker, so without this table it could be deleted from
    ``classify`` and nothing would notice.
    """
    outcome, detail = classify(returncode, output)
    assert outcome == expected, (
        f"the {label} shape (exit {returncode}, {output!r}) was classified "
        f"{outcome!r} with detail {detail!r}, expected {expected!r}"
    )
    assert (detail == "") is (expected == "validated"), (
        f"the {label} shape returned outcome {outcome!r} with detail "
        f"{detail!r}; every outcome but 'validated' must carry a fix to "
        f"suggest, and 'validated' must carry none"
    )
