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
    ConcatOverlapError,
    DataError,
    DimensionNotFoundError,
    OperatingModeMixError,
    UncertaintyError,
)
from itaca.core.varframe import VarFrame
from itaca.ops._content import content_of, rebuild, recoord


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
