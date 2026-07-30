"""A library writes to stdout only from a surface the SRS charters for it.

Usage example (the contract under test)::

    structured = db.pivot(dims=["mach"], auto_detect=True)  # prints nothing
    report = db.diagnostics()                               # prints, by REQ

P-08 grants terminal output to "inspection, summary, and diagnostic
methods". It does not grant it to a transformation. A transformation that
prints corrupts the stdout of any program using itaca as a component, and
there is no argument the caller can pass to stop it.

The AST walk found two violations (``ITC-20260723-2042``, review D9), and
they are NOT the same case:

- ``db.pivot(auto_detect=True)`` printed with no authority behind it.
  REQ-14 specifies the detection and charters no announcement, and the
  test that pinned the print cited REQ-76, which is the required-edge-case
  list and says only that the case must be TESTED. Fixed here: it logs at
  INFO on the module logger, the convention ``core/provenance.py`` and
  ``io/loader.py`` already use.
- ``parse_itceq(..., auto_sort=True)`` prints because **DD-17 charters the
  report**: "the parser reports the resolved order to the user as
  feedback", and "the feedback makes the resolved order auditable". A
  ``logger.info`` is silent under the default configuration, so moving it
  would quietly retire a decided behavior. It stays, chartered below, and
  OQ-48 asks the author whether a library should report on stdout at all.

That asymmetry is the point of keying the allowlist to a citation rather
than to a judgment about which prints look reasonable.

The behavioral tests below are the falsifying pair for the pivot half. The
AST guard after them is the structural half required by the incident rule:
it fails on the NEXT unchartered print rather than on this one, which is
the only form of this check that cannot be defeated by adding a third.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.pproc.equations.parser import parse_itceq

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "itaca"

# Every print in the library, keyed to the SRS surface that charters it.
# A print anywhere else is a defect. Keyed by enclosing callable rather
# than by module, so a future print added to db.compute is not covered by
# the charter that belongs to its private debug helper.
_CHARTERED_PRINTERS: dict[tuple[str, str], str] = {
    ("itaca/io/inspector.py", "inspect"): "REQ-13, output is printed to the terminal",
    ("itaca/io/summary.py", "summary"): "SRS 6, db.summary() prints to the terminal",
    ("itaca/io/diagnostics.py", "diagnostics"): "SRS 6, db.diagnostics(log=None)",
    ("itaca/ops/compute.py", "_debug_report"): "SRS 6, db.compute(..., debug=True)",
    ("itaca/pproc/base.py", "EquationProcessor.info"): "SRS 9, polar.info()",
    ("itaca/pproc/equations/parser.py", "_resolve"): (
        "DD-17, auto_sort reports the resolved order as feedback; OQ-48 asks "
        "whether that should remain stdout"
    ),
}


class _PrintFinder(ast.NodeVisitor):
    """Collect ``print(...)`` calls with the dotted name of their owner."""

    def __init__(self, module: str) -> None:
        self.module = module
        self.stack: list[str] = []
        self.sites: list[tuple[str, str, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            owner = ".".join(self.stack) or "<module>"
            self.sites.append((self.module, owner, node.lineno))
        self.generic_visit(node)


def _print_sites() -> list[tuple[str, str, int]]:
    """Return every ``print(...)`` call in the package, with its owner.

    Read from the AST rather than by regex: a regex over source cannot
    tell a call from the word inside a docstring, and ``history.py``
    mentions ``print(db.history)`` in prose.
    """
    sites: list[tuple[str, str, int]] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        finder = _PrintFinder(path.relative_to(_ROOT).as_posix())
        finder.visit(ast.parse(path.read_text(encoding="utf-8")))
        sites.extend(finder.sites)
    return sites


class TestThePathThatPrintedWithoutAuthority:
    """db.pivot announced its detection on every call, chartered by nothing."""

    def test_pivot_auto_detect_announces_nothing_on_stdout(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # REQ-14 specifies auto_detect and charters no output for it.
        rng = np.linspace(0.0, 1.0, 8)
        arr = np.column_stack(
            [np.repeat([0.1, 0.2], 4), np.tile([0.0, 2.0, 4.0, 6.0], 2), rng]
        )
        db = itc.load(arr, names=["mach", "alpha", "CT"])
        capsys.readouterr()
        structured = db.pivot(dims=["mach"], auto_detect=True)
        captured = capsys.readouterr()
        # The detection itself must still work; a silent no-op would pass
        # an emptiness assertion for the wrong reason.
        assert set(structured.dims) == {"mach", "alpha"}
        assert captured.out == "", f"db.pivot wrote to stdout: {captured.out!r}"
        assert captured.err == "", f"db.pivot wrote to stderr: {captured.err!r}"

    def test_the_resolved_dims_are_still_reported_at_info(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Silencing is not deleting: the diagnostic moved, it did not vanish."""
        rng = np.linspace(0.0, 1.0, 8)
        arr = np.column_stack(
            [np.repeat([0.1, 0.2], 4), np.tile([0.0, 2.0, 4.0, 6.0], 2), rng]
        )
        db = itc.load(arr, names=["mach", "alpha", "CT"])
        with caplog.at_level("INFO", logger="itaca.io.pivot"):
            db.pivot(dims=["mach"], auto_detect=True)
        assert any("alpha" in record.message for record in caplog.records), (
            "auto_detect resolved a dimension list and reported it nowhere"
        )

    def test_the_chartered_report_still_reaches_the_user(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DD-17's feedback is decided behavior and must not be silenced here.

        This is the guard against fixing the pivot defect by sweeping every
        print out of the library: the two cases have different authorities
        and only one of them was wrong. If OQ-48 later retires the stdout
        report, this test changes with the decision that retires it.
        """
        source = tmp_path / "x.itceq"
        source.write_text(
            '[meta]\nname = "x"\n\n[equations]\n'
            'CL = "FZ / q_inf"\nq_inf = "0.5 * rho * V**2"\n',
            encoding="utf-8",
        )
        capsys.readouterr()
        spec = parse_itceq(source, auto_sort=True)
        captured = capsys.readouterr()
        assert [equation.target for equation in spec.equations] == ["q_inf", "CL"]
        assert "q_inf -> CL" in captured.out


class TestTheStructuralGuard:
    """The half that fails on the next one, not on these two."""

    def test_every_print_in_the_library_is_chartered(self) -> None:
        offenders = [
            f"{module}::{owner} line {line}"
            for module, owner, line in _print_sites()
            if (module, owner) not in _CHARTERED_PRINTERS
        ]
        assert not offenders, (
            "itaca library code writes to stdout from a surface the SRS does "
            f"not charter for it: {offenders}. P-08 grants terminal output to "
            "inspection, summary and diagnostic methods only; a transformation "
            "corrupts the stdout of any program using itaca as a component. "
            "Log at INFO on the module logger instead, as core/provenance.py "
            "does, or add the surface to _CHARTERED_PRINTERS with the "
            "requirement that charters it."
        )

    def test_the_guard_has_prints_to_find(self) -> None:
        """A guard that scans nothing passes for the wrong reason.

        If the walk stopped resolving the package, ``offenders`` above
        would be empty and the check would read as green forever.
        """
        sites = _print_sites()
        assert len(sites) >= len(_CHARTERED_PRINTERS), (
            f"the AST walk found {len(sites)} print sites under {_PACKAGE}, "
            f"fewer than the {len(_CHARTERED_PRINTERS)} chartered ones; the "
            "walk is not reaching the package"
        )

    def test_no_charter_outlives_the_print_it_charters(self) -> None:
        """An allowlist nobody prunes becomes a list of permissions to reuse.

        Each entry is an exemption granted to one specific call site. Once
        that site stops printing, the entry is a standing permission for a
        future print nobody reviewed.
        """
        found = {(module, owner) for module, owner, _ in _print_sites()}
        stale = sorted(key for key in _CHARTERED_PRINTERS if key not in found)
        assert not stale, (
            f"_CHARTERED_PRINTERS exempts call sites that no longer print: "
            f"{stale}. Remove the entry rather than leaving the exemption."
        )
