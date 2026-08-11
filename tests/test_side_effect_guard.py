"""Tier-1 wiring of the S3 skill-declaration guard (shared kit artifact).

Usage example (TDD anchor)::

    offenders = audit(Path(".claude/skills"))
    assert offenders == []  # every skill declares what it changes

The guard is the structural replacement for a hardcoded side-effect
allowlist: an allowlist cannot fail on a NEW side-effecting skill. A skill
declares its own side effects in its frontmatter, so the justification
lives with the skill and cannot drift from a second copy.

WHAT IT ASSERTS CHANGED AT KIT 0.2.19, and this file's docstring is
rewritten rather than amended because the old text stated the retired rule
as fact and named skills by a property they no longer carry. Until 0.2.18
the guard enforced an IMPLICATION, ``side-effects:`` present therefore
``disable-model-invocation: true``. The author RETIRED that implication on
2026-08-11, for all skills and with no exception, on the ground that the
verification stages downstream carry the safety level she requires for
more autonomy; the objection was put to her before she decided and is
recorded in ``BRF-079``. This repository APPLIES that decision and does not
weigh it. What the guard asserts now is that every ``*/SKILL.md`` CARRIES a
``side-effects:`` field, with ``none`` a valid answer and SILENCE the thing
refused.

That is strictly less in one direction and strictly more in another, which
is why the live run below is not weaker than it was. Under the implication
form the cheapest way past this guard was to declare nothing at all, and
one of this repository's six skills sat in exactly that hole: the deployed
``version-control/SKILL.md`` was the stamped kit copy, so its frontmatter
started on line 11 and the guard read it as declaring nothing. The 0.2.19
body found it (``5 declaring, 1 undeclared``, exit 1) and the 0.2.2 body
never could. It is fixed by ``tests/test_kit_drift.py``'s
``test_the_runtime_skill_body_matches_the_of_record_copy``, which keeps the
stamp beside the kit and the frontmatter on line 1.

All six skills declare today: five name what they write and
``version-control`` names ``none``. So the live run exercises the rule on
six files rather than passing over them.

Two things are pinned here:

- the live guard: running it over this repository's ``.claude/skills``
  must report no offender (exit 0); and
- the guard itself: its mutation companion must pass, so a guard that
  silently stopped failing is caught here rather than in production.

The guard and its mutation companion are vendored kit copies under
``.claude/kit``; ``tests/test_kit_drift.py`` pins their bodies to the kit
manifest. Both are exercised as subprocesses through ``child_env`` so a
child never starts coverage (see tests/conftest.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

_ROOT = Path(__file__).resolve().parents[1]
_SKILLS = _ROOT / ".claude" / "skills"
_GUARD = _ROOT / ".claude" / "kit" / "check_side_effect_guard.py"
_GUARD_MUTATIONS = _ROOT / ".claude" / "kit" / "check_side_effect_guard_mutations.py"


def test_the_guard_and_its_skills_are_present() -> None:
    """A guard loaded by path fails loudly if it or its target is missing.

    Without this a rename would silently remove the whole check and the
    suite would still report green, which is the self-skipping evidence
    the kit exists to replace.
    """
    assert _GUARD.is_file(), f"S3 guard missing at {_GUARD}"
    assert _GUARD_MUTATIONS.is_file(), (
        f"S3 mutation companion missing at {_GUARD_MUTATIONS}"
    )
    assert _SKILLS.is_dir(), f"skills tree missing at {_SKILLS}"


def test_the_guard_actually_has_skills_to_check() -> None:
    """A clean guard run must not mean it silently checked nothing.

    The guard globs ``*/SKILL.md`` and exits 0 when it finds no offender,
    which is also what it does when it finds no skills at all. So pin that
    this repository's skills tree is non-empty; otherwise "no offender"
    below would be a vacuous pass on an empty or mis-pointed directory.
    """
    skills = sorted(_SKILLS.glob("*/SKILL.md"))
    assert skills, f"no */SKILL.md under {_SKILLS}; the guard would pass vacuously"


def test_every_skill_declares_what_it_changes() -> None:
    """The live guard over this repository's skills must report no offender.

    Renamed with the 0.2.19 adoption: the old name
    (``test_no_side_effecting_skill_is_model_invocable``) asserted the
    retired implication in the one place a reader looks first, and it would
    have gone on describing a property no skill in this tree carries.
    """
    done = subprocess.run(
        [sys.executable, str(_GUARD), str(_SKILLS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.guardproof
def test_the_side_effect_guard_can_still_fail() -> None:
    """The mutation companion proves the guard rejects an undeclared skill.

    A guard that cannot fail the case it exists to catch manufactures
    confidence. The companion builds skills under the OS temp dir (never
    under _private) and, since kit 0.2.19, requires the guard to refuse a
    skill that declares nothing and to pass one that declares, including
    one that declares ``none``.
    """
    done = subprocess.run(
        [sys.executable, str(_GUARD_MUTATIONS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr
