"""Keep the plan-ledger checker proven, the way the incident gate is.

Usage example (TDD anchor)::

    companion = _resolve_companion()  # from ITACA_PLAN_VALIDATOR
    assert companion is None or companion.name == "check_plan_kit_mutations.py"

The plan ledger is validated by the shared-kit checker ``check_plan_kit.py``
(Option C: the strict guards of the old ``check_plan_entries.py`` plus the
union vocabulary), resolved from the ``ITACA_PLAN_VALIDATOR`` environment
variable exactly as the incident checker is resolved from
``ITACA_INCIDENT_LEDGER``. A validator that cannot fail the case it exists
to catch manufactures confidence, so its mutation companion runs here.

Resolution mirrors the plan skill and the incident ledger philosophy:

- unset -> skip (a clone that never configured the validator still runs a
  green suite);
- set but the companion is unreadable -> a configuration error, so fail
  rather than pass silently.

Known coupling (registered, routed to the kit): the kit's
``check_plan_kit_mutations.py`` hardcodes the coordination master path for
the checker under test rather than resolving it as a sibling the way the
S3 mutation companion does. On the author's configured machine both paths
exist, so the companion runs against the same body it validates; the
sibling-resolution fix belongs in the kit and is re-vendored, never
hand-edited into this drift-pinned copy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

_COMPANION_NAME = "check_plan_kit_mutations.py"


def _resolve_companion() -> Path | None:
    """The mutation companion beside the configured plan validator, or None.

    ``ITACA_PLAN_VALIDATOR`` may name the checker file itself or the
    directory holding it; the companion sits beside the checker in either
    case. Returns None only when the variable is unset.
    """
    configured = os.environ.get("ITACA_PLAN_VALIDATOR")
    if not configured:
        return None
    target = Path(configured)
    directory = target.parent if target.suffix == ".py" else target
    return directory / _COMPANION_NAME


def test_the_plan_checker_can_still_fail() -> None:
    """Run the kit plan checker's mutation companion when it is configured."""
    companion = _resolve_companion()
    if companion is None:
        pytest.skip("ITACA_PLAN_VALIDATOR is unset; plan checker not configured here")
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
