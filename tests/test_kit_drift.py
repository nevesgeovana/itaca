"""Tier-1 drift guard: vendored process-kit copies match the pinned manifest.

Usage example (TDD anchor)::

    body = _kit_body(Path(".claude/hooks/role_review_gate.py").read_text())
    assert _sha256(body) == MANIFEST["role_review_gate.py"].body_sha256

The shared process kit (canonical masters at the coordination level) is
vendored into this repository as derived copies. A copy carries a
provenance header, a line ``END KIT PROVENANCE``, and then the artifact
body verbatim. This test recomputes each vendored body's sha256 and
asserts it equals the value this repository pinned when it vendored
kit-version 0.2.0. A hand-edit of any vendored copy changes its body, the
recomputed hash no longer matches, and CI goes red: the copies cannot
silently diverge from the kit again.

The fixture is the manifest (kit ``README.md`` 0.2.0), inlined here so the
test needs no cross-repo filesystem access and cannot deadlock a push. The
0.1.0 -> 0.2.0 promotion changed only ``role_review_gate.py`` and added
the two S3 side-effect-guard artifacts; every other body keeps its 0.1.0
hash, so a MIXED manifest (per-file body hashes, not one kit-wide hash) is
expected and correct.

Two vendoring shapes are covered:

- committed copies (the hooks, the of-record agent charter, the S3 guard
  under ``.claude/kit``) are always present and always checked; and
- shared tools located by an environment variable (the incident checker,
  the ``_private`` snapshot script, the kit plan checker) are checked when
  configured and skipped when not, exactly as the incident gate skips an
  unset ledger, so a clone with no configuration still runs a green suite.

The ``.md`` charter closes its provenance with an HTML ``-->`` after the
marker line; that delimiter is part of the header, not the body, so it is
dropped before hashing (the declared body-sha256 is computed that way).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MARKER = "END KIT PROVENANCE"


@dataclass(frozen=True)
class Pin:
    """The manifest entry a vendored copy must reproduce."""

    body_sha256: str
    kit_version: str


# The kit README 0.2.0 manifest, inlined as the fixture.
MANIFEST: dict[str, Pin] = {
    "role_review_gate.py": Pin(
        "0f1063f5d684e3065fb6864d67e8b933420660088287a5ab1fbf529aaba8de30", "0.2.0"
    ),
    "write_attestation.py": Pin(
        "0c6aa3f9bc7e68aadb921463371b0f4a30a3f4bd9da9f1e3915bc48e8f243a91", "0.1.0"
    ),
    "incident-analyst.md": Pin(
        "9d2bc1bb38d6c249969cb268ce6e9b778457059d691a87cecda172f83f475eac", "0.1.0"
    ),
    "check_side_effect_guard.py": Pin(
        "f11972715660cdcda4fd06cd29925276369878eedafefb007e3cbafaf64d3456", "0.2.0"
    ),
    "check_side_effect_guard_mutations.py": Pin(
        "fc5e7fdabd50a7784e53f0e8a636e87ff19e19260c9a711fb05892f78c1ad97f", "0.2.0"
    ),
    "check_incidents.py": Pin(
        "f6d3430a6d0ee44b4843f7d297a3454ce40d34cd83dc182a2ef840952c5c9c0a", "0.1.0"
    ),
    "snap.sh": Pin(
        "0da13e4da525c1c470dc4429ef6c557a3b74600ad817c534344e999180786383", "0.1.0"
    ),
    "check_plan_kit.py": Pin(
        "4a18d1aa061b92c7fc677c16479730b25cdd6b759625857d4c1720628a5415a6", "0.1.0"
    ),
    "check_plan_kit_mutations.py": Pin(
        "e434e5be6e3c796ab297b0d110e37b58aa213b8199b77367db134f51ed77ed2f", "0.1.0"
    ),
}

# Committed vendored copies: (manifest key, repo-relative path).
COMMITTED: list[tuple[str, str]] = [
    ("role_review_gate.py", ".claude/hooks/role_review_gate.py"),
    ("write_attestation.py", ".claude/hooks/write_attestation.py"),
    ("incident-analyst.md", ".claude/kit/incident-analyst.md"),
    ("check_side_effect_guard.py", ".claude/kit/check_side_effect_guard.py"),
    ("check_side_effect_guard_mutations.py", ".claude/kit/check_side_effect_guard_mutations.py"),
]


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _kit_body(text: str) -> str:
    """The bytes-as-text the body-sha256 is computed over.

    For a stamped copy: everything after the ``END KIT PROVENANCE`` line.
    For an ``.md`` HTML-comment header, the closing ``-->`` line that
    follows the marker belongs to the header, not the body, and is
    dropped. For an unstamped shared tool deployed raw (no marker), the
    whole file is the body.
    """
    norm = _normalize(text)
    if _MARKER not in norm:
        return norm
    after = norm.split(_MARKER, 1)[1]
    after = after.split("\n", 1)[1] if "\n" in after else ""
    if after.startswith("-->\n"):
        after = after[len("-->\n") :]
    elif after == "-->":
        after = ""
    return after


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _header_fields(text: str) -> dict[str, str]:
    """The provenance header's ``key: value`` fields, or empty if unstamped.

    Works for both comment syntaxes: ``# key: value`` for ``.py``/``.sh``
    and bare ``key: value`` inside the ``.md`` HTML comment. Only the lines
    before the marker are read.
    """
    norm = _normalize(text)
    if _MARKER not in norm:
        return {}
    fields: dict[str, str] = {}
    for line in norm.split(_MARKER, 1)[0].splitlines():
        stripped = line.lstrip("#").strip()
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            fields[key.strip().lower()] = value.strip()
    return fields


def _assert_matches_manifest(key: str, path: Path) -> None:
    """The load-bearing check: body hash, and header fields when stamped."""
    pin = MANIFEST[key]
    text = path.read_text(encoding="utf-8")
    computed = _sha256(_kit_body(text))
    assert computed == pin.body_sha256, (
        f"{path} body sha256 {computed} != pinned {pin.body_sha256}. The "
        f"vendored copy has drifted from kit {key}; re-vendor from the kit, "
        f"do not hand-edit the copy."
    )
    header = _header_fields(text)
    if header:
        # A stamped copy must also carry a header consistent with the
        # manifest, so an edit that fixes the body but not the header (or
        # vice versa) still fails.
        assert header.get("body-sha256") == pin.body_sha256, (
            f"{path} header body-sha256 {header.get('body-sha256')} != pinned "
            f"{pin.body_sha256}"
        )
        assert header.get("kit-version") == pin.kit_version, (
            f"{path} header kit-version {header.get('kit-version')} != pinned "
            f"{pin.kit_version}"
        )


@pytest.mark.parametrize("key,rel", COMMITTED, ids=[k for k, _ in COMMITTED])
def test_a_committed_kit_copy_matches_the_manifest(key: str, rel: str) -> None:
    """Every committed vendored copy reproduces its pinned body hash."""
    path = _ROOT / rel
    assert path.is_file(), f"vendored kit copy missing at {path}"
    _assert_matches_manifest(key, path)


def test_the_runtime_agent_body_matches_the_of_record_copy() -> None:
    """The loaded agent must not drift from its stamped drift-of-record copy.

    The runtime ``.claude/agents/incident-analyst.md`` carries no header
    so its loader sees frontmatter on line 1; the stamped copy under
    ``.claude/kit`` is what the manifest check above reads. This ties the
    two together so the runtime cannot be edited without the drift test
    catching it.
    """
    runtime = _ROOT / ".claude" / "agents" / "incident-analyst.md"
    of_record = _ROOT / ".claude" / "kit" / "incident-analyst.md"
    assert runtime.is_file() and of_record.is_file()
    runtime_body = _normalize(runtime.read_text(encoding="utf-8"))
    of_record_body = _kit_body(of_record.read_text(encoding="utf-8"))
    assert runtime_body == of_record_body
    assert _sha256(runtime_body) == MANIFEST["incident-analyst.md"].body_sha256


def _env_located() -> list[tuple[str, Path]]:
    """(manifest key, path) for shared tools resolved from env vars.

    Skipped entirely when neither variable is configured, mirroring the
    incident gate: a clone that never set them still runs a green suite.
    """
    located: list[tuple[str, Path]] = []
    ledger = os.environ.get("ITACA_INCIDENT_LEDGER")
    if ledger:
        base = Path(ledger)
        checker = base if base.suffix == ".py" else base / "check_incidents.py"
        located.append(("check_incidents.py", checker))
    validator = os.environ.get("ITACA_PLAN_VALIDATOR")
    if validator:
        target = Path(validator)
        directory = target.parent if target.suffix == ".py" else target
        located.append(("snap.sh", directory / "snap.sh"))
        located.append(("check_plan_kit.py", directory / "check_plan_kit.py"))
        located.append(
            ("check_plan_kit_mutations.py", directory / "check_plan_kit_mutations.py")
        )
    return located


def test_env_located_shared_tools_match_the_manifest() -> None:
    """Check the env-located shared tools against the manifest when configured."""
    located = _env_located()
    if not located:
        pytest.skip(
            "neither ITACA_INCIDENT_LEDGER nor ITACA_PLAN_VALIDATOR is set; "
            "env-located kit tools are not configured here"
        )
    for key, path in located:
        assert path.is_file(), (
            f"{key} is configured but missing at {path}. A set-but-unreachable "
            f"shared tool is a configuration error, not a clean skip."
        )
        _assert_matches_manifest(key, path)
