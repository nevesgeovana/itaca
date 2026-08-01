"""The public examples are executed, not only shipped (FND-054, REV007-014).

Reproduction (TDD anchor), the shortest call that exhibits the defect::

    python examples/processor_itceq.py
    itaca.core.errors.UncertaintyLineageError: variables 'CL' and
    'blockage' in equation 'CL_corr = CL * blockage': ...

`examples/` holds the code a reader copies first, and nothing ran it.
`pyproject.toml` sets `testpaths = ["tests"]`, so pytest never collected
it; the CI and release smoke steps run a different inline snippet; and
the only mentions of the filenames anywhere in the suite were a
house-style walk scope and an sdist-content assertion, both of which
read the files without executing them.

The cost was not hypothetical. The first run of these three under this
module found `processor_itceq.py` already broken, by a refusal added in
another lane: its `.itceq` chained `CL_corr = CL * blockage` where both
sides descend from the same measured channels, which REQ-41 now refuses
because `compute` carries no lineage between calls. A published example
had been failing for every reader who ran it, and the repository was
green.

Each example is copied into a temporary directory and run there, rather
than run in place. The scripts write their output beside themselves
(`Path(__file__).parent / "output"`), so running them in place would
have this suite writing into the repository, and a test that dirties the
tree is a test people learn to work around.

The list is DISCOVERED and not enumerated, so an example added later is
covered by default and forgetting to register it is not possible. The
same reasoning as the REQ-82 import policy: a list has to be extended
whenever something is added, and the thing added but not listed inherits
no coverage at exactly the moment it is least reviewed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

#: A floor, not a count. It refuses the vacuous pass where discovery
#: silently finds nothing and the module reports success over an empty
#: parametrization; it does not have to be maintained when a fourth
#: example is added.
MINIMUM_EXAMPLES = 3


def _scripts() -> list[Path]:
    return sorted(EXAMPLES.glob("*.py"))


def test_every_example_is_discovered() -> None:
    """Discovery finds the examples, so the parametrization is not empty.

    Without this, a rename of `examples/` would empty the run below and
    the module would pass having executed nothing, which is the
    self-skipping shape the whole finding is about.
    """
    found = _scripts()
    assert len(found) >= MINIMUM_EXAMPLES, (
        f"found {[p.name for p in found]} under {EXAMPLES}, fewer than the "
        f"{MINIMUM_EXAMPLES} public examples this repository ships; the run "
        f"below would be measuring nothing"
    )


@pytest.mark.parametrize("script", _scripts(), ids=lambda p: p.name)
def test_the_example_runs(script: Path, tmp_path: Path) -> None:
    """The example a reader copies runs to completion, here and in CI.

    Measured before this guard existed: `processor_itceq.py` exited 1
    with `UncertaintyLineageError`, having been broken by a refusal
    added in another lane and shipped unnoticed.
    """
    workspace = tmp_path / "examples"
    shutil.copytree(EXAMPLES, workspace)

    done = subprocess.run(
        [sys.executable, str(workspace / script.name)],
        capture_output=True,
        text=True,
        cwd=str(workspace),
        env=child_env(),
    )

    assert done.returncode == 0, (
        f"examples/{script.name} exited {done.returncode}. This is the code a "
        f"reader copies first, so a failure here is a published defect and "
        f"not a test failure.\n--- stdout ---\n{done.stdout}"
        f"\n--- stderr ---\n{done.stderr}"
    )
    assert "Traceback" not in done.stderr, (
        f"examples/{script.name} exited 0 but printed a traceback, so it "
        f"swallowed an error rather than working:\n{done.stderr}"
    )
