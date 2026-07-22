"""db.diagnostics: structured data-quality report (REQ-17).

Prints a report, optionally mirrors it to a log file, and returns a
``DiagnosticsReport``. Diagnostics are inspection, not data export, so
they carry no draft-mode guard (the guard protects results, REQ-11).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from itaca.core.varframe import VarFrame

LOW_COVERAGE = 0.25


@dataclass(frozen=True)
class DiagnosticsReport:
    """Data-quality report of a VarFrame (REQ-17).

    Parameters
    ----------
    missing : mapping of str to int
        NaN count per variable (unfilled grid positions).
    non_finite : mapping of str to int
        Infinity count per variable.
    partial_vars : tuple of str
        Variables with some, but not all, values missing.
    coverage : float
        Populated fraction over all variables (1.0 when complete).
    n_missing : int
        Total NaN count.
    warnings : tuple of str
        Human-readable data-quality warnings.
    summary : str
        The full printed report text.
    """

    missing: Mapping[str, int]
    non_finite: Mapping[str, int]
    partial_vars: tuple[str, ...]
    coverage: float
    n_missing: int
    warnings: tuple[str, ...]
    summary: str

    def to_csv(self, path: str | Path) -> Path:
        """Write the per-variable counts as CSV and return the path."""
        target = Path(path)
        lines = ["variable,missing,non_finite,partial"]
        lines.extend(
            f"{name},{self.missing[name]},{self.non_finite[name]},"
            f"{name in self.partial_vars}"
            for name in self.missing
        )
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def to_json(self, path: str | Path) -> Path:
        """Write the report as JSON and return the path."""
        target = Path(path)
        payload = {
            "missing": dict(self.missing),
            "non_finite": dict(self.non_finite),
            "partial_vars": list(self.partial_vars),
            "coverage": self.coverage,
            "n_missing": self.n_missing,
            "warnings": list(self.warnings),
        }
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return target


def diagnostics(db: VarFrame, log: str | Path | None = None) -> DiagnosticsReport:
    """Print, optionally log, and return a diagnostics report (REQ-17).

    Parameters
    ----------
    db : VarFrame
        The VarFrame to diagnose.
    log : path or None, optional
        When given, the printed output is also written to this file.

    Returns
    -------
    DiagnosticsReport
        The structured report.
    """
    missing: dict[str, int] = {}
    non_finite: dict[str, int] = {}
    partial: list[str] = []
    warnings: list[str] = []
    total_cells = 0
    total_missing = 0
    for name, variable in db.vars.items():
        values = variable.values
        n_nan = int(np.isnan(values).sum())
        missing[name] = n_nan
        non_finite[name] = int(np.isinf(values).sum())
        total_cells += values.size
        total_missing += n_nan
        if values.size and n_nan == values.size:
            warnings.append(f"variable '{name}' has no finite values")
        elif n_nan:
            partial.append(name)
    for name, dim in db.dims.items():
        if dim.cardinality == 1:
            warnings.append(f"dimension '{name}' has a single point")
    coverage = 1.0 - (total_missing / total_cells) if total_cells else 1.0
    if coverage < LOW_COVERAGE:
        warnings.append(
            f"coverage {100 * coverage:.1f} percent is below "
            f"{100 * LOW_COVERAGE:.0f} percent (sparse; see REQ-90)"
        )
    lines = [
        f"ITACA diagnostics | mode={db.mode} | "
        f"coverage {100 * coverage:.1f} percent | "
        f"{total_missing} missing value(s)",
    ]
    lines.extend(
        f"  {name}: missing={missing[name]} non_finite={non_finite[name]}"
        for name in missing
    )
    lines.extend(f"  warning: {message}" for message in warnings)
    text = "\n".join(lines)
    report = DiagnosticsReport(
        missing=missing,
        non_finite=non_finite,
        partial_vars=tuple(partial),
        coverage=float(coverage),
        n_missing=int(total_missing),
        warnings=tuple(warnings),
        summary=text,
    )
    print(text)
    if log is not None:
        Path(log).write_text(text + "\n", encoding="utf-8")
    return report
