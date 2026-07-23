"""The ITACAError exception hierarchy (DD-10, REQ-81).

Families inherit from :class:`ITACAError`; specific classes inherit
from families. Every message carries three parts (REQ-81): the object
involved, the operation attempted, and a suggested fix. Leaf classes
belonging to later milestones are added together with their features;
the families are complete from M0.
"""

__all__ = [
    "AccessorRegistrationError",
    "AxesError",
    "AxisNotFoundError",
    "AxisTranslationError",
    "ConcatOverlapError",
    "CorrelationKeyError",
    "CorrelationMatrixError",
    "DataError",
    "DependencyError",
    "DimensionNotFoundError",
    "DraftModeExportError",
    "FitDegreeError",
    "HashMismatchError",
    "ITACAError",
    "LoadCoordinateError",
    "MissingDependencyError",
    "NonNumericDimensionError",
    "OperatingModeMixError",
    "PivotDuplicateError",
    "PivotError",
    "ProcessorError",
    "ProvenanceError",
    "RotationMatrixError",
    "SelectionError",
    "UncertaintyCompatibilityError",
    "UncertaintyError",
    "UncertaintyKeyError",
    "VariableNotFoundError",
    "VectorGroupError",
    "format_error_message",
]


def format_error_message(obj: str, operation: str, fix: str) -> str:
    """Build the canonical three-part ITACA error message (REQ-81).

    Parameters
    ----------
    obj : str
        The variable or object involved, e.g. ``"VarFrame 'db'"``.
    operation : str
        The operation attempted and why it failed.
    fix : str
        A concrete, actionable suggestion for the user.

    Returns
    -------
    str
        The assembled message, containing all three parts.

    Examples
    --------
    >>> format_error_message("VarFrame 'db'", "pivot failed", "pass dims=[...]")
    "VarFrame 'db': pivot failed. Suggested fix: pass dims=[...]"
    """
    return f"{obj}: {operation}. Suggested fix: {fix}"


class ITACAError(Exception):
    """Base class for all ITACA-specific exceptions (DD-10).

    Parameters
    ----------
    obj : str
        The variable or object involved.
    operation : str
        The operation attempted and why it failed.
    fix : str
        A concrete, actionable suggestion for the user.

    Examples
    --------
    >>> raise ITACAError("VarFrame 'db'", "demo", "catch ITACAError")
    Traceback (most recent call last):
    itaca.core.errors.ITACAError: VarFrame 'db': demo. Suggested fix: catch ITACAError
    """

    def __init__(self, obj: str, operation: str, fix: str) -> None:
        self.obj = obj
        self.operation = operation
        self.fix = fix
        super().__init__(format_error_message(obj, operation, fix))


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------


class DataError(ITACAError):
    """Structural problems in data: dimensions, variables, selection, pivot."""


class ProcessorError(ITACAError):
    """Processor construction, validation, and .itceq parsing problems."""


class ProvenanceError(ITACAError):
    """Operating-mode guards, hash drift, and pipeline compatibility."""


class UncertaintyError(ITACAError):
    """Uncertainty assignment, correlation, and propagation problems."""


class DependencyError(ITACAError):
    """Missing optional dependencies (REQ-84)."""


class AxesError(ITACAError):
    """Axis registration, vector-group resolution, and rotation problems."""


# ---------------------------------------------------------------------------
# DataError leaves (M0)
# ---------------------------------------------------------------------------


class LoadCoordinateError(DataError):
    """itc.load dict-mode coordinate tuple length does not match dims (REQ-03)."""


class PivotError(DataError):
    """db.pivot called on an already-structured VarFrame without dims (REQ-14)."""


class PivotDuplicateError(DataError):
    """Datapoints share identical coordinates on all requested dims (REQ-14)."""


class DimensionNotFoundError(DataError):
    """A dimension referenced in an operation is absent."""


class VariableNotFoundError(DataError):
    """A variable referenced in an equation or operation is absent."""


class NonNumericDimensionError(DataError):
    """Numerical operation requested on a string-valued dimension."""


class SelectionError(DataError):
    """A coordinate value in select is not present (REQ-20)."""


# ---------------------------------------------------------------------------
# DataError leaves (M1)
# ---------------------------------------------------------------------------


class ConcatOverlapError(DataError):
    """itc.concat inputs have overlapping coordinates along `along` (REQ-24)."""


class AxisTranslationError(DataError):
    """interpolate axis-translation target is non-monotonic (REQ-25)."""


class FitDegreeError(DataError):
    """Too few points for the requested polynomial degree (REQ-30).

    The shared leaf for the "needs more points than the degree"
    invariant across ``diff`` (window <= deg), ``smooth`` (savgol
    window <= polyorder), ``interpolate`` (polyfit deg >= points), and
    ``fitmodel`` (deg >= points). REQ-30 originally named
    ``DiffWindowError``; it was unified into this shared leaf at the M1
    Phase B1 checkpoint (SRS document 0.2.0).
    """


# ---------------------------------------------------------------------------
# ProvenanceError leaves (M0)
# ---------------------------------------------------------------------------


class DraftModeExportError(ProvenanceError):
    """db.save on a draft VarFrame without allow_draft=True (REQ-11)."""


class OperatingModeMixError(ProvenanceError):
    """Binary operation mixes draft and production VarFrames (REQ-12)."""


class HashMismatchError(ProvenanceError):
    """itc.open detects source-hash drift (REQ-103)."""


class PipelineCompatibilityError(ProvenanceError):
    """A pipeline cannot be extracted or replayed (REQ-53, REQ-54).

    Raised when ``history.to_pipeline`` spans a non-replayable
    operation (a multi-input ``concat`` or a state-only entry such as
    ``set_uncertainty``), or when ``pipeline.apply`` meets a VarFrame
    that lacks a variable or dimension the recorded sequence needs.
    """


# ---------------------------------------------------------------------------
# UncertaintyError leaves (M0)
# ---------------------------------------------------------------------------


class UncertaintyKeyError(UncertaintyError):
    """set_uncertainty key does not match any variable (REQ-39)."""


class UncertaintyCompatibilityError(UncertaintyError):
    """Non-differentiable function in an expression with uncertainty inputs (REQ-36)."""


class CorrelationKeyError(UncertaintyError):
    """set_correlation references an unknown variable (REQ-40)."""


class CorrelationMatrixError(UncertaintyError):
    """Correlation matrix is not symmetric or violates the |r| <= 1 bound (REQ-40)."""


# ---------------------------------------------------------------------------
# DependencyError leaves (M0)
# ---------------------------------------------------------------------------


class MissingDependencyError(DependencyError):
    """Optional dependency (pandas, matplotlib, plotly, SMT) is absent (REQ-84)."""


# ---------------------------------------------------------------------------
# AxesError leaves (M1)
# ---------------------------------------------------------------------------


class AxisNotFoundError(AxesError):
    """db.rotate target axis is not registered (REQ-38)."""


class VectorGroupError(AxesError):
    """A vector group cannot be resolved from the naming convention (REQ-38)."""


class RotationMatrixError(AxesError):
    """An Axis matrix is not orthogonal, or its definition is ambiguous (REQ-101)."""


# ---------------------------------------------------------------------------
# RuntimeError-carrying leaf for accessors (M1, REQ-106)
# ---------------------------------------------------------------------------


class AccessorRegistrationError(ITACAError):
    """register_accessor name collides with an existing attribute (REQ-106)."""
