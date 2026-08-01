"""Version identity of a source checkout (FND-046, REQ-92, DD-21, DD-38).

Reproduction (TDD anchor), the shortest call that exhibits the defect::

    # with a stray `itaca.egg-info/PKG-INFO` in the working directory
    python -c "import itaca; print(itaca.__version__)"
    9.9.9.dev99          # the stray file decided, not the code

`itaca/core/version.py` used to read the version from the INSTALLED
DISTRIBUTION first. In a source checkout that distribution is neither
unique nor current, and one cause showed three faces. Two of them are
measured here; the third, the push gate reading a stamped value against
a derived one, is pinned in `tests/test_release_integrity.py`.

Face 2, cwd dependence. `importlib.metadata` scans `sys.path` for
`*.egg-info` and `*.dist-info` directories, and the working directory is
on `sys.path`. So any directory holding an `itaca.egg-info/` shadows the
real install, and the repository root holds exactly such a directory
because every in-tree build writes one. Measured before the fix: the
same interpreter at the same commit reported `9.9.9.dev99` from one
directory and `0.3.0.dev24` from another.

Face 3, the null. `importlib.metadata.version()` returns ``None`` when
the metadata parses and carries no `Version:` field. The old resolver
guarded only `PackageNotFoundError`, so ``None`` became
``itaca.__version__`` and was stamped into `Provenance.itaca_version`
and into `.itc` archives at a field typed `str`. `mypy --strict` cannot
see it, because typeshed declares ``version() -> str``.

The module's own docstring already forbade this: "There is no third
fallback. A version that cannot be resolved is not guessed." A null is
worse than a guess; it is not even wrong.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

from itaca.core.errors import VersionResolutionError
from itaca.core.version import _resolve

_PLANTED = "9.9.9.dev99"


def _plant_egg_info(directory: Path, *, version: str | None) -> None:
    """Write a stray `itaca.egg-info/PKG-INFO` that `sys.path` will find."""
    egg = directory / "itaca.egg-info"
    egg.mkdir()
    lines = ["Metadata-Version: 2.1", "Name: itaca"]
    if version is not None:
        lines.append(f"Version: {version}")
    (egg / "PKG-INFO").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _reported_version(cwd: Path) -> str:
    """`itaca.__version__` as a fresh interpreter launched in `cwd` sees it."""
    done = subprocess.run(
        [sys.executable, "-c", "import itaca; print(repr(itaca.__version__))"],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return str(done.stdout.strip())


class TestTheWorkingDirectoryDoesNotDecideTheVersion:
    """Face 2: a stray build artifact must not name the library."""

    def test_a_stray_egg_info_does_not_shadow_the_version(self, tmp_path: Path) -> None:
        """The reported version is the same with and without the plant.

        Measured before the fix: `9.9.9.dev99` with the plant and
        `0.3.0.dev24` without it, same interpreter, same commit.
        """
        clean = tmp_path / "clean"
        planted = tmp_path / "planted"
        clean.mkdir()
        planted.mkdir()
        _plant_egg_info(planted, version=_PLANTED)

        assert _reported_version(planted) == _reported_version(clean)

    def test_the_planted_version_is_never_reported(self, tmp_path: Path) -> None:
        """The plant is a real shadow, so this is not a vacuous pass.

        Without this the test above would also pass if the plant were
        simply never found, which would make it a measurement of
        nothing.
        """
        _plant_egg_info(tmp_path, version=_PLANTED)
        import importlib.metadata

        done = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib.metadata as m; print(m.version('itaca'))",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=child_env(),
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert done.stdout.strip() == _PLANTED, (
            "the plant did not shadow the install, so the sibling test "
            "measures nothing; importlib.metadata reports "
            f"{done.stdout.strip()!r} "
            f"(installed: {importlib.metadata.version('itaca')!r})"
        )
        assert repr(_PLANTED) != _reported_version(tmp_path)


class TestAVersionIsNeverNull:
    """Face 3: a version that cannot be resolved is refused, not returned."""

    def test_metadata_without_a_version_field_does_not_yield_none(
        self, tmp_path: Path
    ) -> None:
        """End to end: a version-less PKG-INFO on `sys.path` is survivable.

        Measured before the fix: `itaca.__version__` was ``None``, and
        nothing anywhere raised.
        """
        _plant_egg_info(tmp_path, version=None)
        reported = _reported_version(tmp_path)
        assert reported != "None"
        assert reported.startswith("'")

    def test_resolve_refuses_when_neither_source_answers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The unit: both sources silent, and the resolver refuses.

        Measured before the fix: `_resolve()` returned ``None``.
        """
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "version", lambda _name: None)
        monkeypatch.setitem(
            sys.modules, "itaca.core._version", types.ModuleType("itaca.core._version")
        )

        with pytest.raises(VersionResolutionError) as excinfo:
            _resolve()

        message = str(excinfo.value)
        assert "itaca.core.version" in message
        assert "pip install -e ." in message

    def test_metadata_still_answers_when_the_version_file_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A never-built clone is not regressed: metadata remains a source."""
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.2.3")
        monkeypatch.setitem(
            sys.modules, "itaca.core._version", types.ModuleType("itaca.core._version")
        )

        assert _resolve() == "1.2.3"

    def test_resolve_refuses_when_nothing_is_installed_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The never-installed source tree: refused, with the fix named."""
        import importlib.metadata

        def _absent(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError(_name)

        monkeypatch.setattr(importlib.metadata, "version", _absent)
        monkeypatch.setitem(
            sys.modules, "itaca.core._version", types.ModuleType("itaca.core._version")
        )

        with pytest.raises(VersionResolutionError):
            _resolve()
