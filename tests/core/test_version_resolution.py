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
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

import pytest

from itaca.core.errors import VersionResolutionError
from itaca.core.version import _resolve

_PLANTED = "9.9.9.dev99"

#: The `child_env` fixture from `tests/conftest.py`, taken rather than imported.
EnvFactory: TypeAlias = Callable[..., dict[str, str]]


def _plant_egg_info(directory: Path, *, version: str | None) -> None:
    """Write a stray `itaca.egg-info/PKG-INFO` that `sys.path` will find."""
    egg = directory / "itaca.egg-info"
    egg.mkdir()
    lines = ["Metadata-Version: 2.1", "Name: itaca"]
    if version is not None:
        lines.append(f"Version: {version}")
    (egg / "PKG-INFO").write_text("\n".join(lines) + "\n", encoding="utf-8")


_ROOT = Path(__file__).resolve().parents[2]
_VERSION_FILE = _ROOT / "itaca" / "core" / "_version.py"


def _child(cwd: Path, env: EnvFactory, source: str) -> str:
    """Run `source` in a fresh interpreter under `cwd`, against THIS tree.

    `child_env` arrives as the fixture rather than by importing it from
    `conftest`, which is what `tests/conftest.py` prescribes for modules
    in a subdirectory: `tests/core/` has no `conftest.py` today, so a
    top-level `from conftest import ...` resolves, and the day someone
    adds one the name collides and this module fails at collection for a
    reason unrelated to what it tests.
    """
    done = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env(PYTHONPATH=str(_ROOT)),
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return str(done.stdout.strip())


def _reported_version(cwd: Path, env: EnvFactory) -> str:
    """`itaca.__version__` as a fresh interpreter launched in `cwd` sees it.

    PYTHONPATH names THE TREE UNDER TEST, and that is the whole point of
    this helper rather than an incidental detail. Without it the child
    imports whatever `pip install -e .` put on `sys.path`, which on a
    developer machine is a DIFFERENT checkout from the one being
    reviewed: a reviewer's detached worktree, a fresh clone or a CI leg
    before its install would all have been certified by measuring
    somebody else's copy. Measured while this was missing: the plant was
    defeated at `0.3.0.dev26` by the installed copy while the tree under
    test resolved it to `9.9.9.dev99`, and this module was green.
    """
    return _child(cwd, env, "import itaca; print(repr(itaca.__version__))")


def _imported_file(cwd: Path, env: EnvFactory) -> str:
    """Where the child actually imported `itaca` from, so the plant is not vacuous."""
    return _child(cwd, env, "import itaca; print(itaca.__file__)")


class TestTheWorkingDirectoryDoesNotDecideTheVersion:
    """Face 2: a stray build artifact must not name the library.

    Both meanings are asserted, against the tree under test, because
    which one applies is decided by whether that tree has ever been
    BUILT and not by anything in the source. A module that assumed one
    of them would be green for the wrong reason half the time: the
    commit tier on a fresh clone exercises the metadata fallback while a
    full-suite run exercises the version-file path, since the artifact
    test builds in place and writes the file as a side effect.
    """

    def test_the_child_imports_the_tree_under_test(
        self, tmp_path: Path, child_env: EnvFactory
    ) -> None:
        """Everything below measures THIS checkout, not the installed one.

        The guard on the guard. Without it the assertions below can pass
        by measuring a different copy of the library, which is what they
        did before this test existed.
        """
        assert _imported_file(tmp_path, child_env) == str(
            _ROOT / "itaca" / "__init__.py"
        )

    def test_a_stray_egg_info_does_not_shadow_a_built_tree(
        self, tmp_path: Path, child_env: EnvFactory
    ) -> None:
        """On a tree carrying its version file, the plant loses.

        Measured before the fix: `9.9.9.dev99` with the plant and
        `0.3.0.dev24` without it, same interpreter, same commit. This is
        the face the reordering closes.
        """
        if not _VERSION_FILE.is_file():
            pytest.skip(
                f"{_VERSION_FILE} does not exist, so this tree has never been "
                f"built and the version-file path cannot be exercised; the "
                f"sibling test asserts what is true instead"
            )
        clean = tmp_path / "clean"
        planted = tmp_path / "planted"
        clean.mkdir()
        planted.mkdir()
        _plant_egg_info(planted, version=_PLANTED)

        assert _reported_version(planted, child_env) == _reported_version(
            clean, child_env
        )

    def test_an_unbuilt_tree_is_still_shadowed_and_that_is_the_residual(
        self, tmp_path: Path, child_env: EnvFactory
    ) -> None:
        """The part DD-48 did NOT close, pinned rather than assumed.

        A tree with no generated version file falls through to the
        metadata path, which is the `sys.path` scan the finding is
        about, so the plant still wins there. That is a real residual on
        a fresh clone, a detached worktree, or a CI leg before
        `pip install -e .`, and the closure written for it would be
        wrong: an editable install legitimately keeps its `dist-info` in
        site-packages while its code sits in the source tree, so
        refusing when those locations differ would refuse the ordinary
        development case.

        Asserting it makes the residual FALSIFIABLE. The day the
        fallback stops being cwd-dependent this test fails, and that
        failure is the signal to delete it and DD-48's residual
        paragraph together.
        """
        if _VERSION_FILE.is_file():
            pytest.skip(
                f"{_VERSION_FILE} exists, so this tree resolves through the "
                f"version file and the residual is not reachable here; the "
                f"sibling test asserts what is true instead"
            )
        _plant_egg_info(tmp_path, version=_PLANTED)
        assert _reported_version(tmp_path, child_env) == repr(_PLANTED), (
            "an unbuilt tree no longer takes its version from a stray "
            "egg-info on sys.path. That is an IMPROVEMENT and this test is "
            "now wrong: delete it, and delete the residual paragraph in "
            "DD-48 and in itaca/core/version.py with it."
        )

    def test_the_plant_really_does_shadow_the_metadata(
        self, tmp_path: Path, child_env: EnvFactory
    ) -> None:
        """The plant is a real shadow, so neither test above is vacuous.

        Without this, `test_a_stray_egg_info_does_not_shadow_a_built_tree`
        would pass just as well if the plant were never found at all,
        which would make it a measurement of nothing. This asserts the
        `importlib.metadata` layer alone, so it holds on a built and an
        unbuilt tree alike: the shadow is a property of the `sys.path`
        scan, and what differs between the two trees is only whether the
        resolver consults that scan.
        """
        _plant_egg_info(tmp_path, version=_PLANTED)
        reported = _child(
            tmp_path,
            child_env,
            "import importlib.metadata as m; print(m.version('itaca'))",
        )
        assert reported == _PLANTED, (
            f"the plant did not shadow the metadata lookup, so the tests "
            f"above measure nothing; importlib.metadata reports {reported!r} "
            f"from a directory holding an itaca.egg-info that declares "
            f"{_PLANTED!r}"
        )


class TestAVersionIsNeverNull:
    """Face 3: a version that cannot be resolved is refused, not returned."""

    def test_metadata_without_a_version_field_does_not_yield_none(
        self, tmp_path: Path, child_env: EnvFactory
    ) -> None:
        """End to end: a version-less PKG-INFO on `sys.path` is survivable.

        Measured before the fix: `itaca.__version__` was ``None``, and
        nothing anywhere raised.

        On a BUILT tree this passes without consulting the metadata at
        all, so it would be inert as a Face 3 measurement on its own;
        the falsifiable half is the unit below, which drives the
        resolver with both sources silenced. What this still earns is
        the end-to-end statement that a malformed distribution on
        `sys.path` cannot make `import itaca` produce a null.

        On an UNBUILT tree the same plant silences both sources at once,
        because the version-less egg-info shadows the real install and
        there is no version file behind it, so the honest answer is the
        REFUSAL rather than a string. That is asserted in its own test
        below rather than folded in here: "returns a version" and
        "refuses" are different guarantees, and a test that accepted
        either would assert neither. Found by running this module
        against a tree with no version file, where it failed on the
        child's exit status.
        """
        if not _VERSION_FILE.is_file():
            pytest.skip(
                f"{_VERSION_FILE} does not exist, so a version-less plant "
                f"silences both sources and the refusal is the right answer; "
                f"the sibling test asserts that instead"
            )
        _plant_egg_info(tmp_path, version=None)
        reported = _reported_version(tmp_path, child_env)
        assert reported != "None"
        assert reported.startswith("'")

    def test_an_unbuilt_tree_refuses_when_the_plant_has_no_version(
        self, tmp_path: Path, child_env: EnvFactory
    ) -> None:
        """Both sources silenced, end to end, and the answer is the refusal.

        This is Face 3's end-to-end half, reachable only where there is
        no version file: the plant shadows the real distribution and
        carries no `Version:`, so nothing can answer. What must NOT
        happen is the original defect, a null travelling into
        `Provenance.itaca_version` at a field typed `str`.
        """
        if _VERSION_FILE.is_file():
            pytest.skip(
                f"{_VERSION_FILE} exists, so the version file answers and both "
                f"sources cannot be silenced from outside; the sibling test "
                f"asserts what is true instead"
            )
        _plant_egg_info(tmp_path, version=None)
        done = subprocess.run(
            [sys.executable, "-c", "import itaca; print(repr(itaca.__version__))"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=child_env(PYTHONPATH=str(_ROOT)),
            timeout=120,
        )
        assert done.returncode != 0, (
            f"a tree with no version file and a version-less distribution "
            f"resolved anyway, to {done.stdout.strip()}"
        )
        assert "VersionResolutionError" in done.stderr, done.stderr
        assert "None" not in done.stdout

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

    def test_a_generated_version_file_that_does_not_parse_is_survivable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt version file degrades to the metadata, it does not kill import.

        The file is GENERATED, so it can exist and be unusable: an
        interrupted or truncated write, or a template using syntax the
        running interpreter rejects. It is read at `import itaca` time
        and it is now FIRST, so a narrow `except ImportError` let a
        SyntaxError out of the import statement itself. Measured before
        this was widened, with `itaca/core/_version.py` truncated to
        `__version__ = (`::

            python -c "import itaca"
            SyntaxError: '(' was never closed

        Not the three-part `VersionResolutionError` this module exists
        to give, and the metadata path that would have answered
        correctly was never reached.
        """
        import importlib.metadata

        broken = types.ModuleType("itaca.core._version")

        def _raise() -> None:
            raise SyntaxError("simulated truncated generated file")

        monkeypatch.setattr(importlib.metadata, "version", lambda _name: "4.5.6")
        monkeypatch.setitem(sys.modules, "itaca.core._version", broken)
        monkeypatch.setattr(
            broken, "__getattr__", lambda _name: _raise(), raising=False
        )

        assert _resolve() == "4.5.6"

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
