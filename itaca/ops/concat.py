"""itc.concat: concatenate VarFrames along a shared dimension (REQ-24).

All inputs share every other dimension identically (same coordinates,
same units) and the same variable set; values along ``along`` must be
unique across inputs. UncFrame components are concatenated unchanged
(REQ-98); presence must match across inputs so no component is
silently dropped or invented (DD-18). Origin tags concatenate with
zero fill for untagged inputs (zero is the documented original state).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from itaca.core.errors import (
    AxesError,
    ConcatOverlapError,
    DataError,
    DimensionNotFoundError,
    OperatingModeMixError,
    UncertaintyError,
    UncertaintyLineageError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild, recoord
from itaca.uncertainty._lineage import derivations


def _validate_inputs(frames: Sequence[VarFrame], along: str) -> None:
    first = frames[0]
    if along not in first.dims:
        raise DimensionNotFoundError(
            f"dimension '{along}'",
            "concat(along=...) referenced an absent dimension",
            f"available dimensions: {list(first.dims)}",
        )
    for index, other in enumerate(frames[1:], start=1):
        if other.mode != first.mode:
            raise OperatingModeMixError(
                f"VarFrames in modes '{first.mode}' and '{other.mode}'",
                "concat requires every input in the same operating mode",
                "call db.promote(...) or db.demote(...) explicitly first (REQ-12)",
            )
        if list(other.dims) != list(first.dims):
            raise DataError(
                f"input {index} dimensions {list(other.dims)} vs {list(first.dims)}",
                "concat requires identical dimension names and order",
                "align the inputs before concatenating (REQ-24)",
            )
        for name, dim in first.dims.items():
            if name == along:
                continue
            other_dim = other.dims[name]
            if (
                not np.array_equal(dim.coords, other_dim.coords)
                or dim.unit != other_dim.unit
            ):
                raise DataError(
                    f"dimension '{name}' of input {index}",
                    "concat found different coordinates or units on a shared dimension",
                    "inputs must share all non-along dimensions identically (REQ-24)",
                )
        if set(other.vars) != set(first.vars):
            missing = sorted(set(first.vars) ^ set(other.vars))
            raise DataError(
                f"variables only in one input: {missing}",
                "concat requires the same variable set in every input",
                "select matching variables before concatenating (REQ-24)",
            )
    seen: NDArray[Any] = frames[0].dims[along].coords
    for index, other in enumerate(frames[1:], start=1):
        incoming = other.dims[along].coords
        overlap = np.intersect1d(seen, incoming)
        if overlap.size:
            raise ConcatOverlapError(
                f"coordinates {overlap.tolist()} along '{along}'",
                f"input {index} repeats values already present",
                "concatenated coordinates must be unique; select "
                "disjoint ranges first (REQ-24)",
            )
        seen = np.concatenate([seen, incoming])
    for label in ("systematic", "random"):
        keyed = [
            set(getattr(frame.uncertainty, label))
            if frame.uncertainty is not None
            else set()
            for frame in frames
        ]
        if any(keyed) and any(entry != keyed[0] for entry in keyed[1:]):
            raise UncertaintyError(
                f"{label} component keys differ across inputs: "
                f"{sorted(set().union(*keyed))}",
                "concat cannot mix inputs with and without uncertainty on a variable",
                "assign the component on every input or on none (DD-18)",
            )
    # concat only stacks points along `along`; no value changes, so a
    # declared coefficient survives exactly. What must not survive is
    # ONE input's declaration standing in for all of them, which is what
    # rebuilding on frames[0] silently did. Compare the pair dicts, never
    # the CorrelationMatrix objects, which are eq=False and so compare by
    # identity.
    # Same class of defect one field across: concat rebuilds on
    # frames[0], so frames[0]'s AxisRegistry stood in for all of them and
    # a body-axis frame concatenated with an already-rotated wind-axis
    # frame came out claiming every row was body-axis. The next
    # rotate('wind') then transformed the rotated rows a SECOND time.
    # REQ-107 makes the recorded source axis the thing that keeps a
    # repeated rotation an identity, so mixing the axis silently is
    # exactly what defeats it (CHK1-003).
    #
    # Driven by the UNION of group names, never by what each frame
    # happens to declare. `rotate` registers a group only when it rotates
    # it, so a frame that never called `declare_vector` carries NO entry
    # while still holding FX/FY/FZ, and `group_axis` answers "body" for
    # it by design. An intersection-shaped check therefore saw one axis,
    # passed, and left the exact double rotation this refuses reachable
    # through the commonest shape of all: nobody declared anything. The
    # correlation guard below is the pattern, comparing the full store of
    # every input rather than the keys they share.
    names: set[str] = set()
    for frame in frames:
        names |= set(frame.axes.vector_groups)
    for name in sorted(names):
        axes = {frame.axes.group_axis(name) for frame in frames}
        if len(axes) > 1:
            per_input = [frame.axes.group_axis(name) for frame in frames]
            raise AxesError(
                f"vector group '{name}' across the inputs",
                f"the inputs express it in different axis systems "
                f"{per_input}, and concat records ONE source axis for the "
                f"merged frame, so a later rotate would transform the rows "
                f"already in the target a second time",
                "express every input in the same axis before concatenating, "
                "by rotating them to a common target; an input that never "
                "declared the group counts as the canonical body axis "
                "(REQ-38, REQ-107)",
            )
        components = {
            frame.axes.vector_groups[name]
            for frame in frames
            if name in frame.axes.vector_groups
        }
        if len(components) > 1:
            raise AxesError(
                f"vector group '{name}' across the inputs",
                f"the inputs declare it over different components "
                f"{sorted(components)}, and concat would record one of them "
                "for the merged frame",
                "declare the same components on every input, or use "
                "distinct group names (REQ-38)",
            )
    stores = [
        dict(frame.correlation.pairs) if frame.correlation is not None else {}
        for frame in frames
    ]
    if any(store != stores[0] for store in stores[1:]):
        key_sets = [set(store) for store in stores]
        common = key_sets[0].intersection(*key_sets[1:])
        union = key_sets[0].union(*key_sets[1:])
        symmetric = sorted(union - common)
        differing = sorted(
            pair
            for pair in common
            if any(store[pair] != stores[0][pair] for store in stores[1:])
        )
        raise UncertaintyError(
            f"declared correlation pairs differ across inputs: "
            f"{symmetric or differing}",
            "concat cannot mix inputs with different correlation declarations",
            "declare the same pairs with the same coefficients on every "
            "input, or drop them before concatenating (REQ-40, DD-18)",
        )


def _refuse_discarded_lineage(frames: Sequence[VarFrame]) -> None:
    """Refuse a concat that would DISCARD a derivation the result needs.

    ARCH-5 and ARCH-8, which are the two halves of one problem and were
    found one review round apart.

    The result carries the History of ``frames[0]`` alone, so every other
    input's derivation record is dropped. When one of those inputs
    derived a variable that carries uncertainty, the joined frame holds
    values whose shared origin nothing records any more: measured, with
    ``p`` and ``q`` as roots in the first input and derived from a common
    ``x`` in the second, ``compute("r = p - q")`` on the joined frame
    returned ``u = 0.3606`` where ``0.1`` is correct on the second
    input's rows.

    The first attempt at this treated ``concat`` as an unreadable
    operation, which poisoned the whole frame and refused EVERY
    multi-carrier ``compute`` on any concatenated frame, including two
    inputs of plain roots with no derivation anywhere. That is REQ-24
    mainline usage and it was far too wide (ARCH-8).

    So the refusal moves to the operation that loses the information,
    which is the only place that can still see it. It fires only when a
    non-first input actually carries a derived variable with
    uncertainty, and an ordinary concat of loaded frames is untouched.
    Failing at the point of loss also gives a message that can say what
    to do, where a refusal three operations later cannot.
    """
    for position, frame in enumerate(frames[1:], start=2):
        if frame.uncertainty is None:
            continue
        carriers = set(frame.uncertainty.systematic) | set(frame.uncertainty.random)
        derived = set(derivations(frame.history, frame.axes.vector_groups).derived)
        lost = sorted(carriers & derived)
        if not lost:
            continue
        raise UncertaintyLineageError(
            f"input {position} of {len(frames)}, whose {lost} carry both a "
            f"derivation and an uncertainty",
            "concat keeps the History of the FIRST input only, so these "
            "variables' derivations would be discarded and the joined frame "
            "would hold quantities whose shared origin nothing records; a "
            "later compute would then treat them as independent",
            "concatenate the INPUTS of that derivation and derive once on "
            "the joined frame, which is also cheaper; or put the frame "
            "carrying the derivations first, if its History covers every "
            "derivation in the result; or drop the uncertainty from those "
            "variables if it is not wanted downstream. Carrying several "
            "inputs' derivation records into one joined History needs "
            "lineage that survives a merge and is v0.3.0 work (SEAT-UNC, "
            "REQ-24, REQ-41)",
        )


def concat(
    frames: Sequence[VarFrame],
    *,
    along: str,
    history: bool = False,
    comment: str | None = None,
) -> VarFrame:
    """Concatenate VarFrames along a shared dimension (REQ-24).

    Parameters
    ----------
    frames : sequence of VarFrame
        Inputs, concatenated in list order. All inputs share every
        other dimension identically and the same variable set.
    along : str
        The dimension to concatenate along; values must be unique
        across inputs (``ConcatOverlapError`` otherwise).
    history : bool, optional
        In draft mode, record only when True (REQ-10).
    comment : str or None, optional
        User comment for the History entry (REQ-19).

    Returns
    -------
    VarFrame
        A new VarFrame carrying the Provenance and History of the
        first input, with the concat operation recorded.

    Raises
    ------
    DataError
        Empty input list, mismatched shared dimensions, or mismatched
        variable sets.
    ConcatOverlapError
        Overlapping coordinates along ``along``.
    OperatingModeMixError
        Inputs in different operating modes (REQ-12).
    UncertaintyError
        Uncertainty present on some inputs but not all (DD-18).
    AxesError
        A vector group is expressed in different axis systems across the
        inputs, or declared over different components. The merged frame
        records ONE source axis, so mixing them would leave a later
        ``rotate`` transforming the rows already in the target a second
        time. An input that never declared the group counts as the
        canonical body axis (REQ-38, REQ-107).

    Examples
    --------
    >>> import numpy as np
    >>> import itaca as itc
    >>> a = np.column_stack([[0.0, 1.0], [1.0, 2.0]])
    >>> b = np.column_stack([[2.0], [3.0]])
    >>> low = itc.load(a, names=["alpha", "CT"]).pivot(dims=["alpha"])
    >>> high = itc.load(b, names=["alpha", "CT"]).pivot(dims=["alpha"])
    >>> both = itc.concat([low, high], along="alpha")
    >>> both.dims["alpha"].coords.tolist()
    [0.0, 1.0, 2.0]
    """
    if not frames:
        raise DataError(
            "an empty input list",
            "concat needs at least one VarFrame",
            "pass the frames to concatenate (REQ-24)",
        )
    _validate_inputs(frames, along)
    _refuse_discarded_lineage(frames)
    first = frames[0]
    content = content_of(first)
    axis = list(content.dims).index(along)
    coords = np.concatenate([frame.dims[along].coords for frame in frames])
    content.dims[along] = recoord(first.dims[along], coords)

    def _stack(
        pick: Any, names: Sequence[str] | None = None
    ) -> dict[str, NDArray[Any]]:
        return {
            name: np.concatenate([pick(frame, name) for frame in frames], axis=axis)
            for name in (content.values if names is None else names)
        }

    content.values = _stack(lambda frame, name: frame.vars[name].values)
    if first.uncertainty is not None:
        for label in ("systematic", "random"):
            component: dict[str, NDArray[Any]] = getattr(first.uncertainty, label)
            if component:

                def _pick(frame: VarFrame, name: str, label: str = label) -> Any:
                    assert frame.uncertainty is not None
                    return getattr(frame.uncertainty, label)[name]

                setattr(content, label, _stack(_pick, list(component)))
    if any(frame.tags is not None for frame in frames):

        def _tags_of(frame: VarFrame, name: str) -> NDArray[Any]:
            if frame.tags is not None and name in frame.tags.tags:
                return frame.tags.tags[name]
            return np.zeros(frame.shape, dtype=np.int8)

        content.tags = _stack(_tags_of)

    others = ", ".join(frame.state_hash[:12] for frame in frames[1:])
    operation = f"concat(along='{along}', with=[{others}])"
    return rebuild(
        first, content, operation=operation, comment=comment, history=history
    )
