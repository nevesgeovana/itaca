"""Reusable pipelines: record a processing sequence, replay it (REQ-53..55).

A pipeline is a contiguous range of History entries lifted into a
reusable object. It replays the recorded operations onto a new
VarFrame, so the same processing is applied identically across runs of
a campaign. The file is human-readable and version-controllable, so it
lives in git next to the data it processes.

All data is synthetic (textbook curves), see examples/README.md for the
provenance statement.
"""

from pathlib import Path

import numpy as np

import itaca as itc

OUTPUT = Path(__file__).parent / "output"


def _run(seed: int) -> itc.VarFrame:
    """One synthetic run: alpha swept, a lift and a drag column."""
    rng = np.random.default_rng(seed)
    alpha = np.arange(-4.0, 12.1, 2.0)
    cl = 0.1 + 0.105 * alpha + rng.normal(0.0, 0.01, alpha.size)
    cd = 0.02 + 0.05 * cl**2 + rng.normal(0.0, 0.002, alpha.size)
    # Array mode with explicit names. The dict mode CLAUDE.md prefers
    # maps coordinate tuples to FILES (REQ-03), which is the campaign
    # case in wt_campaign.py, not a single in-memory run like this one.
    arr = np.column_stack([alpha, cl, cd])
    return itc.load(arr, names=["alpha", "CL", "CD"]).pivot(dims=["alpha"])


def main() -> None:
    """Record a pipeline on one run, replay it on another."""
    OUTPUT.mkdir(exist_ok=True)

    # Process the first run: smooth both curves, then derive L/D.
    first = _run(seed=1)
    first = first.smooth(along="alpha", method="savgol", window=5, polyorder=2)
    processed = first.compute("LD = CL / CD")

    # Lift the processing into a reusable pipeline. The leading load and
    # pivot are input construction and are skipped automatically; the
    # smooth and compute steps are captured.
    pipeline = processed.history.to_pipeline()
    print(f"pipeline: {len(pipeline)} steps")

    # Replay it on a fresh run: identical processing, new data.
    second = _run(seed=2)
    replayed = pipeline.apply(second)
    assert "LD" in replayed.vars
    assert replayed.state_hash != processed.state_hash  # different data

    # Persist and reload: the file is human-readable and reusable.
    path = pipeline.save(OUTPUT / "smooth_and_ld.itc_pipe")
    reloaded = itc.load_pipeline(path)
    again = reloaded.apply(second)
    assert again.state_hash == replayed.state_hash  # replay is deterministic
    print(f"round trip verified: {path.name}, {len(reloaded)} steps")


if __name__ == "__main__":
    main()
