"""Repository-wide house-style guard (workspace rule; pyflightstream pattern).

No em dashes and no en dashes anywhere, in any tracked text file. The
forbidden characters are constructed from code points so this guard
file itself stays clean.
"""

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
