"""Tests for db.interpolate (REQ-25): densify or translate axis.

Usage example (TDD anchor)::

    import itaca as itc
    db = itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])
    dense = db.interpolate({"alpha": [0.0, 0.5, 1.0, 1.5, 2.0]})
    on_cl = db.interpolate(axisTranslation={"from": "alpha", "to": "CL"})

Existing coordinates are preserved unless override=True; the
HistoryFrame gets +1 inside the convex hull of the original axis and
-1 outside; uncertainty propagates through the interpolation weights
(REQ-98, both components).
"""

import dataclasses
import warnings
from pathlib import Path

import numpy as np
import pytest

import itaca as itc
from itaca.core.errors import (
    AxisTranslationError,
    DataError,
    DimensionNotFoundError,
    FitDegreeError,
    NonNumericDimensionError,
)
from itaca.core.uncframe import UncFrame
from itaca.core.varframe import VarFrame


def _line(alpha: list[float], ct: list[float], name: str = "CT") -> VarFrame:
    arr = np.column_stack([np.array(alpha), np.array(ct)])
    return itc.load(arr, names=["alpha", name]).pivot(dims=["alpha"])


def _natural_cubic_reference(
    x: np.ndarray, y: np.ndarray, targets: np.ndarray
) -> np.ndarray:
    """Independent natural cubic spline (Numerical Recipes scalar form).

    Structurally different from the kernel's weight-matrix assembly, so
    a mistake in one is unlikely to be mirrored in the other.
    """
    n = x.size
    y2 = np.zeros(n)
    u = np.zeros(n)
    for i in range(1, n - 1):
        sig = (x[i] - x[i - 1]) / (x[i + 1] - x[i - 1])
        p = sig * y2[i - 1] + 2.0
        y2[i] = (sig - 1.0) / p
        u[i] = (y[i + 1] - y[i]) / (x[i + 1] - x[i]) - (y[i] - y[i - 1]) / (
            x[i] - x[i - 1]
        )
        u[i] = (6.0 * u[i] / (x[i + 1] - x[i - 1]) - sig * u[i - 1]) / p
    for k in range(n - 2, -1, -1):
        y2[k] = y2[k] * y2[k + 1] + u[k]
    out = np.empty(targets.size)
    for j, t in enumerate(targets):
        klo = int(np.clip(np.searchsorted(x, t, side="right") - 1, 0, n - 2))
        khi = klo + 1
        h = x[khi] - x[klo]
        a = (x[khi] - t) / h
        b = (t - x[klo]) / h
        out[j] = (
            a * y[klo]
            + b * y[khi]
            + ((a**3 - a) * y2[klo] + (b**3 - b) * y2[khi]) * h**2 / 6.0
        )
    return out


@pytest.fixture
def ramp() -> VarFrame:
    # CT = 2 * alpha, exactly linear.
    return _line([0.0, 1.0, 2.0], [0.0, 2.0, 4.0])


class TestInterpolateMethods:
    def test_linear_exact_on_linear_data(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.5, 1.5]})
        assert np.allclose(result.dims["alpha"].coords, [0.5, 1.5])
        assert np.allclose(result.vars["CT"].values, [1.0, 3.0])

    def test_nearest(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.4, 1.6]}, method="nearest")
        assert np.allclose(result.vars["CT"].values, [0.0, 4.0])

    def test_cubic_reproduces_nodes_and_linear_data(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.0, 0.5, 1.0, 2.0]}, method="cubic")
        assert np.allclose(result.vars["CT"].values, [0.0, 1.0, 2.0, 4.0])

    def test_cubic_on_curved_data_matches_natural_spline(self) -> None:
        # Genuinely curved data exercises the second-derivative band of
        # the natural-spline operator (linear data zeroes it out).
        alpha = [0.0, 1.0, 2.0, 3.0, 4.0]
        db = _line(alpha, [a**3 for a in alpha])
        result = db.interpolate({"alpha": [0.5, 1.5, 2.5]}, method="cubic")
        # Natural cubic reference (second derivative zero at the ends).
        # Interior midpoints of a smooth cubic sampled on a fine grid.
        expected = _natural_cubic_reference(
            np.array(alpha, dtype=float),
            np.array([a**3 for a in alpha], dtype=float),
            np.array([0.5, 1.5, 2.5]),
        )
        assert np.allclose(result.vars["CT"].values, expected, atol=1e-9)

    def test_cubic_reproduces_curved_nodes_exactly(self) -> None:
        alpha = [0.0, 1.0, 2.0, 3.0, 4.0]
        cubic_vals = [a**3 - 2.0 * a for a in alpha]
        db = _line(alpha, cubic_vals)
        result = db.interpolate({"alpha": alpha}, method="cubic", override=True)
        assert np.allclose(result.vars["CT"].values, cubic_vals, atol=1e-9)

    def test_polyfit_exact_on_quadratic(self) -> None:
        alpha = [0.0, 1.0, 2.0, 3.0]
        db = _line(alpha, [a**2 for a in alpha])
        result = db.interpolate({"alpha": [0.5, 2.5]}, method="polyfit", deg=2)
        assert np.allclose(result.vars["CT"].values, [0.25, 6.25])

    def test_polyfit_needs_deg(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate({"alpha": [0.5]}, method="polyfit")

    def test_unknown_method_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate({"alpha": [0.5]}, method="magic")


class TestInterpolateOverride:
    def test_existing_coordinate_preserved_by_default(self) -> None:
        # REQ-76 edge case: override=False on an existing coordinate.
        # A deg-1 polyfit of quadratic data would change the value at
        # alpha=1; the original must be preserved.
        alpha = [0.0, 1.0, 2.0]
        db = _line(alpha, [a**2 for a in alpha])
        result = db.interpolate({"alpha": [0.5, 1.0]}, method="polyfit", deg=1)
        assert result.vars["CT"].values[1] == pytest.approx(1.0)

    def test_override_recomputes(self) -> None:
        alpha = [0.0, 1.0, 2.0]
        db = _line(alpha, [a**2 for a in alpha])
        result = db.interpolate(
            {"alpha": [0.5, 1.0]}, method="polyfit", deg=1, override=True
        )
        assert result.vars["CT"].values[1] != pytest.approx(1.0)

    def test_preserved_point_keeps_tag_zero(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.5, 1.0]})
        assert result.tags is not None
        assert result.tags.tags["CT"][1] == 0


class TestInterpolateTags:
    def test_hull_tags(self, ramp: VarFrame) -> None:
        # REQ-25: +1 within the convex hull of the original axis, -1
        # outside.
        result = ramp.interpolate({"alpha": [-1.0, 0.5, 3.0]})
        assert result.tags is not None
        assert list(result.tags.tags["CT"]) == [-1, 1, -1]


class TestInterpolateValidation:
    def test_unknown_dimension_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DimensionNotFoundError):
            ramp.interpolate({"beta": [0.5]})

    def test_non_numeric_dimension_rejected(self, prov) -> None:  # type: ignore[no-untyped-def]
        from itaca.core.dimension import Dimension
        from itaca.core.variable import Variable

        blade = Dimension(name="blade", coords=np.array(["A", "B"]), is_numeric=False)
        ct = Variable(name="CT", values=np.array([1.0, 2.0]))
        db = VarFrame(dims={"blade": blade}, vars={"CT": ct}, provenance=prov)
        with pytest.raises(NonNumericDimensionError):
            db.interpolate({"blade": ["C"]})

    def test_empty_call_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate({})


class TestInterpolateMultiDim:
    def test_partial_interpolation_keeps_other_dims(self) -> None:
        rows = [[a, m, 10.0 * a + m] for a in (0.0, 1.0, 2.0) for m in (0.1, 0.2)]
        db = itc.load(np.array(rows), names=["alpha", "mach", "CT"]).pivot(
            dims=["alpha", "mach"]
        )
        result = db.interpolate({"alpha": [0.5, 1.5]})
        assert result.shape == (2, 2)
        assert result.vars["CT"].values[0, 0] == pytest.approx(5.1)
        assert result.vars["CT"].values[1, 1] == pytest.approx(15.2)


class TestInterpolateUncertainty:
    def test_components_through_linear_weights(self, ramp: VarFrame) -> None:
        # Midpoint weights (0.5, 0.5): systematic through the weight
        # sum, random through the RSS (REQ-98).
        unc = UncFrame(
            systematic={"CT": np.full(3, 0.1)},
            random={"CT": np.full(3, 0.1)},
        )
        result = dataclasses.replace(ramp, uncertainty=unc).interpolate(
            {"alpha": [0.5]}
        )
        assert result.uncertainty is not None
        assert result.uncertainty.systematic["CT"][0] == pytest.approx(0.1)
        assert result.uncertainty.random["CT"][0] == pytest.approx(0.1 / np.sqrt(2.0))


class TestAxisTranslation:
    def test_single_line_relabels_axis(self) -> None:
        rows = [[a, 0.1 * a, 2.0 * a] for a in (0.0, 1.0, 2.0)]
        db = itc.load(np.array(rows), names=["alpha", "CL", "CT"]).pivot(dims=["alpha"])
        result = db.interpolate(axisTranslation={"from": "alpha", "to": "CL"})
        assert "alpha" not in result.dims
        assert np.allclose(result.dims["CL"].coords, [0.0, 0.1, 0.2])
        assert "CL" not in result.vars
        assert np.allclose(result.vars["CT"].values, [0.0, 2.0, 4.0])

    def test_explicit_target_grid(self) -> None:
        rows = [[a, 0.1 * a, 2.0 * a] for a in (0.0, 1.0, 2.0)]
        db = itc.load(np.array(rows), names=["alpha", "CL", "CT"]).pivot(dims=["alpha"])
        result = db.interpolate(
            {"CL": [0.05, 0.15]},
            axisTranslation={"from": "alpha", "to": "CL"},
        )
        assert np.allclose(result.dims["CL"].coords, [0.05, 0.15])
        assert np.allclose(result.vars["CT"].values, [1.0, 3.0])

    def test_non_monotonic_target_rejected(self) -> None:
        rows = [[a, v, 1.0] for a, v in [(0.0, 0.0), (1.0, 1.0), (2.0, 0.5)]]
        db = itc.load(np.array(rows), names=["alpha", "CL", "CT"]).pivot(dims=["alpha"])
        with pytest.raises(AxisTranslationError, match="monotonic") as exc:
            db.interpolate(axisTranslation={"from": "alpha", "to": "CL"})
        assert "Suggested fix:" in str(exc.value)

    def test_missing_target_variable_rejected(self, ramp: VarFrame) -> None:
        with pytest.raises(DataError):
            ramp.interpolate(axisTranslation={"from": "alpha", "to": "CL"})


class TestInterpolateBookkeeping:
    def test_recorded_in_history(self, ramp: VarFrame) -> None:
        result = ramp.interpolate({"alpha": [0.5]}, comment="densify")
        assert result.history.last is not None
        assert result.history.last.operation.startswith("interpolate(")
        assert result.history.last.comment == "densify"

    def test_original_untouched(self, ramp: VarFrame) -> None:
        ramp.interpolate({"alpha": [0.5]})
        assert ramp.shape == (3,)


def test_itaca_025d_axis_translation_drops_pairs_naming_the_target() -> None:
    """REV-001 ITACA-025d: the target variable becomes a dimension.

    axisTranslation moves `to` out of vars, so its declared pairs no
    longer name a variable of the frame. The drop is scoped: a pair
    between two variables that both survive is untouched. The operation
    already had a channel for recording exactly this kind of drop, for
    the uncertainty half.
    """
    x = np.array([0.0, 1.0, 2.0, 3.0])
    arr = np.column_stack([x, 1.0 + 2.0 * x, 3.0 * x, 4.0 * x])
    db = itc.load(arr, names=["x", "y", "z", "z2"]).pivot(dims=["x"])
    db = db.set_correlation({("y", "z"): 0.5, ("z", "z2"): 0.1})

    out = db.interpolate(axisTranslation={"from": "x", "to": "y"})

    assert "y" in out.dims
    assert out.correlation is not None
    assert not any("y" in pair for pair in out.correlation.pairs)
    assert out.correlation.get("z", "z2") == 0.1
    assert "axis_correlation=dropped" in out.history[-1].operation


class TestNegativePolynomialDegree:
    """REV-001 ITACA-033: silent zeros where the data is a straight line.

    `interpolate({"alpha": [...]}, "polyfit", -1)` returned `[0., 0., 0.]`
    over data whose true values are `[1.0, 3.0, 5.0]`. `_validate_method`
    checked `deg >= n` and never `deg >= 0`, and `polyfit_matrix` builds
    an all-zero weight matrix for a negative degree.

    Only `interpolate` was silent. `fill` reached NumPy and raised a bare
    `ValueError` from outside the ITACA hierarchy, which is an ITACA-031
    instance rather than this one, and `fitmodel` was already correct.
    The validation is shared so the three cannot drift apart again.
    """

    def test_itaca_033_interpolate_refuses_a_negative_degree(self) -> None:
        """The reported case, with the true values named in the test."""
        x = np.arange(4.0)
        db = itc.load(np.column_stack([x, 1.0 + 2.0 * x]), names=["alpha", "y"]).pivot(
            dims=["alpha"]
        )
        with pytest.raises(DataError) as excinfo:
            db.interpolate({"alpha": [0.5, 1.5, 2.5]}, method="polyfit", deg=-1)
        assert "nonnegative polynomial degree" in str(excinfo.value)

        # And the degree the caller should have passed still works, so
        # the guard is not simply refusing polyfit.
        out = db.interpolate({"alpha": [0.5, 1.5, 2.5]}, method="polyfit", deg=1)
        assert out.vars["y"].values == pytest.approx([2.0, 4.0, 6.0])

    @pytest.mark.parametrize(
        "call",
        [
            lambda db: db.diff(along="alpha", deg=-1),
            lambda db: db.fitmodel(along="alpha", deg=-1),
            lambda db: db.fill("alpha", method="polyfit", deg=-1, window=4),
            lambda db: db.fill("alpha", method="polyfit", deg=-1, global_fit=True),
            lambda db: db.smooth(
                along="alpha", method="savgol", window=3, polyorder=-1
            ),
        ],
    )
    def test_itaca_033_every_degree_parameter_is_validated(self, call: object) -> None:
        """One rule at every public degree boundary, not just the reported one.

        `fill` raised a bare `ValueError` from NumPy and only when the
        frame had a gap to fill; on a gap-free frame it was a silent
        no-op that recorded `deg=-1` in History. Both are closed here.
        """
        x = np.arange(6.0)
        db = itc.load(np.column_stack([x, 1.0 + 2.0 * x]), names=["alpha", "y"]).pivot(
            dims=["alpha"]
        )
        with pytest.raises(DataError) as excinfo:
            call(db)  # type: ignore[operator]
        assert "nonnegative polynomial degree" in str(excinfo.value)
        # DataError, not FitDegreeError: that leaf means "too few points
        # for this degree", which depends on the data. This does not.
        assert not isinstance(excinfo.value, FitDegreeError)


class TestKeywordOnlyOptions:
    """REV-001 ITACA-032: the options are keyword-only, with no window.

    REQ-85 makes every optional parameter beyond the first positional
    argument keyword-only, and mandates no deprecation window.

    THE WINDOW WAS REMOVED BEFORE THE v0.2.0 TAG, and the reason is worth
    keeping. The lane that closed ITACA-032 added a `*args` shim to both
    methods, emitting `FutureWarning` and promising removal in v0.3.0, on
    the reasoning that "breaking it outright would be worse than the
    finding, because `axis` is an int and a positional call would silently
    land it in a different parameter". The release review measured that
    reasoning against the shipped surface and it does not hold here:
    NEITHER method existed in v0.1.0, so there were no released callers to
    protect. With `axis` keyword-only, `db.expand("rpm", vals, 0)` raises
    `TypeError` naming the arity, which is loud.

    The shim therefore inverted its own purpose. It let v0.2.0 users write
    a positional call legally, so v0.3.0 would have broken them: it
    MANUFACTURED the compatibility obligation it was added to avoid, and
    spent three public affordances on it. The `fill` precedent it cited is
    genuinely different, because `fill(along, method)` did ship in v0.1.0
    and its window is still in place.
    """

    @staticmethod
    def _ramp() -> VarFrame:
        x = np.arange(4.0)
        return itc.load(
            np.column_stack([x, 1.0 + 2.0 * x]), names=["alpha", "y"]
        ).pivot(dims=["alpha"])

    def test_itaca_032_positional_interpolate_options_are_refused(self) -> None:
        """A positional option raises, loudly, naming the arity."""
        with pytest.raises(TypeError, match="positional argument"):
            self._ramp().interpolate({"alpha": [0.5]}, "polyfit", 1)  # type: ignore[misc]

    def test_itaca_032_positional_expand_axis_is_refused(self) -> None:
        """Same on expand's `axis`, which is the int the window worried about."""
        with pytest.raises(TypeError, match="positional argument"):
            self._ramp().expand("rpm", [1.0, 2.0], 0)  # type: ignore[misc]

    def test_itaca_032_the_keyword_form_warns_about_nothing(self) -> None:
        """The supported form is silent, and is the only form.

        No `FutureWarning` is emitted by either method any more, which is
        the point: a deprecation that fires on the recommended call teaches
        people to ignore deprecations, and a deprecation for a form that
        never shipped teaches them to write it.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self._ramp().interpolate({"alpha": [0.5]}, method="polyfit", deg=1)
            self._ramp().expand("rpm", [1.0, 2.0], axis=0)

    def test_req105_interpolate_refuses_a_degree_it_does_not_consume(self) -> None:
        """`deg` reaches only `polyfit`, and is refused elsewhere (REQ-105).

        Found by the v0.2.0 release review. `_validate_method` inspected
        `deg` only inside the `polyfit` branch, so `method="linear",
        deg=3` was accepted, `deg` was never read, and it was then written
        into the History string AND into the replay kwargs. The provenance
        record asserted a degree the computation did not use, which is
        ITACA-023 over the library's own keyword instead of NumPy's, in a
        signature new in this release.

        `smooth` already answered this question the other way in the same
        release, so v0.2.0 was about to publish two opposite answers for
        two operations a user reaches for in the same breath.
        """
        ramp = self._ramp()
        for method in ("linear", "cubic", "nearest"):
            with pytest.raises(DataError, match="does not consume deg"):
                ramp.interpolate({"alpha": [0.5]}, method=method, deg=3)
        # And the consuming method still requires it.
        with pytest.raises(DataError, match="called without deg"):
            ramp.interpolate({"alpha": [0.5]}, method="polyfit")

    def test_req105_history_records_no_degree_when_none_was_consumed(self) -> None:
        """The provenance half, which is what made this a defect.

        A recorded `deg=` on a computation that read no degree is a
        provenance record asserting an intent the execution did not honor.
        """
        out = self._ramp().interpolate({"alpha": [0.5]}, method="linear")
        recorded = out.history[-1].operation
        assert "deg=" not in recorded, (
            f"History recorded a degree for a method that consumes none: {recorded!r}"
        )
        step = out.history[-1].step
        assert step is not None and "deg" not in step.kwargs, (
            f"the replay kwargs carry a degree the computation never read: "
            f"{step.kwargs if step else None!r}"
        )
        # The polyfit path still records it, so the absence above is a
        # consequence of the rule and not of the recording being dropped.
        fitted = self._ramp().interpolate({"alpha": [0.5]}, method="polyfit", deg=1)
        assert "deg=1" in fitted.history[-1].operation

    def test_req105_both_selectors_record_a_degree_the_same_way(self) -> None:
        """THE BLOCKER, and the reason it is parametrized over the selector.

        `interpolate` has two return paths, the mapping selector and the
        `axisTranslation` selector, and each built its own History string and
        its own `replay_kwargs` dict inline. The REQ-105 fix landed on the
        mapping one. With `deg` newly defaulting to the sentinel, the other
        recorded `deg=<no_default>`, and the consequences were not cosmetic:

            db.save(path)                   TypeError, from the stdlib JSON
                                            encoder, outside ITACAError
            to_pipeline().save(path)        DataError naming an argument the
                                            caller never passed

        Both worked before the sentinel default, so the fix broke a public
        export path for a REQ-25 capability. Two reviewer lenses found it
        independently and neither the suite nor the gates saw it, because
        nothing asserted provenance content or a round trip for that
        selector.

        Both paths now go through one `_replay` helper, and this test is what
        keeps them answering the same way.
        """
        ramp = self._ramp()
        runs = {
            "mapping": ramp.interpolate({"alpha": [0.5]}, method="linear"),
            "axisTranslation": ramp.interpolate(
                axisTranslation={"from": "alpha", "to": "y"}
            ),
        }
        for selector, out in runs.items():
            entry = out.history[-1]
            assert "deg=" not in entry.operation, (
                f"the {selector} selector recorded a degree for a method that "
                f"consumes none: {entry.operation!r}"
            )
            assert entry.step is not None and "deg" not in entry.step.kwargs, (
                f"the {selector} selector put a degree into the replay kwargs: "
                f"{entry.step.kwargs if entry.step else None!r}"
            )

    def test_req105_an_axis_translated_frame_still_round_trips(
        self, tmp_path: Path
    ) -> None:
        """The consequence half of the blocker, asserted end to end.

        A provenance record is only worth what can be done with it, and the
        sentinel in `replay_kwargs` made both public export paths raise. This
        asserts the paths rather than the record, so a future value that is
        not JSON-native fails here whatever put it there.
        """
        out = self._ramp().interpolate(axisTranslation={"from": "alpha", "to": "y"})
        archive = tmp_path / "translated.itc"
        out.save(str(archive))
        reopened = itc.open(str(archive))
        assert reopened.state_hash == out.state_hash
        out.history.to_pipeline().save(str(tmp_path / "translated.itc_pipe"))

    @pytest.mark.parametrize("bad", [None, 1.0, True, "2"], ids=type)
    def test_a_non_integer_degree_is_refused_with_a_three_part_message(
        self, bad: object
    ) -> None:
        """`deg` must be an int, and the refusal must be an ITACAError.

        `None` is the value a reader writes, because it WAS this parameter's
        documented default before REQ-105 adoption moved it to the sentinel.
        After that move it fell past both identity checks into `value < 0` and
        escaped as a bare `TypeError`, which is outside the ITACA hierarchy
        and carries none of the three parts.

        `True` is here because `bool` is an `int` subclass, so it satisfied
        the downstream `isinstance` assert and was recorded as `deg=True` in
        provenance, which is a degree no polynomial has.
        """
        with pytest.raises(DataError) as caught:
            self._ramp().interpolate({"alpha": [0.5]}, method="polyfit", deg=bad)
        message = str(caught.value)
        assert "integer polynomial degree" in message, message
        assert type(bad).__name__ in message, message

    def test_itaca_032_public_returns_are_not_object(self) -> None:
        """No public method may annotate its return as bare `object`.

        Measured before the fix: eight did, so a caller under
        `mypy --strict` got nothing back they could use. A guard rather
        than an example, because the defect is a class and returns once
        someone adds the ninth method.
        """
        import inspect

        offenders = [
            name
            for name, obj in vars(VarFrame).items()
            if not name.startswith("_")
            and inspect.isfunction(obj)
            and inspect.signature(obj).return_annotation in ("object", object)
        ]
        assert not offenders, (
            f"public method(s) {offenders} annotate their return as bare "
            "`object`, so mypy --strict gives the caller nothing usable "
            "(REQ-78, ITACA-032)."
        )
