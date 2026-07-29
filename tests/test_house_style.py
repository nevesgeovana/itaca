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
"""

import re
from pathlib import Path

FORBIDDEN = {chr(0x2014): "em dash", chr(0x2013): "en dash"}
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


def test_no_em_or_en_dashes_anywhere() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if EXCLUDED_PARTS.intersection(path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for char, label in FORBIDDEN.items():
                if char in line:
                    rel = path.relative_to(root)
                    offenders.append(f"{rel}:{lineno}: {label}")
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
    root = Path(__file__).resolve().parents[1] / "docs" / "srs"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.tex")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _LABEL_USE.finditer(line):
                head = line[: match.start() + 1]
                if not head.endswith(_REFERENCING_COMMANDS):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()[:70]}")
    assert not offenders, f"label reached without a reference command: {offenders}"


# Personal and institutional identifiers must not travel inside the
# importable package. This is a narrower rule than the workspace one and
# deliberately so: authorship in LICENSE, CITATION.cff, README.md and the
# SRS is a library published under the author's own name, is intentional,
# and is not guarded here. What is guarded is the wheel, which
# pyproject.toml ships as ``include = ["itaca*"]`` with no MANIFEST.in, so
# every string under itaca/ reaches the machine of everyone who installs
# it. Four occurrences shipped past this file because the class was not in
# it, one of them a doctest binding a given name to an institution.
#
# The institution token is assembled from code points for the same reason
# the dashes above are: spelling it out would put the exact string this
# test forbids into a tracked artifact.
_INSTITUTION = "".join(map(chr, (116, 117, 100, 101, 108, 102, 116)))
_FORBIDDEN_IN_PACKAGE = {
    "geovana": "the author's given name",
    "neves": "the author's family name",
    _INSTITUTION: "an institution name",
}


def test_no_personal_or_institutional_identifier_ships_inside_the_package() -> None:
    package = Path(__file__).resolve().parents[1] / "itaca"
    patterns = {
        re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE): label
        for token, label in _FORBIDDEN_IN_PACKAGE.items()
    }
    offenders: list[str] = []
    for path in sorted(package.rglob("*")):
        if not path.is_file() or EXCLUDED_PARTS.intersection(path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, label in patterns.items():
                if pattern.search(line):
                    rel = path.relative_to(package.parent)
                    offenders.append(f"{rel}:{lineno}: {label}")
    assert not offenders, (
        f"identifiers ship inside the wheel: {offenders}; "
        "state the fact without the name, and use a neutral example value"
    )
