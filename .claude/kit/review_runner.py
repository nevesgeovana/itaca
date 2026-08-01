# ITACA / pyflightstream shared process kit
# kit-version: 0.2.15
# artifact: review_runner.py
# body-sha256: dd8b9793c5c5b5e7d01365a1ff5ac889b1ca39722b576ad3159320a7aa8aec97
# canonical-source: BUILT for the kit (0.2.11, HUB-9, BRF-061 item 15, author decision 7) from two recorded failures with one structural cause: a reviewer ran git restore in the live tree and destroyed a lane's edits, and two Bash-holding lenses shared one worktree and corrupted each other's measurements (ITC-20260730-0250). One detached worktree per lens, diff and paths only, findings collected at close, worktree removed; a reviewer never receives the live tree as cwd. The charters' restore-prohibition paragraphs shrink to a pointer at each repository's next re-vendor, now that the mechanism they asked for exists. 0.2.15 fixes two defects both measured by lanes: ITC-20260801-0130, close aborting on the first worktree it cannot remove, stranding the rest AND destroying their findings files; and ITC-20260801-1600, the three RR_ files sitting inside the worktree where a house-style walk scans them, reddening every Bash lens. It also fixes a third defect found by executing this promotion's own contract fixture rather than by reading: the shared temp root was keyed on the repository's directory NAME alone, so two checkouts with the same basename shared one root and one repository's close enumerated the other's worktrees. See coordination/DESIGN_HUB-11_kit_batch.md item 7.
# note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
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
system temp directory, and writes BESIDE it, in a sidecar directory named
``<worktree>.io``:

  RR_DIFF.patch   ``git diff <base>..<ref>`` (base defaults to the last
                  commit on any remote, i.e. the unpushed range; an empty
                  range yields an empty patch, stated in the file)
  RR_PATHS.txt    the changed paths, one per line
  RR_FINDINGS.md  an empty findings file the lens appends to

and prints one tab-separated line per lens, five fields:

    <lens>	<worktree>	<diff>	<paths>	<findings>

BESIDE THE WORKTREE AND NOT INSIDE IT, changed at 0.2.15 from
``ITC-20260801-1600``. Those three files used to live inside the worktree,
where they are untracked-but-not-ignored, so a repository whose house-style
walk asks git for tracked plus untracked files SCANNED THEM. ``RR_DIFF.patch``
contains the diff, so a diff touching a file that quotes the author's name
made every reviewer lens report a RED that does not exist on the reviewed
ref. Measured in lane ITA-4: two independent lenses reported it without
prompting, both correctly called it a harness artifact, and both spent tool
calls on it first; round two of that lane carried an "ignore these" paragraph
in all four lens prompts, which is a workaround living in a prompt. The cost
is not the red, it is that a reviewer whose first measurement is a false
positive learns to discount the guard.

THE ALTERNATIVE WAS MEASURED AND REJECTED. Adding the three names to the
worktree's ``.git/info/exclude`` looks cheaper and changes no interface, and
it cannot work: inside a linked worktree ``git rev-parse --git-path
info/exclude`` resolves to the COMMON directory, ``<repo>/.git/info/exclude``.
There is no per-worktree exclude file git reads. So that shape writes into
the operator's own repository, a change that outlives the review and that a
crashed run leaves behind. Measured 2026-08-01 in a scratch repository rather
than argued. Having the consumers exempt the filenames was rejected by the
incident itself: it puts a kit artifact's name into every consumer's guard,
and a repository that forgets inherits the false red silently.

The worktree is therefore a PRISTINE checkout of the reviewed ref. Nothing
the ref does not contain appears in it, under ANY consumer's scanning
discipline rather than only one that keys on ignored-versus-untracked.

``close`` collects every ``RR_FINDINGS.md`` into ``--out`` (default: print
to stdout under a per-lens heading), then removes the worktrees with
``git worktree remove --force`` and prunes. A worktree is only ever removed
by ``close``; a crashed run leaves the trees on disk for inspection and a
later ``close`` still finds them through the marker prefix.

COLLECT EVERYTHING FIRST, THEN REMOVE, AND NEVER ABORT ON A REMOVAL,
changed at 0.2.15 from ``ITC-20260801-0130``. ``close`` used to collect and
remove one worktree at a time and to abort on the first git failure, so a
single lens still running inside its own worktree stranded every worktree
after it AND their findings were never collected. Measured: four worktrees,
the QA lens still running, its removal denied, ``close`` aborted, two later
worktrees left registered with no findings collected, and the QA findings
file printed and then gone. Those findings survived only because an agent
still held them and returned them as text minutes later; had it crashed,
an entire lens's work would have been destroyed by the step whose job is to
collect it. A lens still running is the ORDINARY case, not an exceptional
one.

The two fixes reinforce each other rather than overlapping: with the findings
outside the worktree, a failed worktree removal cannot destroy them at all.

Standalone, stdlib only, no third-party deps, like every kit checker.
Exit 0 on success, 1 on a git failure (reported with the command), 2 for a
CONFIG error (not a repository, unknown usage, no lenses). A ``close`` that
collected every findings file and failed to remove some worktrees exits 1
and names each failure with the command that clears it: the collection
succeeded and the tidying did not, and reporting that as success would hide
worktrees that are still registered.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PREFIX = "rr-"
SIDECAR = ".io"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"git {' '.join(args)} failed in {repo}: "
              f"{r.stderr.strip() or r.stdout.strip()}", file=sys.stderr)
        raise SystemExit(1)
    return r.stdout


def _git_try(repo: Path, *args: str) -> tuple[bool, str]:
    """A git call whose failure is REPORTED and not raised.

    ``close`` uses this for every removal. The raising form aborts the whole
    command at the first failure, which is what stranded three worktrees and
    lost their findings; a removal that fails while a lens is still working
    inside is the ordinary case and must not stop the rest.
    """
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, (r.stderr.strip() or r.stdout.strip()
                       or f"git exited {r.returncode}")
    return True, r.stdout


def _root(repo: Path) -> Path:
    """The shared temp root for one repository.

    The directory NAME alone was the key through 0.2.11, and that is a
    collision: two checkouts with the same basename, which is the ordinary
    shape of a clone and a scratch copy, shared one root, so one repository's
    ``close`` enumerated the other's worktrees and reported them as its own
    with `is not a working tree`. Found by execution while building this
    promotion's own contract fixture, not by reading. The path digest keeps
    the name readable and makes the key unique.

    CONSEQUENCE FOR ADOPTION, and it is why `close` must be run BEFORE
    re-vendoring: a worktree opened under the old root is not found under the
    new one.
    """
    base = Path(tempfile.gettempdir()) / "kit-review-runner"
    resolved = repo.resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:8]
    return base / f"{resolved.name}-{digest}"


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
        io = root / f"{PREFIX}{lens}{SIDECAR}"
        if wt.exists() or io.exists():
            print(f"{wt} already exists; run close first", file=sys.stderr)
            return 2
        _git(repo, "worktree", "add", "--detach", str(wt), ref)
        # The sidecar, never the worktree. See ITC-20260801-1600 in the
        # module docstring: these three files are untracked-but-not-ignored,
        # and a repository that walks that set scans them.
        io.mkdir(parents=True, exist_ok=True)
        (io / "RR_DIFF.patch").write_text(
            diff or f"(empty diff: {base}..{ref} contains no change)\n",
            encoding="utf-8")
        (io / "RR_PATHS.txt").write_text(paths, encoding="utf-8")
        (io / "RR_FINDINGS.md").write_text(
            f"# Findings: {lens} lens, {base}..{ref}\n", encoding="utf-8")
        print(f"{lens}\t{wt}\t{io / 'RR_DIFF.patch'}\t"
              f"{io / 'RR_PATHS.txt'}\t{io / 'RR_FINDINGS.md'}")
    return 0


def cmd_close(repo: Path, out: Path | None) -> int:
    root = _root(repo)
    trees = sorted(p for p in root.glob(f"{PREFIX}*")
                   if p.is_dir() and not p.name.endswith(SIDECAR)) \
        if root.exists() else []
    if not trees:
        print(f"no review worktrees under {root}; nothing to close")
        return 0

    # PHASE 1: COLLECT EVERYTHING. Nothing is removed until every findings
    # file is in hand, so no removal failure can cost a lens its work.
    collected: list[tuple[Path, str, str]] = []
    for wt in trees:
        lens = wt.name[len(PREFIX):]
        sidecar = wt.parent / f"{wt.name}{SIDECAR}" / "RR_FINDINGS.md"
        # The in-worktree path is read as a FALLBACK, so a worktree opened by
        # a pre-0.2.15 body is still collected rather than silently reported
        # as having no findings.
        legacy = wt / "RR_FINDINGS.md"
        if sidecar.exists():
            text = sidecar.read_text(encoding="utf-8")
        elif legacy.exists():
            text = legacy.read_text(encoding="utf-8")
        else:
            text = "(no findings file)\n"
        collected.append((wt, lens, text))

    for wt, lens, text in collected:
        if out:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"findings-{lens}.md").write_text(text, encoding="utf-8")
        else:
            print(f"---- {lens} ----\n{text}")

    # PHASE 2: REMOVE, continuing past every failure. A lens still running
    # inside its worktree is the ordinary case.
    failures: list[tuple[Path, str]] = []
    removed = 0
    for wt, lens, _ in collected:
        ok, message = _git_try(repo, "worktree", "remove", "--force", str(wt))
        if not ok:
            # THE RETRY MUST BE ABLE TO RECOVER, which is the second half of
            # ITC-20260801-0130 and was measured on this promotion's own
            # fixture. A failed `worktree remove --force` can leave the tree
            # HALF removed: git has forgotten the registration while the
            # directory is still on disk, so a second close is told `is not a
            # working tree` and the entry can never be cleared by this tool
            # at all. Prune first, then take the directory directly.
            #
            # Deleting a directory is the one destructive act in this file
            # and it is bounded: the path came from this tool's own root,
            # carries its own PREFIX, and git has just tried to delete it.
            # Nothing outside that root is ever reachable from here.
            _git_try(repo, "worktree", "prune")
            if not wt.exists():
                ok = True
            else:
                try:
                    shutil.rmtree(wt)
                    ok = True
                except OSError as exc:
                    message = (f"{message}; the directory could not be "
                               f"removed either: {exc}")
        if not ok:
            failures.append((wt, message))
            continue
        removed += 1
        # The sidecar goes only when its worktree went. If the removal
        # failed, the findings stay on disk for a retry to find.
        sidecar_dir = wt.parent / f"{wt.name}{SIDECAR}"
        for child in sorted(sidecar_dir.glob("*")) if sidecar_dir.is_dir() \
                else []:
            try:
                child.unlink()
            except OSError:
                pass
        try:
            sidecar_dir.rmdir()
        except OSError:
            pass
    _git_try(repo, "worktree", "prune")

    print(f"collected {len(collected)} findings file(s); "
          f"removed {removed} of {len(collected)} review worktree(s)")
    if failures:
        print(f"{len(failures)} worktree(s) could NOT be removed. Every "
              "findings file above was collected first, so nothing was lost; "
              "these are still registered and still on disk:", file=sys.stderr)
        for wt, message in failures:
            print(f"  {wt}: {message}", file=sys.stderr)
        print("  A lens still working inside its worktree is the usual "
              "cause. Let it finish, then run close again; it collects and "
              "removes what is left.", file=sys.stderr)
        return 1
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
