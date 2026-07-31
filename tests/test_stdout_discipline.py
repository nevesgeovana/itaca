"""A library writes to stdout only from a surface the SRS charters for it.

Usage example (the contract under test)::

    structured = db.pivot(dims=["mach"], auto_detect=True)  # prints nothing
    report = db.diagnostics()                               # prints, by REQ

The operative test is whether a REQUIREMENT asks the surface to print.
P-08 is a positive statement, "inspection, summary, and diagnostic methods
print rich output to the terminal", not a prohibition on everything else,
so it corroborates rather than forbids: what condemns an unchartered print
is the absence of any charter for it, plus the plain cost that a
transformation writing to stdout corrupts the output of any program using
itaca as a component, with no argument the caller can pass to stop it.

The AST walk found two violations (``ITC-20260723-2042``, review D9), and
they are NOT the same case:

- ``db.pivot(auto_detect=True)`` printed with no authority behind it.
  REQ-14 specifies the detection and charters no announcement, and the
  test that pinned the print cited REQ-76, which is the required-edge-case
  list and says only that the case must be TESTED. Fixed here: it logs at
  INFO on the module logger, the convention ``core/provenance.py`` and
  ``io/loader.py`` already use.
- ``parse_itceq(..., auto_sort=True)`` prints because **REQ-48 charters the
  report normatively** and DD-17 records the decision behind it: "the
  parser reports the resolved order to the user as feedback", and "the
  feedback makes the resolved order auditable". Neither names a
  destination, but a ``logger.info`` is silent under the default
  configuration, so moving it would quietly retire a decided behavior. It
  stays, chartered below, and OQ-48 asks the author whether a library
  should report on stdout at all. Retiring it is an SRS change, not only a
  superseding DD, because REQ-48 is stable.

That asymmetry is the point of keying the allowlist to a citation rather
than to a judgment about which prints look reasonable.

The behavioral tests below are the falsifying pair for the pivot half. The
AST guard after them is the structural half required by the incident rule:
it fails on the NEXT unchartered print rather than on this one, which is
the only form of this check that cannot be defeated by adding a third.

**What this guard does NOT cover**, stated so the next widening starts
from the limit rather than from the claim: it matches ``print(...)`` as a
bare name. ``sys.stdout.write``, an aliased or shadowed ``print``, and
``pprint`` all evade it. Measured 2026-07-30: no such site exists under
``itaca/``, so the walk is complete over the tree it guards today, and
that is a fact about today rather than a property of the check.
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

# Every print in the library, keyed to its owner and to the requirement
# that charters it, with the number of print calls that owner is allowed.
#
# THE COUNT IS THE POINT. Keying by owner alone exempts the CALLABLE, not
# the call, so a new print dropped into an already-chartered function
# inherits a permission nobody granted it. Measured by a reviewer on the
# first version of this guard: `print("leaked secret")` added inside
# ``summary`` left all six tests green. The count closes that, and it is
# deliberately brittle: a sixth print in ``inspect`` should require someone
# to look at it.
_CHARTERED_PRINTERS: dict[tuple[str, str], tuple[int, str]] = {
    ("itaca/io/inspector.py", "inspect"): (
        4,
        "REQ-13, db.inspect(), output is printed to the terminal",
    ),
    ("itaca/io/summary.py", "summary"): (
        1,
        "REQ-16, db.summary() prints a one-screen summary to the terminal",
    ),
    ("itaca/io/diagnostics.py", "diagnostics"): (
        1,
        "REQ-17, 'Diagnostics: print and return'",
    ),
    ("itaca/ops/compute.py", "_debug_report"): (
        1,
        "REQ-34, db.compute(..., debug=True) prints a structured debug report",
    ),
    ("itaca/pproc/base.py", "EquationProcessor.info"): (
        1,
        "NO REQBOX. SRS Chapter 9 shows polar.info() printing, in a "
        "contributing-guide code listing, which is not a requirement. "
        "Exempted as shipped behavior and registered as "
        "ITC-20260730-2135 rather than silently blessed",
    ),
    ("itaca/pproc/equations/parser.py", "_resolve"): (
        1,
        "REQ-48 and DD-17, auto_sort 'reports the resolved order to the user "
        "as feedback'; OQ-48 asks whether that should remain stdout",
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
            "itaca library code writes to stdout from a surface no "
            f"requirement charters for it: {offenders}. Nothing in the SRS "
            "asks this surface to print, and a library that writes to stdout "
            "from a data path corrupts the output of any program using it as "
            "a component; P-08 grants terminal output to inspection, summary "
            "and diagnostic methods, which is where the charters are. Log at "
            "INFO on the module logger instead, as core/provenance.py does, "
            "or add the surface to _CHARTERED_PRINTERS with the requirement "
            "that charters it."
        )

    def test_no_chartered_surface_prints_more_than_it_was_granted(self) -> None:
        """The exemption belongs to the calls, not to the callable.

        Without this, a print added inside an already-chartered function
        is covered by a permission granted to a different line. Measured:
        it was, until a reviewer put ``print("leaked secret")`` inside
        ``summary`` and watched every test stay green.
        """
        counted: dict[tuple[str, str], int] = {}
        for module, owner, _ in _print_sites():
            counted[(module, owner)] = counted.get((module, owner), 0) + 1
        excess = {
            key: (found, _CHARTERED_PRINTERS[key][0])
            for key, found in counted.items()
            if key in _CHARTERED_PRINTERS and found != _CHARTERED_PRINTERS[key][0]
        }
        assert not excess, (
            f"a chartered surface changed its number of print calls: {excess} "
            "(found, granted). A new print inside a function that already "
            "prints is a new stdout write and needs its own look; update the "
            "count here once you have taken it."
        )

    def test_the_walk_reaches_every_print_the_charter_knows_about(self) -> None:
        """A guard that scans nothing passes for the wrong reason.

        Set equality rather than a count comparison: the package holds 9
        print sites against 6 chartered keys, so ``len(sites) >= len(charter)``
        would still pass with a third of the walk silently missing, which is
        roughly the whole ``pproc`` subtree.
        """
        assert _PACKAGE.is_dir(), f"the package is not at {_PACKAGE}"
        found = {(module, owner) for module, owner, _ in _print_sites()}
        missing = sorted(set(_CHARTERED_PRINTERS) - found)
        assert not missing, (
            f"the AST walk did not reach chartered print sites: {missing}. "
            "Either the walk is not covering the package or those surfaces "
            "stopped printing; both need a person, and neither may pass."
        )
