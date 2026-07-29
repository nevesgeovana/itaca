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
  one still naming the retired ``check_plan_entries.py``) green the suite.

As of kit 0.2.2 the companion resolves the checker as a sibling
(``Path(__file__).resolve().parent / "check_plan_kit.py"``) instead of
the old hardcoded coordination path, so it now proves the DEPLOYED copy
beside it, not the coordination master. That closes the coupling this
test previously had to disclose (routed item ITC-20260724-1715), which is
why the mutation companion can finally be wired as a tier-1 test here.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from test_management_root import (  # the canonical resolver, not a second copy
    ManagementRootError,
    resolve_management_root,
)

_CHECKER_NAME = "check_plan_kit.py"
_COMPANION_NAME = "check_plan_kit_mutations.py"
_REPO = Path(__file__).resolve().parents[1]


def _ledger_dir() -> Path | None:
    """The resolved plan ledger, or None when no root is resolvable.

    Resolution goes through ``resolve_management_root``, the single home of
    the rule in CLAUDE.md, "Where the session documents live". Reusing it
    rather than re-deriving the root here is deliberate: a second copy of a
    resolution rule is how the two drift apart, and this file only needs the
    answer.
    """
    try:
        root, _branch = resolve_management_root(
            os.environ.get("ITACA_MANAGEMENT_ROOT"), repo=_REPO
        )
    except ManagementRootError:
        return None
    ledger = root / "plan"
    return ledger if ledger.is_dir() else None


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

    ``ITC-20260727-1612``. ``check_plan_kit.py`` exits ZERO on an empty
    ledger folder, printing ``no entries in <dir>``, while a MISSING folder
    is refused loudly with ``not a directory`` and exit 1. So the loud case
    is handled and the empty one is not, and a run pointed at the wrong path
    reports success.

    ``CLAUDE.md`` already tells the reader to read the entry count rather
    than the exit code. That is documentation, and this repository's own
    incident rule says documentation is not a guard. This test is that
    instruction expressed as a mechanism: whatever the exit code was, a
    report covering zero entries fails here.

    What this does NOT claim: it does not fix the checker. That file is a
    shared-kit artifact resolved through ``ITACA_PLAN_VALIDATOR`` and is not
    itaca's to edit, so the refusal itself is routed to the kit and pinned
    below. What itaca owns is its own CONSUMPTION of the checker, and that
    is exactly what is guarded here.
    """
    resolved = _resolve()
    if resolved is None:
        pytest.skip("ITACA_PLAN_VALIDATOR is unset; plan checker not configured here")
    checker, _ = resolved
    ledger = _ledger_dir()
    if ledger is None:
        pytest.skip(
            "no plan ledger is resolvable here; ITACA_MANAGEMENT_ROOT is unset "
            "and _private/plan is absent, so there is nothing to validate"
        )
    done = subprocess.run(
        [sys.executable, str(checker), str(ledger)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    output = done.stdout + done.stderr
    count = _entry_count(output)
    assert count is not None and count > 0, (
        f"the plan checker reported no entries for the ledger at {ledger}, and "
        f"exited {done.returncode}. An empty ledger folder exits ZERO, so this "
        f"reads as a pass while nothing was validated (ITC-20260727-1612). "
        f"Either the resolved ledger path is wrong or the ledger is empty; "
        f"check ITACA_MANAGEMENT_ROOT. Checker output: {output.strip()!r}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="ITC-20260727-1612: the kit checker exits 0 on an empty ledger folder",
)
def test_the_plan_checker_refuses_an_empty_ledger_folder(tmp_path: Path) -> None:
    """The kit-side half of ``ITC-20260727-1612``, pinned as a ratchet.

    The desired behavior is that an empty ledger folder is refused, either
    outright or unless an explicit ``--allow-empty`` is passed for the
    genuine first-run case. It is not refused today, which is why this is
    marked. The marker is the ratchet: the moment the kit is fixed and
    re-vendored, this passes, strict xfail turns that into a failure, and
    whoever fixed it must come here and remove the marker.

    Recorded this way rather than in prose because the checker is reached
    through an environment variable and its defect is therefore invisible to
    this repository's suite unless something asserts it.
    """
    resolved = _resolve()
    if resolved is None:
        pytest.skip("ITACA_PLAN_VALIDATOR is unset; plan checker not configured here")
    checker, _ = resolved
    empty = tmp_path / "plan"
    empty.mkdir()
    done = subprocess.run(
        [sys.executable, str(checker), str(empty)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode != 0, (
        f"an empty ledger folder exited {done.returncode}, so a run against the "
        f"wrong path looks like a pass. Output: "
        f"{(done.stdout + done.stderr).strip()!r}"
    )
