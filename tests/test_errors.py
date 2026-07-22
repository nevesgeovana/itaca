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


def test_base_is_exposed_at_top_level() -> None:
    assert itc.ITACAError is ITACAError


@pytest.mark.parametrize("family", FAMILIES)
def test_families_inherit_from_base(family: type) -> None:
    assert issubclass(family, ITACAError)
    assert issubclass(family, Exception)


@pytest.mark.parametrize(("leaf", "family"), list(M0_LEAVES.items()))
def test_leaves_inherit_from_family(leaf: type, family: type) -> None:
    assert issubclass(leaf, family)
    assert issubclass(leaf, ITACAError)


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
    for cls in [ITACAError, *FAMILIES, *M0_LEAVES]:
        assert cls.__name__ in errors.__all__


def test_validation_reexports_formatter() -> None:
    # utils/validation.py is the shared entry point for io/ and ops/.
    from itaca.utils.validation import format_error_message as reexported

    assert reexported is format_error_message
