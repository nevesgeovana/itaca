# ITACA SRS: LaTeX sources

Authoritative specification of ITACA, document version 0.1.0
(2026-07-21, first workspace-tracked version; research-workspace
snapshot id DLV-008). Companions: `../DECISIONS.md` (DD-01 to DD-22) and
`../OPEN_QUESTIONS.md` (OQ-01 to OQ-18).

## Build

Requires MiKTeX or TeX Live with `pdflatex` and `bibtex` on the PATH.

```
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Output is `main.pdf` (gitignored, regenerable). The title-page logo is
referenced from `../figures/pdf/itaca_logo.pdf`.

## Editing rules

* Add a requirement: next free `REQ-XX`, status `[draft]` until
  implemented and tested. Never reuse or delete identifiers; deprecate.
* Add a design decision: `DD-XX` box in `chapters/05_architecture.tex`
  plus a long-form entry in `../DECISIONS.md`.
* Add an open question: entry in `../OPEN_QUESTIONS.md`; on resolution,
  reference the resulting REQ or DD.
* Every change updates `frontmatter/revision_history.tex` and
  `chapters/11_changelog.tex` together, and bumps the document version
  (MINOR for new requirements, PATCH for clarifications).
* Typography: no em or en dashes anywhere. American English with Z
  (REQ-87).
