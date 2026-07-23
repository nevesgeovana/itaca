"""Per-operation array immutability (REQ-102) for the B1 ops.

Every op result must expose read-only arrays; centralizing the flag in
``rebuild`` is not a substitute for asserting it on each op path, since
an op that materializes arrays outside rebuild could regress unseen.
"""

import numpy as np
import pytest

import itaca as itc
from itaca.core.varframe import VarFrame


def _line(alpha: list[float], ct: list[float]) -> VarFrame:
    arr = np.column_stack([np.array(alpha), np.array(ct)])
    return itc.load(arr, names=["alpha", "CT"]).pivot(dims=["alpha"])


@pytest.fixture
def ramp() -> VarFrame:
    return _line([0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 2.0, 4.0, 6.0, 8.0])


def _assert_read_only(db: VarFrame) -> None:
    for var in db.vars.values():
        assert not var.values.flags.writeable
        with pytest.raises((ValueError, RuntimeError)):
            var.values.flat[0] = 99.0


class TestOpResultsReadOnly:
    def test_expand(self, ramp: VarFrame) -> None:
        _assert_read_only(ramp.expand("rpm", [1.0, 2.0]))

    def test_concat(self, ramp: VarFrame) -> None:
        other = _line([5.0, 6.0], [10.0, 12.0])
        _assert_read_only(itc.concat([ramp, other], along="alpha"))

    def test_interpolate(self, ramp: VarFrame) -> None:
        _assert_read_only(ramp.interpolate({"alpha": [0.5, 1.5]}))

    def test_interpolate_axis_translation(self) -> None:
        rows = [[a, 0.1 * a, 2.0 * a] for a in (0.0, 1.0, 2.0)]
        db = itc.load(np.array(rows), names=["alpha", "CL", "CT"]).pivot(dims=["alpha"])
        _assert_read_only(db.interpolate(axisTranslation={"from": "alpha", "to": "CL"}))

    def test_average(self, ramp: VarFrame) -> None:
        _assert_read_only(ramp.average(along="alpha"))

    def test_integrate(self, ramp: VarFrame) -> None:
        _assert_read_only(ramp.integrate("CT", over=["alpha"]))

    def test_smooth(self, ramp: VarFrame) -> None:
        _assert_read_only(ramp.smooth(along="alpha", method="moving_avg", window=3))

    def test_diff(self, ramp: VarFrame) -> None:
        _assert_read_only(ramp.diff(along="alpha"))

    def test_fitmodel(self, ramp: VarFrame) -> None:
        _assert_read_only(ramp.fitmodel(along="alpha", deg=2))

    def test_fitvalue(self, ramp: VarFrame) -> None:
        model = ramp.fitmodel(along="alpha", deg=2)
        _assert_read_only(model.fitvalue(coef_dims=["alpha_coef"], at={"alpha": [1.5]}))
