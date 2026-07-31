"""Dev-only oracle: ITACA symbolic propagation vs `uncertainties` (DD-25).

Cross-validates the pure-NumPy GUM clause-5 engine in
``uncertainty/propagation.py`` against the ``uncertainties`` package,
which does first-order propagation with a linear error model and tracks
correlation between derived quantities exactly. It is a dev-only
dependency (DD-25); library code may never import it, and the TID251
rule in ``pyproject.toml`` enforces that. Skips cleanly if absent.

DD-25 approved this oracle and no dependency group listed the package
until 2026-07-31, so the rule named an import nobody could make and this
file did not exist. That is the gap that let four confirmed uncertainty
defects sit under 96 percent line coverage: an engine can execute every
line and still compute the wrong number, and only an independent
implementation of the same mathematics says which.

The oracle is used two ways here, and the second is the point:

* Where ITACA propagates, its answer must MATCH the oracle.
* Where ITACA now REFUSES (SEAT-UNC), the oracle says what the right
  answer would have been, which is how these tests show the refusal
  hides a real error rather than a rounding difference.
"""

import warnings

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    UncertaintyCompatibilityError,
    UncertaintyLineageError,
)
from itaca.core.varframe import VarFrame

unc = pytest.importorskip("uncertainties")
umath = pytest.importorskip("uncertainties.umath")
ufloat = unc.ufloat


def _frame(**values: float) -> VarFrame:
    arr = np.column_stack([np.array([value]) for value in values.values()])
    return itc.load(arr, names=list(values))


class TestSingleExpressionMatchesTheOracle:
    """Within one expression ITACA is exact, and this is the evidence."""

    @pytest.mark.parametrize(
        ("equation", "reference"),
        [
            ("y = 3*x", lambda x: 3 * x),
            ("y = x**2", lambda x: x**2),
            ("y = 1/x", lambda x: 1 / x),
            ("y = sqrt(x)", lambda x: x**0.5),
            ("y = log(x)", lambda x: umath.log(x)),
            ("y = exp(x)", lambda x: umath.exp(x)),
            ("y = sin(x)", lambda x: umath.sin(x)),
            ("y = 3*x - 2*x", lambda x: 3 * x - 2 * x),
        ],
    )
    def test_one_variable(self, equation: str, reference: object) -> None:
        db = _frame(x=2.0).set_uncertainty({"x": 0.1})
        got = db.compute(equation).uncertainty.systematic["y"]
        expected = reference(ufloat(2.0, 0.1))  # type: ignore[operator]
        assert got[0] == pytest.approx(expected.std_dev, rel=1e-9)

    def test_two_independent_variables(self) -> None:
        db = _frame(a=3.0, b=5.0).set_uncertainty({"a": 0.2, "b": 0.4})
        got = db.compute("y = a * b").uncertainty.systematic["y"]
        expected = ufloat(3.0, 0.2) * ufloat(5.0, 0.4)
        assert got[0] == pytest.approx(expected.std_dev, rel=1e-9)

    def test_a_shared_variable_inside_one_expression(self) -> None:
        # The control that makes the whole SEAT-UNC posture coherent: the
        # chain rule already sees x twice and cancels it exactly, which is
        # why refusing the STEPWISE form and naming this one is a real
        # workaround and not a dodge.
        db = _frame(x=2.0).set_uncertainty({"x": 0.1})
        got = db.compute("y = 3*x - 2*x").uncertainty.systematic["y"]
        x = ufloat(2.0, 0.1)
        assert got[0] == pytest.approx((3 * x - 2 * x).std_dev, rel=1e-9)
        assert got[0] == pytest.approx(0.1, rel=1e-9)


class TestDeclaredCorrelationMatchesTheOracle:
    def test_perfectly_correlated_difference(self) -> None:
        # r(a, b) = 1 with equal magnitudes cancels exactly, which is the
        # clause-5 covariance term doing its job.
        db = _frame(a=3.0, b=2.0).set_uncertainty({"a": 0.1, "b": 0.1})
        db = db.set_correlation({("a", "b"): 1.0})
        got = db.compute("y = a - b").uncertainty.systematic["y"]
        shared = ufloat(0.0, 0.1)
        expected = (3.0 + shared) - (2.0 + shared)
        assert got[0] == pytest.approx(expected.std_dev, abs=1e-12)


class TestTheRefusalHidesARealError:
    """What the oracle says about the compositions SEAT-UNC now refuses."""

    def test_the_stepwise_route_would_have_been_wrong(self) -> None:
        db = _frame(x=2.0).set_uncertainty({"x": 0.1})
        chain = db.compute("p = 3*x").compute("q = 2*x")
        with pytest.raises(UncertaintyLineageError):
            chain.compute("r = p - q")

        # The oracle, which DOES track the shared origin:
        x = ufloat(2.0, 0.1)
        truth = (3 * x) - (2 * x)
        assert truth.std_dev == pytest.approx(0.1, rel=1e-9)

        # What the engine would have returned, reconstructed from the
        # marginals it stored, treating them as independent:
        u_p = chain.uncertainty.systematic["p"][0]
        u_q = chain.uncertainty.systematic["q"][0]
        as_independent = float(np.hypot(u_p, u_q))
        assert as_independent == pytest.approx(0.36055513, rel=1e-6)

        # 3.6x. The refusal is not conservatism about a rounding
        # difference; it is refusing a number that is wrong by a factor.
        assert as_independent / truth.std_dev == pytest.approx(3.6055513, rel=1e-6)

    def test_the_named_workaround_matches_the_oracle(self) -> None:
        # The expression the refusal suggests is not merely permitted, it
        # is RIGHT, and the oracle is what says so.
        db = _frame(x=2.0).set_uncertainty({"x": 0.1})
        got = db.compute("r = (3*x) - (2*x)").uncertainty.systematic["r"]
        x = ufloat(2.0, 0.1)
        assert got[0] == pytest.approx(((3 * x) - (2 * x)).std_dev, rel=1e-9)

    def test_the_oracle_disagrees_with_abs_at_zero(self) -> None:
        # The sharpest evidence in this file. Two independent
        # implementations of the same first-order mathematics do not
        # agree at x = 0:
        #
        #     ITACA (before the fix)  u(|x|) = 0.0    via np.sign(0) = 0
        #     uncertainties           u(|x|) = 0.1    via |d| = 1
        #
        # Neither is right, because the derivative does not exist there;
        # the left and right values are -1 and +1 and no convention
        # adjudicates between them. A disagreement between two careful
        # implementations at exactly one point is what a non-
        # differentiable point LOOKS like from the outside, and it is why
        # this case is refused rather than checked against an oracle.
        # Away from zero the two agree exactly, which the second half
        # asserts.
        with warnings.catch_warnings():
            # The oracle deprecates its own abs; the value is what is
            # under test, not the spelling, and pinning the warning would
            # couple this test to the oracle's release schedule.
            warnings.simplefilter("ignore", FutureWarning)
            at_zero = umath.fabs(ufloat(0.0, 0.1)).std_dev
            away = umath.fabs(ufloat(3.0, 0.1)).std_dev
        assert at_zero == pytest.approx(0.1, rel=1e-9)
        assert away == pytest.approx(0.1, rel=1e-9)

        # ITACA refuses the first and propagates the second.
        db = _frame(x=0.0).set_uncertainty({"x": 0.1})
        with pytest.raises(UncertaintyCompatibilityError):
            db.compute("y = abs(x)")
        ok = _frame(x=3.0).set_uncertainty({"x": 0.1})
        got = ok.compute("y = abs(x)").uncertainty.systematic["y"]
        assert got[0] == pytest.approx(away, rel=1e-9)
