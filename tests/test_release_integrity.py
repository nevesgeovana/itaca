"""Release integrity: version identity, the release gate, and py.typed.

Usage example (TDD anchor)::

    done = subprocess.run(
        [sys.executable, str(_RELEASE_GATE_CHECK), "--workflows", str(_WORKFLOWS)],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr

Three findings of `REV-001` share one root: the promise a release makes
about itself is not checked by anything that runs. `ITACA-004` is the
version identity, `ITACA-006` the ungated publish path, and `ITACA-014`
the typing marker that never reaches an installed consumer. Each is
pinned here by a test named for its finding id, because a check that
lives only in a reviewer's document is only as durable as the reviewer.

Two of the three are enforced by vendored kit checkers rather than by
assertions written here, and that is deliberate: both libraries reported
the same defect on the same day, so the RULE is kit material and only
its APPLICATION is this repository's. What this file adds is the
guarantee that the checkers actually run against this repository, and
that they can still fail; a vendored guard nobody invokes is the exact
shape of `ITACA-006` one level up.

A fourth item joined them for the same reason rather than from the same
review: `BRF-048`, the identifiers that must not travel to a user's
machine (DD-41). Its rule lives in `tests/identifiers.py` and its other
half runs over the source tree in `tests/test_house_style.py`; what
belongs here is the half that reads the archive, because what ships is a
question only the archive can answer.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterator
from pathlib import Path

import identifiers
import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from packaging.version import Version

# MEASURED 539 s with --no-cov on 2026-07-30, against 0.7 to 3.9 s for
# every module outside this one and test_push_gate.py. It builds real
# sdists and wheels and runs four mutation companions, each spawning a
# checker per case per mutant. That cost is the point of those guards and
# is not reducible here, so it moves to the tier that can afford it.
#
# NOT weakened by the marker, and the distinction is the whole design: the
# pre-push hook runs the full suite with coverage and BLOCKS, and CI runs
# it on every pull request. ITACA-006's checker still gates every push.
pytestmark = pytest.mark.slow

_ROOT = Path(__file__).resolve().parents[1]
_KIT = _ROOT / ".claude" / "kit"
_WORKFLOWS = _ROOT / ".github" / "workflows"
_RELEASE_GATE_CHECK = _KIT / "check_release_gate.py"
_RELEASE_GATE_MUTATIONS = _KIT / "check_release_gate_mutations.py"
_VERSION_IDENTITY_CHECK = _KIT / "check_version_identity.py"
_VERSION_IDENTITY_MUTATIONS = _KIT / "check_version_identity_mutations.py"
_SHIPPED_SURFACE_CHECK = _KIT / "check_shipped_surface.py"
_SHIPPED_SURFACE_MUTATIONS = _KIT / "check_shipped_surface_mutations.py"
_PROBE_CLOSURE_CHECK = _KIT / "check_probe_closure.py"
_PROBE_CLOSURE_MUTATIONS = _KIT / "check_probe_closure_mutations.py"
_SHIPPED_SURFACE_CONFIG = _ROOT / ".claude" / "shipped_surface.conf"
_PROBE_CLOSURE_LEDGER = _ROOT / ".claude" / "probe_closure_CHK-1.ledger"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=str(_ROOT),
    )


def _describe() -> tuple[str, int]:
    """The last release tag and the number of commits since it (FND-046).

    Every version question in this module used to be answered by
    `importlib.metadata.version("itaca")`. That is the version STAMPED
    at the last `pip install -e .`, while every artifact built here
    derives its version from the repository, so the two disagree on any
    tree whose install predates HEAD, and the failing run's own build
    rewrote the metadata it had just been measured against. The retry
    then passed on an identical tree, which taught every session that
    re-running is what one does with this module.

    So the anchor is the repository, which is what the artifact is a
    claim about. This deliberately does NOT reimplement
    `release-branch-semver`: it reads only the part that goes stale, the
    distance from the tag. A missing git is a FAILURE and never a skip;
    `setuptools-scm` cannot build without it either, so a tree that
    cannot answer this cannot have produced the artifact under test.
    """
    done = subprocess.run(
        ["git", "describe", "--tags", "--long", "--match", "v*"],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
    )
    assert done.returncode == 0, (
        "git describe could not name a release tag, so there is nothing to "
        "check the built artifact's version against. This is a failure and "
        "not a skip: setuptools-scm derives the artifact's version from the "
        f"same repository.\n{done.stdout}{done.stderr}"
    )
    described = done.stdout.strip()
    match = re.fullmatch(r"v(?P<tag>.+)-(?P<distance>\d+)-g[0-9a-f]+", described)
    assert match is not None, f"unparsable git describe output: {described!r}"
    return match["tag"], int(match["distance"])


def _released_version() -> str | None:
    """The version of the release AT HEAD, or ``None`` on a development tree."""
    tag, distance = _describe()
    return tag if distance == 0 else None


def test_the_vendored_release_checkers_are_present() -> None:
    """A checker loaded by path fails loudly if it is missing.

    Without this a rename would silently remove the whole check while the
    suite stayed green, which is the self-skipping evidence the kit exists
    to replace.
    """
    for checker in (
        _RELEASE_GATE_CHECK,
        _RELEASE_GATE_MUTATIONS,
        _VERSION_IDENTITY_CHECK,
        _VERSION_IDENTITY_MUTATIONS,
    ):
        assert checker.is_file(), f"vendored kit checker missing at {checker}"


def test_the_release_gate_checker_can_still_fail() -> None:
    """The mutation companion proves the release-gate checker still refuses.

    A guard that cannot fail the case it exists to catch manufactures
    confidence. The companion builds workflow fixtures and requires the
    checker to deny every weakening of its own rules.

    Both counts are pinned, and the reason is narrower than it first looks.
    An earlier version of this docstring argued that a companion which
    dropped half its cases "would still report every mutant denied". That is
    FALSE, and a reviewer measured why: the companion marks a mutant denied
    when ANY case fails, and a mutant nothing catches is reported as
    survived and exits non-zero. So dropping load-bearing cases turns the
    run RED, not green.

    What the case pin actually catches is the loss of cases that are
    redundant with respect to all 28 mutants, on one specific path: a
    re-vendor where the body hash is updated mechanically and a shrunken
    case list goes unnoticed. Both counts are already implied by the
    body-sha256 pin in ``test_kit_drift.py``, which fails first on any byte
    change, so these two literals are defense in depth for that path alone.
    Exact rather than a floor, because a floor is strictly weaker against it
    and no cheaper to maintain.

    It prints ``NOT CHECKED: no release_gate.yml beside this file``, which
    is correct and expected in a vendored copy: the gate lives under
    ``.github/workflows`` and the companion under ``.claude/kit``, so rule
    1 is exercised against fixtures here. The live file is covered by
    ``test_itaca_006_no_ungated_publish_path_survives`` below.
    """
    done = _run(str(_RELEASE_GATE_MUTATIONS))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "all 28 mutants denied" in done.stdout, (
        f"the release-gate mutation companion did not report 'all 28 mutants "
        f"denied'. Two opposite remedies: if a re-vendor changed the count, "
        f"move it here and in tests/test_kit_drift.py's manifest note "
        f"together; if it did not, a mutant SURVIVED and the checker no "
        f"longer refuses what it claims to. Output:\n{done.stdout}"
    )
    assert "40 cases on real workflow files" in done.stdout, (
        f"the release-gate mutation companion did not report 40 cases. The "
        f"mutants can all be denied by a shrunken case list, so this count is "
        f"what catches a re-vendor that quietly dropped cases. If the kit "
        f"really changed it, move the pin; do not delete it. "
        f"Output:\n{done.stdout}"
    )


def test_the_version_identity_checker_can_still_fail() -> None:
    """The mutation companion proves the version-identity rule still bites.

    Slower than the rest of tier 1 (it builds a real git repository per
    case per mutant). Kept here rather than trimmed: the cases are the
    rule, and a faster suite that checks less is the trade this repository
    does not make.
    """
    done = _run(str(_VERSION_IDENTITY_MUTATIONS))
    assert done.returncode == 0, done.stdout + done.stderr


def test_itaca_006_no_ungated_publish_path_survives() -> None:
    """`ITACA-006`: publication must not be reachable without the gates.

    `REV-001` measured `release.yml` triggering on `v*` tags and running
    build, `twine check` and a tag-versus-version comparison, then
    publishing, with no pytest, no coverage, no ruff and no mypy, and
    nothing that reads CI's verdict for that SHA. The remedy is the
    vendored reusable gate, and this test is what proves no second
    publishing path was left beside it: a vendored gate with the old
    workflow still present is a protection worth nothing while every hash
    and every drift test stays green.
    """
    done = _run(str(_RELEASE_GATE_CHECK), "--workflows", str(_WORKFLOWS))
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_release_gate_checker_had_something_to_check() -> None:
    """A clean run must not mean the checker silently scanned nothing.

    The checker exits 0 when it finds no ungated publisher, which is also
    what it would do against an empty or mis-pointed directory. Read the
    count, not only the exit code: the same failure this repository names
    for the incident and plan checkers, both of which now refuse an empty
    folder rather than reporting a clean one (`ITC-20260727-1612`). This
    checker does not, which is why the count is read here.
    """
    done = _run(str(_RELEASE_GATE_CHECK), "--workflows", str(_WORKFLOWS))
    # POSITIVELY, not as an absent substring. Both counts used to be checked
    # by asserting an exactly-padded string was NOT present, which goes
    # silently blind the moment a re-vendor reflows the report line: the
    # substring is then never present, both assertions pass forever, and the
    # guard whose whole purpose is "a clean run must not mean the checker
    # scanned nothing" is gone with CI green. That is this repository's own
    # "a checker whose output wording changes goes blind in a way no exit
    # code reports", one level in.
    for label, pattern in (
        ("publishing jobs", r"publishing job\(s\) found\s*:\s*(\d+)"),
        ("scanned workflow files", r"scanned (\d+) workflow file\(s\)"),
    ):
        found = re.search(pattern, done.stdout)
        assert found, (
            f"the release-gate checker's report no longer carries a "
            f"{label} count, so this guard can no longer tell a clean run "
            f"from an empty scan. Re-read the vendored report format and "
            f"update the pattern. Output:\n{done.stdout}"
        )
        assert int(found.group(1)) >= 1, (
            f"the release-gate checker reported {found.group(1)} {label}. It "
            f"exits 0 against an empty or mis-pointed directory exactly as it "
            f"does against a clean one, so a zero here is a scan that "
            f"happened to find nothing to check."
        )
    # The same reasoning one level further in: a checker can exit 0 having
    # RUN fewer rules than it has. Kit 0.2.13 carries six, and each names a
    # failure this repository actually had.
    verified = next(
        (line for line in done.stdout.splitlines() if "VERIFIED:" in line), ""
    )
    assert "NOT RUN" not in verified, (
        f"the release-gate checker's VERIFIED line reports a rule as NOT RUN, "
        f"so it enumerated six rules and exercised fewer. Rule 1 prints "
        f"'rule 1 (seal) NOT RUN' when it finds no gate file to examine, "
        f"which is a scan that verified nothing about the seal. Line was: "
        f"{verified!r}"
    )
    for rule in range(1, 7):
        assert f"rule {rule} " in verified, (
            f"the release-gate checker's VERIFIED line does not name rule "
            f"{rule}. Kit 0.2.13 runs six rules; a run that exercises fewer "
            f"still exits 0. Line was: {verified!r}"
        )
    # Scope, per rule, because "over 0 publishing job(s)" is what this
    # repository's PRE-adoption tree printed and it satisfies the loop above.
    # The count is the first number after `over` rather than the token
    # immediately following it: rule 4 reads "over the gate and 1 publishing
    # job(s)", so anchoring on `over (\d+)` matches five rules and silently
    # skips the fourth, which is how this assertion first went in.
    for rule in (2, 4, 5, 6):
        scoped = re.search(rf"rule {rule} \([^)]+\) over [^0-9;]*(\d+)", verified)
        assert scoped, (
            f"the release-gate checker's VERIFIED line carries no scope count "
            f"for rule {rule}, so this guard cannot tell a rule that examined "
            f"something from one that examined nothing. Re-read the vendored "
            f"report format. Line was: {verified!r}"
        )
        assert int(scoped.group(1)) >= 1, (
            f"rule {rule} ran over a scope of zero, so it examined nothing "
            f"and still reported VERIFIED. The pre-adoption topology printed "
            f"exactly this, which is the arrangement this repository "
            f"abandoned (DD-45). Line was: {verified!r}"
        )


def test_the_citation_record_matches_the_release_it_describes() -> None:
    """`CITATION.cff` is what Zenodo reads, so it must not lag the tag.

    Asked for by the RELEASE review, which found this file at
    `version: 0.1.0` with `date-released: 2026-07-22` and the v0.1.0 DOI
    while the v0.2.0 tag was being prepared. There is no `.zenodo.json`, so
    Zenodo falls back to this file for deposit metadata: the archive record
    would have been labeled 0.1.0, carried the previous release's DOI, and
    its abstract would have called processors "roadmapped rather than
    released" in the release whose largest feature they are. A minted DOI
    does not come back.

    Repairing the content is not the fix; nothing read the file. This is the
    mechanism, and it is deliberately conditional: on a development tree the
    version carries a `.dev` suffix and there is nothing to compare against,
    so the check applies exactly when it matters, at a tag.

    A per-release `doi:` key must NOT be present. Whatever value could be
    written before the tag is by construction the previous release's, which
    is precisely the defect. The concept DOI lives under `identifiers`.
    """
    text = (_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    fields = {}
    for line in text.splitlines():
        if line.startswith(("version:", "date-released:", "doi:")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()

    assert "doi" not in fields, (
        f"CITATION.cff carries a top-level doi: {fields.get('doi')!r}. Any "
        f"value written before the tag is the PREVIOUS release's DOI, which "
        f"is the defect the release review found. Cite the concept DOI under "
        f"identifiers instead."
    )
    assert "version" in fields and "date-released" in fields, (
        f"CITATION.cff is missing version or date-released: {sorted(fields)}"
    )

    # FND-046: the question is whether THIS TREE is a release, which the
    # installed distribution cannot answer. A stale editable install
    # carrying a `.dev` version made this skip at a tagged commit, so the
    # guard went quiet at exactly the moment it exists for.
    packaged = _released_version()
    if packaged is None:
        tag, distance = _describe()
        pytest.skip(
            f"HEAD is {distance} commits past v{tag}, a development tree, so "
            f"there is no released version for CITATION.cff to match. This "
            f"check applies at a tag, which is when it matters."
        )
    assert fields["version"] == packaged, (
        f"CITATION.cff says version {fields['version']} and this tree is "
        f"tagged {packaged}. Zenodo reads this file, and a minted DOI "
        f"labeled with the wrong version does not come back."
    )
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = f"## [{packaged}] - {fields['date-released']}"
    assert heading in changelog, (
        f"CITATION.cff dates the release {fields['date-released']} and "
        f"CHANGELOG.md has no {heading!r} section. The archive record and the "
        f"release notes must agree on what was released and when."
    )


def test_no_tracked_file_carries_a_byte_order_mark() -> None:
    """No tracked file may start with `EF BB BF`, anywhere in the tree.

    Twice measured, and the second measurement is why this is scoped to
    the tree rather than to workflows. First: the commit that fixed
    `R3-ITA-001` put a BOM at the head of `release.yml`, written by a
    Windows shell whose `utf8` encoding emits one, and PyYAML decodes it
    happily so the permissions guard stayed green over a corrupted file.
    A guard was added, scoped to `.github/workflows`.

    Second, one commit later: the same shell put a BOM into
    `tests/test_chk1_open_defects.py`. `ruff format --check` refused it
    in CI on all three legs while the local run reported 131 files
    already formatted, because the local check had already been run
    before the BOM was written. The guard did not see it, because it had
    been scoped to where the first instance happened instead of to the
    class. That is this repository's registered incident class, so the
    scope is the whole tracked tree now.

    Asked of git rather than of the filesystem, so build output and one
    machine's untracked files cannot decide the verdict, and read as
    BYTES, since every text-mode reader strips the mark before an
    assertion could see it.
    """
    listing = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        check=False,
    )
    if listing.returncode != 0:  # pragma: no cover - not a checkout
        pytest.skip("not a git checkout; the tracked-file list is unavailable")
    offenders = []
    checked = 0
    for name in listing.stdout.split():
        path = _ROOT / name
        if not path.is_file():
            continue
        checked += 1
        if path.read_bytes().startswith(b"\xef\xbb\xbf"):
            offenders.append(name)
    # A walk that returned almost nothing would pass vacuously.
    assert checked >= 100, f"only {checked} tracked file(s) inspected"
    assert not offenders, (
        f"tracked file(s) {offenders} begin with a UTF-8 byte order mark. "
        "Tools disagree about it: ruff format refuses one, PyYAML accepts "
        "it silently. Write the file as UTF-8 without a BOM; on PowerShell "
        "5.1 that means avoiding `-Encoding utf8`, which emits one."
    )


def test_r3_ita_001_every_caller_grants_what_the_called_gate_needs() -> None:
    """`R3-ITA-001`: a caller must grant `contents: read` to a gate that
    checks out.

    Measured before the fix: `release.yml` declared `id-token: write` and
    nothing else, while `release_gate.yml` runs `actions/checkout` three
    times. Declaring any permission sets every undeclared one to `none`,
    and a reusable workflow cannot exceed what its caller granted, so the
    only path a tag would take could not check out. Nothing caught it,
    because the green run on that commit came from `ci.yml`, a different
    caller that does grant it, and the publish jobs it skipped were the
    ones that would have exercised this caller.

    The rule generalizes past this repository and belongs in the shared
    kit next to `check_release_gate.py`; what lives here is its
    application, which is the half this repository owns.

    This assertion is a static check, and static checks are exactly what
    this finding shows to be insufficient on their own. It is the
    regression guard; the closure evidence is a canary run recorded in
    the CHK-1 remediation report.
    """
    yaml = pytest.importorskip("yaml")
    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(_WORKFLOWS.glob("*.yml"))
    }
    assert workflows, f"no workflow files under {_WORKFLOWS}"

    def checks_out(name: str) -> bool:
        called = workflows.get(name)
        if called is None:
            return False
        return "actions/checkout" in (_WORKFLOWS / name).read_text(encoding="utf-8")

    callers = 0
    for name, document in workflows.items():
        for job_name, job in (document.get("jobs") or {}).items():
            uses = job.get("uses", "")
            if not isinstance(uses, str) or not uses.startswith("./.github/workflows/"):
                continue
            target = uses.rsplit("/", 1)[-1]
            if not checks_out(target):
                continue
            callers += 1
            granted = job.get("permissions")
            assert granted is not None, (
                f"{name}: job '{job_name}' calls {target}, which checks out, "
                "and declares no permissions block"
            )
            # GitHub accepts a scalar shorthand as well as a mapping, and
            # `write` is a legitimate stronger grant (a job that creates a
            # release needs it). The rule is that contents must be
            # READABLE, not that it must be exactly "read": asserting the
            # narrower thing would fail a correct workflow, and `.get` on
            # the scalar form would raise AttributeError instead of
            # reporting a policy failure.
            if isinstance(granted, str):
                contents = "read" if granted == "read-all" else None
                if granted == "write-all":
                    contents = "write"
            else:
                contents = granted.get("contents")
            assert contents in {"read", "write"}, (
                f"{name}: job '{job_name}' calls {target}, which runs "
                f"actions/checkout, but grants {granted}. Declaring any "
                "permission sets the rest to none and a reusable workflow "
                "cannot exceed its caller, so the checkout cannot succeed "
                "(R3-ITA-001)."
            )

    # A clean pass must not mean nothing was inspected: the same
    # self-skipping shape ITACA-006 was, one level up.
    assert callers >= 2, (
        f"only {callers} checkout-bearing caller(s) inspected; ci.yml and "
        "release.yml are both expected to call the gate"
    )


class TestIncident0854Guards:
    """The two kit 0.2.7 guards for `INC-20260729-0854-shared`, RUN here.

    The incident's own guard field says it stays open because two of its
    three mechanisms "are not yet promoted to where they run without
    someone choosing to run them". Vendoring them is not that promotion;
    invoking them from tier 1 is. A checker sitting in `.claude/kit`
    that nothing calls is the same shape as the defect it exists to
    catch, one level up, which is the shape this repository already
    names for `ITACA-006`.

    The third mechanism is this repository's own and was already done:
    `tests/test_requirement_trace.py` stopped walking its own file.
    """

    def test_the_vendored_incident_guards_are_present(self) -> None:
        """A checker loaded by path fails loudly if it is missing."""
        for checker in (
            _SHIPPED_SURFACE_CHECK,
            _SHIPPED_SURFACE_MUTATIONS,
            _PROBE_CLOSURE_CHECK,
            _PROBE_CLOSURE_MUTATIONS,
        ):
            assert checker.is_file(), f"vendored kit checker missing at {checker}"
        assert _SHIPPED_SURFACE_CONFIG.is_file(), (
            f"the shipped-surface config is missing at {_SHIPPED_SURFACE_CONFIG}; "
            "the checker refuses an absent config rather than scanning with no "
            "exemptions and no floor, but the absence must fail here too."
        )
        assert _PROBE_CLOSURE_LEDGER.is_file(), (
            f"the CHK-1 probe ledger is missing at {_PROBE_CLOSURE_LEDGER}"
        )

    def test_guard_1_the_versioned_tree_carries_no_forbidden_identifier(self) -> None:
        """The tree boundary, run every round because it needs no build."""
        done = _run(
            str(_SHIPPED_SURFACE_CHECK),
            "--config",
            str(_SHIPPED_SURFACE_CONFIG),
            "--tree",
            str(_ROOT),
        )
        assert done.returncode == 0, done.stdout + done.stderr
        # Read the accounting, not only the exit code: a scan that opened
        # almost nothing exits 0 too, and that is the incident.
        assert "scanned" in done.stdout, done.stdout
        assert "unreadable 0" in done.stdout, done.stdout

    def test_guard_1_can_still_fail(self) -> None:
        """The mutation companion proves the shipped-surface rule still bites.

        28 mutants, each a narrowing that turned a leaking artifact
        green, plus control pairs proving each narrowing is caught by its
        own detector rather than by a neighbor.
        """
        done = _run(str(_SHIPPED_SURFACE_MUTATIONS))
        assert done.returncode == 0, done.stdout + done.stderr
        assert "all 28 mutants denied" in done.stdout, done.stdout

    def test_guard_3_every_closed_probe_reproduced_against_the_base(self) -> None:
        """The probe-closure rule over CHK-1's own ledger.

        A probe reporting a finding closed looks identical whether the
        code changed or the probe was always inert. The one measurement
        that separates them is running it against the tree where the
        defect existed, and this refuses a checkpoint that skipped it.
        """
        done = _run(str(_PROBE_CLOSURE_CHECK), "--ledger", str(_PROBE_CLOSURE_LEDGER))
        assert done.returncode == 0, done.stdout + done.stderr
        assert "probe(s)" in done.stdout, done.stdout

    def test_guard_3_can_still_fail(self) -> None:
        """The mutation companion proves the probe-closure rule still bites."""
        done = _run(str(_PROBE_CLOSURE_MUTATIONS))
        assert done.returncode == 0, done.stdout + done.stderr
        assert "all 8 mutants denied" in done.stdout, done.stdout


class TestBuiltArtifactIdentity:
    """`ITACA-004`, `ITACA-014` and `BRF-048` live in the BUILT artifact,
    so that is what these assert. All three were invisible to a suite that
    only ever looked at the source tree: mypy passed over the sources
    while consumers got no typing at all, the version was consistent
    everywhere in-tree while being wrong about which code it was, and an
    identifier guard scoped to the package was green while the sdist
    shipped the same identifier inside `tests/`.

    One build serves all of them, through a class-scoped fixture, because
    building once per assertion would multiply the slowest test in the
    suite for no extra evidence.
    """

    @pytest.fixture(scope="class")
    def artifacts(self, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
        """The wheel and the sdist, built once for this class."""
        return self._build(tmp_path_factory.mktemp("dist"))

    @staticmethod
    def _build(tmp_path: Path) -> tuple[Path, Path]:
        out = tmp_path / "dist"
        done = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(out)],
            capture_output=True,
            text=True,
            env=child_env(),
            cwd=str(_ROOT),
        )
        assert done.returncode == 0, done.stdout + done.stderr
        wheels = sorted(out.glob("*.whl"))
        sdists = sorted(out.glob("*.tar.gz"))
        assert len(wheels) == 1, f"expected one wheel, got {wheels}"
        assert len(sdists) == 1, f"expected one sdist, got {sdists}"
        return wheels[0], sdists[0]

    def test_itaca_004_and_014_the_built_artifact_carries_both(
        self, artifacts: tuple[Path, Path]
    ) -> None:
        """The artifact is named for the code it holds, and ships py.typed.

        `ITACA-004`, measured before the fix: an sdist built from HEAD
        was named `itaca-0.1.0.tar.gz` while containing `Pipeline`,
        `core/sentinels.py`, `ops/rotate.py` and the whole `pproc`
        package. The artifact claimed to be a release that predated
        every one of them.

        `ITACA-014`, measured before the fix: `pyproject.toml` declared
        the `Typing :: Typed` classifier and `itaca/py.typed` did not
        exist, so it appeared in neither the published wheel's 44
        entries nor an sdist built from the seam. A consumer running
        mypy against the installed package got nothing, while this
        repository's own mypy gate passed against the source tree.
        """
        wheel, sdist = artifacts

        # FND-046: the expected version is derived from the REPOSITORY,
        # never from the installed distribution. ITACA-004 asks that the
        # artifact be named for the code it holds, and the code it holds
        # is this tree, not whatever `pip install -e .` last stamped.
        # Reading the stamped value made this assertion fail once and
        # then pass on an identical tree, because the failing run's own
        # build rewrote `itaca.egg-info/PKG-INFO`.
        tag, distance = _describe()
        wheel_match = re.fullmatch(
            r"itaca-(?P<version>.+?)-py3-none-any\.whl", wheel.name
        )
        assert wheel_match is not None, f"unparsable wheel name: {wheel.name}"
        version = wheel_match["version"]

        # ITACA-004: the artifact's version is the TREE's version. The
        # distance is the part that goes stale, and it is checked rather
        # than the whole scheme, so this does not become a second
        # implementation of the version scheme, which is ITACA-004
        # itself.
        if distance == 0:
            assert version == tag, (
                f"HEAD carries the release tag v{tag} and the wheel is named "
                f"{wheel.name}. A tagged commit builds as exactly X.Y.Z."
            )
        else:
            assert version.endswith(f".dev{distance}"), (
                f"HEAD is {distance} commits past v{tag} and the wheel is "
                f"named {wheel.name}. A development build is named for the "
                f"release being worked toward with the commit distance as "
                f"its dev number (DD-38)."
            )
            # The dev suffix alone leaves X.Y.Z unconstrained, so a wheel
            # named itaca-9.9.9.devN or itaca-0.1.0.devN would pass. This
            # bounds the RELEASE part without reimplementing
            # release-branch-semver: whatever the scheme, a development
            # build names the release being worked TOWARD, so it is
            # strictly after the last tag and advances exactly one
            # component of it.
            built = Version(version)
            released = Version(tag)
            assert built > released, (
                f"the wheel is named {wheel.name}, which is not after the "
                f"last release tag v{tag}."
            )
            advanced = [
                index
                for index, (left, right) in enumerate(
                    zip(built.release, released.release, strict=False)
                )
                if left != right
            ]
            assert len(advanced) == 1, (
                f"the wheel is named {wheel.name} and the last tag is v{tag}; "
                f"a development build advances exactly one component of the "
                f"released version, and this differs in {len(advanced)}. A "
                f"setuptools_scm version_scheme change is the usual cause."
            )

        # ITACA-004: the filename, the metadata and the code agree.
        assert sdist.name == f"itaca-{version}.tar.gz", (
            f"sdist is named {sdist.name} and the wheel is named {wheel.name}; "
            f"one build produced both and they disagree on the version"
        )

        entries = zipfile.ZipFile(wheel).namelist()
        metadata = (
            zipfile.ZipFile(wheel)
            .read(f"itaca-{version}.dist-info/METADATA")
            .decode("utf-8")
        )
        assert f"Version: {version}" in metadata

        # FND-046: `itaca.core.version` reads the generated version file
        # BEFORE the distribution metadata, because the metadata is found
        # by a `sys.path` scan that any stray `itaca.egg-info/` can win.
        # That resolution order is only sound if the file actually ships
        # inside the artifact and carries the artifact's own version, so
        # this asserts both rather than assuming them.
        assert "itaca/core/_version.py" in entries, (
            "the wheel does not ship itaca/core/_version.py, which "
            "itaca.core.version._resolve reads first; an installed consumer "
            "would silently fall back to the distribution metadata (FND-046)."
        )
        version_file = zipfile.ZipFile(wheel).read("itaca/core/_version.py").decode()
        assert f"'{version}'" in version_file, (
            f"the wheel is named {wheel.name} but the version file it ships "
            f"does not carry {version}, so the library would report one "
            f"version while its own artifact is named another (FND-046)."
        )

        # And the seam is genuinely in there, so the name is a claim
        # about content and not about an empty package.
        for module in (
            "itaca/core/pipeline.py",
            "itaca/core/sentinels.py",
            "itaca/ops/rotate.py",
            "itaca/pproc/base.py",
        ):
            assert module in entries, f"{module} missing from the wheel"

        # ITACA-014: the PEP 561 marker reaches the consumer.
        assert "itaca/py.typed" in entries, (
            "the wheel declares the Typing :: Typed classifier but does not "
            "ship itaca/py.typed, so an installed consumer gets no typing "
            "from a promise this repository's own mypy gate satisfies "
            "against the source tree (PEP 561, ITACA-014)."
        )
        with tarfile.open(sdist) as archive:
            assert any(
                name.endswith("itaca/py.typed") for name in archive.getnames()
            ), "itaca/py.typed missing from the sdist"

    def test_fnd056_the_artifact_carries_a_pep_639_license_expression(
        self, artifacts: tuple[Path, Path]
    ) -> None:
        """The license is machine-readable in the ARTIFACT, not only declared.

        `FND-056`, measured before the fix: `pyproject.toml` used the
        legacy `license = { text = "MIT" }` table, so the built
        `PKG-INFO` carried a free-text `License: MIT` and the deprecated
        `License :: OSI Approved :: MIT License` classifier, while
        `License-Expression` was absent. The installed distribution
        reported `License-Expression=None`.

        This is asserted against the ARTIFACT and not against
        `pyproject.toml`, for the same reason `ITACA-014` is: the source
        declaration and the emitted metadata are two different facts,
        and only the second reaches a redistributor.
        """
        wheel, _sdist = artifacts
        archive = zipfile.ZipFile(wheel)
        dist_info = next(
            name.split("/")[0]
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(f"{dist_info}/METADATA").decode("utf-8")

        assert "License-Expression: MIT" in metadata, (
            f"the wheel's METADATA carries no PEP 639 License-Expression. "
            f"Header lines present: "
            f"{[line for line in metadata.splitlines() if 'License' in line]}"
        )
        stale = [
            line
            for line in metadata.splitlines()
            if line.startswith("Classifier: License ::")
        ]
        assert not stale, (
            f"the wheel still declares the deprecated license classifier "
            f"{stale}, which PEP 639 replaces with the expression above; two "
            f"declarations of one fact can disagree (FND-056)."
        )
        assert f"{dist_info}/licenses/LICENSE" in archive.namelist(), (
            "the wheel does not ship the license TEXT, so a consumer gets "
            "the name of a license without its terms (PEP 639, FND-056)."
        )

    def test_brf048_no_identifier_travels_inside_the_built_artifacts(
        self, artifacts: tuple[Path, Path]
    ) -> None:
        """No personal or institutional identifier ships, outside authorship.

        `BRF-048`, measured before the fix: four occurrences sat in the
        importable package, one of them a doctest binding a given name to
        an institutional domain. Measured AFTER that fix and before this
        one: an sdist built from the same commit carried 241 entries,
        because setuptools-scm's file finder now places every tracked
        file into it, and `tests/core/test_provenance_modes.py` still
        held the identical string in the module docstring its own heading
        calls "the contract under test".

        The source guard in `tests/test_house_style.py` decides what
        ships by reasoning about it. This one reads the archive, which is
        the only thing that cannot be wrong about its own contents, and
        it is why the pair exists rather than either alone.
        """
        wheel, sdist = artifacts
        found: list[str] = []

        with zipfile.ZipFile(wheel) as archive:
            entries = [name for name in archive.namelist() if not name.endswith("/")]
            found += identifiers.offenders(
                (name, archive.read(name)) for name in entries
            )
        assert "itaca/core/provenance.py" in entries, entries[:20]

        with tarfile.open(sdist) as bundle:

            def payload() -> Iterator[tuple[str, bytes]]:
                for member in bundle.getmembers():
                    handle = bundle.extractfile(member) if member.isfile() else None
                    if handle is not None:
                        # Strip the "itaca-<version>/" root so the paths
                        # the rule sees are repository-relative.
                        yield member.name.split("/", 1)[-1], handle.read()

            shipped = list(payload())
            found += identifiers.offenders(shipped)

        # A build that produced an empty archive, or an sdist that
        # stopped shipping the tree, would pass every assertion above by
        # scanning nothing or nearly nothing. Both floors are read, and
        # both archives must contain a file the scan exists for: the
        # package module for the wheel, and for the sdist the very test
        # module whose identifier this guard was written to catch.
        assert len(entries) >= 50, f"the wheel holds {len(entries)} entries"
        assert len(shipped) >= 100, f"the sdist holds {len(shipped)} files"
        names = [name for name, _ in shipped]
        assert "tests/core/test_provenance_modes.py" in names, sorted(names)[:20]
        assert not found, (
            f"identifiers travel inside the release artifacts: {found}; "
            f"{identifiers.REMEDY}"
        )

    def test_no_process_machinery_ships_inside_the_sdist(
        self, artifacts: tuple[Path, Path]
    ) -> None:
        """`.claude/` is pruned from the published artifact, and it is READ.

        Author decision 2026-07-30, taken when the release review measured
        that the v0.2.0 sdist would carry the whole of `.claude/`: the agent
        charters, the skills, the vendored shared-process kit and the
        push-gate hooks. No count is written here, deliberately: the first
        version of this docstring carried one, it was the RETIRED
        container's count rather than this repository's, and a count in a
        docstring goes stale on the next charter added.

        setuptools-scm supplies the file list from git, so
        every tracked file ships by default, which is right for `tests/`,
        `docs/` and `examples/` (DD-38) and wrong for process machinery. None
        of it is the library, none of it runs for a user, and a gate hook
        inside a published archive invites being run outside the repository
        it was written for.

        `MANIFEST.in` is the mechanism and this is the guard. Reasoning about
        what a build includes is how the original defect arrived: the source
        guard in `tests/test_house_style.py` decides what ships by inference,
        and this reads the archive, which is the only thing that cannot be
        wrong about its own contents.

        The positive half is asserted too. A `prune` that was too broad, or a
        build that stopped shipping the tree, would satisfy the absence
        assertion by shipping nothing, so the three trees the decision keeps
        are required to still be there.
        """
        _, sdist = artifacts
        with tarfile.open(sdist) as bundle:
            # Strip the "itaca-<version>/" root so paths are repo-relative.
            names = [
                member.name.split("/", 1)[-1]
                for member in bundle.getmembers()
                if member.isfile()
            ]

        machinery = sorted(name for name in names if name.startswith(".claude/"))
        assert not machinery, (
            f"the sdist ships {len(machinery)} file(s) under .claude/, which is "
            f"development process machinery and not the library: "
            f"{machinery[:10]}. `MANIFEST.in` prunes it; if that stopped "
            f"working, a build change put it back. Do not fix this by narrowing "
            f"the scan."
        )
        assert not [name for name in names if name.startswith("_private/")], (
            "the sdist ships files under _private/, the local staging tree for "
            "proprietary material. That directory is gitignored AND pruned; if "
            "it reached an archive, both failed."
        )
        # The floors, so the absence above cannot be satisfied vacuously.
        assert len(names) >= 100, f"the sdist holds {len(names)} files"
        for kept in (
            "itaca/core/varframe.py",
            "tests/test_release_integrity.py",
            "docs/srs/main.tex",
            "examples/wt_campaign.py",
            "CHANGELOG.md",
            "CITATION.cff",
        ):
            assert kept in names, (
                f"the sdist no longer ships {kept}, so the prune above is too "
                f"broad or the build stopped including the tree. DD-38 keeps "
                f"tests, docs and examples in the artifact deliberately."
            )

    def test_guard_1_the_built_artifacts_carry_no_forbidden_identifier(
        self, artifacts: tuple[Path, Path]
    ) -> None:
        """The ARTIFACT boundary of the kit guard, over this class's build.

        Runs beside `test_brf048_...` rather than replacing it, and the
        duplication is deliberate for exactly one release: the kit body
        was PROMOTED from `tests/identifiers.py`, so running both proves
        the promotion did not change the verdict on a real artifact.
        Retiring the local implementation is registered
        (`ITC-20260729-1700`) and is the follow-up, because two
        implementations of one rule that could disagree is the drift the
        kit exists to stop.
        """
        wheel, _ = artifacts
        done = _run(
            str(_SHIPPED_SURFACE_CHECK),
            "--config",
            str(_SHIPPED_SURFACE_CONFIG),
            "--dist",
            str(wheel.parent),
        )
        assert done.returncode == 0, done.stdout + done.stderr
        # Both archives must have been opened, not just listed.
        assert "wheel" in done.stdout and "sdist" in done.stdout, done.stdout
        assert "member(s), scanned" in done.stdout, done.stdout

    def test_itaca_014_the_typed_classifier_is_actually_declared(self) -> None:
        """The other half of the promise, so the pair cannot drift apart.

        If the classifier is ever dropped, shipping `py.typed` becomes
        harmless rather than wrong, and this test says so instead of
        the pair silently going out of sync in either direction.
        """
        config = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        classifiers = config["project"]["classifiers"]
        assert "Typing :: Typed" in classifiers
        assert config["tool"]["setuptools"]["package-data"]["itaca"] == ["py.typed"], (
            "py.typed is declared as package data, or it does not ship"
        )
