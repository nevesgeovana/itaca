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
where an empty folder exits zero; and a walk of the working tree instead
would take its verdict from build output and from one machine's
absolute paths.
"""

import re
import subprocess
import sys
from pathlib import Path

import identifiers
import pytest

DASHES = {chr(0x2014): "em dash", chr(0x2013): "en dash"}
TEXT_SUFFIXES = {
    ".cff",
    ".json",
    ".md",
    ".py",
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
    for path in sorted(root.rglob("*.tex")):
        lines = path.read_text(encoding="utf-8").splitlines()
        nonblank = [index for index, line in enumerate(lines) if line.strip()]
        # A very short include has no room for the ratio to mean anything.
        if len(nonblank) < 10:
            continue
        followed = sum(
            1
            for index in nonblank
            if index + 1 < len(lines) and not lines[index + 1].strip()
        )
        ratio = followed / len(nonblank)
        if ratio >= 0.9:
            offenders.append(
                f"{path.name}: {len(lines)} lines, {len(nonblank)} non-blank, "
                f"{followed} of them followed by a blank (ratio {ratio:.2f})"
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


def test_the_degraded_walk_still_reaches_the_tree_and_honors_the_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback is unreachable in any environment the suite builds.

    Without this it could be deleted or inverted and stay green, and
    EXCLUDED_PARTS would be configuration nothing can falsify, since the
    git path never consults it.
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
