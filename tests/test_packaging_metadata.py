"""Packaging metadata against `pyproject.toml` (FND-015, FND-056).

Reproduction (TDD anchor), the shortest calls that exhibit the defects::

    python -c "import tomllib,pathlib; p=tomllib.loads(
        pathlib.Path('pyproject.toml').read_text())['project']; \
        print(p['license']); print([c for c in p['classifiers'] \
        if c.startswith('License ::')])"
    {'text': 'MIT'}                              # FND-056, legacy table form
    ['License :: OSI Approved :: MIT License']   # FND-056, deprecated classifier

FND-015. REQ-83's table is NORMATIVE: it is the dependency version
policy, in the authoritative specification, of a public library. It was
hand-maintained beside `pyproject.toml` and drifted in both directions
at once. It omitted six declared dependencies, stated a ruff range where
the file carries an exact pin, and carried five rows for packages
declared in no extra at all, so a reader could not tell a policy from a
plan.

The table is not generated, because a generated normative table cannot
carry the ROLE and the USED FOR columns, which are the reason it is in
the specification rather than in a lockfile. It is CHECKED instead, in
both directions, which gives the same protection from drift:

* every requirement `pyproject.toml` declares has a row, and the row's
  range is that requirement's specifier, character for character;
* every row claiming a declared role names something `pyproject.toml`
  actually declares.

The second direction is the one that matters more, and it is why the
roles were split. `planned` and `external` rows are policy for things
not declared yet, and a row may not sit in one of those roles while the
package IS declared: that is exactly how five rows became unfalsifiable.

FND-056. The license was declared in the legacy setuptools table form,
so the built artifact carried a free-text `License: MIT` field and the
deprecated `License :: OSI Approved :: MIT License` classifier, while
`License-Expression` was absent. The distinction is not cosmetic: a
free-text field is not machine-checkable, and PEP 639 exists because
downstream redistributors have to answer the license question
programmatically. Metadata-Version 2.4, which this project already
emits, is the version that introduces the field.
"""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SRS_TABLE = ROOT / "docs" / "srs" / "chapters" / "07_non_functional_requirements.tex"

# A role says WHERE pyproject.toml declares the dependency, so that the
# check knows which section to look in and can refuse a row that claims
# a role its declaration does not support.
DECLARED_ROLES = {"required", "optional", "dev", "build"}
UNDECLARED_ROLES = {"planned", "external"}

# PEP 639's `license` key as an SPDX expression, and `license-files`,
# are understood by setuptools from 77 onward. A lower floor in
# `build-system.requires` would let a build silently fall back to the
# legacy handling, which is the defect itself.
SPDX_SETUPTOOLS_FLOOR = 77

#: Floors this project holds for a SECURITY reason, as
#: ``{package: (fixed_version, advisory)}``. Without this the reason for
#: a floor lives only in a comment, and relaxing the specifier back to a
#: vulnerable range reddens nothing: the table check compares the SRS to
#: `pyproject.toml`, so moving both together is silent.
SECURITY_FLOORS = {
    "pytest": ("9.0.3", "CVE-2025-71176, insecure temporary-directory handling"),
}

#: Declared in an extra for a reason a later editor would not guess, as
#: ``{package: (extra, why)}``. `pandas` is the case that motivated it:
#: it lives in `dev` as well as in its own extra because a test imports
#: it at module scope, so removing it from `dev` breaks the DOCUMENTED
#: `pip install -e ".[dev]"` at collection time, which is ITACA-015. The
#: role check below reads a row's single role and cannot see the second
#: membership, so it is asserted here by name.
LOAD_BEARING_EXTRA_MEMBERSHIPS = {
    "pandas": ("dev", "ITACA-015: a test imports pandas at module scope"),
}

#: Floors, so that emptying either registry above cannot make its guard
#: vanish. A parametrized test over an empty collection SKIPS, which
#: reads like nothing was needed rather than like a guard was deleted.
_SECURITY_FLOOR_COUNT = 1
_LOAD_BEARING_MEMBERSHIP_COUNT = 1

_ROW = re.compile(
    r"^\\code\{(?P<name>[^}]+)\}\s*&\s*(?P<role>\w+)\s*&"
    r"(?P<used_for>[^&]*)&\s*(?P<range>.*?)\\\\\s*$"
)


def _pyproject() -> dict[str, Any]:
    parsed: dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return parsed


def _unescape(value: str) -> str:
    """Undo the LaTeX escaping the table needs in text mode.

    Applied to the RANGE as well as to the name, which it was not: a
    specifier carrying an environment marker (`; python_version < "3.13"`)
    must be written `python\\_version` in the `.tex`, and comparing that
    against `pyproject.toml` character for character would make
    `test_every_row_states_the_declared_specifier` unsatisfiable, with
    the only remedies being an unbuildable document or a test edit.
    """
    return value.replace(r"\_", "_").strip()


def _table_rows() -> dict[str, tuple[str, str]]:
    """Return ``{name: (role, range)}`` parsed from the REQ-83 table.

    Every `\\\\`-terminated line between the header rule and the end of
    the tabular MUST parse. A regex that silently skips what it cannot
    match would drop a row rather than fail, and a dropped `planned` or
    `external` row leaves exactly the unfalsifiable row FND-015 was
    about: no other check names those, so nothing else would notice.
    Duplicate names are refused for the same reason, since a dict
    assignment collapses two rows into the last one and a stale
    contradictory row above a correct one would be invisible.
    """
    text = SRS_TABLE.read_text(encoding="utf-8")
    start = text.index(r"\label{tab:dependency-versions}")
    body_start = text.index(r"\midrule", start)
    end = text.index(r"\bottomrule", body_start)
    rows: dict[str, tuple[str, str]] = {}
    unparsed: list[str] = []
    for line in text[body_start:end].splitlines():
        stripped = line.strip()
        if not stripped.endswith(r"\\"):
            continue
        match = _ROW.match(stripped)
        if match is None:
            unparsed.append(stripped)
            continue
        name = _unescape(match["name"])
        raw_range = match["range"].strip()
        declared = re.fullmatch(r"\\code\{(?P<spec>.+)\}", raw_range)
        assert name not in rows, (
            f"the REQ-83 table declares {name!r} twice; the second row would "
            f"silently replace the first and a stale contradictory row would "
            f"be invisible to every check here"
        )
        rows[name] = (
            match["role"].strip(),
            _unescape(declared["spec"]) if declared else raw_range,
        )
    assert not unparsed, (
        f"{len(unparsed)} row(s) of the REQ-83 table did not parse, so they "
        f"are checked by nothing: {unparsed}"
    )
    assert rows, f"parsed no rows from the REQ-83 table in {SRS_TABLE}"
    return rows


def _declared() -> dict[str, tuple[set[str], str]]:
    """Return ``{name: (roles, specifier)}`` for everything pyproject declares."""
    parsed = _pyproject()
    project = parsed["project"]
    found: dict[str, tuple[set[str], str]] = {
        "python": ({"required"}, project["requires-python"])
    }

    def _add(requirement: str, role: str) -> None:
        match = re.fullmatch(r"(?P<name>[A-Za-z0-9._-]+)(?P<spec>.*)", requirement)
        assert match is not None, f"unparsable requirement: {requirement!r}"
        name = match["name"]
        spec = match["spec"].strip()
        roles, existing = found.get(name, (set(), spec))
        assert existing == spec, (
            f"{name} is declared twice in pyproject.toml with different "
            f"specifiers, {existing!r} and {spec!r}; the REQ-83 table cannot "
            f"state one range for it"
        )
        found[name] = (roles | {role}, spec)

    for requirement in project["dependencies"]:
        _add(requirement, "required")
    for extra, requirements in project["optional-dependencies"].items():
        role = "dev" if extra == "dev" else "optional"
        for requirement in requirements:
            _add(requirement, role)
    for requirement in parsed["build-system"]["requires"]:
        _add(requirement, "build")
    return found


class TestTheDependencyTableMatchesPyproject:
    """FND-015: a normative table that nothing checks drifts both ways."""

    def test_every_declared_dependency_has_a_row(self) -> None:
        """Nothing pyproject.toml installs is missing from the table.

        Measured before the fix: `build`, `pyyaml`, `scipy`,
        `setuptools`, `setuptools-scm` and `uncertainties` were declared
        and unnamed. A dependency policy that omits the dependencies is
        not a policy.
        """
        missing = sorted(set(_declared()) - set(_table_rows()))
        assert not missing, (
            f"pyproject.toml declares {missing} and the REQ-83 dependency "
            f"table names none of them. The table is normative, so an "
            f"omission is a specification defect and not a documentation "
            f"one (FND-015)."
        )

    def test_every_row_states_the_declared_specifier(self) -> None:
        """The range in the table is the specifier in the file, exactly.

        Measured before the fix: the table said ruff `>=0.5,<1.0` where
        `pyproject.toml` carries the exact pin `==0.15.22`, which is
        deliberate and load-bearing (DD-29, the pin's authority; REQ-96
        is the CI-to-hook mirror the pin serves), so the table
        contradicted the reason the pin exists.
        """
        declared = _declared()
        wrong = {
            name: (stated, declared[name][1])
            for name, (_role, stated) in _table_rows().items()
            if name in declared and stated != declared[name][1]
        }
        assert not wrong, (
            f"the REQ-83 table and pyproject.toml disagree on {len(wrong)} "
            f"range(s), as {{name: (table, pyproject)}}: {wrong}"
        )

    def test_every_row_claims_a_role_its_declaration_supports(self) -> None:
        """A row's role names where pyproject declares it, or that it does not.

        Measured before the fix: `matplotlib`, `plotly`, `smt`,
        `tectonic` and `pdflatex` sat under the role `optional` while
        appearing in no extra, so five rows of a normative table could
        not be checked against anything.
        """
        declared = _declared()
        problems: list[str] = []
        for name, (role, _range) in _table_rows().items():
            if role in UNDECLARED_ROLES:
                if name in declared:
                    problems.append(
                        f"{name} has role {role!r} but pyproject.toml declares "
                        f"it under {sorted(declared[name][0])}"
                    )
                continue
            assert role in DECLARED_ROLES, f"{name} has unknown role {role!r}"
            if name not in declared:
                problems.append(
                    f"{name} has role {role!r} but pyproject.toml declares it "
                    f"nowhere; use 'planned' for a package this project "
                    f"intends to declare, or 'external' for something that is "
                    f"not a Python package"
                )
            elif role not in declared[name][0]:
                problems.append(
                    f"{name} has role {role!r} but pyproject.toml declares it "
                    f"under {sorted(declared[name][0])}"
                )
        assert not problems, "\n".join(problems)


class TestSecurityFloorsAreDeclaredAndInstalled:
    """FND-067: a floor taken for a CVE is a fact, not a comment."""

    def test_the_registry_is_not_empty(self) -> None:
        """A parametrized guard over an empty dict SKIPS rather than fails.

        Which means the whole of this class disappears if someone
        removes the row, and pytest reports a skip that reads like
        nothing was needed. The date and version site lists in
        `tests/test_house_style.py` pin their counts for exactly this
        reason; these registries were added without one.
        """
        assert len(SECURITY_FLOORS) >= _SECURITY_FLOOR_COUNT, (
            f"SECURITY_FLOORS holds {len(SECURITY_FLOORS)} entries, below the "
            f"{_SECURITY_FLOOR_COUNT} recorded. Removing one takes its guard "
            f"with it silently. Remove the floor and this count in the same "
            f"commit, with the reason the advisory no longer applies."
        )

    @pytest.mark.parametrize("package", sorted(SECURITY_FLOORS))
    def test_the_declared_floor_is_at_or_above_the_advisorys_fix(
        self, package: str
    ) -> None:
        """`pyproject.toml` may not allow a version the advisory calls vulnerable.

        Measured before this guard existed: nothing in `tests/` named
        `9.0.3` or the CVE, so relaxing the pin back to `>=8.0` reddened
        nothing at all.
        """
        fixed, advisory = SECURITY_FLOORS[package]
        specifier = _declared()[package][1]
        assert SpecifierSet(specifier).contains(fixed), (
            f"{package} is declared {specifier!r}, which excludes {fixed}, the "
            f"version that fixes {advisory}."
        )
        below = Version(fixed).base_version + ".dev0"
        assert not SpecifierSet(specifier, prereleases=True).contains(below), (
            f"{package} is declared {specifier!r}, which still admits {below}, "
            f"below the fix for {advisory}."
        )

    @pytest.mark.parametrize("package", sorted(SECURITY_FLOORS))
    def test_the_running_environment_actually_satisfies_the_floor(
        self, package: str
    ) -> None:
        """The declaration is not the installation.

        A shared virtualenv keeps whatever it was last given, so the
        floor can be correct in the file and absent from the interpreter
        running this suite. That gap is FND-046's own shape one tool
        over, and it is the reason this assertion is separate from the
        one above.
        """
        fixed, advisory = SECURITY_FLOORS[package]
        installed = importlib.metadata.version(package)
        assert Version(installed) >= Version(fixed), (
            f"{package} {installed} is installed here and {fixed} is the fix "
            f'for {advisory}. Reinstall with pip install -e ".[dev]".'
        )


class TestLoadBearingExtraMemberships:
    """A membership whose reason a later editor would not guess."""

    def test_the_registry_is_not_empty(self) -> None:
        """Same shape as the security-floor registry: empty parametrize skips."""
        assert len(LOAD_BEARING_EXTRA_MEMBERSHIPS) >= _LOAD_BEARING_MEMBERSHIP_COUNT, (
            f"LOAD_BEARING_EXTRA_MEMBERSHIPS holds "
            f"{len(LOAD_BEARING_EXTRA_MEMBERSHIPS)} entries, below the "
            f"{_LOAD_BEARING_MEMBERSHIP_COUNT} recorded; removing one takes "
            f"its guard with it silently."
        )

    @pytest.mark.parametrize("package", sorted(LOAD_BEARING_EXTRA_MEMBERSHIPS))
    def test_the_membership_survives(self, package: str) -> None:
        """Measured gap: the SRS row carries ONE role, so a second is unguarded.

        `pandas` sits in its own extra and in `dev`; the table row says
        `optional` and the role check passes on membership, so dropping
        it from `dev` left the SRS, this module and
        `tests/test_tooling_config.py` all green while regressing
        ITACA-015.
        """
        extra, why = LOAD_BEARING_EXTRA_MEMBERSHIPS[package]
        roles = _declared()[package][0]
        expected = "dev" if extra == "dev" else "optional"
        assert expected in roles, (
            f"{package} is no longer declared in the {extra!r} extra. It is "
            f"there for a reason that is not visible from the extra itself: "
            f"{why}."
        )


class TestTheLicenseIsAnSpdxExpression:
    """FND-056: PEP 639, so the license is machine-readable."""

    def test_license_is_an_spdx_string_and_not_the_legacy_table(self) -> None:
        """Measured before the fix: `license = { text = "MIT" }`."""
        license_value = _pyproject()["project"]["license"]
        assert isinstance(license_value, str), (
            f"pyproject.toml declares license as {license_value!r}, the legacy "
            f"setuptools table form. PEP 639 wants an SPDX expression, which "
            f"is what makes the field machine-checkable for a redistributor "
            f"(FND-056)."
        )
        assert license_value == "MIT"

    def test_the_deprecated_license_classifier_is_gone(self) -> None:
        """A classifier and an expression are two answers to one question.

        Measured before the fix: `License :: OSI Approved :: MIT
        License` was declared beside a license field, and PEP 639
        deprecates the classifier precisely because two declarations can
        disagree.
        """
        stale = [
            classifier
            for classifier in _pyproject()["project"]["classifiers"]
            if classifier.startswith("License ::")
        ]
        assert not stale, (
            f"pyproject.toml still declares {stale}. PEP 639 deprecates the "
            f"license classifiers in favour of the SPDX expression (FND-056)."
        )

    def test_the_license_file_is_declared_so_it_reaches_the_artifact(self) -> None:
        """The text of the license ships, not only its name."""
        declared = _pyproject()["project"].get("license-files")
        assert declared, (
            "pyproject.toml declares no license-files, so PEP 639 leaves the "
            "license TEXT out of the built artifact and a consumer gets the "
            "name of a license without its terms (FND-056)."
        )
        for pattern in declared:
            assert list(ROOT.glob(pattern)), (
                f"license-files declares {pattern!r} and it matches no file"
            )

    def test_the_build_requires_a_setuptools_that_understands_pep_639(self) -> None:
        """A floor below 77 lets a build fall back to the legacy handling.

        Without this the two halves disagree silently: `pyproject.toml`
        states an SPDX expression while a conforming build environment
        is free to install a setuptools that cannot emit one.
        """
        requires = _pyproject()["build-system"]["requires"]
        pin = next(r for r in requires if r.startswith("setuptools") and "scm" not in r)
        match = re.search(r">=\s*(\d+)", pin)
        assert match is not None, f"unparsable setuptools requirement: {pin!r}"
        assert int(match.group(1)) >= SPDX_SETUPTOOLS_FLOOR, (
            f"build-system.requires carries {pin!r}, and PEP 639's `license` "
            f"expression and `license-files` need setuptools "
            f">={SPDX_SETUPTOOLS_FLOOR}. A lower floor lets a conforming build "
            f"emit the legacy metadata this change removed (FND-056)."
        )
