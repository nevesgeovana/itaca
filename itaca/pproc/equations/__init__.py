"""Equation files: the .itceq parser and the shipped equation sets.

The parser is here rather than beside the processors because an
``.itceq`` file is the workflow language, independent of any particular
processor that runs it (M1 execution plan, Section 5). The builtin
equation sets land alongside it with their processors.
"""

from itaca.pproc.equations.parser import Equation, ItceqSpec, parse_itceq

__all__ = ["Equation", "ItceqSpec", "parse_itceq"]
