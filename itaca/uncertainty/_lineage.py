"""Shared-ancestry detection for the interim lineage refusal (internal).

SEAT-UNC, the author decision of 2026-07-31. The clause-5 engine in
:mod:`itaca.uncertainty.propagation` is exact WITHIN one expression,
where the chain rule supplies every partial from one operator tree.
"Exact" here means exact to the first order REQ-41 already works to:
the GUM linearization is not what these findings are about, and the
oracle cannot speak to it either, being first order itself (VV-5). It
carries nothing BETWEEN operations: ``compute`` stores a derived
variable as values plus an uncertainty, and nothing records which inputs
produced it, so the next ``compute`` reading two such variables treats
them as independent. Measured both directions on ``dde261c``: ``p = 3*x``
then ``q = 2*x`` then ``r = p - q`` overstated u(r) 3.6x, and ``y = 2*x``
then ``z = y - 2*x`` returned 0.283 where zero is exact.

This module detects the condition and nothing else. It is the SMALLER
half of the problem on purpose, and the boundary is worth stating
because the two halves look adjacent:

* **Detection needs only the names.** Which root variables a derived
  quantity came from is enough to know that two quantities are not
  independent, and that is all a refusal needs.
* **Propagation needs the sensitivities.** To compute the covariance
  instead of refusing, the engine would have to carry the partial
  derivatives of every derived variable with respect to every root,
  updated by every operation. That is lineage tracking, it is owed to
  v0.3.0, and nothing in this module may grow toward it. A function here
  that wants to store a derivative has crossed the line.

So the detector adds NO state to any frame. It reads what REQ-18 already
guarantees: every operation records itself in History, and a replayable
``compute`` entry carries its equation string verbatim. Ancestry is
recovered by walking that record, so a frame built before this module
existed is analyzable by it wherever the record is replayable. Where it
is not, and a schema-1 archive restores its entries WITHOUT steps, the
detector cannot see the derivations at all: those frames REFUSE rather
than pass, which is the only safe reading of a record it cannot read
(ARCH-3).

The detector is deliberately CONSERVATIVE. It over-approximates the
referenced names and treats an unparsable equation as sharing ancestry
with everything, so it may refuse a composition that would have been
fine. It must never miss one: a false refusal is an error message, a
missed one is a wrong number in an engineering report.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from itaca.uncertainty.expression import _CONSTANTS

if TYPE_CHECKING:
    from itaca.core.correlation import CorrelationMatrix
    from itaca.core.history import History

_EQUATION = re.compile(r"^\s*(\w+)\s*=\s*(.+?)\s*$", re.DOTALL)

_EXPRESSION_CONSTANTS = frozenset(_CONSTANTS)
"""Names ``parse_expression`` resolves to numbers rather than variables.

Read from the parser's own table rather than re-listed here. A second
copy drifts, and drift in THIS direction invents a shared ancestor
between two expressions that merely name the same constant, which is a
false refusal (ARCH-4).
"""

_UNKNOWN = "?"
"""Stand-in root for an origin this module could not determine.

It is not a legal variable name, so it can never collide with a real
one. It is added to EVERY carrier's ancestry when anything unreadable
appears in the record, which is what makes the unknown case refuse: a
root that intersects only itself would have let an unparsable variable
compose with the very root it came from.
"""

_MAX_SUGGESTION = 400
"""Length beyond which the expanded single expression stops helping.

A deep chain expands exponentially, and a 4000-character equation is not
an actionable workaround. Past this the refusal says what to do instead
of pasting an unreadable line.
"""


@dataclass(frozen=True)
class _Derivation:
    """What an earlier operation produced, as names only."""

    roots: frozenset[str]
    expanded: str
    faithful: bool = True
    """Whether ``expanded`` reproduces this variable's VALUES exactly.

    False when the recorded call carried anything beyond its equation
    (``where=``, ``fill=``, ``method=``) or spliced in an unfaithful
    ancestor. Review finding ARCH-2 measured the consequence: with
    ``p = 3*x`` computed under ``where="x > 1"``, ``p`` is
    ``[nan, 6., 9.]`` and the suggested ``r = (3*x) - (2*x)`` returns
    ``[1., 2., 3.]``, so the "equivalent" expression silently changed the
    values. DD-46 rests on that expression being equivalent, so an
    unfaithful one must not be offered at all.
    """


@dataclass(frozen=True)
class _Lineage:
    """What this module could read out of a History, and what it could not."""

    derived: dict[str, _Derivation]
    unreadable: frozenset[str]
    """Operations whose effect on ancestry this module cannot determine.

    Non-empty makes EVERY variable's origin unknown, including variables
    that were never derived, so any multi-carrier expression is refused.
    That severity is the point: it cannot be expressed by marking entries
    in :attr:`derived`, because a root variable is absent from that map
    by construction and would keep reading as independent (ARCH-3).
    """


def _referenced_names(text: str) -> frozenset[str] | None:
    """Variable names an expression reads, over-approximated.

    Returns ``None`` when the text cannot be parsed at all, which the
    caller treats as unknown ancestry rather than as no ancestry.

    Names in call position (``sin`` in ``sin(x)``) and the base of an
    attribute (``np`` in ``np.max(v)``) are excluded, because neither is
    a variable and counting them would invent a shared ancestor between
    two unrelated expressions that happen to call the same function.
    """
    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    skip: set[int] = set()
    for node in ast.walk(parsed):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            skip.add(id(node.func))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            skip.add(id(node.value))
    return frozenset(
        node.id
        for node in ast.walk(parsed)
        if isinstance(node, ast.Name)
        and id(node) not in skip
        and node.id not in _EXPRESSION_CONSTANTS
    )


def _substitute(text: str, definitions: dict[str, _Derivation]) -> str:
    """Replace each derived name in ``text`` by its parenthesized definition."""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(0)
        known = definitions.get(name)
        return f"({known.expanded})" if known is not None else name

    return re.sub(r"\b[A-Za-z_]\w*\b", _replace, text)


_STEPLESS_SAFE = frozenset(
    {"load", "pivot", "set_uncertainty", "set_correlation", "concat", "declare_vector"}
)
"""Step-less operations that confer no cross-variable ancestry.

A History entry with no ``step`` is non-replayable, and reading every one
of them as "no ancestry" was a miss: a schema-1 archive restores its
entries WITHOUT steps, so a frame reopened from one had its whole
derivation record invisible to this module, and ``combine`` is
non-replayable by construction while genuinely mixing two frames'
variables (review finding ARCH-3).

Reading every one of them as poison is not the answer either: ``load``
is step-less on every frame ever built, so that would refuse everything.
This is the allowlist, and it is an allowlist rather than a denylist so
an operation added later is conservative by default.

``concat`` is here, and it took two rounds to land on why. It joins
along a DIMENSION and never mixes one variable into another, which is
true of the VALUES and false of the RECORD: it rebuilds from the first
input alone, so every other input's derivation entries are discarded and
a shared origin in a later input goes unrecorded (ARCH-5, measured at
3.6x). Removing it from this set answered that by poisoning EVERY
concatenated frame, which refused two inputs of plain roots with no
derivation anywhere, and that is REQ-24 mainline usage (ARCH-8).

``concat`` satisfies this set's PREDICATE: it joins along a dimension
and never rewrites one variable from another, so it confers no
cross-variable ancestry. That is why it belongs here. Removing it was
tried and poisoned every concatenated frame, refusing two inputs of
plain roots, which is REQ-24 mainline usage (ARCH-8); that is
corroboration and not the reason.

What ``concat`` DOES lose is the RECORD, because the joined frame keeps
the History of its first input alone. A refusal at the concat itself was
implemented and WITHDRAWN by the author's decision of 2026-08-02. The
consequence is a DECLARED GAP covering every refusal in this module, and
REQ-41 is its single home; read it, DD-52 section 4 and OQ-55 before
changing this entry or that decision.

By the time a frame reaches this module the evidence is gone, and a set
membership cannot recover it.

The entries here build or annotate a frame without deriving anything.
"""

_CROSS_VARIABLE_CALLS = frozenset({"translate_moments", "rotate"})
"""Replayable operations that rewrite a variable from OTHER variables.

Found by review (ARCH-1, VV-1) and measured: after one
``translate_moments``, ``compute("c = MY - FZ")`` returned
``u = 1.41421356`` where zero is correct, and ``"c = MY + FZ"`` returned
the same 1.414 where 2.0 is correct. The transfer makes ``M'`` a
function of ``F``, so they share ancestry exactly as two ``compute``
targets do, and reading only ``compute`` entries let FND-058's own shape
back in through a different door.

Most operations are NOT here on purpose. ``smooth``, ``diff``,
``average``, ``select`` and ``expand`` transform a variable from ITSELF
along a dimension; they induce point-to-point correlation, which is
FND-088's axis and handled by :func:`interpolated_dims`, not
variable-to-variable correlation.
"""

_DEFAULT_GROUPS = {"force": ("FX", "FY", "FZ"), "moment": ("MX", "MY", "MZ")}


def _group_members(
    role: str, selected: object, groups: Mapping[str, Sequence[str]] | None
) -> tuple[str, ...] | None:
    """Resolve a vector group to its component names, or ``None`` if it cannot be."""
    if isinstance(selected, str):
        found = (groups or {}).get(selected)
        return tuple(found) if found is not None else None
    declared = (groups or {}).get(role)
    if declared is not None:
        return tuple(declared)
    return _DEFAULT_GROUPS[role]


def derivations(
    history: History, groups: Mapping[str, Sequence[str]] | None = None
) -> _Lineage:
    """Map every derived variable in ``history`` to its roots and full form.

    Walks the record forward once, so a target that is recomputed from
    its own previous value expands against the DEFINITION IN FORCE at
    that point and the walk terminates. A name that was never derived is
    absent from the result, and the caller reads absence as "this is a
    root".

    Parameters
    ----------
    history : History
        The frame's operation record.
    groups : mapping of str to sequence of str, or None
        The frame's declared vector groups, needed to resolve which
        variables a ``rotate`` or ``translate_moments`` rewrote. When a
        group cannot be resolved the operation is treated as conferring
        UNKNOWN ancestry on every variable, which refuses rather than
        guesses.

    Returns
    -------
    _Lineage
        The derived-variable map and the names of any operations this
        module could not read.

    Notes
    -----
    Only NAMES are propagated here. Recording a sensitivity would make
    this the v0.3.0 lineage engine; see the module docstring.
    """
    found: dict[str, _Derivation] = {}
    poisoned: set[str] = set()
    redeclared_roots: set[str] = set()
    consumed_roots: set[str] = set()

    def _roots_of(name: str) -> frozenset[str]:
        previous = found.get(name)
        return previous.roots if previous is not None else frozenset({name})

    def _mix(outputs: Sequence[str], inputs: Sequence[str]) -> None:
        """Give every output the union of every input's roots."""
        roots = frozenset().union(*(_roots_of(name) for name in inputs))
        for name in outputs:
            found[name] = _Derivation(roots=roots, expanded=name, faithful=False)

    for entry in history:
        step = entry.step
        if step is None:
            if entry.name not in _STEPLESS_SAFE:
                poisoned.add(entry.name)
            continue
        if step.call in _CROSS_VARIABLE_CALLS:
            if step.call == "translate_moments":
                force = _group_members("force", step.kwargs.get("force"), groups)
                moment = _group_members("moment", step.kwargs.get("moment"), groups)
                if force is None or moment is None:
                    poisoned.add(step.call)
                    continue
                _mix(moment, (*force, *moment))
            else:
                named = step.kwargs.get("vector_groups")
                wanted = (
                    [str(name) for name in named]
                    if isinstance(named, (list, tuple))
                    else list(groups or {})
                )
                if not wanted:
                    poisoned.add(step.call)
                    continue
                for role in wanted:
                    members = (groups or {}).get(role)
                    if members is None:
                        poisoned.add(step.call)
                        continue
                    _mix(tuple(members), tuple(members))
            continue
        if step.call == "set_uncertainty":
            # VV-8. A declared uncertainty OVERRIDES what propagation
            # produced, so this variable's recorded equation no longer
            # accounts for its stored uncertainty and any expansion past
            # it would reinstate the value the user replaced. Marked
            # here, in the forward walk, rather than checked at the
            # splice site: checking the splice caught only the FIRST
            # level, and `p` re-declared then `q = 2*p` then
            # `r = q - x` still offered a suggestion returning about 0.5
            # against the 10.0 the frame implies.
            spec = step.kwargs.get("spec")
            if isinstance(spec, Mapping):
                for raw in spec:
                    name = str(raw)
                    # Mark the name itself when it is a derivation, and
                    # EVERY derivation already standing on it. The
                    # round-three fix marked forward only, so a variable
                    # derived BEFORE the re-declaration kept faithful =
                    # True: measured, u(x) re-declared to 5.0 after
                    # p = 3*x still offered `r = (3*x) - x` as "already
                    # correct" while returning 10.0 against a stored
                    # u(p) = 0.3 and u(x) = 5.0 (QA round four). It was
                    # reported fixed and was not, which is why the guard
                    # below is a test and not a comment.
                    for held, known in list(found.items()):
                        if held == name or name in known.roots:
                            found[held] = _Derivation(
                                roots=known.roots,
                                expanded=known.expanded,
                                faithful=False,
                            )
                    if name not in found and name in consumed_roots:
                        redeclared_roots.add(name)
            continue
        if step.call != "compute":
            continue
        equation = step.kwargs.get("equation")
        if not isinstance(equation, str):
            continue
        match = _EQUATION.match(equation)
        if match is None:
            continue
        target, text = match.group(1), match.group(2)
        names = _referenced_names(text)
        redeclared_roots.discard(target)
        if names is not None:
            consumed_roots |= {name for name in names if name not in found}
        if names is None:
            # An equation this module cannot read is treated as an
            # UNREADABLE OPERATION, not as a target with an unknown root.
            # Writing it as a root was measurably too weak: `_UNKNOWN`
            # intersects only itself, so an unparsable `p` against the
            # root `x` it may well have come from found no common origin
            # and let the composition through (QA F1, which asked for the
            # test that showed it).
            poisoned.add(f"compute('{target} = ...')")
            found[target] = _Derivation(
                roots=frozenset({_UNKNOWN}), expanded=text, faithful=False
            )
            continue
        roots: set[str] = set()
        for name in names:
            roots |= _roots_of(name)
        # An expansion is faithful only when this entry recorded nothing
        # but its equation AND every ancestor it splices in was faithful
        # too. `where=`, `fill=` and `method=` all change what the call
        # produced, and the expansion drops them silently (ARCH-2).
        faithful = (
            set(step.kwargs) <= {"equation"}
            and all(found[name].faithful for name in names if name in found)
            and not (names & redeclared_roots)
        )
        found[target] = _Derivation(
            roots=frozenset(roots),
            expanded=_substitute(text, found),
            faithful=faithful,
        )
    return _Lineage(derived=found, unreadable=frozenset(poisoned))


def _declared(correlation: CorrelationMatrix | None, name_a: str, name_b: str) -> bool:
    """Whether the user has declared this pair, at any coefficient.

    A declared pair is the second way past the refusal. The engine
    already uses the coefficient in the clause-5 formula, and a user who
    writes one has made a statement about that pair which this module
    has no standing to overrule. Declared ZERO counts: it is a claim of
    independence, not an absence of one.
    """
    if correlation is None:
        return False
    return (name_a, name_b) in correlation.pairs or (
        name_b,
        name_a,
    ) in correlation.pairs


def shared_ancestry(
    history: History,
    carriers: Sequence[str],
    correlation: CorrelationMatrix | None,
    groups: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, str, frozenset[str]] | None:
    """First carrier pair with a common origin, or ``None`` if all independent.

    Parameters
    ----------
    history : History
        The frame's operation record.
    carriers : sequence of str
        Expression variables that carry uncertainty. Only carriers can
        contribute a variance term, so only they can induce covariance.
    correlation : CorrelationMatrix or None
        Declared pairs, which the detector steps aside for.
    groups : mapping of str to sequence of str, or None
        The frame's declared vector groups, so a ``rotate`` or
        ``translate_moments`` can be resolved to the variables it
        rewrote.

    Returns
    -------
    tuple of (str, str, frozenset of str) or None
        The two carriers and the roots they share, or ``None``.
    """
    if len(carriers) < 2:
        return None
    lineage = derivations(history, groups)
    if not lineage.derived and not lineage.unreadable:
        return None
    unknown = frozenset({_UNKNOWN}) if lineage.unreadable else frozenset()
    ancestry = {
        name: (
            lineage.derived[name].roots
            if name in lineage.derived
            else frozenset({name})
        )
        | unknown
        for name in carriers
    }
    ordered = sorted(carriers)
    for index, name_a in enumerate(ordered):
        for name_b in ordered[index + 1 :]:
            common = ancestry[name_a] & ancestry[name_b]
            if common and not _declared(correlation, name_a, name_b):
                return name_a, name_b, common
    return None


def single_expression(
    history: History,
    target: str,
    text: str,
    groups: Mapping[str, Sequence[str]] | None = None,
) -> str | None:
    """Build the one-call equation equivalent to a refused composition.

    This is what makes the refusal actionable rather than a lecture: the
    same arithmetic written as a single expression is ALREADY correct,
    because the chain rule sees the whole tree at once.

    Returns ``None`` rather than a suggestion when the expansion would
    not be equivalent, and the caller then gives generic advice. Three
    ways that happens, and the first two were review findings:

    * An ancestor was computed with anything beyond its equation, so the
      expansion silently drops a ``where=`` mask or a ``fill=`` and
      changes the VALUES (ARCH-2).
    * An ancestor's uncertainty was RE-DECLARED after it was computed,
      so the expansion propagates from the original roots and ignores
      the declaration that overrode them (VV-4).
    * The expansion grows past the point of being pasteable.

    A wrong suggestion is worse than none: the whole argument for
    refusing rather than propagating is that the named expression is
    equivalent (DD-46).
    """
    lineage = derivations(history, groups)
    if lineage.unreadable:
        return None
    names = _referenced_names(text)
    if names is None:
        return None
    spliced = [name for name in names if name in lineage.derived]
    if not all(lineage.derived[name].faithful for name in spliced):
        return None
    equation = f"{target} = {_substitute(text, lineage.derived)}"
    return equation if len(equation) <= _MAX_SUGGESTION else None


def earlier_transfer(history: History) -> tuple[float, float, float] | None:
    """Find the reference point the FIRST recorded transfer moved from.

    FND-074. The rigid transfer ``M' = M + r x F`` makes the new moments
    a linear function of the forces, so ``M'`` and ``F`` are correlated
    however independent they were before. ``translate_moments`` drops the
    pairs naming the moments it rewrote and writes no induced pair in
    their place, so a SECOND transfer reads the two groups as independent
    and understates: measured 1.414 against a correct 2.0, 29 percent low.

    The FIRST transfer is returned rather than the most recent one,
    because the workaround is a single call spanning the whole journey
    and that call starts where the journey started.
    """
    for entry in history:
        step = entry.step
        if step is None or step.call != "translate_moments":
            continue
        point = step.kwargs.get("from_point")
        if isinstance(point, (list, tuple)) and len(point) == 3:
            return (float(point[0]), float(point[1]), float(point[2]))
        return (0.0, 0.0, 0.0)
    return None


def interpolated_dims(history: History) -> frozenset[str]:
    """Dimensions whose points an earlier ``interpolate`` produced.

    FND-088. Interpolation makes every output point a linear combination
    of the SAME source points, so the points along that dimension are
    correlated with each other. ``reduce_random`` (REQ-99) assumes they
    are independent and takes the root sum of squares, which understates:
    measured 0.559 against a correct 0.707, 21 percent low.

    The dimension matters, and this is why the detector reads the mapping
    rather than merely noting that an interpolation happened. Correlation
    induced along ``alpha`` says nothing about points along ``run``, and
    interpolating runs onto a common grid and then averaging across runs
    is the ordinary wind-tunnel workflow. A detector blind to which axis
    was touched would refuse it for no reason.
    """
    touched: set[str] = set()
    for entry in history:
        step = entry.step
        if step is None or step.call != "interpolate":
            continue
        # Mapping, not dict: PipelineStep freezes its kwargs into a
        # MappingProxyType, which is NOT a dict subclass, so an
        # isinstance(..., dict) test here silently matched nothing and
        # the guard never fired.
        mapping = step.kwargs.get("mapping")
        if isinstance(mapping, Mapping):
            touched |= {str(key) for key in mapping}
        translation = step.kwargs.get("axisTranslation")
        if isinstance(translation, Mapping):
            # The old axis is consumed and the target variable becomes the
            # new dimension; both names are recorded, since either may be
            # the one a later reduction names.
            for key in ("from", "to"):
                value = translation.get(key)
                if isinstance(value, str):
                    touched.add(value)
    return frozenset(touched)


def describe_unreadable(
    history: History, groups: Mapping[str, Sequence[str]] | None = None
) -> str:
    """Name the operations that made this frame's origins unreadable."""
    names = sorted(derivations(history, groups).unreadable)
    if not names:
        return "an operation it cannot read"
    return ", ".join(f"'{name}'" for name in names)


def unknown_only(roots: Iterable[str]) -> bool:
    """Whether the shared origin is only that something could not be read.

    The two cases need different messages. "Both were derived from 'x'"
    is a statement of fact; saying it about two INDEPENDENT roots that
    merely sit in a frame carrying an unreadable operation is false, and
    the workaround that follows it cannot be executed because there is no
    derivation to rewrite. Measured in review: ``combine`` then
    ``compute("z = x + y")`` on plain roots refused while claiming they
    were derived from a common origin (VV-10).
    """
    return set(roots) == {_UNKNOWN}


def describe_roots(roots: Iterable[str]) -> str:
    """Render shared roots for an error message, naming the unknown case."""
    named = sorted(root for root in roots if root != _UNKNOWN)
    if not named:
        return "an origin this frame's History does not record"
    return ", ".join(f"'{name}'" for name in named)
