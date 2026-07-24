---
name: audit
description: Retrospective repository health audit for itaca. Sweeps committed files for staleness against the SRS, checks the repo against its adopted external guides, reviews shipped code for structural improvement, and turns every finding into an update, a deletion, or a registered plan item. Use periodically, before every release, and whenever drift is suspected between the SRS, the code, and the public pages.
argument-hint: "[docs|code|full]"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
disable-model-invocation: false
---

Scope: `$ARGUMENTS` (default `full`). `docs` runs pause points 1 to 3,
`code` runs pause point 4, and `full` runs all four. The work is done from expertise,
then verified block by block; treat each pause point as a checklist you
confirm, not a form you fill in. Findings follow one rule: **update or
delete, never leave for later.** A finding that cannot be fixed in the
session becomes a `_private/plan/` item (via `/plan`) with a `ref` and
an owner named; a design question goes to `docs/OPEN_QUESTIONS.md`;
approved scope goes to `docs/M1_EXECUTION_PLAN.md`.

The SRS in `docs/srs/` is the authority: code is audited against the
SRS, and a mismatch is a defect in the code unless the requirement
itself is wrong, in which case it is routed to the author, never patched
silently (CLAUDE.md, "When the SRS and this file disagree").

Output: a dated report in `_private/progress/` (created if absent; the
author reads it on mobile) listing every finding with file:line
evidence, what was fixed in the session with its commit, and what became
a plan item. Fixes to committed files land as one commit per concern.
An audit that ran clean says so; an empty findings list from a real
sweep is information, not a formality.

## Pause point 1: version and metadata truth

1. `pytest tests/test_package.py` passes (the package skeleton and the
   `itc.__version__` contract).
2. Grep the repo for version literals (`0\.\d+\.\d+`) outside
   `pyproject.toml`, `CITATION.cff`, and `CHANGELOG.md`; each hit either
   derives from metadata or is a dated historical record. A hardcoded
   current-version string elsewhere is a finding.
3. A shipped string naming a future version (for example a deprecation
   citing a later release) must have that version present in
   `CHANGELOG.md` (the Unreleased section counts) or the claim is
   unanchored (REQ-94).

## Pause point 2: public-surface currency (docs sweep)

Compare each claim against the code, not against memory:

1. `README.md`: status line, feature list, install and extras, the
   folder map, and the import convention (`import itaca as itc`) against
   what the package actually exports.
2. `examples/`: every example runs. Run them; a reviewer cannot. An
   example that raises is a finding, and it is also the case for adding
   a doctest or CI execution so the failure is caught by machine next
   time rather than by a reader.
3. `CHANGELOG.md`: does the Unreleased section cover everything
   user-visible since the last tag? Cross-check with
   `git diff --stat <last-tag>..HEAD -- itaca/` (the package is the flat
   `itaca/` tree: `core`, `ops`, `uncertainty`, `io`, `utils`).
4. `docs/srs/`: requirement statuses against reality. Anything marked
   stable or implemented names evidence that still exists; anything
   shipped this cycle appears as a requirement or an amendment, with the
   revision history and Chapter 11 moved together. Draft rows get
   special attention (the OQ-18 row of REQ-98 and the M1 draft set
   REQ-104 to REQ-106): a draft implementation frozen without the
   author's confirmation is a finding.
5. `docs/DECISIONS.md` and `docs/OPEN_QUESTIONS.md`: append-only and
   internally consistent. A DD that contradicts itself or a later DD, or
   an OQ marked resolved whose resolution the code does not reflect, is a
   finding. An in-place edit of a frozen entry is a finding on its own.
6. Single-home rule: any fact stated in two places where neither
   generates from a source is a finding; converge on one home and point
   at it. This is the rule the coordination charter exists to protect,
   so a fact restated across CLAUDE.md, the SRS, and a skill is exactly
   the shape to look for.
7. `.claude/skills/*` and `.claude/agents/*`: stale paths, milestone
   maps, folder names, reviewer-seat names, and command examples inside
   every skill and charter file.

## Pause point 3: external-guide conformance

Check against the references adopted in the SRS standards-alignment
chapter (`docs/srs/chapters/08_standards_alignment.tex`):

1. A public MIT PyPI library self-audit: the docs are sufficient without
   installing, the README is complete, the public API is documented, CI
   runs the tests, the license and citation metadata are present, and a
   release matches its tag. Translate each into a concrete check against
   this repo.
2. Packaging and metadata: `pyproject.toml` classifiers, URL labels, and
   license metadata against the current PyPA guidance; run
   `sp-repo-review` when it is available in the environment and turn each
   red check into a finding.
3. For any aspirational item recorded in Chapter 8, ask whether its gate
   has cleared; if so, propose adopting it as a plan item rather than in
   the session.

## Pause point 4: implemented-code review (scope `code` or `full`)

Not a bug hunt (Tier 1 tests and role-review own that); this pass looks
for structural improvement in what already shipped:

1. The NumPy-only rule (REQ-82, DD-02): imports in `core/`, `ops/`, and
   `uncertainty/` against the policy, including deferred imports inside
   functions that dodge the module-level guard. `tests/test_import_policy.py`
   enforces it; a way around it that the test does not cover is a finding,
   and the fix is to extend the test, since the policy guard is a
   denylist and only catches what someone anticipated.
2. Immutability and provenance (REQ-18 for the new object and History,
   REQ-98 for the UncFrame effect, REQ-102 for arrays): every operation
   returns a new object, records itself in History, declares its
   UncFrame effect, and leaves arrays read-only (`writeable=False`). A
   shipped path that mutates in place, skips History, or hands back a
   writeable array is a finding.
3. Error-message contract: every exception derives from `ITACAError` and
   carries the three parts (object involved, operation attempted,
   suggested fix). A message that names a symptom instead of a cause, or
   an exception outside the `ITACAError` tree, is a finding
   (`tests/test_errors.py` is the home for the guard).
4. House style: `tests/test_house_style.py` guards against em and en
   dashes and a dropped LaTeX control sequence in the SRS sources; a new
   file outside its reach, or a British spelling past the American-with-Z
   rule, is a finding worth a guard extension.
5. Tooling-config agreement (REQ-96, REQ-80): the ruff pinned in the
   `[dev]` extra, the pre-commit `rev`, and the ruff in the environment
   agree (`tests/test_tooling_config.py`). A drift here is a finding even
   when CI is green, because it is green by luck.
6. Didactic debt: public callables missing the numpydoc sections
   (Parameters, Returns, Raises, Examples) the SRS requires (REQ-79 for
   Examples), a module top docstring that no longer matches its
   contents, or a docstring whose stated default contradicts the code.
   Documentation-versus-code drift is a real failure class, not a
   formality.
7. Code-smell greps, each a shape seen shipped in a reviewed library:
   mutable default arguments (`= {}` or `= []`) on public signatures;
   bare `except:`; a data-file or environment probe not anchored on
   `__file__` (test it by importing the package from a foreign working
   directory); module-level state mutated inside a function with no
   `global`; a save, restore, or cleanup path with no test asserting the
   restore.
8. Public-surface inventory as data: diff the exported-name list (each
   subpackage `__all__` plus the top-level `itaca` exports) against the
   previous audit's report; an export that appeared or vanished with no
   `CHANGELOG.md` line is a finding.

## Closing

Write the dated report, then close every finding: fix it in the session
(one commit per concern), or register it via `/plan` with a `ref`, or
route it to the author when it needs a non-delegable seat.

Before any push, run the `role-review` skill so the specialist agents
(architect-reviewer, qa-engineer, vv-engineer, tech-writer,
api-designer) review the audit's own commits and write the attestation
that clears the gate (`.claude/hooks/role_review_gate.py`); a paraphrase
does not clear it and must not be written as one.

If the audit uncovered a defect (a guard that let something through, a
validator that reported green on a broken input, a silent corruption),
it is an incident, not just a finding: run the `incident-analyst`
charter, fix it at its structural cause, and give it a guard plus the
evidence that the guard blocks the original failure when re-run.
Documentation is not a guard. An open blocking incident stops the push,
so no audit fix ships on top of a defect whose structural cause is still
unfixed.
