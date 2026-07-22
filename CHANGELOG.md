# Changelog

All notable changes to the ITACA library are documented here. The format
follows Keep a Changelog; versions follow semantic versioning. The SRS
document baseline has its own changelog in `docs/srs/` Chapter 11.

## [Unreleased]

### Added

* M0 Phase 0, project infrastructure: package skeleton (`core/`, `io/`,
  `ops/`, `uncertainty/`, `utils/`) importable as `import itaca as itc`
  with `__version__` single-sourced in `core/version.py` (REQ-92); the
  `ITACAError` hierarchy with all six families and the M0 leaf classes,
  every message carrying object, operation, and suggested fix (DD-10,
  REQ-81); the shared message formatter re-exported by
  `utils/validation.py`; tooling per SRS Chapter 7: ruff lint and
  format with the NumPy-only import ban (REQ-80, REQ-82), `mypy
  --strict` (REQ-78), pytest with the 90 percent coverage gate
  (REQ-75), Hypothesis available, pre-commit mirror (REQ-96), GitHub
  Actions CI testing minimum and latest dependency versions (REQ-83,
  REQ-95), and an AST guard test backing the import policy (DD-02).
* M0 execution plan consolidated in `docs/M0_EXECUTION_PLAN.md` from
  SRS Chapter 10, approved by Geovana 2026-07-21.
* Repository established 2026-07-21 with the design baseline: SRS
  document 0.1.0 (first workspace-tracked version), DECISIONS DD-01 to
  DD-22, OPEN_QUESTIONS OQ-01 to OQ-18, MIT license, citation metadata.
