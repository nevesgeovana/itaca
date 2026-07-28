"""EquationProcessor: the processor an .itceq file defines (REQ-45 to REQ-48).

An .itceq file fully defines a reproducible workflow (REQ-48), and this
class is what runs it. It satisfies the :class:`Processor` protocol,
carries the REQ-47 idempotence policy, and applies its equations through
the ordinary ``db.compute`` path so that every step is recorded in
History and is individually replayable: a processor application lifts
into a Pipeline like any other sequence of operations (REQ-53).

Constants are substituted into the expressions before they run, because
a constant is a declared number and not a VarFrame variable. History
therefore records the expression with the number in it, which is what
actually ran, and a reader can see the value the workflow used without
opening the .itceq file.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

from itaca.core.errors import (
    ProcessorError,
    ProcessorIdempotenceWarning,
    ProcessorValidationError,
)
from itaca.pproc.equations.parser import Equation, ItceqSpec

if TYPE_CHECKING:
    from itaca.core.varframe import VarFrame

__all__ = ["EquationProcessor"]


class EquationProcessor:
    """A processor defined by a parsed .itceq file (REQ-45, REQ-48).

    Parameters
    ----------
    spec : ItceqSpec
        The parsed file, already validated and acyclic.
    config : mapping of str to float, optional
        Overrides for defaults declared in ``[constants]`` (REQ-46). A
        key that is not a declared constant is refused rather than
        ignored: it is almost always a typo, and ignoring it would run
        the workflow with the default while the caller believed
        otherwise.

    Attributes
    ----------
    idempotent : bool
        Whether reapplication is meaningful (REQ-47, DD-16). ``False``
        by default: a second application is refused unless the caller
        passes ``force=True``. Subclasses declare ``True`` when
        reapplying the workflow is well defined.

    Raises
    ------
    ProcessorError
        If a configuration key is not a declared constant, or its value
        is not a number.

    Examples
    --------
    >>> from itaca.pproc.equations.parser import parse_itceq
    >>> processor = EquationProcessor(parse_itceq("balance.itceq"))  # doctest: +SKIP
    >>> processed = processor(db, comment="run 12")  # doctest: +SKIP
    """

    idempotent: ClassVar[bool] = False

    def __init__(
        self, spec: ItceqSpec, *, config: Mapping[str, float] | None = None
    ) -> None:
        self.spec = spec
        self.constants = _configure(spec, config or {})

    @property
    def name(self) -> str:
        """Processor name: ``[meta] name``, else the file stem (REQ-45)."""
        return self.spec.meta.get("name") or self.spec.source.stem

    @property
    def version(self) -> str:
        """Processor version: ``[meta] version``, else ``"0"`` (REQ-45)."""
        return self.spec.meta.get("version") or "0"

    @property
    def signature(self) -> str:
        """The identity recorded in History on every entry it writes."""
        return f"pproc {self.name} v{self.version}"

    def info(self) -> None:
        """Print the workflow: metadata, constants, and evaluation order.

        Returns
        -------
        None
            Printed for the user, in the manner of ``db.inspect``
            (REQ-45).

        Examples
        --------
        >>> processor.info()  # doctest: +SKIP
        """
        lines = [f"{self.name} (version {self.version})"]
        if description := self.spec.meta.get("description"):
            lines.append(f"  {description}")
        lines.append(f"  source: {self.spec.source.name}")
        order = "resolved by auto_sort" if self.spec.sorted else "file order"
        lines.append(f"  evaluation order: {order}")
        lines.append(
            f"  idempotent: {self.idempotent or self.spec.idempotent} "
            "(reapplication refused unless True or force=True)"
        )
        if self.constants:
            declared = self.spec.constants
            lines.append("  constants:")
            lines.extend(
                f"    {key} = {value:g}"
                + ("  (overridden)" if declared.get(key) != value else "")
                for key, value in self.constants.items()
            )
        if self.spec.uncertainties:
            lines.append("  uncertainties (systematic component):")
            lines.extend(
                f"    {key} = {value}" for key, value in self.spec.uncertainties.items()
            )
        for stage, equations in (
            ("equations", self.spec.equations),
            ("corrections", self.spec.corrections),
        ):
            if equations:
                lines.append(f"  {stage}:")
                lines.extend(
                    f"    {equation.target} = {equation.expression}"
                    for equation in equations
                )
        if self.spec.required_variables:
            lines.append(f"  requires: {list(self.spec.required_variables)}")
        print("\n".join(lines))

    def validate(self, db: VarFrame) -> None:
        """Check the VarFrame can feed this processor (REQ-45).

        Parameters
        ----------
        db : VarFrame
            The frame the processor is about to be applied to.

        Returns
        -------
        None
            Returns silently when the frame is usable.

        Raises
        ------
        ProcessorValidationError
            If a variable an equation reads, or an ``[uncertainties]``
            entry names, is absent and is not produced by the file.

        Examples
        --------
        >>> processor.validate(db)  # doctest: +SKIP
        """
        available = set(db.vars)
        missing = sorted(set(self.spec.required_variables) - available)
        unknown_unc = sorted(
            key
            for key in self.spec.uncertainties
            if key not in available and key not in self.spec.targets
        )
        if not missing and not unknown_unc:
            return
        parts = []
        if missing:
            parts.append(f"its equations read absent variable(s) {missing}")
        if unknown_unc:
            parts.append(
                f"its [uncertainties] section names absent variable(s) {unknown_unc}"
            )
        raise ProcessorValidationError(
            f"processor '{self.name}' against VarFrame",
            " and ".join(parts),
            f"the frame carries {sorted(available)}; load the missing "
            "channels, or correct the .itceq file (REQ-45, REQ-48)",
        )

    def __call__(
        self,
        db: VarFrame,
        *,
        report: str | None = None,
        comment: str | None = None,
        force: bool = False,
    ) -> VarFrame:
        """Apply the workflow, returning a new VarFrame (REQ-45, REQ-18).

        Assigns the declared ``[uncertainties]`` as the systematic
        component (SRS Chapter 8, REQ-99), then evaluates
        ``[equations]`` and ``[corrections]`` in the order the parse
        resolved. Each equation is an ordinary recorded operation, so
        uncertainty propagates automatically (REQ-41) and the whole
        application is replayable.

        Parameters
        ----------
        db : VarFrame
            The frame to process. It is not modified (REQ-18).
        report : str or None, optional
            Path for a PDF report. Reports are REQ-51, an M2
            deliverable, and this argument raises until then rather
            than being accepted and ignored.
        comment : str or None, optional
            User comment (REQ-19). The processor signature is recorded
            alongside it on every entry the application writes, so a
            reader who lands on any one of them knows which workflow
            and which version produced it.
        force : bool, optional
            Permit a reapplication that would otherwise be refused
            (REQ-47, DD-16). Without it the reapplication is refused by
            *raising* ``ProcessorIdempotenceWarning``; with it the same
            object is passed to ``warnings.warn`` and the run proceeds.
            Neither path is silent, but only one of them raises.

        Returns
        -------
        VarFrame
            A new frame carrying every target the file declares.

        Warns
        -----
        ProcessorIdempotenceWarning
            When the data is already processed and ``force=True`` or a
            declared ``idempotent=True`` permits the re-run. Standard
            warning filters apply, so repeated re-runs from one call
            site may be shown once.

        Raises
        ------
        ProcessorIdempotenceWarning
            If the data is already processed and neither ``force`` nor
            ``idempotent`` permits the re-run.
        ProcessorValidationError
            If the frame cannot feed the processor.
        ProcessorError
            If ``report`` is requested before REQ-51 ships.

        Examples
        --------
        >>> processed = processor(db, comment="power-off sweep")  # doctest: +SKIP
        >>> reapplied = processor(processed, force=True)  # doctest: +SKIP
        """
        if report is not None:
            raise ProcessorError(
                f"processor '{self.name}'",
                "a PDF report was requested, and report generation is not "
                "part of this milestone",
                "REQ-51 ships pproc.report() with the LaTeX backend in "
                "v0.3.0 (M2); drop report= until then",
            )
        self.validate(db)
        self._check_idempotence(db, force=force)
        signature = self.signature
        if comment is not None:
            signature = f"{signature}: {comment}"

        work = db
        pending = dict(self.spec.uncertainties)
        # Assign what the frame already carries before anything reads
        # it, so the first equation propagates from the declared inputs.
        setup = {key: pending.pop(key) for key in list(pending) if key in work.vars}
        if setup:
            work = work.set_uncertainty(setup, history=True, comment=signature)
        for equation in (*self.spec.equations, *self.spec.corrections):
            work = work.compute(
                f"{equation.target} = {self._substitute(equation)}",
                history=True,
                comment=signature,
            )
            # A declared uncertainty on a variable the file produces is
            # assigned the moment that variable exists, never at the
            # end: a dependent equation evaluated in between would
            # propagate from an uncertainty this file overrides, and the
            # frame would ship u(dependent) inconsistent with the
            # u(input) it reports (REQ-41, REQ-99).
            if equation.target in pending:
                work = work.set_uncertainty(
                    {equation.target: pending.pop(equation.target)},
                    history=True,
                    comment=signature,
                )
        return work

    # -- internals ----------------------------------------------------------

    def _check_idempotence(self, db: VarFrame, *, force: bool) -> None:
        """Refuse or warn on a reapplication (REQ-47, DD-16, DD-35).

        Two pieces of evidence, and the action depends on both:

        ==================  ==================  ====================
        targets all present History signed      action
        ==================  ==================  ====================
        no                  n/a                 apply
        yes                 no                  warn, then apply
        yes                 yes                 refuse unless allowed
        ==================  ==================  ====================

        Names alone are not evidence of a previous run: a CSV that
        arrives carrying ``CL`` and ``q_inf`` beside the forces would
        otherwise be refused on its FIRST application, teaching the user
        to write ``force=True`` by reflex, which is the habit DD-16
        exists to prevent. The History signature is the actual evidence,
        and it survives a save and reopen because History is persisted
        in the ``.itc`` archive. A draft frame that never recorded keeps
        only the warning, which DD-35 records as the accepted cost.
        """
        targets = self.spec.targets
        if not targets or not set(targets) <= set(db.vars):
            return
        signed = any(
            entry.comment is not None and self.signature in entry.comment
            for entry in db.history
        )
        if not signed:
            warnings.warn(
                ProcessorIdempotenceWarning(
                    f"processor '{self.name}' (version {self.version})",
                    f"the VarFrame already carries every variable it "
                    f"produces, {list(targets)}, and its History does not "
                    "record this processor, so they are being overwritten "
                    "rather than reapplied",
                    "check the frame is the one you meant; nothing is "
                    "refused here, because matching names are not evidence "
                    "of a previous run (REQ-47, DD-35)",
                ),
                stacklevel=3,
            )
            return
        warning = ProcessorIdempotenceWarning(
            f"processor '{self.name}' (version {self.version})",
            f"the VarFrame already carries every variable it produces, "
            f"{list(targets)}, and its History records this processor, so "
            "this is a reapplication and corrections would be applied twice",
            "pass force=True to re-run deliberately, or apply the processor "
            "to the unprocessed frame (REQ-47, DD-16)",
        )
        if not force and not (self.idempotent or self.spec.idempotent):
            raise warning
        warnings.warn(warning, stacklevel=3)

    def _substitute(self, equation: Equation) -> str:
        """Replace declared constants by their values in an expression.

        Constants are numbers the file declares, not VarFrame
        variables, so the expression that runs carries the number.
        """
        if not self.constants:
            return equation.expression
        tree = ast.parse(equation.expression, mode="eval")
        tree.body = _ConstantSubstitution(self.constants).visit(tree.body)
        return ast.unparse(ast.fix_missing_locations(tree).body)


class _ConstantSubstitution(ast.NodeTransformer):
    """Rewrite Name nodes that name a declared constant into literals.

    A callee is a name in the syntax but not a variable in the
    expression language, so it is never substituted. Skipping it also
    covers the ``np.`` prefix, since an attribute reaches this
    transformer only as the callee of an ``np.<function>`` call: a bare
    attribute is not valid in an ITACA expression (REQ-44).
    """

    def __init__(self, constants: Mapping[str, float]) -> None:
        self.constants = constants

    def visit_Call(self, node: ast.Call) -> ast.expr:
        """Visit the arguments, never the callee."""
        node.args = [self.visit(argument) for argument in node.args]
        return node

    def visit_Name(self, node: ast.Name) -> ast.expr:
        """Replace a declared constant by its numeric value."""
        if node.id in self.constants:
            return ast.Constant(value=self.constants[node.id])
        return node


def _configure(spec: ItceqSpec, config: Mapping[str, float]) -> Mapping[str, float]:
    """Apply the REQ-46 configuration over the declared constants."""
    unknown = sorted(set(config) - set(spec.constants))
    if unknown:
        raise ProcessorError(
            f"processor configuration for '{spec.source.name}'",
            f"key(s) {unknown} are not declared in [constants], and "
            "configuration overrides declared defaults rather than "
            "introducing new names",
            f"the file declares {sorted(spec.constants)}; correct the key, "
            "or add it to [constants] in the .itceq file (REQ-46)",
        )
    resolved = dict(spec.constants)
    for key, value in config.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProcessorError(
                f"configuration value for constant '{key}'",
                f"it is {value!r}, and every constant is a number",
                f"pass a number, for example config={{{key!r}: 0.1963}} "
                "(REQ-46, REQ-48)",
            )
        resolved[key] = float(value)
    return MappingProxyType(resolved)
