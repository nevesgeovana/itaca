"""Validation evidence for the OQ-18 / OQ-24 / OQ-26 derivations.

These tests exercise the proposed frozen rules of
``docs/derivations/uncertainty_kernels.md`` against the actual kernels,
for Geovana's numerical-analyst validation at Batch B. Where a claim is
"the rule matches independent LPU," the test cross-checks it against an
independent Monte Carlo draw rather than restating the closed form, so a
regression in the rule (not just in NumPy) would fail. The ops
themselves still raise on uncertainty until the Phase B4 freeze, when
op-level tests must bind these harness values to the real op outputs
(registered as a B4 item in docs/M1_EXECUTION_PLAN.md).
"""

import dataclasses

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

import itaca as itc
from itaca.core.axes import stability_axis, wind_axis
from itaca.core.correlation import CorrelationMatrix
from itaca.core.dimension import Dimension
from itaca.core.errors import UncertaintyError
from itaca.core.uncframe import UncFrame
from itaca.ops._movingfit import moving_fit_line
from itaca.ops._reduction import reduce_random, reduce_systematic

_finite = st.floats(
    min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False
)


def _kernel_weights(x, window, deg, derivative):
    """Recover the per-sample weight matrix W (y = W @ values) of the
    moving-fit kernel by probing it with the identity basis."""
    n = x.size
    weights = np.empty((n, n))
    for j in range(n):
        basis = np.zeros(n)
        basis[j] = 1.0
        out, _ = moving_fit_line(x, basis, window, deg, derivative)
        weights[:, j] = out
    return weights


def _mc_random_std(weights_row, u, draws=40000, seed=7):
    """Sample std of y = sum_j w_j e_j with independent e_j ~ N(0, u_j)."""
    rng = np.random.default_rng(seed)
    errors = rng.normal(0.0, 1.0, (draws, u.size)) * u[None, :]
    y = errors @ weights_row
    return float(y.std())


class TestUnifyingRule:
    def test_kernel_is_linear(self):
        # The whole two-component rule rests on the kernels being linear
        # maps of the samples; probe W and confirm W @ y == kernel(y) on
        # NaN-free data (the rule holds only on full windows).
        x = np.linspace(0.0, 1.0, 9)
        w = _kernel_weights(x, window=5, deg=2, derivative=True)
        rng = np.random.default_rng(1)
        y = rng.normal(0.0, 1.0, 9)
        direct, _ = moving_fit_line(x, y, 5, 2, True)
        assert np.allclose(w @ y, direct, atol=1e-9)

    @given(w=st.lists(_finite, min_size=1, max_size=8), u=st.floats(0.1, 5.0))
    def test_systematic_is_signed_sum(self, w, u):
        # The OQ-18 crux: the signed sum, not sum of magnitudes. This
        # discriminates |sum W| from sum|W| on mixed-sign weights.
        weights = np.array(w)
        u_vec = np.full(weights.size, u)
        got = reduce_systematic(weights, u_vec, -1)
        assert np.isclose(got, abs(weights.sum()) * u)

    @given(
        w=st.lists(_finite, min_size=2, max_size=6),
        u=st.floats(0.2, 3.0),
    )
    @settings(max_examples=30, deadline=None)
    def test_random_matches_independent_monte_carlo(self, w, u):
        # Cross-check the RSS rule against an independent MC draw, not the
        # closed form: propagate independent per-point errors through W
        # and compare the sample std to reduce_random.
        weights = np.array(w)
        u_vec = np.full(weights.size, u)
        analytic = reduce_random(weights, u_vec, -1)
        mc = _mc_random_std(weights, u_vec)
        assert mc == pytest.approx(float(analytic), rel=0.06)


class TestOQ18SmoothDiff:
    @given(n=st.integers(min_value=5, max_value=11))
    @settings(max_examples=25)
    def test_smooth_weights_partition_of_unity(self, n):
        # smooth (savgol) reproduces a constant: window rows sum to 1,
        # so a common bias is preserved (u_sys unchanged).
        x = np.linspace(0.0, 1.0, n)
        w = _kernel_weights(x, window=5, deg=2, derivative=False)
        finite = np.isfinite(w).all(axis=1)
        assert np.allclose(w[finite].sum(axis=1), 1.0, atol=1e-9)

    @given(n=st.integers(min_value=6, max_value=11))
    @settings(max_examples=25)
    def test_diff_weights_sum_to_zero(self, n):
        # diff weights sum to 0: a common bias cancels exactly, so the
        # systematic uncertainty of a derivative is 0.
        x = np.linspace(0.0, 1.0, n)
        w = _kernel_weights(x, window=5, deg=2, derivative=True)
        finite = np.isfinite(w).all(axis=1)
        assert np.allclose(w[finite].sum(axis=1), 0.0, atol=1e-9)

    def test_diff_systematic_bias_cancels(self):
        x = np.linspace(0.0, 1.0, 9)
        w = _kernel_weights(x, window=5, deg=2, derivative=True)
        u = np.full(9, 0.1)  # common systematic bias
        center = 4
        assert np.isclose(reduce_systematic(w[center], u, -1), 0.0, atol=1e-9)

    def test_smooth_systematic_bias_preserved(self):
        x = np.linspace(0.0, 1.0, 9)
        w = _kernel_weights(x, window=5, deg=2, derivative=False)
        u = np.full(9, 0.1)
        center = 4
        assert np.isclose(reduce_systematic(w[center], u, -1), 0.1, atol=1e-9)

    def test_diff_random_matches_monte_carlo(self):
        # The random component through a diff kernel matches independent MC.
        x = np.linspace(0.0, 1.0, 9)
        w = _kernel_weights(x, window=5, deg=2, derivative=True)
        u = np.full(9, 0.1)
        center = 4
        analytic = reduce_random(w[center], u, -1)
        mc = _mc_random_std(w[center], u)
        assert mc == pytest.approx(float(analytic), rel=0.06)


def _fit_projection(x, deg):
    """P = (X^T X)^-1 X^T via the stable pseudoinverse, ascending powers
    (c = P @ y), matching np.polyfit's lstsq basis."""
    vander = np.vander(x, deg + 1, increasing=True)
    return np.linalg.pinv(vander)


class TestOQ24Fitmodel:
    @given(
        nodes=st.lists(st.floats(-2.0, 2.0), min_size=4, max_size=9, unique=True),
        deg=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=40)
    def test_projection_row_sums(self, nodes, deg):
        x = np.sort(np.array(nodes))
        assume(deg < len(x) and np.min(np.diff(x)) > 0.1)  # well-conditioned
        p = _fit_projection(x, deg)
        # c_0 absorbs a common bias; higher coefficients cancel it.
        assert np.isclose(p[0].sum(), 1.0, atol=1e-7)
        for k in range(1, deg + 1):
            assert np.isclose(p[k].sum(), 0.0, atol=1e-7)

    def test_systematic_bias_only_hits_constant(self):
        x = np.linspace(-1.0, 1.0, 6)
        p = _fit_projection(x, 3)
        u = np.full(6, 0.2)
        assert np.isclose(reduce_systematic(p[0], u, -1), 0.2, atol=1e-8)
        for k in (1, 2, 3):
            assert np.isclose(reduce_systematic(p[k], u, -1), 0.0, atol=1e-8)

    @given(deg=st.integers(min_value=1, max_value=3))
    @settings(max_examples=20, deadline=None)
    def test_random_coefficient_matches_monte_carlo(self, deg):
        x = np.linspace(-1.0, 1.0, 8)
        p = _fit_projection(x, deg)
        u = np.full(8, 0.1)
        for k in range(deg + 1):
            analytic = reduce_random(p[k], u, -1)
            mc = _mc_random_std(p[k], u)
            assert mc == pytest.approx(float(analytic), rel=0.06)


def _wind_v(alpha, beta, v):
    """R(alpha, beta) @ v via the code's own DCM (no hand transcription)."""
    return wind_axis().matrix_at({"alpha": alpha, "beta": beta}) @ v


class TestOQ26RotationIndependence:
    @pytest.mark.parametrize(
        "alpha,beta,v",
        [
            (0.35, -0.2, np.array([2.0, -1.0, 0.5])),
            (-0.5, 0.4, np.array([1.0, 0.0, 2.0])),
            (0.1, 0.9, np.array([0.5, 3.0, -1.0])),
        ],
    )
    def test_independent_angle_variance_matches_monte_carlo(self, alpha, beta, v):
        axis = wind_axis()
        u_a, u_b = 0.03, 0.04
        grads = axis.d_matrix_d_angle({"alpha": alpha, "beta": beta})
        analytic = (grads["alpha"] @ v) ** 2 * u_a**2 + (
            grads["beta"] @ v
        ) ** 2 * u_b**2
        rng = np.random.default_rng(20260723)
        draws = 200000
        da = rng.normal(0.0, u_a, draws)
        db = rng.normal(0.0, u_b, draws)
        samples = np.stack(
            [_wind_v(alpha + da[i], beta + db[i], v) for i in range(0, draws, 100)]
        )
        # atol covers components whose first-order variance is near zero
        # (an accidental cancellation at that attitude leaves only the
        # O(u^4) second-order MC term, ~ 1e-5 here).
        assert np.allclose(analytic, samples.var(axis=0), rtol=0.07, atol=1e-5)

    def test_correlated_angles_differ_from_diagonal(self):
        # The model DROPS the alpha-beta cross term. This test proves the
        # cross term is real and nonzero: a correlated-angle MC variance
        # differs from the diagonal analytic by exactly the cross term.
        axis = wind_axis()
        v = np.array([2.0, -1.0, 0.5])
        alpha, beta, u_a, u_b, rho = 0.35, -0.2, 0.03, 0.04, 0.8
        grads = axis.d_matrix_d_angle({"alpha": alpha, "beta": beta})
        sa, sb = grads["alpha"] @ v, grads["beta"] @ v
        diagonal = sa**2 * u_a**2 + sb**2 * u_b**2
        cross = 2.0 * rho * sa * sb * u_a * u_b
        rng = np.random.default_rng(11)
        draws = 400000
        cov = np.array([[u_a**2, rho * u_a * u_b], [rho * u_a * u_b, u_b**2]])
        angles = rng.multivariate_normal([0.0, 0.0], cov, draws)
        samples = np.stack(
            [
                _wind_v(alpha + angles[i, 0], beta + angles[i, 1], v)
                for i in range(0, draws, 200)
            ]
        )
        mc_var = samples.var(axis=0)
        # The correlated MC matches diagonal + cross, not diagonal alone.
        assert np.allclose(mc_var, diagonal + cross, rtol=0.08, atol=1e-6)
        assert not np.allclose(mc_var, diagonal, rtol=0.05, atol=1e-9)

    def test_shared_angle_cancels_in_accumulated_gradient(self):
        # Source stability(alpha) to target wind(alpha, beta=0): the
        # composite R is alpha-independent, so the accumulated dR/dalpha
        # (target + source contributions) is zero: no double count.
        alpha = 0.4
        l_tb = wind_axis().matrix_at({"alpha": alpha, "beta": 0.0})
        l_sb = stability_axis().matrix_at({"alpha": alpha})
        d_tb = wind_axis().d_matrix_d_angle({"alpha": alpha, "beta": 0.0})["alpha"]
        d_sb = stability_axis().d_matrix_d_angle({"alpha": alpha})["alpha"]
        # dR_total/dalpha = dL_tb @ L_sb^T + L_tb @ dL_sb^T.
        d_total = d_tb @ l_sb.T + l_tb @ d_sb.T
        assert np.allclose(d_total, 0.0, atol=1e-12)

    def test_declared_angle_correlation_raises(self):
        # REQ-40 fail-loud: a declared correlation touching a frame angle
        # is rejected rather than silently dropped (OQ-26 guard).
        rows = [[0.5, 1.0, 0.0, 0.0]]
        db = itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
            dims=["alpha"]
        )
        db = dataclasses.replace(
            db,
            dims={"alpha": Dimension(name="alpha", coords=np.array([0.5]), unit="rad")},
            uncertainty=UncFrame(
                systematic={c: np.array([0.1]) for c in ("FX", "FY", "FZ")},
                random={},
            ),
            correlation=CorrelationMatrix(pairs={("alpha", "FX"): 0.3}),
        )
        with pytest.raises(UncertaintyError, match="OQ-26"):
            db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")
