"""db.summary: the short, practical first look (REQ-16).

Prints a one-screen summary and returns a ``Summary`` object with
matching attributes, including the in-memory footprint (REQ-89).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from itaca.core.varframe import VarFrame


@dataclass(frozen=True)
class Summary:
    """Concise VarFrame summary (REQ-16).

    Parameters
    ----------
    dims : tuple of (str, int)
        Dimension names with their cardinalities, in order.
    variables : tuple of str
        Variable names.
    stats : mapping of str to (float, float, float)
        Per-variable (min, max, mean) over finite values; NaN when a
        variable has no finite value.
    ram_bytes : int
        In-memory footprint of data and mirrors (REQ-89).
    mode : str
        Operating mode.
    history_index : int
        Index of the latest History entry.
    """

    dims: tuple[tuple[str, int], ...]
    variables: tuple[str, ...]
    stats: Mapping[str, tuple[float, float, float]]
    ram_bytes: int
    mode: str
    history_index: int

    def __str__(self) -> str:
        dims_desc = ", ".join(f"{name}: {size}" for name, size in self.dims) or "none"
        lines = [
            f"ITACA summary | mode={self.mode} | history index {self.history_index}",
            f"  dims: {dims_desc}",
            f"  RAM: {self.ram_bytes / 1024:.1f} KiB",
        ]
        for name in self.variables:
            low, high, mean = self.stats[name]
            lines.append(f"  {name}: min={low:.6g} max={high:.6g} mean={mean:.6g}")
        return "\n".join(lines)


def summary(db: VarFrame) -> Summary:
    """Print and return the one-screen summary of a VarFrame (REQ-16).

    Parameters
    ----------
    db : VarFrame
        The VarFrame to summarize.

    Returns
    -------
    Summary
        Object with the printed values as attributes.
    """
    stats: dict[str, tuple[float, float, float]] = {}
    ram = sum(d.coords.nbytes for d in db.dims.values())
    for name, variable in db.vars.items():
        ram += variable.values.nbytes
        finite = variable.values[np.isfinite(variable.values)]
        if finite.size:
            stats[name] = (
                float(finite.min()),
                float(finite.max()),
                float(finite.mean()),
            )
        else:
            stats[name] = (float("nan"), float("nan"), float("nan"))
    if db.uncertainty is not None:
        for component in (db.uncertainty.systematic, db.uncertainty.random):
            ram += sum(array.nbytes for array in component.values())
    if db.tags is not None:
        ram += sum(array.nbytes for array in db.tags.tags.values())
    result = Summary(
        dims=tuple((name, dim.cardinality) for name, dim in db.dims.items()),
        variables=tuple(db.vars),
        stats=stats,
        ram_bytes=int(ram),
        mode=db.mode,
        history_index=len(db.history),
    )
    print(result)
    return result
