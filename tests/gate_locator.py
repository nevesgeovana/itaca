"""The ledger variable the vendored push gate resolves, read from the gate.

One fact, one reader. Two test modules need the name the gate assigns to
``LEDGER_ENV``, and each had grown its own regex: ``test_push_gate.py``
anchored with ``re.MULTILINE``, ``test_house_style.py`` unanchored. They agree
today and would stop agreeing the moment a kit body mentioned the retired name
in an indented comment, at which point the unanchored one would match the
comment and the house-style guard's own failure message would prescribe
renaming the locator table to match a commented-out literal, introducing the
misconfiguration it reports. That is the class ``INC-20260724-0410-shared``
names, arriving through a guard rather than through a reviewer.

Extracted to a plain helper module rather than imported from a test module for
the reason ``tests/management_root.py`` and ``tests/identifiers.py`` were: a
test module imported as a library makes another module's NAME part of the
suite's internal API.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
GATE = _ROOT / ".claude" / "hooks" / "role_review_gate.py"
#: Anchored to the start of a line, so an indented or in-comment mention of a
#: variable name is not mistaken for the assignment.
_ASSIGNMENT = re.compile(r'^LEDGER_ENV = "([A-Z_]+)"', re.MULTILINE)


def ledger_env(gate: Path | None = None) -> str:
    """The variable the gate resolves the shared incident ledger from.

    Raises
    ------
    AssertionError
        If the assignment cannot be read, or if there is more than one. The
        second case is not hypothetical: the per-target ``LEDGER_ENV_BY_REPO``
        map that kit 0.2.8 retired is exactly the shape that reintroduces a
        second assignment, and ``re.search`` would silently take the first
        while the module takes the last. A suite that resolved the wrong name
        would export a variable the gate does not read, and every case would
        then inherit the machine's real ledger.
    """
    source = (gate or GATE).read_text(encoding="utf-8")
    found = _ASSIGNMENT.findall(source)
    assert len(found) == 1, (
        f"expected exactly one line-anchored LEDGER_ENV assignment in "
        f"{gate or GATE}, found {len(found)}: {found}. Two assignments must be "
        f"resolved by hand: the gate takes the LAST and a naive reader takes "
        f"the first, so the suite would export a variable the gate does not "
        f"read and every case would fall back to the real ledger."
    )
    return str(found[0])
