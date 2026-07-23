# Patterns adopted from pyflightstream

Status: adopted 2026-07-21 at Geovana's direction, at the start of M0
Phase 1. Source: survey of `C:\WORK\ClaudeProjects\pyflightstream`
(same author). Where a pyflightstream pattern conflicts with the SRS,
the SRS wins; the conflicts and their resolutions are listed at the
end. This file records intent; the SRS remains the specification.

## Adopted in Phase 1 (core data model)

1. Append-only, identity-enforced records. History entries follow the
   `runs.json` manifest discipline: frozen records, contiguous indices
   validated on construction, appending returns a new object, no
   in-place mutation. Identity lives in the record, never in file
   names.
2. Canonical, formatting-independent state hash. The REQ-103 state
   hash is computed the `config_hash` way: a canonical byte stream
   (names, dtypes, shapes, array bytes, normalized operation strings
   and comments) fed to SHA-256, so equal states hash equal regardless
   of construction details such as variable insertion order.
3. Version stamping that cannot drift. `pyproject.toml` reads the
   version from `core/version.py` (single source); Provenance stamps
   that same attribute. This fixes the drift pyflightstream has
   between its hardcoded `__version__` and its package metadata.
4. Exception discipline. Docstring on every exception class stating
   when it is raised; messages name the offending value, the rule
   violated, and the remedy (already REQ-81); guard violations are
   hard errors, never `warnings.warn`; soft caveats become recorded
   fields, not warnings.
5. Refuse-to-act guards. Production mode refuses unrecorded state
   changes; mode transitions (`promote`/`demote`) are explicit
   operations that are always recorded in History.
6. House-style guard test. A repository-wide test asserts the no
   em dash / no en dash rule over all tracked text files, constructing
   the forbidden characters from code points so the guard file itself
   stays clean.
7. Library-only logging. `logging.getLogger(__name__)` per module, no
   handlers or `basicConfig` inside the library, `%s` lazy formatting,
   levels used semantically. Logging is the ephemeral diagnostic
   stream; History and Provenance are the durable record. The two are
   never conflated.

## Adopted in later phases

* Phase 2 (loading, diagnostics): registry idiom with cached loaders
  and duplicate-name rejection; unknown-name errors that enumerate the
  registered set and distinguish unknown from unavailable; typed
  result objects with exactly one terminal status per item (no silent
  skips); `importlib.resources` for any packaged data.
* Phase 5 (persistence): atomic writes (temp file plus `os.replace`)
  for every artifact that must survive a crash; versioned `schema`
  strings inside every persisted file (the `.itc` `metadata.json`
  already carries a format version per the SRS; the same discipline
  extends to `.itc_pipe` and manifests); JSON for machine records,
  human-readable formats for reviewed artifacts; UTF-8 and trailing
  newline everywhere; golden-file byte comparison and
  write-read-revalidate round-trip tests for every serializer.
* Phase 6 (hardening): reason-required changes for canonical
  artifacts; provenance sentence stamped into generated human-facing
  output.
* Published docs site (REQ-108, late M1): ProperDocs on GitHub Pages,
  material theme, build-strict-then-deploy workflow, mirroring the
  pyflightstream site. The API reference follows pyflightstream's
  current scheme, `mkdocs-gen-files` plus `mkdocs-literate-nav` with a
  docs-build script that reads the live docstrings via standard-library
  introspection (not `mkdocstrings`, which pyflightstream dropped). The
  generator and the mkdocs tooling live in the docs build tree, are
  never imported by library code (so the NumPy-only rule of core, ops,
  and uncertainty is untouched), and nothing generated is committed, so
  the site cannot drift from the code. ITACA-specific: the SRS chapters
  are authored in markdown for a browsable SRS (pyflightstream's SRS was
  already markdown; ITACA's is LaTeX, so this is a port).

## Conflicts resolved in favor of the SRS

* pydantic models: pyflightstream validates records with pydantic.
  ITACA's `core/`, `ops/`, and `uncertainty/` are NumPy plus stdlib
  only (REQ-82, DD-02), so ITACA uses frozen dataclasses with explicit
  `__post_init__` validation instead.
* Property-based testing: pyflightstream uses deterministic
  closed-form fixtures only. The SRS mandates Hypothesis for math
  kernel contracts (REQ-77), so ITACA uses both: analytic fixtures for
  known answers, Hypothesis for kernel and hash invariants.
* xarray: present in pyflightstream's core dependencies, barred from
  ITACA's core packages (REQ-82). The interoperability boundary
  between the two packages is DD-22 and stays as specified.
