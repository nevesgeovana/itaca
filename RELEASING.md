# Releasing ITACA

The procedure for cutting a release, and the one thing no file in this
repository can enforce.

Everything that decides whether a tag may ship is in
`.github/workflows/release_gate.yml`, called twice by
`.github/workflows/release.yml`, which is also the publisher. Why the
publishing job sits in the caller rather than in the reusable gate is
DD-45 in `docs/DECISIONS.md`; the short form is that PyPI matches two
different claims against one configured publisher, and with a reusable
workflow no publisher value satisfies both.

## 0. The publisher configuration, which is not in this repository

**This is step zero because it is the only step that can be wrong before
anything runs, and the only one no test can catch.**

On PyPI, under Manage project, Publishing, the trusted publisher for
`itaca` must be:

| field | value |
|---|---|
| owner | this repository's owner, as it appears in its URL |
| repository | `itaca` |
| workflow | `release.yml` |
| environment | `pypi` |

The first two are written here as descriptions rather than as literals on
purpose: an account name is a personal identifier, and DD-41 keeps those
out of tracked files. You do not need to look them up. The publish job
prints all four resolved values into every run summary before it uploads,
so the authoritative copy is the one the run itself shows you.

A publisher naming `release_gate.yml` is the abandoned workaround from
v0.2.0. It cannot work now and it is not a fallback. If one is still
configured, repoint it before tagging.

Nothing in this repository verifies the above. `tests/` cannot see PyPI,
and `check_release_gate.py` checks this repository's own topology, not the
configuration on another website. What the repository does instead is tell
you: `release.yml`'s publish job prints the table above into every run
summary before it uploads, and prints a fix-it block if the upload is
refused.

## 1. Before the tag

- The working tree is clean and pushed, and CI is green on that commit.
- `CHANGELOG.md` has a section for the version, not `[Unreleased]`.
- **That section carries a `### Known open` block**, stating each known
  limitation as something a user can observe from their own usage rather
  than as an internal defect id, with at least three lines under the
  heading. `tests/test_release_integrity.py` refuses the tag without one,
  and a hollow heading does not satisfy it. This is written here because
  a required release step that lives only in a test is a step you meet
  for the first time as a red gate.
  Carry the previous release's block FORWARD and edit it rather than
  starting from nothing: most limitations outlive one release, and the
  ones that closed are the most useful thing the new block can say. A
  fresh `[Unreleased]` section recording no changes at all is exempt, so
  cutting the tag does not immediately redden the next commit.
- `CITATION.cff` carries the version being released and its DOI, if one
  is minted for it. The v0.2.0 release review found this file still at
  `0.1.0` with the previous release's DOI, which Zenodo would have
  archived unrecoverably.
- `README.md` does not describe the release being cut as unreleased. It
  is the PyPI long description.
- The role review has run and the release attestation is written. The
  push gate refuses a version tag without one.

## 2. Cutting it

Tag and push in separate commands, and never with `--follow-tags`,
`--tags`, `--all` or `--mirror`. The push gate denies those forms because
it cannot resolve offline what they would send, and `--follow-tags` is how
an unattested tag once reached a publish workflow.

    git tag -a vX.Y.Z -m "..."
    git push origin main
    git push origin vX.Y.Z

The tag push starts `release.yml`. It runs the SRS build, the full CI
matrix through the gate on the tagged commit, a separate single gate call
whose artifact is the one that ships, and only then `publish`.

## 3. If the upload is refused

Read the run summary of the `publish` job first. It carries the expected
publisher configuration and, on failure, a block naming the likely cause.

| what you see | what it means |
|---|---|
| `invalid-publisher` | PyPI has no publisher matching this workflow. Step 0. |
| a 400 about a Build Config URI | The same misconfiguration from the attestation side, not a separate problem. Step 0. |
| `publish` skipped, not failed | A gate failed. Nothing was built or uploaded; fix the gate. |

Nothing is half-published in any of these cases. A failing gate skips
`publish` entirely rather than running it and declining, so the index is
untouched and no artifact exists to have leaked.

## 4. After a successful upload

A tag push publishes to PyPI. It does **not** archive to Zenodo: that
hooks on a GitHub Release, which is a separate step. Cutting the Release
is what mints the DOI.

## What is not automated, deliberately

The decision to tag is the author's. So is whether the `pypi` environment
carries a required reviewer: the gate requires the environment to exist,
because it is the only place a human stop can attach, and whether to
attach one is hers.
