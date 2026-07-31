"""Shared-ancestry detection for the interim lineage refusal (internal).

SEAT-UNC, the author decision of 2026-07-31. The clause-5 engine in
:mod:`itaca.uncertainty.propagation` is exact WITHIN one expression,
where the chain rule supplies every partial from one operator tree. It
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
recovered by walking that record, which is why a frame built before this
module existed is analyzable by it.

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

if TYPE_CHECKING:
    from itaca.core.correlation import CorrelationMatrix
    from itaca.core.history import History

_EQUATION = re.compile(r"^\s*(\w+)\s*=\s*(.+?)\s*$", re.DOTALL)

_EXPRESSION_CONSTANTS = frozenset({"pi", "e"})
"""Names ``parse_expression`` resolves to numbers rather than variables."""

_UNKNOWN = "?"
"""Stand-in root for an equation this module could not parse.

It is not a legal variable name, so it can never collide with a real
one, and it intersects only with itself. Two targets whose equations
both failed to parse are therefore treated as sharing ancestry, which is
the conservative direction.
"""

_MAX_SUGGESTION = 400
"""Length beyond which the expanded single expression stops helping.

A deep chain expands exponentially, and a 4000-character equation is not
an actionable workaround. Past this the refusal says what to do instead
of pasting an unreadable line.
"""


@dataclass(frozen=True)
class _Derivation:
    """What an earlier ``compute`` produced, as names only."""

    roots: frozenset[str]
    expanded: str


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


def derivations(history: History) -> dict[str, _Derivation]:
    """Map every ``compute`` target in ``history`` to its roots and full form.

    Walks the record forward once, so a target that is recomputed from
    its own previous value expands against the DEFINITION IN FORCE at
    that point and the walk terminates. A name that was never a compute
    target is absent from the result, and the caller reads absence as
    "this is a root".
    """
    found: dict[str, _Derivation] = {}
    for entry in history:
        step = entry.step
        if step is None or step.call != "compute":
            continue
        equation = step.kwargs.get("equation")
        if not isinstance(equation, str):
            continue
        match = _EQUATION.match(equation)
        if match is None:
            continue
        target, text = match.group(1), match.group(2)
        names = _referenced_names(text)
        if names is None:
            found[target] = _Derivation(roots=frozenset({_UNKNOWN}), expanded=text)
            continue
        roots: set[str] = set()
        for name in names:
            previous = found.get(name)
            roots |= previous.roots if previous is not None else {name}
        found[target] = _Derivation(
            roots=frozenset(roots), expanded=_substitute(text, found)
        )
    return found


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
) -> tuple[str, str, frozenset[str]] | None:
    """First carrier pair with a common origin, or ``None`` if all independent.

    Parameters
    ----------
    history : History
        The frame's operation record, read for its ``compute`` entries.
    carriers : sequence of str
        Expression variables that carry uncertainty. Only carriers can
        contribute a variance term, so only they can induce covariance.
    correlation : CorrelationMatrix or None
        Declared pairs, which the detector steps aside for.

    Returns
    -------
    tuple of (str, str, frozenset of str) or None
        The two carriers and the roots they share, or ``None``.
    """
    if len(carriers) < 2:
        return None
    known = derivations(history)
    if not known:
        return None
    ancestry = {
        name: (known[name].roots if name in known else frozenset({name}))
        for name in carriers
    }
    ordered = sorted(carriers)
    for index, name_a in enumerate(ordered):
        for name_b in ordered[index + 1 :]:
            common = ancestry[name_a] & ancestry[name_b]
            if common and not _declared(correlation, name_a, name_b):
                return name_a, name_b, common
    return None


def single_expression(history: History, target: str, text: str) -> str | None:
    """Build the one-call equation equivalent to a refused composition.

    This is what makes the refusal actionable rather than a lecture: the
    same arithmetic written as a single expression is ALREADY correct,
    because the chain rule sees the whole tree at once. Returns ``None``
    when the expansion grows past the point of being pasteable.
    """
    expanded = _substitute(text, derivations(history))
    equation = f"{target} = {expanded}"
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


def describe_roots(roots: Iterable[str]) -> str:
    """Render shared roots for an error message, naming the unknown case."""
    named = sorted(root for root in roots if root != _UNKNOWN)
    if not named:
        return "an origin this frame's History does not record"
    return ", ".join(f"'{name}'" for name in named)
