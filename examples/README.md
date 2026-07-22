# ITACA examples

Every dataset in this directory is synthetic, generated inside the
example scripts themselves from fixed-seed pseudo-random numbers and
textbook-shaped aerodynamic curves. No measured, employer-origin, or
proprietary data enters this repository in any form (workspace data
policy; release provenance-scrub gate, SRS Chapter 10).

* `wt_campaign.py`: the canonical M0 walkthrough. Generates a small
  synthetic wind tunnel campaign (two Mach numbers, an alpha sweep in
  each file), loads it in the most traceable form (`itc.load` dict
  mode, REQ-03), assigns two-component uncertainties (REQ-39, REQ-99)
  with a correlated balance pair (REQ-40), derives coefficients with
  automatic GUM propagation (REQ-33, REQ-41), and exports a fully
  provenanced `.itc` archive plus CSV (REQ-70). Outputs land in
  `examples/output/` (not tracked).

Run from the repository root::

    python examples/wt_campaign.py
