"""itc.processor(): construct a processor by name or by path (REQ-46).

The argument is a registered name or a path to an .itceq file. The two
are told apart by shape and not by trying the filesystem first: a
``Path`` or a string ending in ``.itceq`` is a path, and anything else
is a name. Probing the filesystem instead would make a missing file
report itself as an unknown processor name, which sends the reader
looking in the wrong place.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from itaca.pproc.base import EquationProcessor
from itaca.pproc.equations.parser import parse_itceq
from itaca.pproc.protocol import Processor
from itaca.pproc.registry import _resolve

__all__ = ["processor"]

SUFFIX = ".itceq"


def processor(
    name_or_path: str | Path,
    config: Mapping[str, float] | None = None,
    *,
    auto_sort: bool = False,
) -> Processor:
    """Construct a processor (REQ-46).

    Parameters
    ----------
    name_or_path : str or pathlib.Path
        A registered processor name (e.g. ``"WT_propeller"``), or a
        path to an ``.itceq`` file. A ``Path``, or a string ending in
        ``.itceq``, is read as a path.
    config : mapping of str to float, optional
        Overrides for defaults declared in the file's ``[constants]``
        section. A key that is not a declared constant is refused.
    auto_sort : bool, optional
        Resolve the equation order by dependency instead of file order,
        reporting the resolved order (REQ-48, DD-17). Cycles are
        detected either way.

    Returns
    -------
    Processor
        An object satisfying the REQ-45 protocol.

    Raises
    ------
    ProcessorNotFoundError
        If a name is given and is not registered.
    ItceqParseError
        If a path is given and the file is absent or malformed.
    ItceqCycleError
        If the file's equations are cyclic.
    ProcessorError
        If a configuration key is not a declared constant.

    Examples
    --------
    >>> processor = itc.processor("balance_off.itceq", auto_sort=True)  # doctest: +SKIP
    >>> processed = processor(db, comment="power-off sweep")  # doctest: +SKIP
    >>> config = {"S_ref": 0.25}
    >>> rescaled = itc.processor("balance_off.itceq", config)  # doctest: +SKIP
    """
    if isinstance(name_or_path, Path) or str(name_or_path).endswith(SUFFIX):
        spec = parse_itceq(name_or_path, auto_sort=auto_sort)
        return EquationProcessor(spec, config=config)
    constructor = _resolve(str(name_or_path))
    return constructor(config=config, auto_sort=auto_sort)
