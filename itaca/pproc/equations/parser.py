"""The .itceq equation-file parser (REQ-48, DD-17, OQ-04, OQ-28).

An .itceq file is a TOML-structured text file with five sections (SRS
Section 4.6). It is read with the standard-library ``tomllib``: the
Python floor is 3.11 precisely so this needs no dependency, no vendored
reader, and no parser of ours (REQ-83, DD-32).

Two things happen here that cannot happen later. Section rules are
enforced on the declared shape, so a malformed file is refused before it
touches data; and cyclic dependencies are detected at parse time, before
any computation (REQ-48), in both ordering modes (OQ-04).

Ordering (DD-17)
----------------
Equations evaluate in file order by default. ``auto_sort=True`` resolves
the dependency order instead and reports the order it chose, so a file
whose behavior depends on the sort says so out loud. That report goes to
stdout because REQ-48 charters it as feedback to the user, DD-17 records
why, and a log record at INFO is silent under the default configuration;
OQ-48 asks whether a library should be reporting on stdout at all. The
resolved order
is the stable topological order: at each step the equation earliest in
FILE order whose dependencies are already met. That rule is stated
rather than incidental, which is what answers the portability risk
DD-17 names; it is not an edit-distance-minimal reordering, and it may
hoist an independent equation above a dependent one.

In file order, which is the default, an equation may only read what an
earlier line produced. A forward reference is refused when the file is
read rather than left to fail later, because the frame may happen to
carry the same name, in which case the equation would silently use the
measured value and the later line would overwrite it.

Dependencies and what counts as a cycle
---------------------------------------
An expression's dependencies are the names it reads. Function names,
the ``np`` prefix, and the constants ``pi`` and ``e`` are not names it
reads. Neither is anything an earlier stage supplies: ``[constants]``
are registered before any equation runs, and ``[corrections]`` run after
``[equations]``, so a correction reading a variable ``[equations]``
produced reads a value that already exists. Dependency edges therefore
only ever point within a stage, and a cycle is a cycle within one stage.

That is also what makes replacement work. ``[corrections]`` may replace
existing variables (SRS Section 4.6), so ``CL = "CL * blockage"`` reads
the ``CL`` that ``[equations]`` produced and writes a new one: not a
self-cycle. The same line inside ``[equations]`` is a self-cycle and is
refused, because ``[equations]`` derives new variables and replacement
is what ``[corrections]`` is for.
"""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

from itaca.core.errors import ItceqCycleError, ItceqParseError

__all__ = ["Equation", "ItceqSpec", "parse_itceq"]

SECTIONS = ("meta", "constants", "uncertainties", "equations", "corrections")
"""The five sections of SRS Section 4.6, in evaluation order."""

_EXPRESSION_CONSTANTS = frozenset({"pi", "e"})
"""Names the expression engine supplies as literals (REQ-44)."""

_NAMESPACE = "np"
"""The one attribute namespace expressions may call into (REQ-44)."""

_META_BOOLEAN = frozenset({"idempotent"})
"""The typed exception to the strings-only ``[meta]`` rule (REQ-47).

Idempotence decides whether a workflow may legally re-run, and REQ-48
says the file defines the workflow in full, so it is declared in the
file rather than only in Python. It is kept out of ``meta`` on the spec
so that mapping stays honestly strings-only.
"""


@dataclass(frozen=True)
class Equation:
    """One ``target = expression`` line of an .itceq file.

    Parameters
    ----------
    target : str
        The variable the line derives. A Python identifier.
    expression : str
        The right-hand side, over the REQ-44 operator set.
    """

    target: str
    expression: str


@dataclass(frozen=True)
class ItceqSpec:
    """A parsed, validated, acyclic .itceq file (REQ-48).

    The equation sequences are already in evaluation order: file order,
    or the resolved dependency order when the file was parsed with
    ``auto_sort=True``.

    Parameters
    ----------
    source : pathlib.Path
        The file this was read from.
    meta : mapping of str to str
        The ``[meta]`` section. Required to exist; all fields optional.
    constants : mapping of str to float
        The ``[constants]`` section, registered before any equation.
    uncertainties : mapping of str to float or str
        The ``[uncertainties]`` section. A float is absolute, a string
        ending in ``"%"`` is relative. Enters the UncFrame as the
        systematic component (SRS Chapter 8, REQ-99).
    equations : tuple of Equation
        The ``[equations]`` section, in evaluation order.
    corrections : tuple of Equation
        The ``[corrections]`` section, in evaluation order. Runs after
        ``equations`` and may replace variables it produced.
    idempotent : bool
        The ``[meta] idempotent`` declaration (REQ-47). Whether
        reapplying this workflow is meaningful; ``False`` by default,
        so a second application is refused unless the caller forces it.
    sorted : bool
        Whether the order above was resolved by ``auto_sort``.
    required_variables : tuple of str
        Names the VarFrame must supply, sorted: everything an
        expression reads that the file does not itself provide, so not
        a constant, not a target of any section, and not a literal of
        the expression engine.

    Examples
    --------
    >>> spec = parse_itceq("balance.itceq")  # doctest: +SKIP
    >>> [equation.target for equation in spec.equations]  # doctest: +SKIP
    ['q_inf', 'CL', 'CD']
    """

    source: Path
    meta: Mapping[str, str]
    constants: Mapping[str, float]
    uncertainties: Mapping[str, float | str]
    equations: tuple[Equation, ...] = ()
    corrections: tuple[Equation, ...] = ()
    idempotent: bool = False
    sorted: bool = False
    required_variables: tuple[str, ...] = ()

    @property
    def targets(self) -> tuple[str, ...]:
        """Every variable the file writes, equations then corrections."""
        written: list[str] = []
        for equation in (*self.equations, *self.corrections):
            if equation.target not in written:
                written.append(equation.target)
        return tuple(written)

    @property
    def builtin_constants(self) -> tuple[str, ...]:
        """Built-in expression constants any expression reads (REQ-44).

        ``required_variables`` subtracts ``pi`` and ``e`` unconditionally,
        which is right for "which channels must the frame supply" and
        wrong for "can this frame feed this processor": a frame carrying a
        variable named ``e`` makes every read of that name ambiguous while
        the name appears in no field for anything to notice.

        Computed over equations AND corrections, in the shape of
        :attr:`targets` beside it, because ``__call__`` evaluates both. An
        earlier form scanned only ``equations``, so a correction reading
        the name passed ``validate`` and then failed partway through the
        application, after earlier equations had already been written.

        Returns
        -------
        tuple of str
            The subset of ``pi`` and ``e`` read as a name, sorted.

        Examples
        --------
        >>> spec = parse_itceq("drag.itceq")  # doctest: +SKIP
        >>> spec.builtin_constants               # doctest: +SKIP
        ('e', 'pi')
        """
        found: set[str] = set()
        for equation in (*self.equations, *self.corrections):
            # No try/except. Every expression here already parsed in
            # `_dependencies` at read time, so a SyntaxError is an
            # impossible state, and swallowing one would silently skip
            # the shadowing check for that equation, which is the very
            # defect this property exists to catch.
            tree = ast.parse(equation.expression, mode="eval")
            found |= {
                node.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Name) and node.id in _EXPRESSION_CONSTANTS
            }
        return tuple(sorted(found))


def parse_itceq(path: str | Path, *, auto_sort: bool = False) -> ItceqSpec:
    """Read and validate an .itceq file (REQ-48).

    Parameters
    ----------
    path : str or pathlib.Path
        The .itceq file to read.
    auto_sort : bool, optional
        Resolve the dependency order instead of keeping file order, and
        report the resolved order (DD-17). Cycles are detected either
        way (OQ-04).

    Returns
    -------
    ItceqSpec
        The parsed file, with both equation sequences in evaluation
        order.

    Raises
    ------
    ItceqParseError
        If the file is absent, is not valid TOML, declares an unknown
        section, or violates a section rule of SRS Section 4.6.
    ItceqCycleError
        If the equations or the corrections depend on each other
        cyclically.

    Examples
    --------
    >>> spec = parse_itceq("balance.itceq", auto_sort=True)  # doctest: +SKIP
    >>> spec.required_variables  # doctest: +SKIP
    ('FZ', 'V', 'rho')
    """
    source = Path(path)
    raw = _read(source)
    unknown = sorted(set(raw) - set(SECTIONS))
    if unknown:
        raise ItceqParseError(
            f"file '{source.name}'",
            f"it declares unknown section(s) {unknown}",
            f"an .itceq file has exactly these sections: {list(SECTIONS)} "
            "(REQ-48, SRS Section 4.6)",
        )
    if "meta" not in raw:
        raise ItceqParseError(
            f"file '{source.name}'",
            "it has no [meta] section, which is required",
            'add a [meta] section, for example name = "Balance: power off" (REQ-48)',
        )
    meta, idempotent = _meta(source, raw["meta"])
    constants = _constants(source, raw.get("constants", {}))
    uncertainties = _uncertainties(source, raw.get("uncertainties", {}))
    equations = _equations(source, raw.get("equations", {}), "equations")
    corrections = _equations(source, raw.get("corrections", {}), "corrections")

    _refuse_shadowed_constants(source, constants, equations, corrections)

    # Stage by stage: [constants] first, then [equations], then
    # [corrections]. Each stage resolves against what the earlier ones
    # supply, which is what makes correction-side replacement legal.
    supplied = set(constants)
    equations = _resolve(source, equations, supplied, "equations", auto_sort)
    supplied |= {equation.target for equation in equations}
    corrections = _resolve(source, corrections, supplied, "corrections", auto_sort)

    required = tuple(sorted(_required(source, constants, equations, corrections)))
    return ItceqSpec(
        source=source,
        meta=meta,
        constants=MappingProxyType(constants),
        uncertainties=MappingProxyType(uncertainties),
        equations=equations,
        corrections=corrections,
        idempotent=idempotent,
        sorted=auto_sort,
        required_variables=required,
    )


# ---------------------------------------------------------------------------
# Section rules (SRS Section 4.6)
# ---------------------------------------------------------------------------


def _read(source: Path) -> dict[str, Any]:
    if not source.is_file():
        raise ItceqParseError(
            f"path '{source}'",
            "the .itceq file does not exist, so no processor can be built from it",
            "check the path, or pass a registered processor name instead (REQ-46)",
        )
    try:
        parsed: dict[str, Any] = tomllib.loads(source.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ItceqParseError(
            f"file '{source.name}'",
            f"it is not valid TOML: {error}",
            "an .itceq file is TOML with five sections; fix the syntax at "
            "the position reported above (REQ-48)",
        ) from None
    except UnicodeDecodeError as error:
        raise ItceqParseError(
            f"file '{source.name}'",
            f"it is not valid UTF-8 text: {error}",
            "save the file as UTF-8; .itceq files are text and in English (REQ-86)",
        ) from None
    return parsed


def _meta(source: Path, section: Any) -> tuple[Mapping[str, str], bool]:
    """Split ``[meta]`` into its string fields and the one typed flag."""
    table = _table(source, section, "meta")
    fields: dict[str, str] = {}
    idempotent = False
    for key, value in table.items():
        if key in _META_BOOLEAN:
            if not isinstance(value, bool):
                raise ItceqParseError(
                    f"[meta] field '{key}' in '{source.name}'",
                    f"it is {type(value).__name__}, and this field is a "
                    "boolean rather than a string",
                    f"write it unquoted, as {key} = true or {key} = false "
                    "(REQ-47, REQ-48)",
                )
            idempotent = value
            continue
        if not isinstance(value, str):
            raise ItceqParseError(
                f"[meta] field '{key}' in '{source.name}'",
                f"it is {type(value).__name__}, but every [meta] field is a "
                f"string except {sorted(_META_BOOLEAN)}",
                f'quote the value, for example {key} = "{value}" (REQ-48)',
            )
        fields[key] = value
    return MappingProxyType(fields), idempotent


def _constants(source: Path, section: Any) -> dict[str, float]:
    table = _table(source, section, "constants")
    constants: dict[str, float] = {}
    for key, value in table.items():
        _identifier(source, key, "constant")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ItceqParseError(
                f"constant '{key}' in '{source.name}'",
                f"its value {value!r} is not a number, and every [constants] "
                "entry is numeric",
                f"write it as a number, for example {key} = 0.1963 (REQ-48)",
            )
        constants[key] = float(value)
    return constants


def _uncertainties(source: Path, section: Any) -> dict[str, float | str]:
    table = _table(source, section, "uncertainties")
    uncertainties: dict[str, float | str] = {}
    for key, value in table.items():
        _identifier(source, key, "uncertainty target")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            _bad_uncertainty(source, key, value)
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped.endswith("%") or not _is_float(stripped[:-1]):
                _bad_uncertainty(source, key, value)
            uncertainties[key] = stripped
        else:
            uncertainties[key] = float(value)
    return uncertainties


def _bad_uncertainty(source: Path, key: str, value: object) -> NoReturn:
    raise ItceqParseError(
        f"uncertainty for '{key}' in '{source.name}'",
        f"its value {value!r} is neither a number nor a relative string",
        f"write an absolute value as {key} = 0.005, or a relative one as "
        f'{key} = "0.05%" (REQ-48, REQ-39)',
    )


def _equations(source: Path, section: Any, name: str) -> tuple[Equation, ...]:
    table = _table(source, section, name)
    equations: list[Equation] = []
    for key, value in table.items():
        _identifier(source, key, f"{name.rstrip('s')} target")
        if not isinstance(value, str):
            raise ItceqParseError(
                f"equation '{key}' in '{source.name}'",
                f"its value {value!r} is {type(value).__name__}, but an "
                f"[{name}] entry is an expression string",
                f'quote the expression, for example {key} = "FZ / q_inf" (REQ-48)',
            )
        equations.append(Equation(target=key, expression=value))
    return tuple(equations)


def _table(source: Path, section: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(section, dict):
        raise ItceqParseError(
            f"section [{name}] in '{source.name}'",
            f"it is {type(section).__name__}, not a table of key-value pairs",
            f"write it as a TOML table, `[{name}]` followed by its entries (REQ-48)",
        )
    return section


def _identifier(source: Path, key: str, role: str) -> None:
    if not key.isidentifier():
        raise ItceqParseError(
            f"{role} '{key}' in '{source.name}'",
            "it is not a valid Python identifier, so it cannot name a variable",
            "use letters, digits, and underscores, not starting with a digit (REQ-48)",
        )


def _is_float(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Dependencies, cycles, and the opt-in order (REQ-48, DD-17)
# ---------------------------------------------------------------------------


def _refuse_shadowed_constants(
    source: Path,
    constants: Mapping[str, float],
    equations: tuple[Equation, ...],
    corrections: tuple[Equation, ...],
) -> None:
    """Refuse a name declared both as a constant and as a target.

    A constant is substituted into every read before the expression
    runs, so an equation writing the same name produces a variable
    nothing in the file can ever read: the equation runs and its result
    is unreachable, silently. A name with two definitions of different
    kinds has no obvious reading, and the one the parser would pick is
    invisible in the file, so it is refused rather than resolved.

    Redefinition WITHIN the equation sections is a different thing and
    stays legal: ``[corrections]`` replacing an ``[equations]`` target
    is what SRS Section 4.6 provides for.
    """
    targets = {equation.target for equation in (*equations, *corrections)}
    shadowed = sorted(set(constants) & targets)
    if shadowed:
        raise ItceqParseError(
            f"name(s) {shadowed} in '{source.name}'",
            "each is declared in [constants] and as an equation target, and "
            "a constant is substituted into every read, so the equation "
            "would run and its result would never be read",
            "rename one of the two; a value that is computed belongs in "
            "[equations], a value that is declared belongs in [constants] "
            "(REQ-48, SRS Section 4.6)",
        )


def _required(
    source: Path,
    constants: Mapping[str, float],
    equations: tuple[Equation, ...],
    corrections: tuple[Equation, ...],
) -> set[str]:
    """Names the VarFrame must supply, resolved stage by stage.

    The stage split matters in both directions. ``[equations]`` runs
    first, so a name only ``[corrections]`` produces is not available to
    it and must come from the frame. ``[corrections]`` runs second, so a
    correction that replaces a variable reads whatever existed before
    it: that is supplied by ``[equations]`` when the name is an equation
    target, and by the frame otherwise, in which case the frame must
    carry it.
    """
    equation_targets = {equation.target for equation in equations}
    correction_targets = {equation.target for equation in corrections}
    required: set[str] = set()
    for equation in equations:
        required |= _dependencies(source, equation) - set(constants) - equation_targets
    for equation in corrections:
        # The entry's own target is excluded from what this stage
        # supplies: reading it is a replacement, satisfied by an earlier
        # stage or by the frame, never by this entry.
        available = (
            set(constants) | equation_targets | (correction_targets - {equation.target})
        )
        required |= _dependencies(source, equation) - available
    return required


def _dependencies(source: Path, equation: Equation) -> set[str]:
    """Names the expression reads, excluding functions and literals."""
    try:
        tree = ast.parse(equation.expression, mode="eval")
    except SyntaxError as error:
        raise ItceqParseError(
            f"equation '{equation.target}' in '{source.name}'",
            f"its expression {equation.expression!r} does not parse: "
            f"{error.msg} at offset {error.offset}",
            "check the syntax against the REQ-44 operator set; the parser "
            "refuses it here rather than at computation time (REQ-48)",
        ) from None
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            skip.add(id(node.func))  # a function name, not a variable
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == _NAMESPACE
        ):
            skip.add(id(node.value))  # the np. prefix
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and id(node) not in skip
        and node.id not in _EXPRESSION_CONSTANTS
    }


def _resolve(
    source: Path,
    equations: tuple[Equation, ...],
    supplied: Iterable[str],
    stage: str,
    auto_sort: bool,
) -> tuple[Equation, ...]:
    """Detect cycles in one stage, and order it when asked (REQ-48, DD-17)."""
    if not equations:
        return equations
    earlier = set(supplied)
    targets = [equation.target for equation in equations]
    position = {target: index for index, target in enumerate(targets)}
    # An edge only points inside this stage: anything an earlier stage
    # supplies is already a value by the time this stage runs, including
    # a name this stage then replaces.
    replaceable = stage == "corrections"
    edges = {
        equation.target: {
            name
            for name in _dependencies(source, equation)
            if name in position
            and name not in earlier
            # A correction reading its own target is a replacement, not
            # a dependency: it reads whatever existed before this entry,
            # which SRS Section 4.6 permits to be a variable the frame
            # supplies. In [equations] the same line is a self-cycle,
            # because that section derives rather than replaces.
            and not (replaceable and name == equation.target)
        }
        for equation in equations
    }
    order = _kahn(targets, edges)
    if len(order) != len(targets):
        remaining = [target for target in targets if target not in set(order)]
        raise ItceqCycleError(
            f"[{stage}] in '{source.name}'",
            "the equations are cyclic and cannot be evaluated in any order: "
            f"{_chain(remaining, edges)}",
            "break the cycle by deriving one of these from variables the "
            "VarFrame supplies; a replacement of an existing variable "
            "belongs in [corrections] (REQ-48, DD-17)",
        )
    if not auto_sort:
        # Only once the graph is known acyclic: a cycle is a forward
        # reference too, and reporting it as one would name the symptom.
        _refuse_forward_reference(source, equations, edges, stage)
        return equations
    by_target = {equation.target: equation for equation in equations}
    resolved = tuple(by_target[target] for target in order)
    # Printed, not logged: REQ-48 charters this feedback normatively and
    # DD-17 records the decision, and a logger.info is silent under the
    # default configuration. Whether that is still the right call is OQ-48,
    # whose answer would need an SRS revision and not only a new DD.
    print(f"auto_sort resolved [{stage}] of {source.name} to: " + " -> ".join(order))
    return resolved


def _refuse_forward_reference(
    source: Path,
    equations: tuple[Equation, ...],
    edges: Mapping[str, set[str]],
    stage: str,
) -> None:
    """Refuse a file whose own order cannot run (REQ-48, DD-17).

    In file order an equation may only read what an earlier line
    produced. Accepting a forward reference has two outcomes and both
    are bad: the frame does not carry the name and ``compute`` raises
    about a variable the file visibly defines, or the frame does carry
    it and the equation silently uses the measured value, which the next
    line then overwrites. The second is a wrong number with no error, so
    the file is refused here instead.
    """
    produced: set[str] = set()
    for equation in equations:
        unmet = sorted(edges[equation.target] - produced)
        if unmet:
            raise ItceqParseError(
                f"equation '{equation.target}' in [{stage}] of '{source.name}'",
                f"it reads {unmet}, which this file defines below it, and "
                "equations run in file order by default",
                f"move {unmet} above '{equation.target}', or parse with "
                "auto_sort=True to resolve the order by dependency "
                "(REQ-48, DD-17)",
            )
        produced.add(equation.target)


def _kahn(targets: Sequence[str], edges: Mapping[str, set[str]]) -> list[str]:
    """Topological order, ties broken by file order (DD-17).

    Emits one target at a time, always the earliest in file order whose
    dependencies are met. Deterministic and independent of dict order
    and of parser internals, which is what DD-17 asks for; it is not an
    edit-distance-minimal reordering and does not claim to be.

    Returns a short list when the graph has a cycle: the caller reads
    the length to detect one, so the same pass serves both modes.
    """
    remaining = {target: set(edges[target]) for target in targets}
    order: list[str] = []
    while remaining:
        for target in targets:
            if target in remaining and not remaining[target]:
                order.append(target)
                del remaining[target]
                for pending in remaining.values():
                    pending.discard(target)
                break
        else:
            break
    return order


def _chain(remaining: Sequence[str], edges: Mapping[str, set[str]]) -> str:
    """Render one cycle from the unordered remainder, for the message."""
    stuck = set(remaining)
    seen: list[str] = []
    current = remaining[0]
    while current not in seen:
        seen.append(current)
        # Every unordered target has an unmet dependency, and an unmet
        # dependency is itself unordered, so the walk never runs dry and
        # always closes on a node it has already seen.
        current = min(edges[current] & stuck)
    return " -> ".join([*seen[seen.index(current) :], current])
