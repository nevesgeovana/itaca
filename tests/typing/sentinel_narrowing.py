"""mypy strict conformance snippet for the REQ-105 sentinel.

Checked by ``mypy --strict`` from the typing-conformance test in
``tests/core/test_sentinels.py``; never imported at runtime. Both
assignments below typecheck only if the ``is`` identity check narrows
the single-member enum out of the union, which is the typed half of
the REQ-105 contract.
"""

from itaca.core.sentinels import NoDefault, no_default


def resample(weights: list[float] | None | NoDefault = no_default) -> str:
    """Return which of the three argument states the caller produced."""
    if weights is no_default:
        taken: NoDefault = weights
        assert taken is no_default
        return "not passed"
    narrowed: list[float] | None = weights
    return "disabled" if narrowed is None else "passed"
