# Worked derivations: two-component propagation through linear kernels

Prepared for Geovana's validation (numerical-analyst seat), M1 Batch B,
2026-07-23. Validation evidence toward resolving OQ-18, OQ-24, and
OQ-26 (all three remain `open` until she signs off). The property tests
in `tests/derivations/test_kernel_derivations.py` exercise every claim
below against the actual kernels; they are the validation evidence.

Notation: a variable `x` carries two uncertainty components (DD-19): a
systematic part `u_sys`, treated as fully correlated across the points
of the variable (one common bias `b` with standard deviation `u_sys`),
and a random part `u_rand`, independent between points. GUM clause 5
linear propagation (LPU) applies because every operation below is a
linear map of the sampled values.

## 1. The unifying rule: a linear map with a signed weight sum

Let an operation produce `y_i = sum_j W_ij x_j` for a fixed weight
matrix `W` (a kernel, a quadrature, an interpolation, a fit, an
evaluation, a rotation row). Write the two components of the inputs as
`u_sys` (a common bias `b`, the same realized value across all `j` of
one variable) and `u_rand,j` (independent per `j`).

**Random component (independent inputs).**

    Var_rand(y_i) = sum_j W_ij^2 * u_rand,j^2
    u_rand(y_i)   = sqrt( sum_j (W_ij * u_rand,j)^2 )                (RSS)

**Systematic component (one common bias).** The bias enters every input
as the same random variable `b`, so

    y_i's systematic part = sum_j W_ij * b = ( sum_j W_ij ) * b
    u_sys(y_i) = | sum_j W_ij * u_sys,j |                     (signed sum)

The systematic rule uses the **signed** weighted sum, not the sum of
magnitudes. This is the crux of OQ-18: whether the systematic component
must track sign changes of the weights. It must, and the reason is that
a common bias is a single realized number, so its contributions add
with their signs and can cancel. `reduce_systematic` and
`reduce_random` in `itaca/ops/_reduction.py` already implement exactly
`|sum W u|` and `sqrt(sum (W u)^2)`.

Two corollaries fix the behavior of every weight-based operation:

- **Partition of unity (`sum_j W_ij = 1`): a common bias is preserved.**
  Smoothing kernels, interpolation, and quadrature-normalized averages
  reproduce a constant, so `sum_j W_ij = 1` and `u_sys(y_i) = u_sys`.
  A smooth or an interpolation carries the bias through unchanged, as
  physical intuition demands.

- **Zero weight sum (`sum_j W_ij = 0`): a common bias cancels exactly.**
  A derivative of a constant is zero, so a differentiation kernel has
  `sum_j W_ij = 0`, and `u_sys(dy) = 0`. The systematic bias contributes
  nothing to a derivative. Using `sum_j |W_ij|` instead would wrongly
  inflate the systematic uncertainty of a derivative to a nonzero value;
  the signed sum makes the cancellation exact.

This single rule, applied to each operation's weight matrix, resolves
OQ-18 and OQ-24 below.

## 2. OQ-18: systematic weights through smooth and diff

`smooth` (Savitzky-Golay / moving average) and `diff` (moving-window
polynomial derivative) are linear kernels `y_i = sum_j W_ij x_j` whose
weights come from the local least-squares fit (`itaca/ops/_movingfit.py`
builds them per window). Applying section 1:

- **smooth:** the moving fit reproduces a constant, so each window's
  weights sum to 1. Random: RSS of the kernel weights. Systematic:
  preserved (`u_sys(smooth) = u_sys`). A smoothing does not reduce a
  common bias.

- **diff:** the analytic derivative of the local polynomial evaluated at
  the center has weights that sum to 0 (the derivative of a constant is
  zero). Random: RSS of the derivative weights (this is the honest
  amplification a numerical derivative applies to random noise).
  Systematic: exactly 0. A common calibration bias does not appear in a
  derivative.

**Proposed freeze:** smooth and diff propagate both components through
their kernel weights with `reduce_systematic` / `reduce_random`, i.e.
the same rule already validated for `average` and `integrate`. The
`smooth`/`diff` provisional row of REQ-98 becomes: "propagated through
the kernel or moving-fit weights, both components (signed systematic
sum, RSS random)," matching the reductions row. `fill` with
`method="polyfit"` un-raises under the same rule (its polyfit weights
are a linear map too).

Validation properties (tested):
- diff of a pure systematic-bias field gives zero systematic derivative
  uncertainty (exact cancellation, `sum W = 0`);
- smooth of a pure systematic-bias field preserves it (`sum W = 1`);
- the diff-kernel random component matches an independent Monte Carlo
  draw (the RSS rule follows from the generically tested reduction).

## 3. OQ-24: fitmodel coefficient-space covariance

`fitmodel` maps samples `y` to least-squares polynomial coefficients

    c = (X^T X)^{-1} X^T y = P y ,        P = (X^T X)^{-1} X^T

which is a **linear** map `P` of the samples (the Vandermonde `X` is
fixed by the sweep coordinates). So the coefficients propagate through
`P` by exactly the section-1 rule:

- Random: `u_rand(c_k) = sqrt( sum_j P_kj^2 u_rand,j^2 )`.
- Systematic: `u_sys(c_k) = | sum_j P_kj | u_sys`.

The signed row sums have a clean meaning. Fitting `y + b` (a common bias)
shifts only the constant coefficient by `b` and leaves the higher
coefficients unchanged, so

    sum_j P_0j = 1   (the constant coefficient absorbs the bias)
    sum_j P_kj = 0   for k >= 1  (higher coefficients cancel the bias)

Thus a systematic bias flows entirely into `c_0` and cancels exactly in
`c_1, c_2, ...`, the coefficient-space analogue of the derivative
cancellation. `fitvalue` (forward evaluation `sum_k c_k t^k`, weights
`t^k`) is linear in the coefficients and propagates by the same rule; it
un-raises together with `fitmodel`.

**Proposed freeze:** `fitmodel` and `fitvalue` propagate both components
through `P` and through the evaluation weights respectively, with
`reduce_systematic` / `reduce_random`. The REQ-98 `fitmodel`/`fitvalue`
provisional row becomes: "propagated through the fit projection `P` (and
the evaluation weights), both components." This is the Gauss-Markov
estimator covariance specialized to the two-component model; no new
machinery, the same `|sum W u|` / RSS rule.

Validation properties (tested):
- `P` row sums: `sum P_0j = 1`, `sum P_kj = 0` for k >= 1 (over a range
  of grid sizes, node placements, and degrees);
- a systematic bias produces `u_sys` on `c_0` and `0` on higher
  coefficients;
- random coefficient uncertainty matches an independent Monte Carlo
  draw.

## 4. OQ-26: angle independence in rotation propagation

Rotation is `v_t = R(theta) v_s` with the frame angles `theta` (alpha,
beta) and the vector components `v_s`. First-order LPU:

    d v_t = R d v_s + sum_over_theta ( dR/dtheta * v_s ) d theta

Taking the covariance, with `Cov_s` the within-cell component covariance
(built from the declared correlation, REQ-40/OQ-23) and `Sigma_theta`
the angle covariance:

    Cov(v_t) = R Cov_s R^T
             + sum_{a,b} (dR/dtheta_a v_s)(dR/dtheta_b v_s)^T Sigma_theta[a,b]
             + 2 * sym( R Cov(v_s, theta) (dR/dtheta v_s)^T )

The B2 implementation keeps the first line exactly (the component
Jacobian, `diag(R Cov_s R^T)`) and, in the second line, the diagonal
`a = b` terms with `Sigma_theta[a,a] = u_theta_a^2`, after accumulating
`dR/dtheta_a` over the source and target frames so a shared angle does
not double count. It drops:

- the **off-diagonal angle covariance** `Sigma_theta[a,b], a != b`
  (angles mutually independent), and
- the **component-angle cross covariance** `Cov(v_s, theta)` (angles
  independent of the components).

**The modeling claim to validate.** In wind-tunnel practice alpha and
beta are set or measured by independent mechanisms, and the balance
component uncertainties are independent of the attitude-measurement
uncertainties, so the dropped cross terms are genuinely zero. Under that
assumption the implemented form is the exact first-order covariance.

**Fail-loud stance.** ITACA does not silently assume independence where
the user says otherwise: if a declared correlation pair involves a frame
angle variable (angle-angle or component-angle), `rotate` raises rather
than dropping the cross term (REQ-40 is never silently violated). The
independence model therefore applies only to *undeclared* angle
relationships, which are the physical default.

**Proposed resolution:** accept angle independence as the model, and the
raise as the fail-loud guard, OR specify the joint covariance to
propagate (which would require the user to declare angle-angle and
component-angle correlations, and ITACA to consult them). Recommendation:
accept independence + raise; revisit only if a real calibration couples
an angle to a component.

Validation properties (tested):
- with independent angles, the diagonal first-order variance reproduces
  a well sampled Monte Carlo estimate of `Var(v_t)` over several
  attitudes (the MC builds its matrices from the code's own DCM, so it
  is an independent check of `d_matrix_d_angle`, not circular);
- with *correlated* angles, the Monte Carlo variance differs from the
  diagonal form by exactly the dropped cross term, demonstrating the
  independence model is a genuine (non-vacuous) modeling choice;
- a shared angle across source and target cancels: the accumulated
  `dR_total/dtheta` is zero for a stability-to-wind rotation at
  `beta = 0` (no double count);
- a declared correlation touching a frame angle raises
  `UncertaintyError` (the REQ-40 fail-loud guard).

## 5. What changes on approval (Phase B4)

If validated: freeze the REQ-98 `smooth`/`diff` and `fitmodel`/`fitvalue`
rows to the linear-map rule above (revision history + Chapter 11
together), un-raise `smooth`/`diff`/`fitmodel`/`fitvalue`/`fill(polyfit)`
on uncertainty, wire `reduce_systematic`/`reduce_random` (and the fit
projection `P`) into them, and promote the validation properties here to
live regression tests. REQ-101's angle-independence note stands with
OQ-26 marked resolved (accepted or amended).
