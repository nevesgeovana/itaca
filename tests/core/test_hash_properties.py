"""Property-based tests for the state-hash contract (REQ-103, REQ-77).

Hypothesis is used per the SRS testing policy; deterministic
closed-form fixtures cover known answers elsewhere.
"""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from itaca.core.dimension import Dimension
from itaca.core.history import compute_state_hash
from itaca.core.variable import Variable

_finite = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)


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
    build = lambda: compute_state_hash(  # noqa: E731
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
    h_ab = compute_state_hash(
        dims=dims, variables={"A": var_a, "B": var_b}, operations=()
    )
    h_ba = compute_state_hash(
        dims=dims, variables={"B": var_b, "A": var_a}, operations=()
    )
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
    h_original = compute_state_hash(
        dims=dims,
        variables={"A": Variable(name="A", values=a)},
        operations=(),
    )
    h_changed = compute_state_hash(
        dims=dims,
        variables={"A": Variable(name="A", values=changed)},
        operations=(),
    )
    assert h_original != h_changed
