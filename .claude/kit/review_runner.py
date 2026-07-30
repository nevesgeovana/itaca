# ITACA / pyflightstream shared process kit
# kit-version: 0.2.11
# artifact: review_runner.py
# body-sha256: 22c48be54b18c73c80d632d0d178d7b94d6f7321d60824d8695b10c79ac278ca
# canonical-source: BUILT for the kit (0.2.11, HUB-9, BRF-061 item 15, author decision 7) from two recorded failures with one structural cause: a reviewer ran git restore in the live tree and destroyed a lane's edits, and two Bash-holding lenses shared one worktree and corrupted each other's measurements (ITC-20260730-0250). One detached worktree per lens, diff and paths only, findings collected at close, worktree removed; a reviewer never receives the live tree as cwd. The charters' restore-prohibition paragraphs shrink to a pointer at each repository's next re-vendor, now that the mechanism they asked for exists.
# note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
# 
# END KIT PROVENANCE (body verbatim below)
#!/usr/bin/env python3
"""Review runner: one detached worktree per reviewer lens, never the live tree.

Usage:
    review_runner.py open  <repo> [--ref HEAD] [--base <rev>] <lens> [<lens> ...]
    review_runner.py close <repo> [--out <dir>]

WHY THIS EXISTS, twice over. A recorded incident has a reviewer running
``git restore`` inside the live tree and destroying the session's edits; a
second (`ITC-20260730-0250`) has two Bash-holding lenses sharing one
worktree and corrupting each other's measurements. Both failure modes are
the same structural cause: reviewers execute inside a tree someone else is
mutating. The charters said a separate worktree "would be stronger and is
not in place"; this artifact is that mechanism, so the restore-prohibition
paragraphs can shrink to a pointer at each repository's next re-vendor.

``open`` creates, per lens, a DETACHED worktree of ``--ref`` under the
system temp directory, and writes into each:

  RR_DIFF.patch   ``git diff <base>..<ref>`` (base defaults to the last
                  commit on any remote, i.e. the unpushed range; an empty
                  range yields an empty patch, stated in the file)
  RR_PATHS.txt    the changed paths, one per line
  RR_FINDINGS.md  an empty findings file the lens appends to

and prints one ``lens<TAB>path`` line per worktree. The invoking skill
gives each reviewer ITS OWN worktree as cwd, the diff and the paths; a
reviewer never receives the live tree, and nothing a lens runs can touch
another lens's measurements.

``close`` collects every ``RR_FINDINGS.md`` into ``--out`` (default: print
to stdout under a per-lens heading), removes the worktrees with
``git worktree remove --force`` and prunes. A worktree is only ever removed
by ``close``; a crashed run leaves the trees on disk for inspection and a
later ``close`` still finds them through the marker prefix.

Standalone, stdlib only, no third-party deps, like every kit checker.
Exit 0 on success, 1 on a git failure (reported with the command), 2 for a
CONFIG error (not a repository, unknown usage, no lenses).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PREFIX = "rr-"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"git {' '.join(args)} failed in {repo}: "
              f"{r.stderr.strip() or r.stdout.strip()}", file=sys.stderr)
        raise SystemExit(1)
    return r.stdout


def _root(repo: Path) -> Path:
    base = Path(tempfile.gettempdir()) / "kit-review-runner"
    return base / repo.resolve().name


def cmd_open(repo: Path, ref: str, base: str | None,
             lenses: list[str]) -> int:
    _git(repo, "rev-parse", "--verify", ref)
    if base is None:
        # The unpushed range: what a PUSH review must read. No remote at all
        # is reported rather than guessed around.
        remotes = _git(repo, "remote").split()
        if not remotes:
            print("no remote and no --base given; name the base revision "
                  "the review diff starts from", file=sys.stderr)
            return 2
        merge_base = _git(repo, "rev-list", ref, "--not", "--remotes",
                          "--reverse").split()
        base = (merge_base[0] + "^") if merge_base else ref
    diff = _git(repo, "diff", f"{base}..{ref}")
    paths = _git(repo, "diff", "--name-only", f"{base}..{ref}")
    root = _root(repo)
    root.mkdir(parents=True, exist_ok=True)
    for lens in lenses:
        wt = root / f"{PREFIX}{lens}"
        if wt.exists():
            print(f"{wt} already exists; run close first", file=sys.stderr)
            return 2
        _git(repo, "worktree", "add", "--detach", str(wt), ref)
        (wt / "RR_DIFF.patch").write_text(
            diff or f"(empty diff: {base}..{ref} contains no change)\n",
            encoding="utf-8")
        (wt / "RR_PATHS.txt").write_text(paths, encoding="utf-8")
        (wt / "RR_FINDINGS.md").write_text(
            f"# Findings: {lens} lens, {base}..{ref}\n", encoding="utf-8")
        print(f"{lens}\t{wt}")
    return 0


def cmd_close(repo: Path, out: Path | None) -> int:
    root = _root(repo)
    trees = sorted(root.glob(f"{PREFIX}*")) if root.exists() else []
    if not trees:
        print(f"no review worktrees under {root}; nothing to close")
        return 0
    for wt in trees:
        findings = wt / "RR_FINDINGS.md"
        text = findings.read_text(encoding="utf-8") \
            if findings.exists() else "(no findings file)\n"
        if out:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"findings-{wt.name[len(PREFIX):]}.md").write_text(
                text, encoding="utf-8")
        else:
            print(f"---- {wt.name[len(PREFIX):]} ----\n{text}")
        _git(repo, "worktree", "remove", "--force", str(wt))
    _git(repo, "worktree", "prune")
    print(f"closed {len(trees)} review worktree(s)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in ("open", "close"):
        print(__doc__, file=sys.stderr)
        return 2
    repo = Path(argv[2])
    if not (repo / ".git").exists():
        print(f"{repo} is not a git repository", file=sys.stderr)
        return 2
    rest = argv[3:]
    if argv[1] == "open":
        ref, base, lenses = "HEAD", None, []
        it = iter(rest)
        for a in it:
            if a == "--ref":
                ref = next(it, "HEAD")
            elif a == "--base":
                base = next(it, None)
            else:
                lenses.append(a)
        if not lenses:
            print("no lenses named; e.g. architect qa vv", file=sys.stderr)
            return 2
        return cmd_open(repo, ref, base, lenses)
    out = None
    if "--out" in rest:
        out = Path(rest[rest.index("--out") + 1])
    return cmd_close(repo, out)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
