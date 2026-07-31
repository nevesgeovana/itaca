"""Property-based tests for the state-hash contract (REQ-103, REQ-77).

Hypothesis is used per the SRS testing policy; deterministic
closed-form fixtures cover known answers elsewhere.
"""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from itaca.core.canonical import frame
from itaca.core.coords import Cartesian, Polar
from itaca.core.dimension import Dimension
from itaca.core.history import compute_state_hash
from itaca.core.variable import Variable

_finite = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)


def _hash(**kwargs: object) -> str:
    """Hash with the frame-level fields at their ordinary values.

    ``coords`` and ``mode`` are required arguments of
    ``compute_state_hash`` (DD-47), deliberately, so that a call site
    cannot narrow what is authenticated by omitting one. The properties
    below are about the CONTENT fields, so they hold the frame-level two
    fixed; the two properties at the end of this module are the ones
    that vary them.
    """
    return compute_state_hash(coords=Cartesian(), mode="production", **kwargs)  # type: ignore[arg-type]


@st.composite
def _content(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = draw(st.integers(min_value=1, max_value=5))
    coords = draw(hnp.arrays(np.float64, n, elements=_finite))
    a = draw(hnp.arrays(np.float64, n, elements=_finite))
    b = draw(hnp.arrays(np.float64, n, elements=_finite))
    return coords, a, b


@given(_content())
def test_hash_is_deterministic(
    content: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    coords, a, _ = content
    build = lambda: _hash(  # noqa: E731
        dims={"x": Dimension(name="x", coords=coords)},
        variables={"A": Variable(name="A", values=a)},
        operations=(("load()", None),),
    )
    assert build() == build()


@given(_content())
def test_hash_independent_of_variable_insertion_order(
    content: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    coords, a, b = content
    dims = {"x": Dimension(name="x", coords=coords)}
    var_a = Variable(name="A", values=a)
    var_b = Variable(name="B", values=b)
    h_ab = _hash(dims=dims, variables={"A": var_a, "B": var_b}, operations=())
    h_ba = _hash(dims=dims, variables={"B": var_b, "A": var_a}, operations=())
    assert h_ab == h_ba


@given(_content(), st.integers(min_value=0, max_value=4))
def test_hash_sensitive_to_any_value_change(
    content: tuple[np.ndarray, np.ndarray, np.ndarray], position: int
) -> None:
    coords, a, _ = content
    index = position % a.size
    changed = a.copy()
    changed[index] = changed[index] + 1.0
    dims = {"x": Dimension(name="x", coords=coords)}
    h_original = _hash(
        dims=dims,
        variables={"A": Variable(name="A", values=a)},
        operations=(),
    )
    h_changed = _hash(
        dims=dims,
        variables={"A": Variable(name="A", values=changed)},
        operations=(),
    )
    assert h_original != h_changed


@given(
    st.lists(st.one_of(st.none(), st.binary(max_size=8)), max_size=5),
    st.lists(st.one_of(st.none(), st.binary(max_size=8)), max_size=5),
)
def test_framing_is_injective(
    left: list[bytes | None], right: list[bytes | None]
) -> None:
    """FND-036 as a contract rather than as three examples.

    The framing kernel's whole job is that distinct field sequences
    produce distinct byte streams. The defect it replaced was injective
    on every example anyone had written and collided elsewhere: a
    missing comment against an empty one, and content carrying the
    separator byte. An example-based test cannot express "no two
    sequences collide", so this is the property that can.
    """
    encode = lambda fields: b"".join(frame(field) for field in fields)  # noqa: E731
    if left == right:
        assert encode(left) == encode(right)
    else:
        assert encode(left) != encode(right)


def test_absent_is_not_empty() -> None:
    """The single case the whole encoding exists to separate."""
    assert frame(None) != frame(b"")


@given(_content())
def test_hash_sensitive_to_the_coordinate_system(
    content: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """FND-037, as a property rather than one fixture.

    Whatever the content, a Cartesian frame and the same frame tagged
    Polar are different states: the tag selects the integration element.
    """
    coords, a, _ = content
    fields = {
        "dims": {"x": Dimension(name="x", coords=coords)},
        "variables": {"A": Variable(name="A", values=a)},
        "operations": (),
    }
    cartesian = compute_state_hash(coords=Cartesian(), mode="production", **fields)  # type: ignore[arg-type]
    polar = compute_state_hash(coords=Polar(), mode="production", **fields)  # type: ignore[arg-type]
    assert cartesian != polar


@given(_content())
def test_hash_sensitive_to_the_operating_mode(
    content: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """FND-089, the critical finding, as a property.

    Whatever the content, draft and production are different states.
    While they were not, editing one string inside a saved archive
    promoted a draft file and it reopened with a valid hash.
    """
    coords, a, _ = content
    fields = {
        "dims": {"x": Dimension(name="x", coords=coords)},
        "variables": {"A": Variable(name="A", values=a)},
        "operations": (),
    }
    production = compute_state_hash(coords=Cartesian(), mode="production", **fields)  # type: ignore[arg-type]
    draft = compute_state_hash(coords=Cartesian(), mode="draft", **fields)  # type: ignore[arg-type]
    assert production != draft
