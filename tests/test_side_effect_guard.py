"""Tier-1 wiring of the S3 side-effecting-skill guard (shared kit artifact).

Usage example (TDD anchor)::

    offenders = audit(Path(".claude/skills"))
    assert offenders == []  # no side-effecting skill is model-invocable

The guard is the structural replacement for a hardcoded side-effect
allowlist an allowlist cannot fail on a NEW side-effecting skill. A skill
declares its own side effects in frontmatter and the guard enforces the
implication: ``side-effects:`` present -> ``disable-model-invocation:
true``. The justification lives with the skill and cannot drift from a
second copy.

Two things are pinned here:

- the live guard: running it over this repository's ``.claude/skills``
  must report no offender (exit 0); and
- the guard itself: its mutation companion must pass, so a guard that
  silently stopped failing is caught here rather than in production.

itaca currently declares no side-effecting skill. All four skills (audit,
handoff, plan, role-review) are model-invocable by design: none publishes
a tag, spends a licensed run, or bumps a version, and role-review in
particular MUST stay model-invocable because the development rules have
the model invoke it to close a work item and write the push attestation.
So the guard runs green today with zero declarations; its value is
forward-looking, and the mutation companion proves it fires the moment a
future side-effecting skill forgets the human-only flag.

The guard and its mutation companion are vendored kit copies under
``.claude/kit``; ``tests/test_kit_drift.py`` pins their bodies to the kit
manifest. Both are exercised as subprocesses through ``child_env`` so a
child never starts coverage (see tests/conftest.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    assert _GUARD_MUTATIONS.is_file(), f"S3 mutation companion missing at {_GUARD_MUTATIONS}"
    assert _SKILLS.is_dir(), f"skills tree missing at {_SKILLS}"


def test_no_side_effecting_skill_is_model_invocable() -> None:
    """The live guard over this repository's skills must report no offender."""
    done = subprocess.run(
        [sys.executable, str(_GUARD), str(_SKILLS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_side_effect_guard_can_still_fail() -> None:
    """The mutation companion proves the guard rejects an unguarded skill.

    A guard that cannot fail the case it exists to catch manufactures
    confidence. The companion builds skills under the OS temp dir (never
    under _private) and requires the guard to refuse a side-effecting
    skill that is not human-only, and to pass one that is.
    """
    done = subprocess.run(
        [sys.executable, str(_GUARD_MUTATIONS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr
