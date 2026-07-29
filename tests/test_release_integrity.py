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
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

_ROOT = Path(__file__).resolve().parents[1]
_KIT = _ROOT / ".claude" / "kit"
_WORKFLOWS = _ROOT / ".github" / "workflows"
_RELEASE_GATE_CHECK = _KIT / "check_release_gate.py"
_RELEASE_GATE_MUTATIONS = _KIT / "check_release_gate_mutations.py"
_VERSION_IDENTITY_CHECK = _KIT / "check_version_identity.py"
_VERSION_IDENTITY_MUTATIONS = _KIT / "check_version_identity_mutations.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=str(_ROOT),
    )


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
    checker to deny six weakenings of its own rules.

    It prints ``NOT CHECKED: no release_gate.yml beside this file``, which
    is correct and expected in a vendored copy: the gate lives under
    ``.github/workflows`` and the companion under ``.claude/kit``, so rule
    1 is exercised against fixtures here. The live file is covered by
    ``test_itaca_006_no_ungated_publish_path_survives`` below.
    """
    done = _run(str(_RELEASE_GATE_MUTATIONS))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "all 6 mutants denied" in done.stdout, done.stdout


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
    for the incident and plan checkers, where an empty folder reports `no
    entries` and exits zero.
    """
    done = _run(str(_RELEASE_GATE_CHECK), "--workflows", str(_WORKFLOWS))
    assert "publishing job(s) found    : 0" not in done.stdout, done.stdout
    assert "scanned 0 workflow file(s)" not in done.stdout, done.stdout


class TestBuiltArtifactIdentity:
    """`ITACA-004` and `ITACA-014` live in the BUILT artifact, so that is
    what these assert. Both findings were invisible to a suite that only
    ever looked at the source tree: mypy passed over the sources while
    consumers got no typing at all, and the version was consistent
    everywhere in-tree while being wrong about which code it was.

    One build serves both, because building twice would double the
    slowest test in the suite for no extra evidence.
    """

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
        self, tmp_path: Path
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
        wheel, sdist = self._build(tmp_path)
        version = importlib.metadata.version("itaca")

        # ITACA-004: the filename, the metadata and the code agree.
        assert wheel.name.startswith(f"itaca-{version}-"), (
            f"wheel is named {wheel.name} but the package reports {version}"
        )
        assert sdist.name == f"itaca-{version}.tar.gz", (
            f"sdist is named {sdist.name} but the package reports {version}"
        )

        entries = zipfile.ZipFile(wheel).namelist()
        metadata = (
            zipfile.ZipFile(wheel)
            .read(f"itaca-{version}.dist-info/METADATA")
            .decode("utf-8")
        )
        assert f"Version: {version}" in metadata

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
