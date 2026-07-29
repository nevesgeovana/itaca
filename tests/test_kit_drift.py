"""Tier-1 drift guard: vendored process-kit copies match the pinned manifest.

Usage example (TDD anchor)::

    text = (_ROOT / ".claude/hooks/role_review_gate.py").read_text(
        encoding="utf-8"
    )
    assert _sha256(_kit_body(text)) == MANIFEST["role_review_gate.py"].body_sha256

The shared process kit (canonical masters at the coordination level) is
vendored into this repository as derived copies. A copy carries a
provenance header, a line ``END KIT PROVENANCE``, and then the artifact
body verbatim. This test recomputes each vendored body's sha256 and
asserts it equals the value this repository pinned when it vendored the
kit.

What that does and does not prove, stated exactly, because the strong
form of the claim is false and a counterexample sits in this very file.
It proves a committed copy cannot be silently HAND-EDITED: the body
changes, the recomputed hash stops matching, and CI goes red. It does
NOT prove a copy is CURRENT with the kit, because the manifest below is
an inlined frozen copy rather than a live read of the master. A
repository that has fallen behind stays green until someone moves a pin,
which is exactly the state of the two plan-checker entries described
below. The env-located shared tools are checked only when their variable
is set (see below), so in a clone that never configured them they are not
drift-guarded in ordinary CI.

The fixture is the manifest (kit ``README.md``), inlined here so the test
needs no cross-repo filesystem access and cannot deadlock a push. A MIXED
manifest (per-file body hashes and versions, not one kit-wide hash) is
expected and correct, and the pins below are per file:

- 0.2.6, the release-integrity promotion: ``role_review_gate.py`` and
  ``write_attestation.py`` re-vendored, plus five NEW artifacts. The
  vocabulary change is the whole of it for the two existing bodies:
  ``write_attestation.py`` gains ``numerical-analyst`` and
  ``integration-reviewer`` in ``KNOWN_PASSES``, and the gate's deny
  message names the two new lenses. No control flow moved and no allow
  or deny decision changed. Read that for what it is: a recordable pass
  is still not a REQUIRED pass, and the gate still never reads the
  ``passes`` field. What changed is that the honest answer became
  expressible.
- 0.2.5: ``snap.sh`` alone, the false-success defect this repository
  found and routed up. 0.2.5 was closed rather than extended, so it
  keeps its own label while everything promoted beside it is 0.2.6;
  the label is already cited by name in plan entry
  ``ITC-20260728-2010`` and a label whose contents change after it is
  cited makes the citation say something it no longer means.
- 0.2.4: ``incident-analyst.md``, from the privacy promotion.
- 0.2.2: both side-effect-guard artifacts, and both kit plan-checker
  artifacts. The plan-checker pair is a KNOWN LAG: the kit is at 0.2.3
  for those two (adoption-review hardening), and itaca still pins and
  runs 0.2.2. Re-vendoring them is separate work, out of scope for the
  release-integrity promotion.
- 0.1.0: ``check_incidents.py``, unchanged.

The rule that decides both of those, stated once so the asymmetry is not
mistaken for an oversight: a pin for an artifact deployed OUTSIDE this
repository moves only together with the deployed copy it names. The
``snap.sh`` pin moved to 0.2.5 because the deployed copy already
carries that body: it was written when the defect was fixed, and this
repository's pin was the half left behind, which is why the suite at
``0d0dadd`` was red on exactly this one test before the pin moved. The
plan-checker pins did not move because
their deployed copies were not, and moving them alone would redden this
suite for a change made elsewhere. A reader who repoints
``ITACA_PLAN_VALIDATOR`` at a directory holding a different kit version
will see this suite fail; that is configuration, not drift, and the
remedy the failure message suggests (re-vendor) is the wrong one for it.

The vendored copies carry a per-copy ``note:`` line ("derived copy ...");
the header, including that line, is not hashed, so restamping it does not
affect the body sha256.

Two vendoring shapes are covered:

- committed copies (the hooks, the of-record agent charter, the two
  side-effect-guard artifacts under ``.claude/kit``) are always present,
  always checked, and are additionally required to still CARRY their
  provenance stamp, so that deleting the header cannot quietly downgrade
  a stamped-copy check into a hash-only one; and
- shared tools located by an environment variable (the incident checker
  and the kit plan checker) are checked when configured and skipped when
  not, exactly as the incident gate skips an unset ledger, so a clone
  with no configuration still runs a green suite. These may legitimately
  be deployed raw, so the stamp requirement above is not applied to them.

``snap.sh``, the snapshot script for the ``_private`` trees, has no
locator variable of its own, so it is drift-checked best-effort where it
happens to sit beside a configured plan validator (``_snap_if_present``)
rather than through the env-located path above. One consequence worth
naming rather than discovering: CI sets neither locator, so this pin is
NOT exercised there. The 0.2.4 body's false-success defect, in which an
unset ``COORD_SHARED_LEDGER_TREE`` reported a snapshot it did not take
instead of skipping, is fixed in the 0.2.5 body pinned below and was
registered by the sister repository as
``PLN-20260728-1615-snap-shared-tree-false-success``.

One vendored artifact lives OUTSIDE the two ``.claude`` directories:
``release_gate.yml`` is a reusable GitHub workflow and must sit under
``.github/workflows/`` to be callable at all. It is pinned like any
other copy, and ``test_no_unpinned_artifact_hides_in_the_vendored_dirs``
was widened for it on two counts, because it would otherwise have
escaped on both: the directory is not swept, and ``.yml`` was not in the
suffix list. The widening for that directory is deliberately
marker-based rather than suffix-based, since ``ci.yml`` and
``release.yml`` are this repository's own files and pinning them would
be false.

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


# The kit README manifest, inlined as the fixture, with two DELIBERATE
# deviations marked in place below (per-file versions: a mix of 0.2.4,
# 0.2.2 and 0.1.0 is correct; see the module docstring). This is not a
# verbatim copy of the manifest of record and must not be resynced from
# it wholesale.
MANIFEST: dict[str, Pin] = {
    "role_review_gate.py": Pin(
        "889b8647b704394b28b48a87b473cacdc02d0222ee458e754c47726c8f7e5585", "0.2.6"
    ),
    # 0.2.9, the INC-20260729-2355 guard: the attestation refuses while
    # TRACKED files carry uncommitted changes, and reports untracked paths
    # instead of refusing on them. RECOMPUTED from the master body with
    # `_kit_body`/`_normalize` from this file, not copied from the
    # master's declared value, which is STALE: the master's header
    # declares kit-version 0.2.9 beside the 0.2.6 body-sha256. That
    # mismatch is a defect in the master's header and is routed to the
    # coordination level; the body itself is the 0.2.9 guard and hashes
    # as pinned here. The recompute-not-copy rule is the same one the
    # 0.2.7 entries below already record.
    "write_attestation.py": Pin(
        "9d62d8a32c7aba156deade505a05759e26e9d7c72f87bf0ac5632f4ce17afa28", "0.2.9"
    ),
    "release_gate.yml": Pin(
        "f8e0262a1f9ada6220afd9bee1bf488e030e827fd2b3dc4d90bea684a4607a10", "0.2.7"
    ),
    # 0.2.7, the HUB-6 promotion. Two of the three guards
    # INC-20260729-0854-shared needs, plus the review policy they are
    # stated in. Every hash below was RECOMPUTED from the master with
    # `_kit_body`/`_normalize` from this file, not copied from the kit
    # README: the lane brief refuses the manifest as a source because the
    # two shipped-surface bodies changed three times during the
    # promotion. The recomputation agreed with all nineteen declared
    # entries, which is the check having been run, not skipped.
    "check_shipped_surface.py": Pin(
        "6fbbdbce007e8acff486f8fc28cd23d3e0f81023d808d70cd7fe13ce91a6d4ba", "0.2.7"
    ),
    "check_shipped_surface_mutations.py": Pin(
        "517fa0746254857ab5ce7319e3010aa87cd0a15ebfaa3ee5b32a6570391bf3b8", "0.2.7"
    ),
    "check_probe_closure.py": Pin(
        "5b4a76ea8e94d6185cd200d0f0324e6501967d1d959c94e5a0e0f31019c142a2", "0.2.7"
    ),
    "check_probe_closure_mutations.py": Pin(
        "59f3f3c120d7b834bae78b047b2e76d638952a4fb749783b78caba9214767b9c", "0.2.7"
    ),
    "review-policy.md": Pin(
        "d3845ed17ef14d013ee2ffc8350f61bf0c0f585f63fc93c19e172d0a8afbd561", "0.2.7"
    ),
    "check_release_gate.py": Pin(
        "a0ef06b1aa031245e0354eadfbe120e69e38515ce3184eb2ea0b1d68adf34eb3", "0.2.6"
    ),
    "check_release_gate_mutations.py": Pin(
        "897ace78c3d664b3de16f6a3947df746e9ab79d3916e448a61f499eef830d134", "0.2.6"
    ),
    "check_version_identity.py": Pin(
        "d9fd719a92bc82cd8c81ab60888bcae4eeed320af89bced74b2602350afe68bd", "0.2.6"
    ),
    "check_version_identity_mutations.py": Pin(
        "49f0dd3c2dd3ef257761ecbac32c5c0d3f56937f5d735080040843f6aeebf58a", "0.2.6"
    ),
    "incident-analyst.md": Pin(
        "891fa0bce811aade6fe58494d99db2f048987871cf5487fda77d9ff180ef7beb", "0.2.4"
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
        "0835e6ae1bd43d05e213a88552bcd94a1b91ebec946f9dabb5411d7595b265d1", "0.2.5"
    ),
    # KNOWN LAG, deliberate: the kit is at 0.2.3 for these two. Do NOT sync
    # them from the manifest of record without also moving the deployed
    # copies these pins name; see the module docstring.
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
    ("check_release_gate.py", ".claude/kit/check_release_gate.py"),
    (
        "check_release_gate_mutations.py",
        ".claude/kit/check_release_gate_mutations.py",
    ),
    ("check_version_identity.py", ".claude/kit/check_version_identity.py"),
    (
        "check_version_identity_mutations.py",
        ".claude/kit/check_version_identity_mutations.py",
    ),
    ("release_gate.yml", ".github/workflows/release_gate.yml"),
    ("check_shipped_surface.py", ".claude/kit/check_shipped_surface.py"),
    (
        "check_shipped_surface_mutations.py",
        ".claude/kit/check_shipped_surface_mutations.py",
    ),
    ("check_probe_closure.py", ".claude/kit/check_probe_closure.py"),
    (
        "check_probe_closure_mutations.py",
        ".claude/kit/check_probe_closure_mutations.py",
    ),
    ("review-policy.md", ".claude/kit/review-policy.md"),
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


def _assert_matches_manifest(
    key: str, path: Path, *, require_stamp: bool = False
) -> None:
    """The load-bearing check: body hash, and header fields when stamped.

    ``require_stamp`` is passed for COMMITTED copies, which must carry
    their provenance header. Without it the header assertions below are
    opt-in: an unstamped file skips them, and because ``_kit_body`` falls
    back to "no marker means the whole file is the body", DELETING the
    provenance block leaves the body hash correct and the suite green.
    That would silently downgrade a stamped-copy check to a hash-only one
    and discard the only in-repo record of which kit version a copy is at.
    Env-located tools are legitimately deployed raw, so they do not set it.
    """
    pin = MANIFEST[key]
    text = path.read_text(encoding="utf-8")
    if require_stamp:
        assert _MARKER in _normalize(text), (
            f"{path} has lost its kit provenance stamp (no {_MARKER!r} line). "
            f"A committed vendored copy must keep its header: without it the "
            f"kit-version and body-sha256 assertions below do not run at all. "
            f"Re-vendor from the kit; do not strip the header."
        )
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
    _assert_matches_manifest(key, path, require_stamp=True)


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
    assert runtime.is_file(), (
        f"the runtime agent charter is missing at {runtime}; the "
        f"incident-analyst agent will not load. Materialize it from the "
        f"of-record copy at {of_record} (its body, with the header dropped)."
    )
    assert of_record.is_file(), (
        f"the drift-of-record copy is missing at {of_record}; the runtime "
        f"charter has nothing to be checked against. Re-vendor it from the kit."
    )
    runtime_body = _normalize(runtime.read_text(encoding="utf-8"))
    of_record_body = _kit_body(of_record.read_text(encoding="utf-8"))
    assert runtime_body == of_record_body, (
        f"{runtime} has drifted from its drift-of-record copy {of_record}. "
        f"The runtime charter is a DERIVED kit copy, not a source: the fix is "
        f"to re-vendor {of_record} from the kit and rewrite the runtime file "
        f"from that body. Do not hand-edit either, and do not sync the "
        f"of-record copy to the runtime one, which would defeat the pin. Run "
        f"pytest -vv to see the full body diff."
    )
    assert _sha256(runtime_body) == MANIFEST["incident-analyst.md"].body_sha256, (
        f"{runtime} body sha256 {_sha256(runtime_body)} != pinned "
        f"{MANIFEST['incident-analyst.md'].body_sha256}. The runtime charter "
        f"has drifted from kit incident-analyst.md; re-vendor from the kit, "
        f"do not hand-edit the copy."
    )


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
        if target.suffix == ".py" and not target.is_file():
            # ITC-20260727-1542. A .py value naming a file that exists
            # NOWHERE must not be reinterpreted as its parent directory.
            # ITACA_PLAN_VALIDATOR was once set to a retired
            # check_plan_entries.py; the parent happened to hold a
            # version-matched check_plan_kit.py, so the derivation below
            # succeeded and this suite stayed green while the plan skill
            # resolved the same variable to a path that does not exist and
            # validation silently skipped. Pointing at the configured value
            # itself makes the caller's is_file assertion name the real
            # error instead of hiding it one directory up.
            located.append(("check_plan_kit.py", target))
        else:
            directory = target.parent if target.suffix == ".py" else target
            located.append(("check_plan_kit.py", directory / "check_plan_kit.py"))
            located.append(
                (
                    "check_plan_kit_mutations.py",
                    directory / "check_plan_kit_mutations.py",
                )
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


def test_a_configured_locator_names_something_that_exists() -> None:
    """A locator naming nothing must fail, never be reinterpreted.

    ``ITC-20260727-1542``. ``ITACA_PLAN_VALIDATOR`` was set to a retired
    ``check_plan_entries.py``, a file present in no tree. ``_env_located``
    derived a DIRECTORY from a ``.py`` value by taking its parent, that
    parent happened to hold a version-matched ``check_plan_kit.py``, and so
    this suite stayed green. The consequence was one-sided, which is what
    makes it worth a guard rather than a correction: the test was fine and
    the plan skill was not, because it resolved the same variable to
    ``.../check_plan_entries.py/check_plan_kit.py`` and plan validation had
    been silently skipping. A guard reporting green while the behavior it
    guards is absent is the failure class the incident rule exists to catch.

    The variable was repaired the same day. The repair is not the fix: the
    derivation trusted a path it never checked, so the next mistyped value
    would have failed in exactly the same way. This test checks the
    CONFIGURED value itself, so no parent directory can stand in for it.
    """
    configured = [
        (name, Path(value))
        for name in ("ITACA_INCIDENT_LEDGER", "ITACA_PLAN_VALIDATOR")
        if (value := os.environ.get(name))
    ]
    if not configured:
        pytest.skip(
            "neither ITACA_INCIDENT_LEDGER nor ITACA_PLAN_VALIDATOR is set; "
            "there is no configured locator to check"
        )
    missing = [f"{name}={path}" for name, path in configured if not path.exists()]
    assert not missing, (
        f"a configured shared-tool locator names a path that does not exist: "
        f"{missing}. This is a configuration error and not a skip. Note the "
        f"failure mode this guards (ITC-20260727-1542): when the value ends in "
        f"'.py', the directory derived from it is the PARENT, so a value naming "
        f"nothing can still resolve to a valid checker beside it and green this "
        f"suite while the plan skill resolves the same value to nothing. Point "
        f"the variable at the directory holding the checker, or at the checker "
        f"itself, and make sure that path exists."
    )


def test_snap_script_matches_the_manifest_where_it_is_deployed() -> None:
    """Drift-check snap.sh best-effort; it has no locator of its own."""
    found = _snap_if_present()
    if found is None:
        pytest.skip("snap.sh is not present beside a configured plan validator")
    key, path = found
    _assert_matches_manifest(key, path)


def test_the_run_reports_which_pins_it_could_not_check() -> None:
    """Name the unchecked pins, so a skip is an inventory and not a shrug.

    Four of the nine manifest entries are reachable only through an
    environment locator, and CI sets none, so they are routinely unchecked
    there. A pin nobody reads can be moved to anything and the suite stays
    green, which is the failure this repository already names elsewhere as
    reading a checker's exit code without reading its entry count. This
    test never fails on a legitimately unconfigured clone; it exists so the
    run states WHICH pins went unread rather than emitting a bare skip.
    """
    checked = {key for key, _ in COMMITTED}
    checked.update(key for key, path in _env_located() if path.is_file())
    snap = _snap_if_present()
    if snap is not None:
        checked.add(snap[0])
    unchecked = sorted(set(MANIFEST) - checked)
    assert checked, "no manifest entry was checked at all; the fixture is inert"
    if unchecked:
        pytest.skip(
            f"{len(checked)} of {len(MANIFEST)} pinned kit artifacts were "
            f"verified in this run. NOT verified, because their locator is "
            f"unset or the file is absent: {unchecked}. These pins are "
            f"unread here and a wrong value in them would not redden this run."
        )


def test_no_unpinned_artifact_hides_in_the_vendored_dirs() -> None:
    """A new artifact under a vendored dir must be pinned, or it escapes both.

    ``.claude/hooks`` and ``.claude/kit`` are excluded from ruff because
    everything in them is a drift-pinned vendored copy, and COMMITTED is a
    fixed list, not a glob. So a future file dropped there would be neither
    linted nor drift-checked. Pin that every artifact under them is a
    committed manifest entry, closing that gap before it opens.

    The sweep covers ``.md``, ``.sh``, ``.yml`` and ``.yaml`` as well as
    ``.py``. Checking only ``.py`` reproduced the gap one suffix over:
    ``.claude/kit`` already holds a pinned ``.md`` (the of-record
    incident-analyst charter), so a second ``.md`` dropped beside it would
    have escaped both layers, which is the exact shape this test exists to
    prevent. ``.yml`` was added when kit 0.2.6 introduced a vendored
    workflow; it does not live under these directories today, but the
    suffix gap is closed here rather than left for the copy that does.

    ``.github/workflows`` is swept too, and by a DIFFERENT rule: not every
    file there is a vendored copy (``ci.yml`` and ``release.yml`` are this
    repository's own), so the sweep keys on the kit provenance marker
    instead of the suffix. Any file carrying that marker must be a pinned
    COMMITTED entry. This is the gap that let ``release_gate.yml`` escape
    on two counts at once, wrong directory and wrong suffix, and nothing
    would have reminded anyone: the vendored-directory sweep passes
    whether or not that file is pinned.
    """
    committed = {(_ROOT / rel).resolve() for _, rel in COMMITTED}
    for vendored_dir in (".claude/hooks", ".claude/kit"):
        for suffix in ("*.py", "*.md", "*.sh", "*.yml", "*.yaml"):
            for artifact in (_ROOT / vendored_dir).glob(suffix):
                assert artifact.resolve() in committed, (
                    f"{artifact} is under a ruff-excluded vendored directory "
                    f"but is not a pinned COMMITTED kit copy; add it to the "
                    f"manifest and the drift test, or it is neither linted nor "
                    f"drift-checked."
                )
    workflows = _ROOT / ".github" / "workflows"
    for artifact in sorted(workflows.glob("*")):
        if not artifact.is_file():
            continue
        if _MARKER not in _normalize(artifact.read_text(encoding="utf-8")):
            continue
        assert artifact.resolve() in committed, (
            f"{artifact} carries the kit provenance marker but is not a "
            f"pinned COMMITTED kit copy. A vendored body outside "
            f"'.claude' escapes the directory sweep above, so it is pinned "
            f"by this marker rule instead; add it to the manifest and to "
            f"COMMITTED."
        )
