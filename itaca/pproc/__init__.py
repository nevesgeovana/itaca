"""Processors: reusable, version-controlled analysis workflows (REQ-45 to REQ-48).

A processor turns a declared workflow into an operation on a VarFrame.
The workflow itself lives in an ``.itceq`` file, which is TOML with five
sections and no Python, so it is reviewed, diffed, and version
controlled next to the data it processes.

The factory is ``itc.processor(name_or_path)``, and this package is
``itc.pproc``. They are deliberately different names (OQ-29, resolved
2026-07-27). Binding the factory as ``itc.pproc`` would have shadowed
this package on that attribute, so ``itc.pproc.statistics(db)`` could
never resolve, and REQ-49 to REQ-51 are written exactly that way. The
factory was renamed rather than the package because that leaves both the
module paths and those requirement texts true as written, and it follows
the constructor pattern the top-level API surface already uses for
``itc.datavis`` and ``itc.surrogate``.
"""

from itaca.pproc.base import EquationProcessor
from itaca.pproc.equations.parser import Equation, ItceqSpec, parse_itceq
from itaca.pproc.factory import processor
from itaca.pproc.protocol import Processor
from itaca.pproc.registry import register_processor, registered_processors

__all__ = [
    "Equation",
    "EquationProcessor",
    "ItceqSpec",
    "Processor",
    "parse_itceq",
    "processor",
    "register_processor",
    "registered_processors",
]
