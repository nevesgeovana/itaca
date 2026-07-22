"""Synthetic wind tunnel campaign: the canonical M0 walkthrough.

All data is synthetic (fixed-seed noise over textbook curves); see
examples/README.md for the provenance statement. The load uses dict
mode, the most traceable form and the recommended production pattern
(REQ-03).
"""

from pathlib import Path

import numpy as np

import itaca as itc

OUTPUT = Path(__file__).parent / "output"
S_REF = 0.1963  # m^2, synthetic reference wing area


def generate_sources(rng: np.random.Generator) -> dict[tuple[float, str], Path]:
    """Write one synthetic CSV per Mach number and return the load map."""
    OUTPUT.mkdir(exist_ok=True)
    sources: dict[tuple[float, str], Path] = {}
    alpha = np.arange(-4.0, 12.1, 2.0)
    for mach in (0.1, 0.2):
        q_inf = 0.5 * 1.225 * (mach * 340.0) ** 2
        cl = 0.1 + 0.105 * alpha
        fz = cl * q_inf * S_REF + rng.normal(0.0, 0.02, alpha.size)
        fx = (0.02 + 0.05 * cl**2) * q_inf * S_REF + rng.normal(0.0, 0.01, alpha.size)
        path = OUTPUT / f"run_m{int(mach * 100):02d}.csv"
        lines = ["alpha,FX,FZ,V"]
        lines.extend(
            f"{a},{x:.6f},{z:.6f},{mach * 340.0:.3f}"
            for a, x, z in zip(alpha, fx, fz, strict=True)
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sources[(mach, "*")] = path
    return sources


def main() -> None:
    """Run the walkthrough end to end."""
    rng = np.random.default_rng(20260721)
    sources = generate_sources(rng)

    # Load: dict mode, alpha swept within each file (OQ-19).
    db = itc.load(
        sources,
        dims=["mach", "alpha"],
        version="v1.0-synthetic",
        comment="synthetic campaign, examples/wt_campaign.py",
    )
    db.summary()
    db.diagnostics()
    db.manifest(OUTPUT / "manifest.csv")

    # Uncertainty: systematic balance calibration plus random scatter
    # (REQ-39, REQ-99), with a correlated balance pair (REQ-40).
    db = db.set_uncertainty(
        {"FX": 0.01, "FZ": 0.02}, comment="balance calibration (synthetic)"
    )
    db = db.set_uncertainty({"FX": 0.01, "FZ": 0.02}, component="random")
    db = db.set_correlation({("FX", "FZ"): 0.3})

    # Derivation with automatic GUM propagation (REQ-33, REQ-41).
    db = db.compute("q_inf = 0.5 * 1.225 * V**2")
    db = db.compute(f"CL = FZ / (q_inf * {S_REF})")
    db = db.compute(f"CD = FX / (q_inf * {S_REF})")

    # Export: full provenance in every format (REQ-70, REQ-71).
    db.to_csv(OUTPUT / "campaign_flat.csv")
    archive = db.save(OUTPUT / "campaign.itc")

    reopened = itc.open(archive)
    assert reopened.state_hash == db.state_hash
    assert reopened.uncertainty is not None
    print(
        "round trip verified: state hash "
        f"{reopened.state_hash[:12]}..., "
        f"u(CL) at first point = "
        f"{reopened.uncertainty.combined('CL').ravel()[0]:.5f}"
    )


if __name__ == "__main__":
    main()
