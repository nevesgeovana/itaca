"""Tests for the typed no-default sentinel (REQ-105).

Usage example (TDD anchor), the pattern every M1 operation signature
adopts where not-passed must be distinguished from an explicit None::

    import itaca as itc
    from itaca.core.sentinels import NoDefault

    def resample(
        weights: list[float] | None | NoDefault = itc.no_default,
    ) -> str:
        if weights is itc.no_default:
            return "caller did not pass weights"
        if weights is None:
            return "caller explicitly disabled weights"
        return "caller passed weights"
"""

import copy
import pickle
import subprocess
import sys
from pathlib import Path

import itaca as itc
from itaca.core.sentinels import NoDefault, no_default


class TestSingleton:
    def test_module_and_package_expose_the_same_object(self):
        assert itc.no_default is no_default

    def test_is_the_single_enum_member(self):
        assert no_default is NoDefault.no_default
        assert len(NoDefault) == 1

    def test_listed_in_public_api(self):
        assert "no_default" in itc.__all__

    def test_type_import_path_is_pinned(self):
        # The sanctioned annotation import path is part of the public
        # contract (documented in the module docstring); a rename or
        # move must be a deliberate decision, not a refactor accident.
        assert NoDefault.__module__ == "itaca.core.sentinels"


class TestSemantics:
    def test_repr_and_str_are_readable(self):
        assert repr(no_default) == "<no_default>"
        assert str(no_default) == "<no_default>"
        assert f"{no_default}" == "<no_default>"

    def test_distinguishes_not_passed_from_explicit_none(self):
        def probe(value: object = no_default) -> str:
            if value is no_default:
                return "not passed"
            if value is None:
                return "explicit None"
            return "passed"

        assert probe() == "not passed"
        assert probe(None) == "explicit None"
        assert probe(0.0) == "passed"

    def test_is_not_a_valid_data_value(self):
        assert not isinstance(no_default, (int, float, complex, str, bytes))
        # A refactor to a value-comparable form (e.g. StrEnum) would
        # make the sentinel usable as the string "no_default"; keep it
        # unequal to any plain value, including its own backing value.
        assert no_default != "no_default"
        assert no_default != NoDefault.no_default.value


class TestIdentityInvariants:
    def test_copy_preserves_identity(self):
        assert copy.copy(no_default) is no_default
        assert copy.deepcopy(no_default) is no_default

    def test_pickle_round_trip_preserves_identity(self):
        assert pickle.loads(pickle.dumps(no_default)) is no_default


class TestTypingConformance:
    def test_mypy_strict_narrows_the_identity_check(self):
        # The typed half of REQ-105: the docstring's adoption pattern
        # must hold under mypy --strict. The snippet's assignments fail
        # to typecheck if the enum singleton stops narrowing out of the
        # union, so this test falsifies the promise instead of trusting
        # the annotation.
        snippet = Path(__file__).parents[1] / "typing" / "sentinel_narrowing.py"
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--strict", str(snippet)],
            capture_output=True,
            text=True,
            cwd=snippet.parents[2],
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
