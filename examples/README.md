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

* `pipeline_reuse.py`: reusable pipelines (REQ-53 to REQ-55). Processes
  one synthetic run (smooth, then a derived ratio), lifts the recorded
  processing out of History as a `Pipeline`, replays it on a second run
  so both are processed identically, and round trips the recipe through
  a human-readable `.itc_pipe` file. Outputs land in `examples/output/`
  (not tracked).

* `processor_itceq.py`: processors and the `.itceq` equation file
  (REQ-45 to REQ-48). Writes a small `.itceq` workflow, builds a
  processor from it (`itc.processor`), inspects it, validates a synthetic
  balance run against it, and applies it so the coefficients are derived
  with automatic GUM propagation from the declared `[uncertainties]`.
  The file declares `q_inf` after the coefficients that consume it, so
  it also shows both halves of DD-17: file order by default,
  `auto_sort=True` resolving and reporting the dependency order. It ends
  on the REQ-47 idempotence refusal and a `[constants]` override.
  Outputs land in `examples/output/` (not tracked).

Run from the repository root::

    python examples/wt_campaign.py
    python examples/pipeline_reuse.py
    python examples/processor_itceq.py
