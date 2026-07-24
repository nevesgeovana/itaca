"""Tier-1 drift guard: vendored process-kit copies match the pinned manifest.

Usage example (TDD anchor)::

    body = _kit_body(Path(".claude/hooks/role_review_gate.py").read_text())
    assert _sha256(body) == MANIFEST["role_review_gate.py"].body_sha256

The shared process kit (canonical masters at the coordination level) is
vendored into this repository as derived copies. A copy carries a
provenance header, a line ``END KIT PROVENANCE``, and then the artifact
body verbatim. This test recomputes each vendored body's sha256 and
asserts it equals the value this repository pinned when it vendored the
kit. A hand-edit of a committed vendored copy changes its body, the
recomputed hash no longer matches, and CI goes red: the committed copies
cannot silently diverge from the kit again. The env-located shared tools
are checked only when their variable is set (see below), so in a clone
that never configured them they are not drift-guarded in ordinary CI.

The fixture is the manifest (kit ``README.md``), inlined here so the test
needs no cross-repo filesystem access and cannot deadlock a push. itaca
tracks kit 0.2.2: ``role_review_gate.py`` (the ``\\x01`` heredoc-byte fix
plus the deny-message taxonomy), both S3 side-effect-guard artifacts, and
both kit plan-checker artifacts are at 0.2.2; ``write_attestation.py``,
``incident-analyst.md``, ``check_incidents.py`` and ``snap.sh`` are
unchanged and stay at 0.1.0. A MIXED manifest (per-file body hashes and
versions, not one kit-wide hash) is expected and correct. The vendored
copies carry a per-copy ``note:`` line ("derived copy ..."); the header,
including that line, is not hashed, so restamping it does not affect the
body sha256.

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


# The kit README 0.2.2 manifest, inlined as the fixture (per-file
# versions: mixed 0.2.2 and 0.1.0 is correct).
MANIFEST: dict[str, Pin] = {
    "role_review_gate.py": Pin(
        "762297b3d7752710aa6146719e8c4540b6b05bbf851f71f5a66105b9db58134e", "0.2.2"
    ),
    "write_attestation.py": Pin(
        "0c6aa3f9bc7e68aadb921463371b0f4a30a3f4bd9da9f1e3915bc48e8f243a91", "0.1.0"
    ),
    "incident-analyst.md": Pin(
        "9d2bc1bb38d6c249969cb268ce6e9b778457059d691a87cecda172f83f475eac", "0.1.0"
    ),
    "check_side_effect_guard.py": Pin(
        "ba9007941dcc44887e31d70dc74be8efe409f51a249d2b79398e66c276e9810c", "0.2.2"
    ),
    "check_side_effect_guard_mutations.py": Pin(
        "af5674911c06e5c67c5a178374c6c79245be25c8e9d1eb742667fc2f4bd8decb", "0.2.2"
    ),
    "check_incidents.py": Pin(
        "f6d3430a6d0ee44b4843f7d297a3454ce40d34cd83dc182a2ef840952c5c9c0a", "0.1.0"
    ),
    "snap.sh": Pin(
        "0da13e4da525c1c470dc4429ef6c557a3b74600ad817c534344e999180786383", "0.1.0"
    ),
    "check_plan_kit.py": Pin(
        "d7b7126a83ad96196c5a063d3b6d6c771747af84e590a9c97a3d702b057b9e52", "0.2.2"
    ),
    "check_plan_kit_mutations.py": Pin(
        "cef4d90a31b11e8642f78ed47a4fad20c3f5c1a6e33dd36e6ddb60dc7390c4aa", "0.2.2"
    ),
}

# Committed vendored copies: (manifest key, repo-relative path).
COMMITTED: list[tuple[str, str]] = [
    ("role_review_gate.py", ".claude/hooks/role_review_gate.py"),
    ("write_attestation.py", ".claude/hooks/write_attestation.py"),
    ("incident-analyst.md", ".claude/kit/incident-analyst.md"),
    ("check_side_effect_guard.py", ".claude/kit/check_side_effect_guard.py"),
    (
        "check_side_effect_guard_mutations.py",
        ".claude/kit/check_side_effect_guard_mutations.py",
    ),
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
    """(manifest key, path) for shared tools that MUST exist when configured.

    Skipped entirely when neither variable is configured, mirroring the
    incident gate: a clone that never set them still runs a green suite.
    Each tool is located by its OWN variable: the incident checker by
    ITACA_INCIDENT_LEDGER, the plan checker (and its companion) by
    ITACA_PLAN_VALIDATOR. snap.sh is deliberately NOT here: it has no
    locator variable of its own, so binding it to the plan-validator
    directory would be a false coupling (a correctly configured plan
    validator whose directory happens not to hold snap.sh would fail a
    check that is not about the plan validator). It is drift-checked
    best-effort by ``_snap_if_present`` instead, and a locator variable for
    it is a registered kit item.
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
        located.append(("check_plan_kit.py", directory / "check_plan_kit.py"))
        located.append(
            ("check_plan_kit_mutations.py", directory / "check_plan_kit_mutations.py")
        )
    return located


def _snap_if_present() -> tuple[str, Path] | None:
    """snap.sh beside the plan validator, only if it is actually there.

    Best-effort: snap.sh has no locator of its own, so it is checked where
    it happens to sit and never asserted-present, which keeps a false
    coupling to ITACA_PLAN_VALIDATOR from reddening a correct config.
    """
    validator = os.environ.get("ITACA_PLAN_VALIDATOR")
    if not validator:
        return None
    target = Path(validator)
    directory = target.parent if target.suffix == ".py" else target
    snap = directory / "snap.sh"
    return ("snap.sh", snap) if snap.is_file() else None


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


def test_snap_script_matches_the_manifest_where_it_is_deployed() -> None:
    """Drift-check snap.sh best-effort; it has no locator of its own."""
    found = _snap_if_present()
    if found is None:
        pytest.skip("snap.sh is not present beside a configured plan validator")
    key, path = found
    _assert_matches_manifest(key, path)


def test_no_unpinned_python_hides_in_the_vendored_dirs() -> None:
    """A new .py under a vendored dir must be a pinned copy, or it escapes both.

    ``.claude/hooks`` and ``.claude/kit`` are excluded from ruff because
    everything in them is a drift-pinned vendored copy, and COMMITTED is a
    fixed list, not a glob. So a future .py dropped there would be neither
    linted nor drift-checked. Pin that every .py under them is a committed
    manifest entry, closing that gap before it opens.
    """
    committed = {(_ROOT / rel).resolve() for _, rel in COMMITTED}
    for vendored_dir in (".claude/hooks", ".claude/kit"):
        for py in (_ROOT / vendored_dir).glob("*.py"):
            assert py.resolve() in committed, (
                f"{py} is under a ruff-excluded vendored directory but is not a "
                f"pinned COMMITTED kit copy; add it to the manifest and the "
                f"drift test, or it is neither linted nor drift-checked."
            )
