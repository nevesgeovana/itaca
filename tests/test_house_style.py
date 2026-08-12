"""Repository-wide house-style guard (workspace rule; pyflightstream pattern).

No em dashes and no en dashes anywhere, in any tracked text file. The
forbidden characters are constructed from code points so this guard
file itself stays clean.

Also guards the SRS against a dropped LaTeX control sequence, which is
invisible in a green build: a substitution that ate the backslash of
``\\ref`` leaves ``Section~ef{sec:itc-pipe}``, which compiles without a
warning (``\\ref`` was never called, so nothing is undefined) and ships
a document whose own correction notice points nowhere. Every SRS
cross-reference opens a brace on a labeled target, so the guard checks
that each one is reached by a real reference command.

And guards the repository against personal and institutional
identifiers, whose rule and remedy live in ``tests/identifiers.py`` so
that the same implementation also scans the built artifacts in
``tests/test_release_integrity.py`` (DD-41). Four occurrences shipped
past this file because the class was not in it.

Every walk here asks git what belongs to the repository, and then
reports what it scanned. A discovery that silently returns nothing
passes every check vacuously, which is the shape this repository already
refuses for the import policy and for the plan and incident checkers,
both of which now refuse an empty folder rather than reporting a clean
one (`ITC-20260727-1612`); and a walk of the working tree instead
would take its verdict from build output and from one machine's
absolute paths.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import identifiers
import pytest
import yaml
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from gate_locator import ledger_env  # one reader of the gate's ledger variable

DASHES = {chr(0x2014): "em dash", chr(0x2013): "en dash"}
TEXT_SUFFIXES = {
    ".cff",
    ".json",
    ".md",
    ".py",
    # A vendored kit body whose path must NOT end in `.yml`, or GitHub would
    # run it and the release-gate checker would scan it. Every other vendored
    # body is already walked (the `.py` ones by suffix, `release_gate.yml` as
    # `.yml`), and this one arrived exempt by accident rather than by
    # decision. CLAUDE.md states the dash rule with "No exceptions", so the
    # suffix is added here and the path is pinned in `_MUST_REACH` below.
    ".template",
    ".tex",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
EXCLUDED_PARTS = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "_private",
    "htmlcov",
}
_ROOT = Path(__file__).resolve().parents[1]

# One file per top-level tree that ships, so narrowing the walk cannot
# go unnoticed. The earlier version named three files that all sat in
# the scope the guard was being widened OUT of, so adding one word to
# EXCLUDED_PARTS left every assertion satisfied while the walk went
# green on the very commit that shipped the defect.
_MUST_REACH = (
    "itaca/core/provenance.py",
    "tests/core/test_provenance_modes.py",
    "docs/DECISIONS.md",
    "examples/wt_campaign.py",
    ".claude/skills/audit/SKILL.md",
    ".claude/kit/check_release_gate.py",
    # The one vendored kit body whose suffix is neither `.py` nor `.yml`.
    # Pinned by path as well as by suffix because it reached this repository
    # exempt from this walk, and a suffix set is one edit away from losing it
    # again.
    ".github/workflows/release.yml.template",
    ".github/workflows/ci.yml",
    "CLAUDE.md",
    "README.md",
    "pyproject.toml",
)


def _repository_files() -> list[str] | None:
    """Everything git considers part of the repository, or None.

    The union of tracked files and untracked-but-not-ignored ones: the
    first is what the sdist is built from, and the second is a file
    written but not yet added, which a guard must still see. Returns
    None when git cannot answer, where the caller degrades to a
    filesystem walk rather than skipping.

    Both failure shapes return None. A non-zero exit is what an unpacked
    sdist gives, having no checkout; a missing executable RAISES, and an
    unpacked sdist is exactly the place with no git at all, so catching
    only the first would turn the degradation this docstring promises
    into an error in the one case it was written for.
    """
    names: list[str] = []
    for extra in ([], ["--others", "--exclude-standard"]):
        try:
            done = subprocess.run(
                ["git", "ls-files", "-z", *extra],
                capture_output=True,
                cwd=str(_ROOT),
                env=child_env(),
            )
        except OSError:
            return None
        if done.returncode != 0:
            return None
        names += [
            name
            for name in done.stdout.decode(errors="surrogateescape").split("\0")
            if name
        ]
    return names


def _walk(suffixes: set[str] | None = None) -> list[tuple[str, Path]]:
    """Every repository file, as (relative posix, path).

    Asking git rather than the filesystem is what keeps the verdict off
    local state. A working-tree walk read `dist/`, `itaca.egg-info/` and
    `.claude/settings.local.json`, so the result depended on what had
    been built and on one developer's absolute paths, and the artifact
    test in `test_release_integrity` writes two of those DURING the run.
    """
    names = _repository_files()
    if names is None:  # no checkout: an unpacked sdist, for instance
        names = [
            path.relative_to(_ROOT).as_posix()
            for path in _ROOT.rglob("*")
            if path.is_file()
            and not EXCLUDED_PARTS.intersection(path.relative_to(_ROOT).parts)
        ]
    found: list[tuple[str, Path]] = []
    for name in sorted(set(names)):
        path = _ROOT / name
        if not path.is_file():
            continue
        if suffixes is not None and path.suffix not in suffixes:
            continue
        found.append((name, path))
    return found


def _assert_the_walk_reached_the_tree(scanned: list[str], expected: str) -> None:
    """Refuse a walk that found nothing, or that missed a known file."""
    assert len(scanned) >= 50, f"the {expected} walk scanned {len(scanned)} files"
    missing = [name for name in _MUST_REACH if name not in scanned]
    assert not missing, f"the {expected} walk never reached {missing}"


def test_no_em_or_en_dashes_anywhere() -> None:
    offenders: list[str] = []
    scanned = _walk(TEXT_SUFFIXES)
    for relative, path in scanned:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for char, label in DASHES.items():
                if char in line:
                    offenders.append(f"{relative}:{lineno}: {label}")
    _assert_the_walk_reached_the_tree([name for name, _ in scanned], "dash")
    assert not offenders, f"forbidden dash characters found: {offenders}"


#: British spellings this repository has actually written, with the
#: American form the rule requires. It is a MEASURED list and not an
#: attempt at completeness: every entry below is a word that reached a
#: tracked file here and had to be corrected by hand.
#:
#: WHY IT EXISTS AT ALL. `CLAUDE.md` and REQ-87 both require American
#: English with Z, and until lane ITA-15 nothing checked it. An architect
#: lens measured the consequence: the rule was enforced by whoever
#: happened to read the diff, `behaviour` sat in a tracked test file
#: undetected, and the same lane that corrected three files introduced
#: `neighbour` twice while doing it. The dash rule beside this one has had
#: a mechanism since the beginning; this one had prose.
#:
#: A LIST IS THE WRONG SHAPE FOR A LANGUAGE and the right shape for this
#: guard, which is worth stating because the repository prefers discovery
#: to enumeration elsewhere. There is no way to decide Britishness by
#: rule: `analyses` is correct American English and `licence` appears here
#: only as the name of a kit fixture. So this enumerates what has bitten,
#: and grows when something new does, rather than pretending to a coverage
#: it cannot have. It is a floor, and it is stated as one.
BRITISH_SPELLINGS = {
    "behaviour": "behavior",
    "neighbour": "neighbor",
    "colour": "color",
    "organise": "organize",
    "organisation": "organization",
    "visualisation": "visualization",
    "initialise": "initialize",
    "normalise": "normalize",
    "serialise": "serialize",
    "recognise": "recognize",
    "summarise": "summarize",
}


#: Paths this spelling guard does NOT read, each with its reason. Unlike
#: the dash walk, which reaches everything, this one cannot: four
#: categories of file legitimately contain a British spelling, and a guard
#: that demanded an impossible edit in any of them would be turned off.
#: Every exemption below is a file this repository may not, or must not,
#: hand-edit for this reason.
SPELLING_EXEMPT = (
    # DERIVED COPIES. Their standard is the kit master's, and hand-editing
    # one breaks its drift pin with no in-repo remedy, which is the same
    # rule the ruff exclusion states. MEASURED on 2026-08-11: the kit ships
    # `recognise`, `behaviour` and `neighbour` across nine vendored bodies,
    # so this is not a hypothetical exemption. Routed to the coordination
    # level rather than absorbed.
    ".claude/kit/",
    ".claude/hooks/",
    ".claude/skills/version-control/",
    # THE REQUIREMENT THAT FORBIDS THEM. REQ-87 enumerates the British
    # forms in order to reject them ("organize (not organise)"), so a guard
    # reading it finds every word it is looking for, by design.
    "docs/srs/chapters/07_non_functional_requirements.tex",
    # FROZEN AND APPEND-ONLY. A decision entry freezes at the commit that
    # ships it, so the remedy for a British spelling inside one is a
    # superseding entry, never an edit. DD-55 records exactly that for
    # DD-54's own instance.
    "docs/DECISIONS.md",
    # THIS MODULE, which has to name the words it forbids. The same
    # self-reference the dash note in `tests/test_kit_drift.py` records for
    # the em dash it deliberately does not quote.
    "tests/test_house_style.py",
)


def test_no_british_spelling_in_a_repository_owned_file() -> None:
    """American English with Z, mechanically, for the words that have bitten.

    `CLAUDE.md` states the rule and REQ-87 makes it normative. This is the
    mechanism, added by lane ITA-15 after an architect lens measured that
    there was none: the rule was enforced by whoever happened to read the
    diff, `behaviour` sat undetected in a tracked test file, and the lane
    that corrected three files introduced `neighbour` twice while doing it.

    WHAT IT DOES NOT COVER is `SPELLING_EXEMPT` above, and the largest
    entry there is the vendored kit, which really does ship these words.
    So this guard is a floor over the files this repository OWNS, and it is
    stated as one rather than described as a house-wide rule it does not
    enforce.

    Case-insensitive, because the two that bit here were `BEHAVIOUR` in
    upper case and `neighbour` in lower.
    """
    offenders: list[str] = []
    scanned = [
        (relative, path)
        for relative, path in _walk(TEXT_SUFFIXES)
        if not relative.startswith(SPELLING_EXEMPT)
    ]
    for relative, path in scanned:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for british, american in BRITISH_SPELLINGS.items():
                if british in lowered:
                    offenders.append(
                        f"{relative}:{lineno}: {british!r}, write {american!r}"
                    )
    # The walk must still have reached a real tree; the exemptions above
    # remove specific paths, not the repository.
    assert len(scanned) >= 50, (
        f"the spelling walk scanned {len(scanned)} files after exemptions, "
        f"which is too few to be reading the repository at all."
    )
    assert not offenders, (
        f"British spellings found in repository-owned files: {offenders}. "
        f"CLAUDE.md and REQ-87 require American English with Z. If you believe "
        f"the file is exempt, add it to SPELLING_EXEMPT with its reason rather "
        f"than widening the word list."
    )


#: Clauses of the BRF-082 wording, which is shared VERBATIM with the sister
#: repository. Fragments rather than the whole text: this asserts the rule is
#: present and un-trimmed, and it is not a second copy of the paragraph.
#:
#: FRAGMENTS ALONE WERE NOT ENOUGH, measured in ITA-17 round one. A QA lens
#: applied four material inversions that every fragment survived, because
#: each is searched anywhere in the file: reversing "runs BEFORE the claim"
#: to after, negating clause 2 to "need not go RED", deleting the CLI
#: flag-precedence half of clause 3, and deleting the whole "Report the
#: findings ALONGSIDE the implementation" paragraph. Two fragments were
#: added for the last two, and `_ADVERSARIAL_BLOCK_SHA256` below is what
#: closes the class rather than those two instances.
_ADVERSARIAL_CLAUSES = (
    "adversarial pass runs",
    "BEFORE the claim",
    "asserted PRESENT and UNIQUE",
    "go RED when the code it covers is sabotaged",
    "flags its case needs",
    "real precedence",
    "names ONLY properties this run evaluated",
    "PRINTED as unreached",
    "TRIED to break and could not",
    "ALONGSIDE the implementation",
)

#: The whole shared block, hashed. NOT a second copy of the text: a hash
#: cannot be read as the rule, so it creates no drift risk of its own, and
#: it is exactly what a verbatim requirement needs. Any edit inside the
#: block fails, which is the point: this text may only change at the
#: coordination level and arrive here by brief.
#:
#: Recomputed by the same slice this test takes, on 2026-08-11.
_ADVERSARIAL_BLOCK_SHA256 = (
    "9635a970b85dc04d79734233c2a20007fdab5090f7c38a00918a22c2afc5ec02"
)
_ADVERSARIAL_START = "## The adversarial pass is a precondition, not a round"
_ADVERSARIAL_END = "### Where this wording comes from"


def test_the_adversarial_pass_rule_is_present_in_both_of_its_places() -> None:
    """BRF-082 lives in two files, and the split is the point.

    The author's decision of 2026-08-11 corrected this brief's own first
    proposal, which put the rule in the `role-review` skill alone. A skill
    loads WHEN IT IS INVOKED, which is exactly the load-time failure the
    same morning had measured: a precondition that only exists once someone
    remembers to invoke something is not a precondition. So `CLAUDE.md`,
    which loads always, POINTS, and the skill carries the reasoning.

    This asserts both halves, because either alone fails differently and
    silently: the pointer without the wording sends a reader nowhere, and
    the wording without the pointer is never read at the moment it applies.

    ADDED BY THE RULE'S OWN FIRST APPLICATION. Lane ITA-17 ran the hostile
    pass over its own diff before claiming the work done, and one of the
    attacks it recorded was deleting this pointer from `CLAUDE.md`, which
    no test noticed. This is that finding fixed rather than reported.

    The clause list is fragments, not the paragraph. Restating the wording
    here would create the second copy the brief exists to prevent, and the
    fragments are what catches a clause quietly trimmed as boilerplate,
    which is the failure mode the brief names.
    """
    charter = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    skill = (_ROOT / ".claude" / "skills" / "role-review" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "adversarial pass is a PRECONDITION" in charter, (
        "CLAUDE.md carries no pointer to the adversarial-pass rule. That file "
        "loads always and the skill does not, so without the pointer the rule "
        "only exists once someone invokes role-review, which is the failure "
        "the author's decision of 2026-08-11 corrected (BRF-082)."
    )
    assert "role-review/SKILL.md" in charter, (
        "the CLAUDE.md pointer does not name the file carrying the wording, so "
        "a reader who follows it arrives nowhere."
    )
    missing = [clause for clause in _ADVERSARIAL_CLAUSES if clause not in skill]
    assert not missing, (
        f"the role-review skill is missing {len(missing)} clause(s) of the "
        f"BRF-082 wording: {missing}. The text is shared VERBATIM with the "
        f"sister repository and every clause is a defect this project shipped, "
        f"so none is boilerplate. If it must change, it changes at the "
        f"coordination level and arrives here by brief."
    )
    # THE BLOCK ITSELF, hashed, which is what makes "verbatim" mechanical.
    # The fragment list above catches a clause deleted wholesale; it does
    # NOT catch a clause negated, reordered or half-removed, which a QA lens
    # demonstrated four times over in ITA-17 round one.
    normalized = skill.replace("\r\n", "\n").replace("\r", "\n")
    assert _ADVERSARIAL_START in normalized and _ADVERSARIAL_END in normalized, (
        f"the role-review skill no longer carries both markers bounding the "
        f"shared block ({_ADVERSARIAL_START!r} .. {_ADVERSARIAL_END!r}), so "
        f"the verbatim check below cannot run and would pass vacuously."
    )
    block = normalized[
        normalized.index(_ADVERSARIAL_START) : normalized.index(_ADVERSARIAL_END)
    ].strip()
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
    assert digest == _ADVERSARIAL_BLOCK_SHA256, (
        f"the shared BRF-082 block hashes to {digest}, not the pinned "
        f"{_ADVERSARIAL_BLOCK_SHA256}. This text is VERBATIM across two "
        f"repositories, so it may not be edited here at all, not even to "
        f"improve it: two independently drafted versions of one rule diverge "
        f"inside a month. Change it at the coordination level and re-adopt by "
        f"brief, then move this pin in the same commit."
    )


# Every cross-reference in the SRS opens a brace on a labeled target.
# The failure this catches is a substitution that wrote "\ref" into a
# non-raw Python string: "\r" is a carriage return, so the command
# collapses to "ef{sec:...}", which LaTeX typesets literally and never
# warns about, because \ref was never invoked and nothing is undefined.
_LABEL_USE = re.compile(r"\{(?:sec|ch|tab|fig|eq|app):")
_REFERENCING_COMMANDS = (
    "\\ref{",
    "\\eqref{",
    "\\label{",
    "\\pageref{",
    "\\autoref{",
    "\\cref{",
    "\\nameref{",
)


def test_every_srs_label_is_reached_by_a_real_latex_command() -> None:
    root = _ROOT / "docs" / "srs"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.tex")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _LABEL_USE.finditer(line):
                head = line[: match.start() + 1]
                if not head.endswith(_REFERENCING_COMMANDS):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()[:70]}")
    assert not offenders, f"label reached without a reference command: {offenders}"


# Two accepted wordings, not one, because two authors write these charters.
# itaca's own three say FORBIDDEN; the kit's incident-analyst master says
# "may NEVER use it to mutate git state". Matching one exact sentence is what
# forced a by-name exemption for the vendored charter even after the kit
# shipped the rule, so the guard matches the RULE in either wording and the
# exemption is gone.
#
# Each wording is paired with the SECTION HEADING it must appear under. A
# reviewer measured the sentence alone as satisfiable by prose that negates
# it: "you are not FORBIDDEN to run any command that mutates git state"
# passed. Requiring the heading too does not make the check airtight, and
# nothing short of reading the charter would, but it removes the two forms an
# ordinary edit can produce: a negation, and a passing mention of the rule
# in text that is about something else.
_PROHIBITIONS = (
    (
        "## Bash is granted to observe, and never to mutate git state",
        "You are FORBIDDEN to run any command that mutates git state.",
    ),
    (
        "## You hold Bash, and you may NEVER use it to mutate git state",
        "you may NEVER use it to mutate git state",
    ),
)
# Words that turn the sentence into its opposite while leaving every pinned
# token in place. Measured: "You are not FORBIDDEN to run any command that
# mutates git state." passed a version of this guard that matched the
# predicate alone, so the subject is now part of the pinned phrase AND the
# text immediately before it is checked. Neither is airtight; together they
# remove the forms an ordinary edit produces.
_NEGATIONS = ("not", "never", "no longer", "untrue", "unless")
# The Bash-holding seats today: the three PUSH lenses and the vendored
# analyst. Asserted as a SET rather than a count, so a charter that stops
# granting Bash fails with "the roster changed" instead of with the
# anti-vacuity message, which is a different cause and was the advice the
# sibling assertion gave.
_BASH_HOLDERS = frozenset(
    {
        "architect-reviewer.md",
        "incident-analyst.md",
        "qa-engineer.md",
        "vv-engineer.md",
    }
)


def _charter_tools(text: str) -> list[str]:
    """The frontmatter ``tools:`` list of an agent charter."""
    for line in text.splitlines():
        if line.startswith("tools:"):
            return [item.strip() for item in line[len("tools:") :].split(",")]
    return []


def _charter_field(text: str, key: str) -> str | None:
    """One scalar frontmatter field of an agent charter, or None."""
    for line in text.split("---", 2)[1].splitlines():
        if line.startswith(f"{key}:"):
            return line[len(key) + 1 :].strip()
    return None


# The five GATED reviewer seats, named rather than globbed. A glob would
# make this guard agree with whatever is on disk, which is the opposite of
# pinning: deleting a charter would satisfy it.
_GATED_REVIEWERS = (
    "architect-reviewer",
    "qa-engineer",
    "vv-engineer",
    "tech-writer",
    "api-designer",
)
# Kit-derived, and therefore deliberately NOT pinned here. Its body is tied
# byte for byte to the stamped of-record copy under `.claude/kit` by
# `tests/test_kit_drift.py`, so adding frontmatter to it by hand would
# redden that test. Its pin lands in the kit master and arrives by
# re-vendor, which is the same rule that sent five other kit-body defects
# upward rather than into a local edit.
_KIT_DERIVED_CHARTER = "incident-analyst"


def test_the_gated_reviewers_pin_their_model_and_effort() -> None:
    """Author decision 11 (BRF-064, 2026-07-30), installed and falsifiable.

    WHY THE PIN EXISTS: independence. Without it a reviewer inherits the
    IMPLEMENTING session's model, so the review follows whatever the
    session happened to be running, and a lane on a weaker model reviews
    its own work with a weaker reviewer exactly when that matters most.

    WHY IT IS A TEST: this repository holds that a rule with no guard is
    documentation. The decision was taken and documented on 2026-07-30 and
    was then described to a lane as already installed here when no charter
    carried it (`ITC-20260730-2145`). A frontmatter key is deleted by
    accident more easily than prose is, and nothing else would notice.

    BOTH DIRECTIONS ARE PINNED, and the second is the load-bearing one:
    `incident-analyst` is a kit-derived body whose runtime copy must
    match its stamped of-record copy byte for byte, so its pin may only
    ARRIVE BY RE-VENDOR and never by a local edit. This guard used to
    say that by requiring the field to be ABSENT, which was right while
    the kit master carried no pin. Kit 0.2.11 added `model: opus` and
    `effort: low` to that master and itaca adopted it on 2026-08-01, so
    the absence rule would now refuse the very thing it told the reader
    to do.

    The requirement it becomes is the same one, stated against the
    source instead of against the value: the runtime charter carries the
    pin AND the stamped of-record copy carries the identical pin. A hand
    edit cannot satisfy both. Touch the runtime alone and
    `test_the_runtime_agent_body_matches_the_of_record_copy` fails;
    touch both and the of-record body hash stops matching the kit
    manifest. So "by re-vendor, not by hand" is still what is enforced,
    and it no longer depends on the master staying silent forever.

    NOT PINNED HERE: the effort VALUE as a permanent choice. The author's
    falsifiable safeguard is that if findings per review drop after the
    effort pin, the RELEASE tier returns to `effort: high` by her decision.
    That is a measurement against the counts already written into review
    records, not a rule this file should freeze. If the value moves by her
    decision, move it here too; the guard exists so the move is deliberate.
    """
    agents = _ROOT / ".claude" / "agents"
    for name in _GATED_REVIEWERS:
        path = agents / f"{name}.md"
        assert path.is_file(), (
            f"the gated reviewer charter {path} is missing, so the "
            f"role-review skill cannot run that pass at all."
        )
        text = path.read_text(encoding="utf-8")
        for key, want in (("model", "opus"), ("effort", "low")):
            got = _charter_field(text, key)
            assert got == want, (
                f"{path.name} declares {key}: {got!r}, not {want!r}. Author "
                f"decision 11 (BRF-064) pins the five gated reviewers so a "
                f"review does not inherit the implementing session's model. "
                f"If she moved the value, move it in this guard too."
            )
    kit_charter = (agents / f"{_KIT_DERIVED_CHARTER}.md").read_text(encoding="utf-8")
    of_record = (_ROOT / ".claude" / "kit" / f"{_KIT_DERIVED_CHARTER}.md").read_text(
        encoding="utf-8"
    )
    for key, want in (("model", "opus"), ("effort", "low")):
        runtime_value = _charter_field(kit_charter, key)
        assert runtime_value == want, (
            f"{_KIT_DERIVED_CHARTER}.md declares {key}: {runtime_value!r}, not "
            f"{want!r}. Kit 0.2.11 carries this pin in the master; if it is "
            f"missing here the re-vendor was partial, and the fix is to "
            f"re-vendor from the kit rather than to add the field by hand."
        )
        assert _charter_field(of_record, key) == want, (
            f"the runtime {_KIT_DERIVED_CHARTER}.md declares {key}: "
            f"{runtime_value!r} and the stamped of-record copy under "
            f".claude/kit does not. That is a HAND EDIT to a kit-derived "
            f"body: the pin must arrive by re-vendor, so that the of-record "
            f"copy's hash still matches the kit manifest."
        )


def test_every_bash_holding_charter_carries_the_git_prohibition() -> None:
    """Bind the capability to the restriction, instead of trusting prose.

    ``INC-20260729-2355-itaca``. A reviewer agent holding ``Bash`` ran a git
    restore while a lane carried uncommitted review fixes and silently reverted
    two files of nine, losing three edits. The prohibition that answers it was
    written into three charters by hand, and three reviewers independently
    raised the same objection: this repository's incident rule says
    documentation is not a guard, so a re-vendor, a reformat, or a new seat
    granting ``Bash`` tomorrow drops the section with no signal. Measured at
    the time: the prohibition was in three of the FOUR local charters holding
    ``Bash``.

    So the invariant is mechanical from here: hold ``Bash``, carry the
    prohibition. A new reviewer seat inherits it by failing this test rather
    than by someone remembering.

    NO CHARTER IS EXEMPT ANY MORE, and the removal of the exemption is the
    point. ``incident-analyst.md`` was exempted BY NAME while it was a
    vendored kit body carrying ``Bash`` without the rule, since itaca cannot
    hand-edit a hash-pinned copy. Kit 0.2.10 shipped the rule to that master,
    adopted here, so the gap is closed at its source and
    ``ITC-20260730-0180`` is done.

    The exemption did not notice that, which is the lesson worth keeping: it
    tested only that the exempt name was still a Bash-holding vendored
    charter, never that the exemption was still NECESSARY, so it stayed green
    through the very promotion its own failure message told the reader to
    watch for. The kit writes the rule in different words from itaca's three
    charters, so an exact-sentence match would have kept the exemption alive
    on wording alone. Both wordings are accepted above, and a charter holding
    ``Bash`` with neither now fails whoever owns it.
    """
    charters = sorted((_ROOT / ".claude" / "agents").glob("*.md"))
    assert len(charters) >= 5, (
        f"only {len(charters)} agent charters were found under "
        f"{_ROOT / '.claude' / 'agents'}; a walk that finds nothing would "
        f"otherwise report green."
    )
    holders: set[str] = set()
    offenders: list[str] = []
    negated: list[str] = []
    for path in charters:
        text = path.read_text(encoding="utf-8")
        if "Bash" not in _charter_tools(text):
            continue
        holders.add(path.name)
        carried = [
            (head, rule)
            for head, rule in _PROHIBITIONS
            if head in text and rule in text
        ]
        if not carried:
            offenders.append(path.name)
            continue
        # The pinned sentence is present. Is it still a prohibition? A
        # negation word in the clause immediately before it inverts the
        # meaning while every token this guard reads stays put.
        for _, rule in carried:
            head_text = text[: text.index(rule)]
            clause = head_text.rsplit(".", 1)[-1].lower()
            if any(word in clause.split() for word in _NEGATIONS):
                negated.append(f"{path.name}: ...{clause.strip()[-40:]!r}")
    assert not offenders, (
        f"these charters grant Bash without carrying the git-mutation "
        f"prohibition, under its own section heading, in any accepted "
        f"wording: {offenders}. A lens that can execute can destroy "
        f"uncommitted work, which is INC-20260729-2355-itaca. Add the section, "
        f"or remove Bash from the charter. For a VENDORED charter the fix "
        f"belongs to the kit and the copy may not be hand-edited: route it up "
        f"and re-vendor (ITC-20260730-0180 is the precedent)."
    )
    assert not negated, (
        f"a charter carries the prohibition sentence with a negation in the "
        f"clause before it, so the pinned text is present and the rule is "
        f"reversed: {negated}. This is the shape a phrase-matching guard "
        f"cannot see and it is why the subject is part of the pinned phrase."
    )
    # The roster, so an empty or shrunken walk cannot green this. Asserted as
    # a set and not a count, so removing Bash from a charter (which the
    # message above offers as a fix) fails HERE with its own cause named
    # instead of being reported as a broken frontmatter parse.
    assert holders == set(_BASH_HOLDERS), (
        f"the set of Bash-holding charters is {sorted(holders)}, where "
        f"{sorted(_BASH_HOLDERS)} is recorded. If a seat gained or lost Bash "
        f"deliberately, update _BASH_HOLDERS in the same commit. If this is "
        f"empty or short, _charter_tools stopped parsing the frontmatter and "
        f"the assertion above proves nothing."
    )


_SRS_VERSION_SITES = (
    # Deliberately unanchored. The anchored form matched ZERO times, because
    # the file is CRLF and `$` sits before the carriage return, and a pattern
    # matching nothing is how a guard like this goes vacuous. The `== 1`
    # assertion below is what caught it.
    ("docs/srs/main.tex", re.compile(r"% Version (\d+\.\d+\.\d+), Living Document")),
    (
        "docs/srs/main.tex",
        re.compile(
            r"pdftitle=\{ITACA Software Requirements Specification v(\d+\.\d+\.\d+)\}"
        ),
    ),
    (
        "docs/srs/main.tex",
        re.compile(r"\\textit\{Document version\} & \\textbf\{(\d+\.\d+\.\d+)\}"),
    ),
    (
        "docs/srs/README.md",
        re.compile(
            r"Authoritative specification of ITACA, document version (\d+\.\d+\.\d+)"
        ),
    ),
    (
        "CLAUDE.md",
        re.compile(r"the authoritative specification \(document (\d+\.\d+\.\d+)"),
    ),
    ("docs/M1_EXECUTION_PLAN.md", re.compile(r"Authority: SRS (\d+\.\d+\.\d+)")),
    # The NEWEST revision-history row, which is not a live declaration but
    # must agree with them: a bump with NO revision entry is exactly the
    # partial change the workspace rule ("revision history plus Chapter 11
    # updated together") is written against, and the six sites above cannot
    # see it. Anchored to the first data row after the doubled \midrule, so
    # it reads the newest entry and not every historical one.
    (
        "docs/srs/frontmatter/revision_history.tex",
        re.compile(r"\\midrule\s*\\midrule\s*(\d+\.\d+\.\d+) &"),
    ),
)
# The floor, so deleting a tuple entry cannot quietly narrow the guard. The
# import policy discovers rather than enumerates for exactly this reason;
# here the sites are genuinely heterogeneous (three LaTeX shapes, three prose
# shapes, one table row), so the list stays explicit and the count is pinned
# instead.
_SRS_VERSION_SITE_COUNT = 7

# The DATE of the current revision, wherever it is declared. Separate
# from the version sites above because the shapes differ and because the
# lesson is separate: pinning the version alone was measured
# insufficient. A bump moved all seven version sites and left three of
# them dated 2026-07-31 with 0.2.9's title, so the title page was dated a
# day before the revision it contained and the README advertised the
# previous revision's subject, while this guard was green.
#
# `main.tex` writes a long date and everything else writes ISO, so each
# site declares how to normalize what it captured.
#
# The last field says how many times the pattern may match. `"once"` is a
# live declaration and a second match means the pattern is loose;
# `"newest"` is a per-revision record whose FIRST match is the current
# one, and demanding uniqueness there would just be wrong (Chapter 11
# carries a section per revision, thirteen of them today). Both still
# refuse ZERO matches, which is the way a guard like this goes vacuous.
_SRS_DATE_SITES = (
    (
        "docs/srs/main.tex",
        re.compile(r"\\textit\{Date\}\s*& \\textbf\{([A-Z][a-z]+ \d+, \d{4})\}"),
        "long",
        "once",
    ),
    (
        "docs/srs/README.md",
        re.compile(r"document version \d+\.\d+\.\d+\s*\n\((\d{4}-\d\d-\d\d),"),
        "iso",
        "once",
    ),
    (
        "CLAUDE.md",
        re.compile(r"\(document \d+\.\d+\.\d+,\s*\n\s*(\d{4}-\d\d-\d\d);"),
        "iso",
        "once",
    ),
    (
        "docs/srs/frontmatter/revision_history.tex",
        re.compile(r"\\midrule\s*\\midrule\s*\d+\.\d+\.\d+ & (\d{4}-\d\d-\d\d) &"),
        "iso",
        "once",
    ),
    (
        "docs/srs/chapters/11_changelog.tex",
        re.compile(r"\\section\*\{Document \d+\.\d+\.\d+, (\d{4}-\d\d-\d\d),"),
        "iso",
        "newest",
    ),
)
_SRS_DATE_SITE_COUNT = 5


def _as_iso(value: str, shape: str) -> str:
    """Normalize a captured date to ISO, so the shapes can be compared."""
    if shape == "iso":
        return value
    return datetime.strptime(value, "%B %d, %Y").date().isoformat()


def test_every_document_dating_the_srs_revision_dates_it_the_same_day() -> None:
    """One revision, one date, in all five places that state it.

    The companion to the version guard below, and it exists because
    pinning the version alone was measured insufficient. Lane ITA-4
    bumped 0.2.9 to 0.2.10 across all seven version sites and left the
    title page reading `July 31, 2026`, the SRS README reading
    `2026-07-31` with 0.2.9's subtitle, and `CLAUDE.md` reading
    `2026-07-31`, while the revision history and Chapter 11 both said
    `2026-08-01`. Three statements of one fact, wrong, in the
    authoritative document, with every existing guard green: the built
    PDF was dated a day before the revision it contained.

    A date is not a version, so it needs its own list; what it shares
    with the version is that a partial edit is the failure mode, and a
    partial edit is only visible to something that reads the sites
    together.
    """
    assert len(_SRS_DATE_SITES) == _SRS_DATE_SITE_COUNT, (
        f"_SRS_DATE_SITES holds {len(_SRS_DATE_SITES)} entries, where "
        f"{_SRS_DATE_SITE_COUNT} is recorded; deleting one narrows this guard "
        f"silently."
    )
    found: dict[str, list[str]] = {}
    for relative, pattern, shape, cardinality in _SRS_DATE_SITES:
        text = (_ROOT / relative).read_text(encoding="utf-8")
        matches = pattern.findall(text)
        assert matches, (
            f"{relative}: the revision-date pattern {pattern.pattern!r} matched "
            f"nothing, which is how this guard goes vacuous."
        )
        if cardinality == "once":
            assert len(matches) == 1, (
                f"{relative}: the revision-date pattern matched {len(matches)} "
                f"times where one live declaration is expected; the pattern is "
                f"too loose to say which date is current."
            )
        found.setdefault(_as_iso(matches[0], shape), []).append(relative)
    assert len(found) == 1, (
        f"the SRS revision is dated differently in different places: "
        f"{ {date: sites for date, sites in found.items()} }. The revision "
        f"history and Chapter 11 are the record; the title page, the SRS "
        f"README and CLAUDE.md must agree with them."
    )

    # The date and the version are ONE record, and asserting each set is
    # self-consistent does not say they belong together. A bump that
    # moved all seven version sites and no date site would satisfy both
    # guards while dating the new revision to the old one's day, which is
    # the same partial edit that produced this guard, with the halves
    # swapped. So the two records that carry BOTH are read as pairs.
    changelog = (_ROOT / "docs/srs/chapters/11_changelog.tex").read_text(
        encoding="utf-8"
    )
    history = (_ROOT / "docs/srs/frontmatter/revision_history.tex").read_text(
        encoding="utf-8"
    )
    paired = re.search(
        r"\\section\*\{Document (\d+\.\d+\.\d+), (\d{4}-\d\d-\d\d),", changelog
    )
    row = re.search(
        r"\\midrule\s*\\midrule\s*(\d+\.\d+\.\d+) & (\d{4}-\d\d-\d\d) &", history
    )
    assert paired is not None and row is not None
    assert paired.groups() == row.groups(), (
        f"Chapter 11's newest section is {paired.groups()} and the newest "
        f"revision-history row is {row.groups()}. They are two records of one "
        f"revision and must name the same version AND the same date."
    )
    current_date = next(iter(found))
    assert paired.group(2) == current_date, (
        f"the newest Chapter 11 section is dated {paired.group(2)} and the "
        f"live declarations say {current_date}."
    )

    # The "newest" cardinality above takes the FIRST match, which is only
    # the current revision because Chapter 11 is written newest-first.
    # Nothing said so, and a section appended at the bottom would make
    # this guard compare against an old date and fail with a message
    # about disagreement rather than about ordering.
    dated = re.findall(
        r"\\section\*\{Document \d+\.\d+\.\d+, (\d{4}-\d\d-\d\d),", changelog
    )
    assert dated == sorted(dated, reverse=True), (
        f"Chapter 11's sections are no longer newest-first: {dated}. The date "
        f"guard reads the first section as the current revision, so a section "
        f"appended at the bottom silently changes what it checks."
    )


def test_every_document_naming_the_srs_version_names_the_same_one() -> None:
    """One SRS document version, stated in seven places, agreeing.

    ``ITC-20260730-0165``. Four documents named four different versions at
    once (0.2.2, 0.2.1, 0.2.0, 0.2.0), because the workspace rule that every
    normative change increments the document version was documentation only:
    nothing read these sites together, so a partial bump was caught by
    nothing and each amendment could leave a different subset behind.

    Repairing the content is not the fix. The rule needs a mechanism, or the
    next amendment diverges the same way, which is the shape this repository
    refuses everywhere else.

    WHAT IS AND IS NOT A SITE, since the distinction is the rule a future
    author needs. A site is a LIVE declaration of the current version, and
    all six of those are here. The newest revision-history ROW is here too,
    though it is a record rather than a declaration, because a bump with no
    revision entry is the partial change the workspace rule most cares about
    and no live site can see it. Everything else that names a version is a
    DATED REFERENCE to a past one, and belongs nowhere near this list: the
    older revision-history rows, every Chapter 11 section, and the version
    citations in ``CHANGELOG.md`` and ``docs/OPEN_QUESTIONS.md``.

    This does NOT check that a normative change was accompanied by a bump,
    which is the other half of ``ITC-20260730-0165`` and needs a definition
    of "normative change" that the document does not yet give.
    """
    assert len(_SRS_VERSION_SITES) == _SRS_VERSION_SITE_COUNT, (
        f"_SRS_VERSION_SITES holds {len(_SRS_VERSION_SITES)} entries, where "
        f"{_SRS_VERSION_SITE_COUNT} is recorded. Deleting one narrows this "
        f"guard silently, which is how the divergence it exists to catch got "
        f"in. Add or remove the count in the same commit, with the reason."
    )
    found: dict[str, list[str]] = {}
    for relative, pattern in _SRS_VERSION_SITES:
        text = (_ROOT / relative).read_text(encoding="utf-8")
        matches = pattern.findall(text)
        assert len(matches) == 1, (
            f"{relative}: the SRS version pattern {pattern.pattern!r} matched "
            f"{len(matches)} times, expected once. A pattern that matches "
            f"nothing makes this guard vacuous, so it fails rather than "
            f"skipping the site (ITC-20260730-0165)."
        )
        found.setdefault(matches[0], []).append(relative)
    assert len(found) == 1, (
        f"the SRS document version is stated inconsistently across the "
        f"documents that name it: {found}. Every normative SRS change "
        f"increments the version, and every one of these sites moves with it "
        f"(ITC-20260730-0165)."
    )


def test_one_ledger_variable_is_named_by_the_gate_and_by_the_locator_table() -> None:
    """The gate, the vendored charter and CLAUDE.md name ONE variable.

    Author decision LEDGER-ENVVAR made ``COORD_INCIDENT_LEDGER`` the single
    name for every workspace sharing the incident ledger. Kit 0.2.8 carried it
    into the push gate, together with the change that matters more: an ABSENT
    ledger denies rather than reading as does-not-apply.

    This test began life pinning a DIVERGENCE. itaca ran kit 0.2.6 while the
    vendored charter had already moved to 0.2.10, so for a day the gate read
    the old name and, worse, could FAIL OPEN: on a clone that configured
    nothing, the incident half of the gate did not gate. Both are closed by
    the 0.2.8 re-vendor (``ITC-20260730-0215``), so the assertion is now a
    convergence: whatever literal the gate assigns to ``LEDGER_ENV`` is the
    one variable the locator table declares, and no other.

    Reading the literal OUT of the gate is the load-bearing part. Asserting a
    name would pass in the state that actually misconfigures a clone, which is
    the gate renamed and the table not, and a substring test over the row
    passed for EITHER name while the row mentioned both. Falsified in three
    directions: the gate renamed alone, the table renamed alone, and a second
    variable name smuggled into the row.

    The refusal itself is pinned by ``tests/test_push_gate.py``; this pins
    that the documentation a reader configures from cannot drift from it.
    """
    charter = (_ROOT / ".claude" / "agents" / "incident-analyst.md").read_text(
        encoding="utf-8"
    )
    claude_md = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    # Read the gate's variable out of the gate rather than asserting a
    # literal. Asserting a name would pass in the one state that actually
    # misconfigures a clone: the gate renamed and the locator table not.
    #
    # Through `tests/gate_locator.py`, which tests/test_push_gate.py also
    # uses. This module had its own unanchored regex and that one its own
    # anchored one; they agreed until a kit body mentioned a retired name in
    # an indented comment, at which point the unanchored reader would match
    # the comment and this test's failure message would prescribe renaming
    # the locator table to match it.
    reads = ledger_env()
    # Whatever the gate reads must be the variable CLAUDE.md's locator table
    # declares, so the two cannot be renamed apart in either direction. The
    # row is found by the guard file it names.
    table_row = [
        line
        for line in claude_md.splitlines()
        if line.lstrip().startswith("|") and "role_review_gate.py" in line
    ]
    assert len(table_row) == 1, (
        f"expected exactly one locator-table row naming role_review_gate.py "
        f"in CLAUDE.md, found {len(table_row)}. The table is where a reader "
        f"configures the variable, so this test needs to find it "
        f"(ITC-20260730-0215)."
    )
    # EXACT, not a substring of the row. A substring test passed for EITHER
    # name while the row mentioned both, which is the state that misconfigures
    # a clone: the gate renamed and the row not.
    declared_names = re.findall(r"`([A-Z_]+_LEDGER)`", table_row[0])
    assert declared_names == [reads], (
        f"the push gate resolves {reads} and CLAUDE.md's locator-table row "
        f"declares {declared_names}: {table_row[0].strip()!r}. The row must "
        f"name exactly the one variable the gate reads, so the two cannot be "
        f"renamed apart. If a later kit version renamed it again, the remedy "
        f"is to re-vendor and move this row, the Incidents section, "
        f".claude/skills/plan/SKILL.md, tests/test_kit_drift.py and "
        f"tests/test_plan_validator.py together; tests/test_push_gate.py and "
        f"this test read the name out of the gate and need no edit "
        f"(ITC-20260730-0215)."
    )
    # And the vendored charter names the same one, so a future kit version that
    # moved only one of the two is caught here rather than by a reader.
    assert reads in charter, (
        f"the push gate resolves {reads} and the vendored incident-analyst "
        f"charter does not name it, so the analyst and the gate would read "
        f"different variables. The charter is a kit body and may not be "
        f"hand-edited: route the divergence up and re-vendor "
        f"(ITC-20260730-0215 is the precedent)."
    )
    # THE UNSET SEMANTICS, not only the name. The name is what a reader
    # exports; the Unset cell is what tells them whether they may skip it, and
    # this is the one member of the family whose absence is a refusal. Pinning
    # the name alone left the cell free to revert to "check does not apply,
    # silently" with the suite green, which a reviewer measured: the row and
    # the two prose statements would then have said opposite things and the
    # reader who trusted the row would have believed the gate was optional.
    cells = [cell.strip() for cell in table_row[0].strip().strip("|").split("|")]
    assert len(cells) == 6, (
        f"the locator-table row for the gate has {len(cells)} cells, expected "
        f"six (Variable, Names, Unset, Set but invalid, Mechanism, Guard): "
        f"{cells}. This test reads the third."
    )
    assert "DENIES" in cells[2], (
        f"the locator table's Unset cell for {reads} reads {cells[2]!r}, which "
        f"does not say the push gate DENIES. Since kit 0.2.8 an absent ledger "
        f"is a refusal, not a skip, and the table is where a reader decides "
        f"whether configuring it is optional. If the kit reverted to the "
        f"fail-open branch, that is the finding, not this cell "
        f"(ITC-20260730-0215)."
    )
    # And the prose must not contradict the cell. The sentence below was in
    # this file's Incidents section while the row said the opposite.
    assert "Unset never blocks" not in claude_md, (
        "CLAUDE.md carries the sentence 'Unset never blocks a clone that "
        "configured nothing', which is false of COORD_INCIDENT_LEDGER and is "
        "exactly the sentence a reader would use to talk themselves out of the "
        "denial the locator table states. Spell the three unset meanings out "
        "per row instead of generalizing over the family."
    )


def test_both_workflows_build_the_srs_and_check_the_log() -> None:
    """Pin the build itself, so deleting it cannot reopen the P0 in silence.

    ``ITC-20260730-0010`` is "nothing compiles the specification, so a broken
    document is indistinguishable from a working one". The remedy is a CI job,
    and a remedy that is one deletion away from gone with the suite green is
    the shape this repository refuses. A reviewer raised exactly that: no test
    parsed the workflow for it, though two other tests already parse the same
    file for other properties.

    Three properties. The build must actually run latexmk over ``docs/srs``;
    it must read ``main.log``, because a nonstopmode build emits a PDF while
    logging errors; and it must sit in the publishing job's transitive
    ``needs`` closure in ``release.yml``, which is the one that carries the
    P0, since a check outside that closure is advisory and the tag push
    starts both at once.

    NOT proved here: that the document compiles. That is the workflow's job,
    and this only proves nothing deleted the wiring.

    The closure half binds on IDENTITY, not on the job's label. An earlier
    version asked whether the token ``srs`` was reachable, and a reviewer
    made that pass against a ``release.yml`` whose ``srs`` job ran
    ``echo "nothing is compiled here"``: renaming or repointing the job's
    ``uses:`` while leaving the name in place reopened
    ``ITC-20260730-0010`` with the suite green. What is required now is a job
    whose ``uses`` ends in ``srs_build.yml``.
    """
    workflows = _ROOT / ".github" / "workflows"
    reusable = workflows / "srs_build.yml"
    assert reusable.is_file(), (
        f"{reusable} is absent, so nothing builds the specification "
        f"(ITC-20260730-0010)."
    )
    body = reusable.read_text(encoding="utf-8")
    assert "latexmk" in body and "docs/srs" in body, (
        "the SRS build workflow no longer runs latexmk over docs/srs, so it "
        "does not build the document it exists to build."
    )
    assert "main.log" in body, (
        "the SRS build no longer inspects main.log. Exit status alone is not "
        "enough: a nonstopmode build emits a PDF while logging errors, which "
        "is this repository's own 'read the count, not only the exit code'."
    )
    for caller in ("ci.yml", "release.yml"):
        text = (workflows / caller).read_text(encoding="utf-8")
        assert "srs_build.yml" in text, (
            f"{caller} does not call srs_build.yml, so on the path it governs "
            f"the specification is never compiled. Both callers need it: the "
            f"triggers are disjoint, and a tag push that skips the build "
            f"publishes a document no machine has read (ITC-20260730-0010)."
        )
    # The load-bearing half, asserted on STRUCTURE rather than on a literal.
    # It used to read ``"needs: [srs]" in release``, which was true of the
    # shape that existed when it was written and said nothing about the
    # property: kit 0.2.12 moved the publishing job out of the gate and into
    # this file, so the job that must wait on the build is `publish` and its
    # needs list is no longer that string.
    release = yaml.safe_load((workflows / "release.yml").read_text(encoding="utf-8"))
    jobs = release["jobs"]
    publishing = [
        name
        for name, job in jobs.items()
        if any(
            "gh-action-pypi-publish" in str(step.get("uses", ""))
            for step in job.get("steps") or []
        )
    ]
    assert publishing, (
        "release.yml declares no publishing job at all, so this test can no "
        "longer say whether the SRS build gates publication. If publication "
        "moved elsewhere, move this assertion with it (ITC-20260730-0010)."
    )
    for name, job in jobs.items():
        needs = job.get("needs") or []
        for parent in [needs] if isinstance(needs, str) else needs:
            assert parent in jobs, (
                f"release.yml's job {name!r} needs {parent!r}, which is not a "
                f"job declared in that file; the needs graph cannot be walked "
                f"and this guard cannot say what gates publication. Fix the "
                f"reference or remove it."
            )

    def closure(name: str) -> set[str]:
        """Transitive ``needs`` closure, iterative so a cycle cannot recurse."""
        reached: set[str] = set()
        pending = [name]
        while pending:
            needs = jobs[pending.pop()].get("needs") or []
            for parent in [needs] if isinstance(needs, str) else needs:
                if parent not in reached:
                    reached.add(parent)
                    pending.append(parent)
        return reached

    gating = {
        name
        for name, job in jobs.items()
        if str(job.get("uses", "")).endswith("srs_build.yml")
    }
    assert gating, (
        "release.yml declares no job whose `uses` is srs_build.yml, so on the "
        "path that publishes, the specification is never compiled. A job named "
        "`srs` is not enough: this asserts the identity of the build, because a "
        "job keeping the name while its `uses` moves reopens "
        "ITC-20260730-0010 with the suite green."
    )
    for name in publishing:
        reached = closure(name)
        assert gating & reached, (
            f"release.yml's publishing job {name!r} does not transitively need "
            f"the SRS build ({sorted(gating)}), so the build runs beside "
            f"publication instead of before it. Add it to that job's `needs`: "
            f"a check outside the publishing job's needs closure is advisory, "
            f"and the tag push starts both at once (ITC-20260730-0010)."
        )
        # Every OTHER job in the file too, and this half is guarded HERE
        # because the vendored checker does not guard it. `check_release_gate`
        # rule 2 enumerates gate CALLS; it has no concept of a
        # repository-owned gating job, and a reviewer measured that deleting
        # `srs` from `publish`'s `needs` leaves the checker at exit 0. Stated
        # as "every other job" rather than as a list, so the next
        # repository-owned gate (a license scan, a shipped-surface job) is
        # covered by default instead of being remembered.
        ungated = sorted(set(jobs) - set(publishing) - reached)
        assert not ungated, (
            f"release.yml declares {ungated}, which the publishing job "
            f"{name!r} does not transitively need, so on a tag push they run "
            f"BESIDE publication rather than gating it. Add each to that job's "
            f"`needs`, or delete it. The release-gate checker does not catch "
            f"this: its rule 2 enumerates gate calls only."
        )
        # `needs` alone does not block: with `if: always()` a job runs AFTER
        # its dependencies fail. That would make the whole property false
        # while every other guard here stayed green, and it is a NEW surface
        # in this repository, because until kit 0.2.12 the publish job lived
        # inside the hash-pinned gate body rather than in this editable file.
        assert "if" not in jobs[name], (
            f"release.yml's publishing job {name!r} carries a job-level `if:`. "
            f"`needs` does not block a job whose condition is always(): it "
            f"runs after those jobs FAIL, so publication would no longer "
            f"depend on the gates passing. Remove the condition."
        )
        for gated in sorted(reached | {name}):
            assert not jobs[gated].get("continue-on-error"), (
                f"release.yml's job {gated!r} sets continue-on-error, and it "
                f"is inside the publishing job {name!r}'s needs closure, so "
                f"its failure would not stop the release. Remove it."
            )
        # A `repository-url` left behind after a rehearsal sends a REAL
        # release to the test index and reports success. The vendored
        # template warns about it in prose; prose is not a guard, and this
        # repository's own header cites a TestPyPI rehearsal, so the edit
        # demonstrably gets made.
        for step in jobs[name].get("steps") or []:
            if "gh-action-pypi-publish" not in str(step.get("uses", "")):
                continue
            assert "repository-url" not in (step.get("with") or {}), (
                "release.yml's publish step names a `repository-url`. That "
                "sends this release to the index it names, not to PyPI, and "
                "reports SUCCESS while doing it. Delete the input; it belongs "
                "only in a rehearsal copy that is never committed."
            )


def test_no_srs_source_is_blank_line_doubled() -> None:
    """A blank after EVERY content line makes each line its own paragraph.

    In LaTeX a blank line is ``\\par``. A source carrying a blank between
    every pair of content lines therefore renders every line of every
    requirement as a separate paragraph, and the breaks fall mid-sentence
    because they are a tooling artifact rather than authored spacing. It
    also breaks outright wherever a construct may not span a paragraph:
    ``ITC-20260729-2300`` was four of the seven errors in the first SRS
    build anyone had run since 2026-07-23, three of them at one
    ``\\caption`` that a doubled blank split.

    Why this is guarded here and not left to the build. The CI job added by
    ``ITC-20260730-0010`` compiles the document and so catches a doubling
    that happens to break a caption. It does NOT catch the general case: a
    doubled chapter containing no such construct compiles perfectly and
    renders as garbage, which is the same defect with no signal. So the
    structural property is asserted directly.

    The threshold rests on measurement rather than taste. The ratio of
    non-blank lines immediately followed by a blank, over all non-blank
    lines, was 1.00 for the doubled chapter 7 and 0.04 to 0.23 for the
    other fourteen sources. 0.9 sits four times above the healthy maximum
    and a tenth below the defect, so it separates them without being
    sensitive to how any one chapter is spaced.
    """
    root = _ROOT / "docs" / "srs"
    offenders: list[str] = []
    scanned: list[str] = []
    for path in sorted(root.rglob("*.tex")):
        lines = path.read_text(encoding="utf-8").splitlines()
        scanned.append(path.name)
        nonblank = [index for index, line in enumerate(lines) if line.strip()]
        followed_flags = [
            index + 1 < len(lines) and not lines[index + 1].strip()
            for index in nonblank
        ]
        followed = sum(followed_flags)
        # The FILE-level signal: a whole source that is doubled throughout.
        if len(nonblank) >= 10:
            ratio = followed / len(nonblank)
            if ratio >= 0.9:
                offenders.append(
                    f"{path.name}: {len(lines)} lines, {len(nonblank)} "
                    f"non-blank, {followed} of them followed by a blank "
                    f"(ratio {ratio:.2f})"
                )
                continue
        # The SCALE-INVARIANT signal, which the ratio alone misses. A reviewer
        # measured that a HALF-doubled chapter, a doubled 40-line block, and a
        # fully doubled 6-line include all passed the ratio test, while
        # rendering exactly as badly over the affected region. A run of content
        # lines each followed by exactly one blank is the doubling signature
        # regardless of how much of the file carries it. Authored prose does
        # not reach 8: the longest such run across the fourteen healthy sources
        # is well below it, because real paragraphs are several lines long.
        longest = current = 0
        for flag in followed_flags:
            current = current + 1 if flag else 0
            longest = max(longest, current)
        if longest >= 8:
            offenders.append(
                f"{path.name}: {longest} consecutive content lines each "
                f"followed by exactly one blank, which is the doubling "
                f"signature over a region rather than a whole file"
            )
    # A discovery that silently returns nothing passes every check vacuously,
    # which this module refuses elsewhere and must refuse here: the walk is the
    # working tree, so a moved or renamed docs/srs would green this guard.
    assert len(scanned) >= 10 and "06_functional_requirements.tex" in scanned, (
        f"the SRS walk reached {len(scanned)} .tex sources ({scanned}) under "
        f"{root}, which is not the tree this guard exists to read. Ten or more "
        f"sources including 06_functional_requirements.tex are expected; a walk "
        f"that finds nothing would otherwise report green."
    )
    assert not offenders, (
        f"an SRS source is blank-line doubled, so every content line renders "
        f"as its own LaTeX paragraph: {offenders}. The inverse transform is "
        f"deterministic from the blank-run histogram: delete every run of one "
        f"blank, and collapse every run of three to one. Verify afterwards "
        f"that the non-blank lines are byte-identical and in the same order, "
        f"since the transform may only add or remove blank lines "
        f"(ITC-20260729-2300)."
    )


def test_no_personal_or_institutional_identifier_is_tracked_outside_authorship() -> (
    None
):
    """The source half of the rule; ``test_release_integrity`` has the other.

    Scoped to the tree rather than to ``itaca/`` because the sdist ships
    the tree: an earlier version of this guard was green while
    ``tests/core/test_provenance_modes.py`` carried the exact identifier
    pair that had just been removed from a docstring.
    """
    scanned = _walk()
    found = identifiers.offenders(
        (relative, path.read_bytes()) for relative, path in scanned
    )
    _assert_the_walk_reached_the_tree([name for name, _ in scanned], "identifier")
    assert not found, (
        f"identifiers are tracked outside the authorship set: {found}; "
        f"{identifiers.REMEDY}"
    )


# The scan above is a "found nothing" assertion, so once the tree is
# clean it stays green for ANY token set, including an empty one. What
# follows proves the detector still fires. A mutated code point in the
# institution token, a dropped entry, or a regex edit that loses the
# trailing \w* turns one of these red, which the negative scan alone
# would never do.
#
# The samples are built from code points for the same reason the dashes
# above are, and it is load bearing twice over: this file is NOT exempt,
# so a literal token here would fail the scan it is testing, and building
# them independently of tests/identifiers.py is what makes a mutation
# there visible. Spelling out what they are, since the digits do not:
# the author's given name, her family name, the institution in its
# spaced prose form, and the institution as it appeared in the doctest
# that made BRF-048 urgent.
_GIVEN = "".join(map(chr, (71, 101, 111, 118, 97, 110, 97)))
_FAMILY = "".join(map(chr, (78, 101, 118, 101, 115)))
_SPACED = "".join(map(chr, (84, 85, 32, 68, 101, 108, 102, 116)))
_DOMAIN = "".join(map(chr, (116, 117, 100, 101, 108, 102, 116)))

_MUST_BE_CAUGHT = (
    (f"SME-accepted by {_GIVEN} at the checkpoint", "the author's given name"),
    (f"cite: {_FAMILY.upper()}, G. (2026)", "the author's family name"),
    (f"affiliation: ITA / {_SPACED}", "an institution name"),
    (f"Co-Authored-By: {_GIVEN.lower()}n90@example.com", "the author's given name"),
    (f'itc.set_user("{_GIVEN.lower()}@{_DOMAIN}")', "the author's given name"),
)
_MUST_PASS = (
    'itc.set_user("analyst@lab01")',
    "the unevenness of the grid never matters here",
    "an author call at the M1 Phase B1 checkpoint",
)


def test_the_identifier_detector_fires_on_every_forbidden_shape() -> None:
    for sample, label in _MUST_BE_CAUGHT:
        found = identifiers.offenders([("itaca/core/sample.py", sample.encode())])
        assert f"itaca/core/sample.py:1: {label}" in found, (
            f"the detector missed a {label} in {sample!r}"
        )


def test_the_identifier_detector_passes_clean_text() -> None:
    for sample in _MUST_PASS:
        assert not identifiers.offenders([("itaca/core/sample.py", sample.encode())]), (
            f"the detector fired on clean text: {sample!r}"
        )


def test_the_authorship_exemption_covers_the_files_it_names_and_no_others() -> None:
    """The exemption is what makes this guard survivable; pin its edges.

    The "no others" half is the half that matters. An exemption keyed on
    a bare basename would let any file called `LICENSE` or `PKG-INFO`
    through from anywhere in the tree, which is why the derived metadata
    is matched by shape and why the misplaced cases below are asserted
    rather than assumed.
    """
    line = f"{_GIVEN} {_FAMILY}, aerospace engineer, ITA / {_SPACED}.".encode()
    for exempt in ("LICENSE", "README.md", "docs/srs/main.tex", "CITATION.cff"):
        assert not identifiers.offenders([(exempt, line)]), f"{exempt} should be exempt"
    for derived in (
        "PKG-INFO",
        "itaca-0.2.0.dist-info/METADATA",
        "itaca-0.2.0.dist-info/licenses/LICENSE",
        "itaca.egg-info/PKG-INFO",
    ):
        assert not identifiers.offenders([(derived, line)]), f"{derived} is derived"
    for guarded in (
        "tests/core/test_axes.py",
        "itaca/core/axes.py",
        "examples/one.py",
        "itaca/core/LICENSE",
        "tests/data/PKG-INFO",
        "vendor/thing/METADATA",
        "docs_site/tutorial.py",
        r"itaca\core\axes.py",
    ):
        assert identifiers.offenders([(guarded, line)]), f"{guarded} must be guarded"
    assert not identifiers.offenders([(r"docs\srs\main.tex", line)]), (
        "the exemption must survive a Windows separator"
    )


def test_the_rule_module_spells_none_of_the_tokens_it_forbids() -> None:
    """Independent of ``FORBIDDEN``, which is what makes it worth having.

    The rule module needs no exemption only while it spells nothing, and
    the pattern set cannot check that: the occurrence that prompted this
    was a surname preceded by an initial, which is precisely the shape
    the leading word boundary is documented as missing.
    """
    raw = Path(identifiers.__file__).read_bytes().lower()
    for token in (_GIVEN, _FAMILY, _SPACED, _DOMAIN):
        assert token.lower().encode() not in raw, (
            "tests/identifiers.py spells a token it forbids, so it would "
            "ship one in the sdist; it carries no exemption by design"
        )


def test_the_walk_degrades_when_git_cannot_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Outside a checkout, and with no git at all: both return None.

    An unpacked sdist is both at once, and it is the case the fallback
    exists for, so it is the case that must not raise.
    """
    monkeypatch.setattr(sys.modules[__name__], "_ROOT", tmp_path)
    assert _repository_files() is None, "a directory with no checkout"
    monkeypatch.setenv("PATH", "")
    assert _repository_files() is None, "no git executable on PATH"


@pytest.mark.slow
def test_the_degraded_walk_still_reaches_the_tree_and_honors_the_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback is unreachable in any environment the suite builds.

    Without this it could be deleted or inverted and stay green, and
    EXCLUDED_PARTS would be configuration nothing can falsify, since the
    git path never consults it.

    Marked ``slow``, so it runs at pre-push and in CI, where it still
    BLOCKS, and not on every commit. It is the degraded path by
    definition: `_repository_files` is stubbed to None, so the walk gets
    no `git ls-files` answer and stats the whole tree itself, reading
    every file it does not exclude. Measured on this repository at
    1.67 s alone and 13.37 s inside the full commit tier, against a
    3.0 s per-test budget, and it grows with the tree.

    The marker is on the TEST and not the module: everything else in
    this file reads the git listing and runs in milliseconds, and moving
    the module would take eighteen fast guards out of the commit tier to
    fix one.

    It was `a9606f0` that installed the budget, and it left this test
    breaking it, which is `ITC-20260730-2355` in one line: a tier guard
    weaker than its own prose. The budget is not raised to make this
    pass, because the budget is the thing that found it.
    """
    monkeypatch.setattr(sys.modules[__name__], "_repository_files", lambda: None)
    scanned = [name for name, _ in _walk()]
    _assert_the_walk_reached_the_tree(scanned, "degraded")
    for name in scanned:
        assert not EXCLUDED_PARTS.intersection(name.split("/")), name


def test_a_binary_payload_is_skipped_and_the_limit_is_deliberate() -> None:
    """Both directions of the skip, so the blind spot cannot move silently.

    `.itc` is a ZIP and carries a user identity by design, so a
    committed archive fixture would pass both boundaries. That is a
    stated limit of the rule, not an accident, and it is asserted here so
    that removing the skip is a visible act.
    """
    prose = f"user: {_GIVEN}@{_DOMAIN}".encode()
    assert identifiers.offenders([("itaca/io/sample.txt", prose)])
    assert not identifiers.offenders(
        [("itaca/io/sample.itc", b"PK\x03\x04\x00" + prose)]
    )


def test_the_release_runbook_matches_the_workflow_it_documents() -> None:
    """The runbook must not drift from the path it tells a maintainer to use.

    `RELEASING.md` exists because the one thing that can break a release is
    the one thing no test can reach: the trusted publisher configured on
    PyPI. A reviewer put it plainly, that the failure a maintainer meets is
    `invalid-publisher`, raised by a third-party action, naming neither the
    workflow file nor the environment nor the decision that chose them.

    A runbook is prose, and prose that disagrees with the workflow is worse
    than none: it sends someone to configure the wrong thing with
    confidence. So the two values a reader would act on are read from the
    workflow and required to appear in the document, rather than being
    trusted to have been copied correctly.

    Deliberately NOT checked here, because it is not checkable from this
    repository at all: whether PyPI actually carries that publisher. That
    is why the publish job prints the expected configuration into every run
    summary and prints a fix-it block when the upload is refused. This test
    covers the document; those steps cover the moment.
    """
    workflows = _ROOT / ".github" / "workflows"
    release = yaml.safe_load((workflows / "release.yml").read_text(encoding="utf-8"))
    runbook_path = _ROOT / "RELEASING.md"
    assert runbook_path.is_file(), (
        "RELEASING.md is missing. It is the only place the PyPI publisher "
        "configuration is written down as standing state, and no test can "
        "reach that configuration; deleting the document removes the only "
        "route a maintainer has to it."
    )
    runbook = runbook_path.read_text(encoding="utf-8")

    publishing = [
        (name, job)
        for name, job in release["jobs"].items()
        if any(
            "gh-action-pypi-publish" in str(step.get("uses", ""))
            for step in job.get("steps") or []
        )
    ]
    assert publishing, "release.yml declares no publishing job to document"
    for name, job in publishing:
        environment = job.get("environment")
        env_name = (
            environment.get("name") if isinstance(environment, dict) else environment
        )
        assert env_name, (
            f"release.yml's publishing job {name!r} declares no environment "
            f"name, so the runbook has nothing to document and the OIDC "
            f"claim PyPI matches is incomplete."
        )
        assert f"`{env_name}`" in runbook, (
            f"RELEASING.md never names the environment {env_name!r} that "
            f"release.yml's {name!r} job actually declares. A maintainer "
            f"following the runbook would configure the publisher with the "
            f"wrong environment and meet `invalid-publisher` anyway."
        )

    # The workflow FILE name is half of the bind DD-45 records, and naming
    # the wrong one is the single most likely misconfiguration, since it is
    # what v0.2.0's abandoned workaround used.
    assert "`release.yml`" in runbook, (
        "RELEASING.md never names `release.yml` as the workflow the "
        "publisher must be configured with. That is the value the v0.2.0 "
        "workaround got wrong, and the reason this document exists."
    )
    assert "invalid-publisher" in runbook, (
        "RELEASING.md does not mention `invalid-publisher`, which is the "
        "exact string a maintainer will search for when the upload is "
        "refused. A runbook that cannot be found by the error it explains "
        "is one hop too far away."
    )

    # And the failure path in the workflow must route to the document. Two
    # steps legitimately name both strings and they play different roles:
    # one states the expected configuration BEFORE uploading and runs
    # always, the other fires only when the upload was refused. What must
    # exist is at least one of the SECOND kind, so requiring the condition
    # of every matching step is wrong and was how this assertion first went
    # in; it failed against the pre-publish step, which correctly has no
    # condition at all.
    publish_steps = [step for _, job in publishing for step in job.get("steps") or []]
    diagnostics = [
        step
        for step in publish_steps
        if "RELEASING.md" in str(step.get("run", ""))
        and "invalid-publisher" in str(step.get("run", ""))
    ]
    assert diagnostics, (
        "release.yml's publishing job has no step whose output names both "
        "`invalid-publisher` and RELEASING.md. Without one, the only thing "
        "a maintainer sees on a refused upload is a third-party action's "
        "message, which names neither the workflow, the environment, nor "
        "where the procedure is written."
    )
    on_failure = [
        step for step in diagnostics if "failure()" in str(step.get("if", ""))
    ]
    assert on_failure, (
        "release.yml names `invalid-publisher` and RELEASING.md, but in no "
        "step conditioned on failure(). The fix-it block must fire when the "
        "upload is REFUSED; a message that only prints on the happy path is "
        "not there at the moment a maintainer needs it."
    )


def test_every_gate_call_passes_the_same_checks_and_toolchain() -> None:
    """The three gate calls must agree, because nothing else compares them.

    Kit 0.2.12's two-call topology took the gate inputs from ONE call site
    to three: ``ci.yml:gate``, and ``release.yml``'s ``breadth`` and
    ``release``. All three files say in comments that they are kept
    identical, and until this test nothing checked it. What the vendored
    ``check_release_gate.py`` compares is DECLARED MATRICES (rule 5); every
    other ``with:`` input is invisible to it.

    Measured by a reviewer on scratch copies, which is why this exists: the
    ``types`` gate deleted from BOTH of ``release.yml``'s calls, together
    with a diverged ``build-toolchain``, leaves the checker at exit 0 with
    no violations. The tag path would then ship without the type gate and
    built by a toolchain CI never proved, with the whole suite green.

    ``gates`` is compared as PARSED JSON rather than as text, so
    reformatting is not a failure and a reordered array is not either. The
    gate itself accepts an entry carrying ``absent`` (a reason) instead of
    ``run`` (a command), which is the shape that would otherwise let a
    release declare a gate away in one file only.
    """
    workflows = _ROOT / ".github" / "workflows"
    compared = ("gates", "build-toolchain", "version-command", "smoke")
    calls: dict[str, dict[str, object]] = {}
    for name in ("ci.yml", "release.yml"):
        parsed = yaml.safe_load((workflows / name).read_text(encoding="utf-8"))
        for job, body in parsed["jobs"].items():
            if not str(body.get("uses", "")).endswith("release_gate.yml"):
                continue
            calls[f"{name}:{job}"] = body.get("with") or {}
    assert len(calls) >= 3, (
        f"expected at least three release-gate calls across ci.yml and "
        f"release.yml and found {sorted(calls)}. Either the topology changed "
        f"or this guard is reading the wrong jobs; it cannot compare what it "
        f"cannot find."
    )
    reference, expected = sorted(calls)[0], calls[sorted(calls)[0]]
    for key in compared:
        want = json.loads(expected[key]) if key == "gates" else expected[key]
        for call, given in sorted(calls.items()):
            got = json.loads(given[key]) if key == "gates" else given[key]
            assert got == want, (
                f"the release-gate input {key!r} differs between {reference!r} "
                f"and {call!r}, so CI and the tag path do not prove the same "
                f"thing about the commit being released. Make them identical, "
                f"or state in both files why they must differ. Neither the "
                f"release-gate checker nor any other guard compares this: "
                f"rule 5 compares declared matrices only.\n"
                f"  {reference}: {want!r}\n  {call}: {got!r}"
            )
