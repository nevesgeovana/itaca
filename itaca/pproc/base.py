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

A constant whose name the VarFrame also carries is refused by
``validate`` rather than substituted, because the declared number would
beat the measurement and neither the result nor History would say so
(DD-39, OQ-31).
"""

from __future__ import annotations

import ast
import math
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
            # Say WHEN each one takes effect, not only what it is. The
            # moment is normative (SRS Section 4.6) and depends on the
            # frame as well as the file, so a flat list of numbers hides
            # exactly the thing R4-ITA-003 turned on. "when applied"
            # cannot be resolved here without a frame, so what is shown
            # is the half the file decides.
            written = set(self.spec.targets)
            lines.append("  uncertainties (systematic component):")
            lines.extend(
                f"    {key} = {value}"
                + (
                    "  (reapplied after the line that writes it)"
                    if key in written
                    else "  (applied before the first line)"
                )
                for key, value in self.spec.uncertainties.items()
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
            entry names, is absent and is not produced by the file; if a
            name declared in ``[constants]`` is also a variable the frame
            carries; or if a name any expression reads as a built-in
            expression constant (``pi``, ``e``) is also a variable the
            frame carries.

        Notes
        -----
        There are two collision checks and they are ordered
        constants-first, because a file can hit both and the message
        should name the declaration the author controls. Both are
        whole-file: they cover ``[equations]`` and ``[corrections]``,
        since ``__call__`` evaluates both and a refusal that arrived
        mid-application would land after earlier equations had already
        been written.

        The collision case is refused HERE and not at parse time
        because the parser never sees the frame: ``parse_itceq`` takes a
        path and ``EquationProcessor.__init__`` takes a spec, so
        ``validate`` is the first lifecycle step that holds both
        (DD-39, OQ-31). The same file is perfectly legal against a
        campaign that does not log that channel, which is why this is
        not a file defect.

        It is checked before the absence checks and raised alone,
        because the two fixes are opposites: the absence message says to
        load the missing channels, and this one says to remove a
        declaration. Being first also makes the message deterministic
        when both conditions hold.

        Examples
        --------
        >>> processor.validate(db)  # doctest: +SKIP
        """
        available = set(db.vars)
        # OQ-31, answered REFUSE: a constant is substituted into every
        # read, so a declared number silently beats a measured channel of
        # the same name and neither the result nor History says so.
        # Symmetric with DD-37, which already refuses the harmless
        # sibling (a constant against an equation target).
        #
        # Checked against self.constants and not self.spec.constants,
        # because _substitute rewrites exactly self.constants: a config=
        # override changes the value, so checking what actually
        # substitutes is the honest surface.
        collisions = sorted(set(self.constants) & available)
        if collisions:
            declared = {name: self.constants[name] for name in collisions}
            raise ProcessorValidationError(
                f"name(s) {collisions} of processor '{self.name}' against VarFrame",
                "each is declared in [constants] and also carried by the "
                "VarFrame as a measured variable, and a constant is "
                "substituted into every read, so every equation would run "
                f"on the declared value(s) {declared} and the measurement "
                "would never be read",
                "remove the entry from [constants] to use the measured "
                "channel, or rename one of the two; a value that is "
                "measured belongs in the VarFrame, a value that is "
                "declared belongs in [constants]. To OVERRIDE a bad "
                "channel deliberately, correct it with a [corrections] "
                "line or db.compute instead, so the substitution is "
                "recorded in History (REQ-45, REQ-48, SRS Section 4.6)",
            )
        # The same collision one layer down: `pi` and `e` are supplied by
        # the expression language, so _dependencies subtracts them and
        # they never reach required_variables. A frame carrying `e` was
        # therefore certified usable while every equation reading that
        # name got Euler's number (CHK1-001). Refused beside the
        # [constants] case because it is the same defect with a different
        # source of the number.
        # Read from the spec property, so corrections are covered too:
        # __call__ evaluates equations AND corrections, and scanning only
        # the first moved the refusal to mid-application, after earlier
        # equations had already been written. Neither name is exempt:
        # `pi` is no safer than `e`, because the defect is a MEASURED
        # channel becoming unreadable.
        shadowed = sorted(set(self.spec.builtin_constants) & available)
        if shadowed:
            raise ProcessorValidationError(
                f"name(s) {shadowed} of processor '{self.name}' against VarFrame",
                "each is a built-in expression constant (REQ-44) and also "
                "carried by the VarFrame as a measured variable, so every "
                "equation reading the name would use the constant and the "
                "measurement would never be read",
                "give the channel another name on the way in, with "
                "itc.load(..., names=[...]) for an array source or by "
                "correcting the header for a file source (which changes "
                "Provenance.source_hash); a measured channel cannot be "
                "referenced while a language constant shadows it. A "
                "recorded rename operation does not exist yet and is "
                "OQ-41 (REQ-44, REQ-45, DD-42)",
            )
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

        Evaluates ``[equations]`` and ``[corrections]`` in the order the
        parse resolved. Each equation is an ordinary recorded operation,
        so uncertainty propagates automatically (REQ-41) and the whole
        application is replayable.

        Each declared ``[uncertainties]`` value is assigned as the
        systematic component (SRS Section 4.6, REQ-99) at the moment the
        file's own use of the name requires, which is twice for a name
        that is both read and written: before the first line runs when
        the frame carries the name, so every line reading it propagates
        from the declared value, and again once the first line that
        writes it has run, so the declaration is not left as the
        propagation of itself. Whether a LATER line rewriting the same
        name should propagate over the declaration is OQ-43.

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
        declared = self.spec.uncertainties
        produced = set(self.spec.targets)
        # TWO questions, asked separately, because a name can answer yes
        # to both and the two answers want different moments. Does the
        # incoming frame CARRY the name? Then the declaration is assigned
        # here, before any line reads it. Does the FILE WRITE the name?
        # Then it is assigned again after the first line that writes it,
        # because that line's propagation would otherwise replace it.
        #
        # Both wrong answers have shipped. Sorting only by what the frame
        # carried was R4-ITA-003 (ITC-20260730-0105): a target the frame
        # carried was assigned here and then OVERWRITTEN by its own
        # equation's propagation, so with `x = 1.0, y = 5.0` and
        # `y = "2*x"` the frame shipped u(y) = 2.0 against a declared
        # 5.0. Sorting only by what the file produces was the first
        # repair, and three reviewer passes found it regressed the
        # mirror case: a declared name the frame carries and a
        # `[corrections]` line rewrites was withheld from the
        # `[equations]` lines that READ it, so with `CL = 0.01`,
        # `[equations] CD = "CL * 2"` and `[corrections] CL = "CL*1.02"`
        # against a frame carrying a stale u(CL) = 99, u(CD) shipped as
        # 198.0 where 0.02 is correct. Same failure mode, mirrored: a
        # finite plausible number chosen by the shape of the input.
        #
        # So the partition is not a partition. `validate` refuses a
        # declaration that is neither carried nor produced (REQ-45), so
        # every declared name answers yes to at least one question and no
        # declaration goes unapplied; the assertion after the loop is
        # what holds that claim to account rather than assuming it.
        setup = {key: declared[key] for key in declared if key in work.vars}
        pending = {key: declared[key] for key in declared if key in produced}
        if setup:
            work = work.set_uncertainty(setup, history=True, comment=signature)
        for equation in (*self.spec.equations, *self.spec.corrections):
            work = work.compute(
                f"{equation.target} = {self._substitute(equation)}",
                history=True,
                comment=signature,
            )
            # A declared uncertainty on a variable the file writes is
            # assigned the moment that variable is written, never at the
            # end: a dependent equation evaluated in between would
            # propagate from an uncertainty this file overrides, and the
            # frame would ship u(dependent) inconsistent with the
            # u(input) it reports (REQ-41, REQ-99). After the FIRST write
            # only, so a later line rewriting the same name propagates
            # over it; whether that is right is OQ-43, open.
            if equation.target in pending:
                work = work.set_uncertainty(
                    {equation.target: pending.pop(equation.target)},
                    history=True,
                    comment=signature,
                )
        # Every declared name was carried, or written, or both, so both
        # dicts are exhausted. Asserted rather than trusted: this is the
        # exact claim the SRS rule rests on, and the two ways it has been
        # got wrong both showed up as a declaration that was applied and
        # then lost, which is silent. An unapplied one would be silent
        # too, so it is made loud here.
        if pending:
            raise ProcessorError(
                f"processor '{self.name}'",
                f"the declared uncertainties {sorted(pending)} were never "
                f"applied: each names a variable the file's targets include, "
                f"yet no evaluated line wrote it",
                "this is an internal inconsistency between the parsed "
                "targets and the lines that were evaluated, not something a "
                "caller can cause; report it with the .itceq file (REQ-45, "
                "SRS Section 4.6)",
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
        signed = any(self._signs(entry.comment) for entry in db.history)
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

    def _signs(self, comment: str | None) -> bool:
        """Whether this comment was written BY this processor (DD-35).

        Exactly as permissive as the writer and no more. ``__call__``
        writes either the signature alone or ``"<signature>: <user
        comment>"``, always at offset zero, so those two shapes are the
        whole contract.

        Containment would be wrong in both directions, and both were
        reachable. A user comment quoting the signature, which REQ-19
        invites, would sign a frame this processor never touched, which
        is the false refusal DD-35 exists to remove arriving through
        another door. And ``"pproc bal v1"`` is contained in
        ``"pproc bal v1.2: ..."``, so one version would read another
        version's History as its own while the version is part of the
        identity the signature asserts.
        """
        if comment is None:
            return False
        return comment == self.signature or comment.startswith(f"{self.signature}: ")

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
        """Replace a declared constant by its numeric value.

        A negative value is emitted as unary minus over its magnitude
        rather than as a negative literal. ``ast.unparse`` writes
        ``Constant(-0.25)`` as the bare token ``-0.25``, which is not an
        atom: re-parsed in the base of a power it binds as
        ``-(0.25 ** 2)``, so ``x_ref ** 2`` with ``x_ref = -0.25``
        returned the wrong sign AND History recorded an expression that
        is not equivalent to the file's. The unary form unparses to
        ``(-0.25) ** 2`` and is identical everywhere else (CHK1-002).
        """
        if node.id not in self.constants:
            return node
        value = self.constants[node.id]
        # Guarded on the SIGN BIT, not on `value < 0`, so that -0.0 takes
        # this branch too: `-0.0 ** 2` unparses to a bare token that
        # re-parses as `-(0.0 ** 2)` and evaluates to -0.0, which is not
        # 0.0 once anything divides by it, and History would again record
        # an expression that is not the file's.
        if math.copysign(1.0, value) < 0:
            return ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=abs(value)))
        return ast.Constant(value=value)


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
