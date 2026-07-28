"""The Processor typing protocol (REQ-45).

A processor is anything that satisfies this shape. It is a
``typing.Protocol`` and not a base class on purpose: a domain processor
may carry its own state and its own construction, and nothing here
should force it to inherit. :class:`itaca.pproc.base.EquationProcessor`
is one implementation, the one an .itceq file produces.

The canonical lifecycle is ``validate`` then ``info`` then the call
itself, with ``report`` requested through the call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from itaca.core.varframe import VarFrame

__all__ = ["Processor"]


@runtime_checkable
class Processor(Protocol):
    """The interface every ITACA processor satisfies (REQ-45).

    Attributes
    ----------
    name : str
        Human-readable processor name, recorded in History.
    version : str
        Processor version, recorded alongside the name so a reprocessed
        dataset says which revision of the workflow produced it.

    Notes
    -----
    REQ-45 writes the two attributes as ``name: str`` and
    ``version: str``. They are declared here as read-only properties,
    which is the more permissive of the two readings: a plain attribute
    satisfies a read-only protocol member, while a property does not
    satisfy a settable one. Writing them as settable would therefore
    exclude every implementation that derives its name from a file, the
    .itceq case, without gaining anything a caller uses: nothing sets a
    processor's name.

    Examples
    --------
    >>> from itaca.pproc.protocol import Processor
    >>> isinstance(object(), Processor)
    False
    """

    @property
    def name(self) -> str:
        """Human-readable processor name (REQ-45)."""
        ...

    @property
    def version(self) -> str:
        """Processor version (REQ-45)."""
        ...

    def info(self) -> None:
        """Print what the processor does, its constants, and its order."""
        ...

    def validate(self, db: VarFrame) -> None:
        """Raise if the VarFrame cannot feed this processor.

        Raises
        ------
        ProcessorValidationError
            If a variable the processor needs is absent.
        """
        ...

    def __call__(
        self,
        db: VarFrame,
        *,
        report: str | None = None,
        comment: str | None = None,
        force: bool = False,
    ) -> VarFrame:
        """Apply the processor, returning a new VarFrame (REQ-18)."""
        ...
