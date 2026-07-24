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
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

_CHECKER_NAME = "check_plan_kit.py"
_COMPANION_NAME = "check_plan_kit_mutations.py"


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
