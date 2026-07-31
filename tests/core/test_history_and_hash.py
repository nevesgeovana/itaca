"""Tests for History and the state hash (SRS 4.4.2, REQ-103; DD-01).

History follows the append-only manifest discipline adopted from
pyflightstream: frozen entries, contiguous indices enforced on
construction, appending returns a new object.

Usage example (the contract under test)::

    from itaca.core.history import History

    history = History().append(operation="load(...)", state_hash="...")
    assert history[0].index == 1
"""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest

import itaca as itc
from itaca.core.axes import Axis, AxisRegistry
from itaca.core.coords import Cartesian
from itaca.core.dimension import Dimension
from itaca.core.errors import ProvenanceError
from itaca.core.history import History, HistoryEntry, compute_state_hash
from itaca.core.varframe import VarFrame
from itaca.core.variable import Variable


def hash_of(**fields: Any) -> str:
    """Hash CONTENT fields, holding the frame-level two at their default.

    ``compute_state_hash`` requires ``coords`` and ``mode`` (DD-47), so
    that no production call site can narrow what is authenticated by
    omitting one. Every test below is about a content field, so naming
    the same two constants twenty-eight times would say nothing; the
    tests that vary them are in
    ``tests/io/test_ita2e_canonical_payload.py`` and, as properties, in
    ``tests/core/test_hash_properties.py``.
    """
    fields.setdefault("coords", Cartesian())
    fields.setdefault("mode", "production")
    return compute_state_hash(**fields)


def _entry(index: int, operation: str = "op") -> HistoryEntry:
    return HistoryEntry(
        index=index,
        operation=operation,
        timestamp=datetime(2026, 7, 21, tzinfo=UTC),
        state_hash="f" * 64,
    )


class TestHistory:
    def test_empty(self) -> None:
        history = History()
        assert len(history) == 0
        assert history.last is None

    def test_append_returns_new_history(self) -> None:
        # DD-03 instinct applied to History: append-only, immutable.
        h0 = History()
        h1 = h0.append(operation="load(source='a.csv')", state_hash="a" * 64)
        assert len(h0) == 0
        assert len(h1) == 1
        entry = h1[0]
        assert entry.index == 1
        assert entry.operation == "load(source='a.csv')"
        assert entry.comment is None
        assert entry.timestamp.tzinfo is not None

    def test_indices_are_sequential_from_one(self) -> None:
        history = History()
        for i in range(3):
            history = history.append(operation=f"op{i}", state_hash="a" * 64)
        assert [e.index for e in history] == [1, 2, 3]
        assert history.last is not None
        assert history.last.index == 3

    def test_comment_is_stored(self) -> None:
        # REQ-19: optional comment on every operation.
        history = History().append(
            operation="fill(along='alpha')",
            state_hash="a" * 64,
            comment="removed bad point at alpha=8.0",
        )
        assert history[0].comment == "removed bad point at alpha=8.0"

    def test_non_contiguous_indices_rejected(self) -> None:
        with pytest.raises(ProvenanceError):
            History(entries=(_entry(1), _entry(3)))

    def test_indices_must_start_at_one(self) -> None:
        with pytest.raises(ProvenanceError):
            History(entries=(_entry(2),))

    def test_repr_lists_entries_with_comments(self) -> None:
        history = History().append(
            operation="load()", state_hash="a" * 64, comment="first"
        )
        text = repr(history)
        assert "History(1 entries)" in text
        assert "[1] load()" in text
        assert "first" in text

    def test_getitem(self) -> None:
        history = History().append(operation="load()", state_hash="a" * 64)
        assert history[0] is history.entries[0]


class TestStateHash:
    def _content(
        self, values: np.ndarray | None = None
    ) -> tuple[dict[str, Dimension], dict[str, Variable]]:
        if values is None:
            values = np.arange(3.0)
        dims = {"alpha": Dimension(name="alpha", coords=np.array([0.0, 2.0, 4.0]))}
        variables = {"CT": Variable(name="CT", values=values)}
        return dims, variables

    def test_deterministic(self) -> None:
        # REQ-103: same content, same operations, same hash.
        dims_a, vars_a = self._content()
        dims_b, vars_b = self._content()
        ops = (("load(source='a.csv')", None),)
        h1 = hash_of(dims=dims_a, variables=vars_a, operations=ops)
        h2 = hash_of(dims=dims_b, variables=vars_b, operations=ops)
        assert h1 == h2
        assert len(h1) == 64

    def test_sensitive_to_values(self) -> None:
        dims, vars_a = self._content()
        _, vars_b = self._content(values=np.array([0.0, 1.0, 99.0]))
        h1 = hash_of(dims=dims, variables=vars_a, operations=())
        h2 = hash_of(dims=dims, variables=vars_b, operations=())
        assert h1 != h2

    def test_sensitive_to_operations_and_comments(self) -> None:
        dims, variables = self._content()
        h0 = hash_of(dims=dims, variables=variables, operations=())
        h1 = hash_of(dims=dims, variables=variables, operations=(("squeeze()", None),))
        h2 = hash_of(dims=dims, variables=variables, operations=(("squeeze()", "why"),))
        assert len({h0, h1, h2}) == 3

    def test_variable_insertion_order_is_canonical(self) -> None:
        dims, _ = self._content()
        a = Variable(name="A", values=np.arange(3.0))
        b = Variable(name="B", values=np.arange(3.0) + 1)
        h_ab = hash_of(dims=dims, variables={"A": a, "B": b}, operations=())
        h_ba = hash_of(dims=dims, variables={"B": b, "A": a}, operations=())
        assert h_ab == h_ba

    def test_sensitive_to_correlation_and_tags(self) -> None:
        from itaca.core.correlation import CorrelationMatrix
        from itaca.core.historyframe import HistoryFrame
        from itaca.core.uncframe import UncFrame

        dims, variables = self._content()
        base = hash_of(dims=dims, variables=variables, operations=())
        with_corr = hash_of(
            dims=dims,
            variables=variables,
            operations=(),
            correlation=CorrelationMatrix(pairs={("CT", "CP"): 0.5}),
        )
        with_tags = hash_of(
            dims=dims,
            variables=variables,
            operations=(),
            tags=HistoryFrame(tags={"CT": np.array([0, 1, 0])}),
        )
        with_unc = hash_of(
            dims=dims,
            variables=variables,
            operations=(),
            uncertainty=UncFrame(random={"CT": np.full(3, 0.1)}),
        )
        assert len({base, with_corr, with_tags, with_unc}) == 4

    def test_dimension_order_is_semantic(self) -> None:
        # Dimension order dictates array shape (SRS 4.1.1), so it hashes.
        alpha = Dimension(name="alpha", coords=np.array([0.0, 2.0]))
        mach = Dimension(name="mach", coords=np.array([0.1, 0.2]))
        h1 = hash_of(dims={"alpha": alpha, "mach": mach}, variables={}, operations=())
        h2 = hash_of(dims={"mach": mach, "alpha": alpha}, variables={}, operations=())
        assert h1 != h2


class TestSemanticStateHash:
    """REV-001 ITACA-003: two states with the same identity produced
    different physics.

    `rotate` reads a unit to convert an angle to radians, so a frame
    labeled `deg` and a frame labeled `rad` compute different results
    from identical arrays. They hashed identically, because the digest
    covered arrays and names and nothing a Dimension or Variable calls
    itself. SEAT-lib-wording answered that the hash is a SEMANTIC
    GUARANTEE rather than an enumeration of fields, so every metadata
    field the archive reconstructs is in scope (DD-40).
    """

    @staticmethod
    def _base(**dim_kwargs: object) -> dict[str, object]:
        return {
            "dims": {
                "alpha": Dimension(
                    name="alpha",
                    coords=np.array([0.0, 2.0, 4.0]),
                    **dim_kwargs,  # type: ignore[arg-type]
                )
            },
            "variables": {"CT": Variable(name="CT", values=np.arange(3.0))},
            "operations": (("load()", None),),
        }

    def test_itaca_003_unit_changes_the_hash(self) -> None:
        """The reported case, at the level the finding is about."""
        deg = hash_of(**self._base(unit="deg"))  # type: ignore[arg-type]
        rad = hash_of(**self._base(unit="rad"))  # type: ignore[arg-type]
        assert deg != rad

    def test_itaca_003_the_deg_and_rad_frames_differ_end_to_end(self) -> None:
        """The whole finding in one test: same identity, different physics.

        Before the fix, `same_pre_rotation_hash` was True while
        `FZ_with_deg` was -1.0 and `FZ_with_rad` was
        -0.8939966636005579. Asserting the hashes differ AND that the
        rotation results differ pins both halves, so a future change
        cannot satisfy one by breaking the other.
        """

        def frame(unit: str) -> VarFrame:
            rows = [[0.5, 1.0, 0.0, 0.0]]
            db = itc.load(np.array(rows), names=["alpha", "FX", "FY", "FZ"]).pivot(
                dims=["alpha"]
            )
            return dataclasses.replace(
                db,
                dims={
                    "alpha": Dimension(name="alpha", coords=np.array([0.5]), unit=unit)
                },
            )

        deg, rad = frame("deg"), frame("rad")
        assert deg.state_hash != rad.state_hash

        def rotated(db: VarFrame) -> float:
            out = db.declare_vector("force", ["FX", "FY", "FZ"]).rotate("stability")
            return float(out.vars["FZ"].values[0])

        assert rotated(deg) != pytest.approx(rotated(rad))

    def test_itaca_003_the_digest_of_a_bare_frame_is_pinned(self) -> None:
        """The canary. It was a proof; it is now a tripwire.

        This test was written at DD-40 to prove the digest had NOT
        moved: an unset metadata field emitted no token, and the literal
        was the evidence that the compatibility break was bounded.

        DD-47 moves it deliberately. Canonical framing tells an absent
        field from an empty one without the emit-nothing rule, so that
        rule is gone, and ``coords`` and ``mode`` now enter the digest.
        The value below is the post-migration one, measured on the fix.

        The literal stays, with its purpose rewritten rather than the
        test deleted, because what it guards is still worth guarding:
        after a deliberate migration the next move of this value will be
        an accidental one, and nothing else in the suite would notice a
        reordered field or a stray token.
        """
        assert hash_of(**self._base()) == (  # type: ignore[arg-type]
            "48679696326381c0c4f49bf08fa161d0f1ab31487e36c111db8ea9adcadab07d"
        )

    def test_itaca_003_pivot_promotes_a_variable_unit_into_the_hash(self) -> None:
        """The shortest real-world path to the finding.

        `pivot` promotes a Variable's unit into the Dimension it
        creates, and that Dimension unit is what `rotate` reads. So a
        unit that looked like pure metadata on a variable becomes
        load-bearing one operation later. Measured before the fix: the
        pivoted hash was identical to the no-unit variant.
        """
        arr = np.column_stack([[0.0, 2.0], [1.0, 2.0]])

        def pivoted(unit: str | None) -> VarFrame:
            db = itc.load(arr, names=["alpha", "CT"])
            db = dataclasses.replace(
                db,
                vars={
                    **db.vars,
                    "alpha": dataclasses.replace(db.vars["alpha"], unit=unit),
                },
            )
            return db.pivot(dims=["alpha"])

        with_unit = pivoted("deg")
        without = pivoted(None)
        assert with_unit.dims["alpha"].unit == "deg"
        assert with_unit.state_hash != without.state_hash

    @pytest.mark.parametrize(
        "field,value",
        [
            ("unit", "deg"),
            ("description", "angle of attack"),
        ],
    )
    def test_itaca_003_mutating_any_dimension_metadata_changes_the_hash(
        self, field: str, value: str
    ) -> None:
        """BRF-043's mutation sweep, dimension half."""
        assert hash_of(**self._base(**{field: value})) != (  # type: ignore[arg-type]
            hash_of(**self._base())  # type: ignore[arg-type]
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("unit", "N"),
            ("description", "normal force"),
            ("long_name", "Normal force in the body axis"),
        ],
    )
    def test_itaca_003_mutating_any_variable_metadata_changes_the_hash(
        self, field: str, value: str
    ) -> None:
        """BRF-043's mutation sweep, variable half.

        The boundary is WIDE by the author's decision: every field the
        archive reconstructs, not only the fields an operation reads.
        The archive persists description and long_name and rebuilds the
        frame from them, so under a narrower line an editor could change
        what a variable claims to be inside an archive the state hash
        certifies.
        """
        base = {
            "dims": {"alpha": Dimension(name="alpha", coords=np.array([0.0, 2.0]))},
            "operations": (),
        }
        plain = hash_of(
            **base,  # type: ignore[arg-type]
            variables={"CT": Variable(name="CT", values=np.arange(2.0))},
        )
        mutated = hash_of(
            **base,  # type: ignore[arg-type]
            variables={
                "CT": Variable(name="CT", values=np.arange(2.0), **{field: value})
            },
        )
        assert plain != mutated

    def test_itaca_003_the_axis_registry_description_is_covered(self) -> None:
        """REQ-103's text now names the registry, and the description too.

        The registry was already hashed while the requirement omitted
        it, which is the same drift as the units in the opposite
        direction: the code covered more than the text said. Both are
        closed in one revision.
        """
        base = {
            "dims": {"alpha": Dimension(name="alpha", coords=np.array([0.0]))},
            "variables": {},
            "operations": (),
        }
        plain = AxisRegistry().with_axis(Axis(name="rig", rotation_matrix=np.eye(3)))
        described = AxisRegistry().with_axis(
            Axis(name="rig", rotation_matrix=np.eye(3), description="balance rig")
        )
        assert hash_of(**base, axes=plain) != (  # type: ignore[arg-type]
            hash_of(**base, axes=described)  # type: ignore[arg-type]
        )

    def test_itaca_003_byte_order_is_normalized(self) -> None:
        """A representational guarantee still normalizes the unobservable.

        Byte order is not reachable through the read-only public surface
        (REQ-102), so a big-endian and a native array holding the same
        values ARE the same semantic state and must not hash
        differently. Normalizing to NATIVE rather than to a fixed
        canonical order is what leaves every existing hash unchanged.
        """
        native = np.array([0.0, 2.0, 4.0])
        swapped = native.astype(">f8")
        assert np.array_equal(native, swapped)
        base = {
            "variables": {"CT": Variable(name="CT", values=np.arange(3.0))},
            "operations": (("load()", None),),
        }
        assert hash_of(
            **base,  # type: ignore[arg-type]
            dims={"alpha": Dimension(name="alpha", coords=native)},
        ) == hash_of(
            **base,  # type: ignore[arg-type]
            dims={"alpha": Dimension(name="alpha", coords=swapped)},
        )

    def test_itaca_003_signed_zero_is_not_normalized(self) -> None:
        """The author accepted a REPRESENTATIONAL definition, and this is why.

        -0.0 is observable through the public API: `1.0 / x` yields
        -inf for -0.0 and +inf for 0.0. Canonicalizing signed zeros
        would make the guarantee FALSE rather than merely strict, so
        they stay distinct.
        """
        base = {
            "dims": {"alpha": Dimension(name="alpha", coords=np.array([0.0]))},
            "operations": (),
        }
        positive = hash_of(
            **base,  # type: ignore[arg-type]
            variables={"x": Variable(name="x", values=np.array([0.0]))},
        )
        negative = hash_of(
            **base,  # type: ignore[arg-type]
            variables={"x": Variable(name="x", values=np.array([-0.0]))},
        )
        assert positive != negative
