"""Dev-only oracle: ITACA direction-cosine matrices vs scipy (DD-26).

Cross-validates the pure-NumPy general direction-cosine formulation in
``core/axes.py`` against ``scipy.spatial.transform.Rotation``, using
scipy's validated single-axis rotations as ground-truth building
blocks composed in ITACA's documented order. scipy is a dev-only
dependency (DD-26); it is never imported by library code. Skips
cleanly if scipy is absent.
"""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from itaca.core.axes import stability_axis, wind_axis

Rotation = pytest.importorskip("scipy.spatial.transform").Rotation

_angle = st.floats(min_value=-1.4, max_value=1.4, allow_nan=False, allow_infinity=False)


def _active(axis: str, theta: float) -> np.ndarray:
    """scipy's validated active single-axis rotation matrix."""
    return np.asarray(Rotation.from_euler(axis, theta).as_matrix())


class TestStabilityAgainstScipy:
    @given(alpha=_angle)
    def test_matrix_matches_scipy_ry(self, alpha: float) -> None:
        # Body-to-stability is the active rotation about y by alpha.
        reference = _active("y", alpha)
        assert np.allclose(stability_axis().matrix_at({"alpha": alpha}), reference)


class TestWindAgainstScipy:
    @given(alpha=_angle, beta=_angle)
    def test_matrix_matches_scipy_composition(self, alpha: float, beta: float) -> None:
        # Body-to-wind (Etkin): Rz(-beta) @ Ry(alpha), composed from
        # scipy's single-axis matrices.
        reference = _active("z", -beta) @ _active("y", alpha)
        got = wind_axis().matrix_at({"alpha": alpha, "beta": beta})
        assert np.allclose(got, reference)

    @given(alpha=_angle, beta=_angle)
    def test_is_a_proper_rotation(self, alpha: float, beta: float) -> None:
        # scipy accepts the matrix as a proper rotation (det +1,
        # orthonormal) without raising.
        got = wind_axis().matrix_at({"alpha": alpha, "beta": beta})
        round_trip = Rotation.from_matrix(got).as_matrix()
        assert np.allclose(round_trip, got, atol=1e-9)


class TestDerivativesAgainstScipy:
    @given(alpha=_angle, beta=_angle)
    def test_wind_derivatives_match_scipy_finite_difference(
        self, alpha: float, beta: float
    ) -> None:
        axis = wind_axis()
        grads = axis.d_matrix_d_angle({"alpha": alpha, "beta": beta})
        eps = 1e-6
        for name in ("alpha", "beta"):
            if name == "alpha":
                plus = _active("z", -beta) @ _active("y", alpha + eps)
                minus = _active("z", -beta) @ _active("y", alpha - eps)
            else:
                plus = _active("z", -(beta + eps)) @ _active("y", alpha)
                minus = _active("z", -(beta - eps)) @ _active("y", alpha)
            fd = (plus - minus) / (2.0 * eps)
            assert np.allclose(grads[name], fd, atol=1e-5)
