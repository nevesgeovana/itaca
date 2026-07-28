"""Tests for the ITACAError hierarchy (DD-10, REQ-81, SRS Chapter 5).

Usage example (the contract under test)::

    import itaca as itc
    from itaca.core.errors import DimensionNotFoundError

    try:
        ...
    except itc.ITACAError as exc:
        print(exc)   # object involved, operation attempted, suggested fix
"""

import pytest

import itaca as itc
from itaca.core import errors
from itaca.core.errors import (
    AxesError,
    CorrelationKeyError,
    CorrelationMatrixError,
    DataError,
    DependencyError,
    DimensionNotFoundError,
    DraftModeExportError,
    HashMismatchError,
    ITACAError,
    LoadCoordinateError,
    MissingDependencyError,
    NonNumericDimensionError,
    OperatingModeMixError,
    PivotDuplicateError,
    PivotError,
    ProcessorError,
    ProvenanceError,
    SelectionError,
    UncertaintyCompatibilityError,
    UncertaintyError,
    UncertaintyKeyError,
    VariableNotFoundError,
    format_error_message,
)

FAMILIES = [
    DataError,
    ProcessorError,
    ProvenanceError,
    UncertaintyError,
    DependencyError,
    AxesError,
]

# M0 leaf classes mapped to their family (SRS Table: ITACAError hierarchy).
M0_LEAVES = {
    LoadCoordinateError: DataError,
    PivotError: DataError,
    PivotDuplicateError: DataError,
    DimensionNotFoundError: DataError,
    VariableNotFoundError: DataError,
    NonNumericDimensionError: DataError,
    SelectionError: DataError,
    DraftModeExportError: ProvenanceError,
    OperatingModeMixError: ProvenanceError,
    HashMismatchError: ProvenanceError,
    UncertaintyKeyError: UncertaintyError,
    UncertaintyCompatibilityError: UncertaintyError,
    CorrelationKeyError: UncertaintyError,
    CorrelationMatrixError: UncertaintyError,
    MissingDependencyError: DependencyError,
}

# Leaves are DISCOVERED, not enumerated. The map above is kept as the
# M0 floor: it pins the classes that must exist, so a walk that comes
# back empty fails instead of passing every check vacuously. The checks
# themselves run over everything the module actually defines, because an
# enumerated list stops covering the newest class at exactly the moment
# it is least reviewed (DD-33, and the same defect this file carried:
# the five ProcessorError leaves of M1 were named in neither list).


def discovered_leaves() -> dict[type[ITACAError], type[ITACAError]]:
    """Every public ITACAError subclass that is not itself a family."""
    found: dict[type[ITACAError], type[ITACAError]] = {}
    for name in dir(errors):
        if name.startswith("_"):
            continue
        candidate = getattr(errors, name)
        if not isinstance(candidate, type) or not issubclass(candidate, ITACAError):
            continue
        if candidate is ITACAError or candidate in FAMILIES:
            continue
        parents = [family for family in FAMILIES if issubclass(candidate, family)]
        found[candidate] = parents[0] if parents else ITACAError
    return found


def test_base_is_exposed_at_top_level() -> None:
    assert itc.ITACAError is ITACAError


@pytest.mark.parametrize("family", FAMILIES)
def test_families_inherit_from_base(family: type) -> None:
    assert issubclass(family, ITACAError)
    assert issubclass(family, Exception)


@pytest.mark.parametrize(
    ("leaf", "family"),
    sorted(discovered_leaves().items(), key=lambda item: item[0].__name__),
)
def test_leaves_inherit_from_family(leaf: type, family: type) -> None:
    assert issubclass(leaf, family)
    assert issubclass(leaf, ITACAError)


def test_the_leaf_walk_covers_at_least_the_m0_floor() -> None:
    discovered = discovered_leaves()
    missing = sorted(cls.__name__ for cls in M0_LEAVES if cls not in discovered)
    assert not missing, (
        f"the leaf walk missed {missing}; every check in this module runs "
        "over what it returns, so a broken walk would pass them all while "
        "checking nothing."
    )


def test_every_leaf_belongs_to_a_family() -> None:
    # AccessorRegistrationError sits directly under ITACAError by design
    # (SRS Chapter 5 exception table); everything else has a family, so
    # `except family` catches it.
    orphans = sorted(
        leaf.__name__
        for leaf, family in discovered_leaves().items()
        if family is ITACAError and leaf.__name__ != "AccessorRegistrationError"
    )
    assert not orphans, (
        f"error class(es) {orphans} derive from ITACAError but from no "
        "family, so a caller catching the family misses them; give each a "
        "family or record it in the SRS exception table (REQ-81, DD-10)."
    )


def test_three_part_message() -> None:
    # REQ-81: object involved, operation attempted, suggested fix.
    exc = DimensionNotFoundError(
        "VarFrame 'db'",
        "select along dimension 'beta' which is not present",
        "use one of the dimensions listed by db.summary()",
    )
    text = str(exc)
    assert "VarFrame 'db'" in text
    assert "select along dimension 'beta'" in text
    assert "Suggested fix:" in text
    assert "db.summary()" in text
    assert exc.obj == "VarFrame 'db'"
    assert exc.operation.startswith("select along")
    assert exc.fix.startswith("use one of")


def test_family_level_catch() -> None:
    # DD-10: users can catch at family level.
    with pytest.raises(DataError):
        raise PivotError(
            "VarFrame 'db'",
            "pivot() called without dims on a structured VarFrame",
            "pass dims=[...] or operate on a datapoint-mode VarFrame",
        )
    with pytest.raises(ITACAError):
        raise MissingDependencyError(
            "pandas",
            "itc.load(df) requires the optional pandas bridge",
            "install it via pip install itaca[pandas]",
        )


def test_format_error_message_contains_all_parts() -> None:
    msg = format_error_message("obj", "operation attempted", "the fix")
    assert "obj" in msg
    assert "operation attempted" in msg
    assert "Suggested fix: the fix" in msg


def test_all_public_error_names_are_exported() -> None:
    for cls in [ITACAError, *FAMILIES, *discovered_leaves()]:
        assert cls.__name__ in errors.__all__


def test_validation_reexports_formatter() -> None:
    # utils/validation.py is the shared entry point for io/ and ops/.
    from itaca.utils.validation import format_error_message as reexported

    assert reexported is format_error_message
