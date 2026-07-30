"""Keep the plan-ledger checker proven, the way the incident gate is.

Usage example (TDD anchor)::

    checker, companion = _resolve()  # from ITACA_PLAN_VALIDATOR
    assert checker.name == "check_plan_kit.py" or checker.suffix == ".py"

The plan ledger is validated by the shared-kit checker ``check_plan_kit.py``
(Option C: the strict guards of the old ``check_plan_entries.py`` plus the
union vocabulary), resolved from the ``ITACA_PLAN_VALIDATOR`` environment
variable exactly as the incident checker is resolved from
``ITACA_INCIDENT_LEDGER``. A validator that cannot fail the case it exists
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
- resolving correctly but reporting ZERO entries -> a failure here whatever
  the exit code was, because a run against the wrong path would otherwise
  read as a pass.

That last one is kept as a check on itaca's own CONSUMPTION even though the
checker itself now refuses the case (kit 0.2.10: ``CANNOT VERIFY``, exit
2). Two reasons it is not redundant. The count assertion also catches a
checker whose output wording changed, which is a way for this guard to go
blind that no exit code reports. And the two live at different levels: the
kit decides what an empty walk means to a checker, and this decides what a
zero-entry REPORT means to itaca, which would still be a silent pass if
some future caller here read the exit code alone.

As of kit 0.2.2 the companion resolves the checker as a sibling
(``Path(__file__).resolve().parent / "check_plan_kit.py"``) instead of
the old hardcoded coordination path, so it now proves the DEPLOYED copy
beside it, not the coordination master. That closes the coupling this
test previously had to disclose (routed item ITC-20260724-1715), which is
why the mutation companion can finally be wired as a tier-1 test here.
The deployed pair moved to kit 0.2.10 (checker) and 0.2.3 (companion) on
2026-07-30, together with their pins, and the companion still reports
``0 check(s) could not fail``.
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

    THREE outcomes, told apart, because they want three different fixes and
    the first version of this test conflated two of them. Once the kit
    refused the empty case, an empty ledger stopped printing a count line at
    all, so the "no count line" branch fired with the message "the output
    format changed" for a run where nothing had changed: a reader following
    it would have gone to re-read ``_entry_count`` while the real cause was
    a ledger with no entries in it. The checker's own refusal is therefore
    read first, and only an unexplained missing count is reported as drift.
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
    count = _entry_count(output)
    where = f"{ledger} (resolved by the {branch} branch), exit {done.returncode}"
    # 1. The checker itself said it could not verify. Since kit 0.2.10 that is
    #    what an empty walk looks like, and it prints no count line, so this
    #    must be read BEFORE the missing-count branch or an empty ledger is
    #    misreported as a wording change.
    assert not (done.returncode == 2 or "CANNOT VERIFY" in output), (
        f"the plan checker refused to verify the ledger at {where}. Since kit "
        f"0.2.10 that is what an EMPTY plan directory produces, so either the "
        f"resolved path is wrong or the ledger is genuinely empty; check "
        f"ITACA_MANAGEMENT_ROOT and that the tree is synced. Nothing was "
        f"validated (ITC-20260727-1612). Output: {output.strip()!r}"
    )
    # 2. No count line and no refusal: the wording this guard reads has moved.
    assert count is not None, (
        f"the plan checker's output carried no '<N> entries checked' line and "
        f"did not refuse either, so its entry count could not be read at all. "
        f"That means the checker's output format changed and this guard can no "
        f"longer see what it exists to see (ITC-20260727-1612). Re-read "
        f"check_plan_kit.py and update _entry_count. Ledger: {where}. "
        f"Output: {output.strip()!r}"
    )
    # 3. A count of zero reported as a SUCCESS, which is the original defect
    #    and remains itaca's own failure mode if a future checker regresses.
    assert count > 0, (
        f"the plan checker reported {count} entries for the ledger at {where}, "
        f"without refusing. A zero-entry report reads as a pass while nothing "
        f"was validated, which is ITC-20260727-1612 whatever the exit code "
        f"was. Either the resolved ledger path is wrong or the ledger is "
        f"genuinely empty; check ITACA_MANAGEMENT_ROOT. "
        f"Output: {output.strip()!r}"
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
        f"1 for a validation failure (the entries were read and some were bad) "
        f"and 2 for CANNOT VERIFY. An empty walk is the second. Output: "
        f"{output.strip()!r}"
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
    assert absent.returncode == 1, (
        f"a missing plan directory exited {absent.returncode}, where it has "
        f"always exited 1 with 'not a directory'. Output: "
        f"{(absent.stdout + absent.stderr).strip()!r}"
    )
