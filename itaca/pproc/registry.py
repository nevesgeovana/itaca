"""The built-in processor registry (REQ-46).

``itc.processor("WT_propeller")`` resolves a name through this registry. It
is empty in v0.2.0: the wind tunnel builtins are M1 stretch scope, and
the registry ships ahead of them so the factory has one place to look
and one error to raise when a name is wrong.

Registration is explicit and refuses a duplicate name. A silently
overwritten processor would mean two workflows answering to one name,
with which one runs decided by import order.
"""

from __future__ import annotations

from collections.abc import Callable

from itaca.core.errors import ProcessorError, ProcessorNotFoundError
from itaca.pproc.protocol import Processor

__all__ = ["register_processor", "registered_processors"]

_REGISTRY: dict[str, Callable[..., Processor]] = {}


def register_processor(name: str, constructor: Callable[..., Processor]) -> None:
    """Register a processor under a name (REQ-46).

    Parameters
    ----------
    name : str
        The name ``itc.processor`` will accept, e.g. ``"WT_propeller"``.
    constructor : callable
        Called with the factory's keyword arguments (``config`` and
        ``auto_sort``) and returning a Processor.

    Returns
    -------
    None

    Raises
    ------
    ProcessorError
        If the name is already registered.

    Examples
    --------
    >>> register_processor("WT_demo", build_demo)  # doctest: +SKIP
    """
    if name in _REGISTRY:
        raise ProcessorError(
            f"processor name '{name}'",
            "it is already registered, and registering it again would leave "
            "two workflows answering to one name",
            f"choose a different name; registered: {registered_processors()} (REQ-46)",
        )
    _REGISTRY[name] = constructor


def registered_processors() -> tuple[str, ...]:
    """Return every registered processor name, sorted.

    Returns
    -------
    tuple of str
        The names ``itc.processor`` accepts.

    Examples
    --------
    >>> registered_processors()  # doctest: +SKIP
    ('WT_propeller',)
    """
    return tuple(sorted(_REGISTRY))


def _resolve(name: str) -> Callable[..., Processor]:
    """Look a name up, or raise listing the alternatives (REQ-46).

    Parameters
    ----------
    name : str
        The requested processor name.

    Returns
    -------
    callable
        The registered constructor.

    Raises
    ------
    ProcessorNotFoundError
        If the name is not registered. The message lists the
        registered alternatives, so a typo is fixable from it.

    Examples
    --------
    >>> _resolve("WT_propeller")  # doctest: +SKIP
    """
    if name in _REGISTRY:
        return _REGISTRY[name]
    known = registered_processors()
    available = (
        f"registered processors: {list(known)}"
        if known
        else "no processors are registered in this build"
    )
    raise ProcessorNotFoundError(
        f"processor name '{name}'",
        "itc.processor found no processor registered under it",
        f"{available}; pass a path to an .itceq file instead, or check the "
        "spelling (REQ-46)",
    )
