# ITACA / pyflightstream shared process kit
# kit-version: 0.2.6
# artifact: check_release_gate_mutations.py
# body-sha256: 897ace78c3d664b3de16f6a3947df746e9ab79d3916e448a61f499eef830d134
# canonical-source: BUILT for the kit (0.2.6): the mutation companion for check_release_gate.py, proving the release-gate checker still refuses the pre-fix release workflow both reviews measured, the kept-alongside second publisher, and a publish job that drops one gate from its needs.
# note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
# END KIT PROVENANCE (body verbatim below)
#!/usr/bin/env python3
"""Prove check_release_gate.py can still refuse, on real workflow fixtures.

Usage:
  python check_release_gate_mutations.py [--gate <path to release_gate.yml>]

Every case writes actual workflow files into a temporary directory and runs
the checker as a subprocess, so what is asserted is behaviour. Then each
mutant reintroduces one way the checker can be weakened and must be REFUSED
by at least one case.

Case 2 is the important one: it is the release workflow both libraries
actually shipped, reduced to its shape. A tag push built, checked metadata,
compared the tag against the declared version, and uploaded, with `publish`
needing `build` and `build` needing nothing. If that case ever stops being
refused, this checker has lost the finding it was written for.

DIVISION OF LABOUR, stated because a reader will look for the missing half.
This file proves the CHECKER fails on bad input; it does not prove the
repository's own workflows are good. That is the vendored tier-1 test's job,
which runs `check_release_gate.py --workflows .github/workflows` against the
repository it lives in. When the canonical `release_gate.yml` happens to sit
beside this file, as it does in the kit master directory, it is additionally
checked here; in a vendored deployment it does not, and that is reported
rather than silently skipped.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_release_gate.py"

# ---- fixture fragments -----------------------------------------------------

_GATE_HEAD = """\
name: Release gate
on:
  workflow_call:
    inputs:
      publish:
        required: false
        type: boolean
        default: false
jobs:
  inventory:
    runs-on: ubuntu-latest
    steps:
      - run: echo inventory
  gates:
    needs: inventory
    runs-on: ubuntu-latest
    steps:
      - run: pytest
  identity:
    needs: inventory
    runs-on: ubuntu-latest
    steps:
      - run: python check_version_identity.py --version 1.0.0
  build:
    needs: [inventory, gates, identity]
    runs-on: ubuntu-latest
    steps:
      - run: python -m build
  smoke:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - run: python -c "import pkg"
"""

_PUBLISH_ACTION = """\
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""


def gate(needs: str, publish_steps: str = _PUBLISH_ACTION, extra: str = "",
         build_needs: str = "[inventory, gates, identity]") -> str:
    head = _GATE_HEAD.replace("needs: [inventory, gates, identity]",
                              f"needs: {build_needs}", 1)
    return head + extra + f"  publish:\n    needs: {needs}\n" + publish_steps


CANONICAL_GATE = gate("[inventory, gates, identity, build, smoke]")

# The chain form: publish names only smoke, and the rest is reached through
# it. Valid, and the case that separates a transitive closure from a direct
# read of `needs`.
CHAIN_GATE = gate("[smoke]")

# The release workflow both libraries actually shipped, reduced to its shape.
PRE_FIX_RELEASE = """\
name: Release
on:
  push:
    tags: ["v*"]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python -m build && twine check dist/*
  publish:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""

CALLER = """\
name: Release
on:
  push:
    tags: ["v*"]
jobs:
  gate:
    uses: ./.github/workflows/release_gate.yml
    with:
      publish: true
"""

CI_ONLY = """\
name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
"""

TWINE_UPLOAD_WORKFLOW = """\
name: manual upload
on: workflow_dispatch
jobs:
  ship:
    runs-on: ubuntu-latest
    steps:
      - run: |
          python -m build
          twine upload dist/*
"""

MALFORMED = "jobs:\n  build:\n   - this: [is\n  not: yaml\n"


# A job-level `uses:` has no steps at all, so a checker reading only steps sees
# nothing. Both shapes below were invisible before 2026-07-28.
LOCAL_CALL_TO_A_PUBLISHER = """name: sneaky
on: [push]
jobs:
  ship:
    uses: ./.github/workflows/inner.yml
"""

INNER_PUBLISHER = """name: inner
on: workflow_call
jobs:
  upload:
    runs-on: ubuntu-latest
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""

EXTERNAL_CALL = """name: external
on: [push]
jobs:
  ship:
    uses: some-org/shared/.github/workflows/publish.yml@v1
"""


# ---- fixtures --------------------------------------------------------------
def write(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp(prefix="kit_relgate_"))
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8", newline="\n")
    return d


# (label, files or None for "no directory", want_exit, substrings required)
CASES: list[tuple[str, dict[str, str] | None, int, tuple[str, ...]]] = [
    ("the canonical gate plus a caller is CLEAN",
     {"release_gate.yml": CANONICAL_GATE, "release.yml": CALLER, "ci.yml": CI_ONLY},
     0, ("no ungated release path found", "rule 1 (structure) over release_gate.yml")),
    ("the release workflow both libraries shipped is REFUSED",
     {"release.yml": PRE_FIX_RELEASE, "ci.yml": CI_ONLY},
     1, ("is not the vendored release gate", "has no vendored release_gate.yml")),
    ("the gate vendored WITH the old release.yml kept is REFUSED",
     {"release_gate.yml": CANONICAL_GATE, "release.yml": PRE_FIX_RELEASE},
     1, ("is not the vendored release gate",)),
    # `identity` is deliberately detached from `build` here. Dropping it from
    # publish's needs while build still needed it proved nothing: the closure
    # reached it through build, and the case passed. Isolating the rule needs a
    # job that NOTHING else depends on, which is also the realistic shape of the
    # mistake this guards, a gate added to the file and wired to nothing.
    ("a publish job that drops a gate nothing else needs is REFUSED",
     {"release_gate.yml": gate("[inventory, gates, build, smoke]",
                               build_needs="[inventory, gates]")},
     1, ("publishes without depending on identity",)),
    ("the same gate, with identity back in publish's needs, is CLEAN",
     {"release_gate.yml": gate("[inventory, gates, identity, build, smoke]",
                               build_needs="[inventory, gates]")},
     0, ("no ungated release path found", "rule 1 (structure) over release_gate.yml")),
    ("a new job the publish job does not need is REFUSED",
     {"release_gate.yml": gate(
         "[inventory, gates, identity, build, smoke]",
         extra="  licence:\n    runs-on: ubuntu-latest\n    steps:\n      - run: ./licence.sh\n")},
     1, ("publishes without depending on licence",)),
    ("a transitive chain through smoke is CLEAN",
     {"release_gate.yml": CHAIN_GATE},
     0, ("no ungated release path found", "rule 1 (structure) over release_gate.yml")),
    ("a plain `twine upload` step outside the gate is REFUSED",
     {"release_gate.yml": CANONICAL_GATE, "upload.yml": TWINE_UPLOAD_WORKFLOW},
     1, ("is not the vendored release gate", "twine upload")),
    ("a gate that publishes by `twine upload` rather than the action is CLEAN",
     {"release_gate.yml": gate(
         "[inventory, gates, identity, build, smoke]",
         publish_steps="    steps:\n      - run: twine upload dist/*\n")},
     0, ("no ungated release path found", "rule 1 (structure) over release_gate.yml")),
    ("an EMPTY workflow directory is a distinct outcome, not a silent pass",
     {}, 0, ("no workflow files at all",)),
    ("a gate present with no caller PASSES but says only what it verified",
     {"release_gate.yml": CANONICAL_GATE}, 0,
     ("rule 1 (structure) over release_gate.yml", "rule 2 (exclusivity)")),
    # Also asserts the VERIFIED line, because the success sentence used to
    # read "publish depends on every gate, and nothing else publishes" even
    # here, where there is no gate file and the structure rule never ran. A
    # review lens found the checker claiming coverage it did not have, which
    # is the failure it exists to catch one level up.
    ("workflows that never publish are a distinct outcome",
     {"ci.yml": CI_ONLY}, 0,
     ("no publishing job in any workflow", "rule 1 (structure) NOT RUN")),
    ("a missing directory is a CONFIG error, not a clean tree",
     None, 2, ("CONFIG ERROR",)),
    ("unparseable YAML is a CONFIG error, not a clean tree",
     {"release_gate.yml": CANONICAL_GATE, "broken.yml": MALFORMED},
     2, ("CONFIG ERROR",)),
    ("a local job-level `uses:` reaching a publisher is REFUSED",
     {"release_gate.yml": CANONICAL_GATE,
      "sneaky.yml": LOCAL_CALL_TO_A_PUBLISHER, "inner.yml": INNER_PUBLISHER},
     1, ("which publishes", "is not the vendored release gate")),
    ("the sanctioned caller of the gate is NOT counted as a second publisher",
     {"release_gate.yml": CANONICAL_GATE, "release.yml": CALLER},
     0, ("no ungated release path found",)),
    ("an externally-called job is REPORTED as not examined, not assumed benign",
     {"release_gate.yml": CANONICAL_GATE, "external.yml": EXTERNAL_CALL},
     0, ("NOT RESOLVABLE from here", "externally-called job(s) NOT examined")),
    ("a gate whose publish step was removed is REFUSED",
     {"release_gate.yml": gate("[inventory, gates, identity, build, smoke]",
                               publish_steps="    steps:\n      - run: echo nothing\n"),
      "ci.yml": CI_ONLY},
     1, ("has no publishing job",)),
]


def run(checker: Path, workflows: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(checker), "--workflows", str(workflows), *extra],
        capture_output=True,
        text=True,
    )


def check(checker: Path) -> list[str]:
    bad: list[str] = []
    for label, files, want, needles in CASES:
        if files is None:
            d = Path(tempfile.mkdtemp(prefix="kit_relgate_"))
            target = d / "does-not-exist"
        else:
            d = write(files)
            target = d
        try:
            proc = run(checker, target)
            out = proc.stdout + proc.stderr
            if proc.returncode != want:
                bad.append(
                    f"{label}: exit {proc.returncode}, expected {want}. "
                    f"output={out.strip()[:300]!r}"
                )
                continue
            for needle in needles:
                if needle not in out:
                    bad.append(
                        f"{label}: exit code was right but the output never said "
                        f"{needle!r}, so the outcome is not distinguishable. "
                        f"output={out.strip()[:300]!r}"
                    )
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return bad


# ---- mutants ---------------------------------------------------------------
def _action_only(src: str) -> str:
    """Detect the publish action and stop reading run steps."""
    return src.replace(
        '        run = step.get("run")',
        '        run = None',
        1,
    )


def _direct_needs_only(src: str) -> str:
    """Read `needs` once instead of closing over it transitively."""
    return src.replace(
        "    stack = list(needs_of(jobs.get(start) or {}))\n"
        "    while stack:\n"
        "        name = stack.pop()\n"
        "        if name in seen or name not in jobs:\n"
        "            continue\n"
        "        seen.add(name)\n"
        "        stack.extend(needs_of(jobs[name]))\n",
        "    seen.update(n for n in needs_of(jobs.get(start) or {}) if n in jobs)\n",
        1,
    )


def _drop_exclusivity(src: str) -> str:
    """Stop caring that another workflow also publishes."""
    return src.replace(
        "    outside = [(f, j, r) for f, j, r in publishers if f != gate_name]",
        "    outside = []",
        1,
    )


def _config_error_passes(src: str) -> str:
    """Turn an unrunnable check into a clean tree."""
    return src.replace(
        '        print(f"CONFIG ERROR: {exc}", file=sys.stderr)\n        return 2',
        '        print(f"CONFIG ERROR: {exc}", file=sys.stderr)\n        return 0',
        1,
    )


def _needs_something(src: str) -> str:
    """Require the publish job to need SOMETHING rather than everything."""
    return src.replace(
        "                uncovered = sorted(set(gate_jobs) - covered - {name})",
        "                uncovered = [] if covered else sorted(set(gate_jobs) - {name})",
        1,
    )


def _ignore_job_level_uses(src: str) -> str:
    """Read only `steps`, so a job that calls another workflow is invisible."""
    return src.replace(
        '    ref = job.get("uses")\n'
        '    return ref.strip() if isinstance(ref, str) and ref.strip() else None',
        "    return None",
        1,
    )


MUTANTS = {
    "detect only the publish action, never a run step": _action_only,
    "ignore a job-level `uses:` entirely": _ignore_job_level_uses,
    "read `needs` directly instead of transitively": _direct_needs_only,
    "drop the exclusivity rule (a second publisher is fine)": _drop_exclusivity,
    "let a configuration error exit 0": _config_error_passes,
    "require the publish job to need something rather than everything": _needs_something,
}


def main(argv: list[str]) -> int:
    gate_path = HERE / "release_gate.yml"
    if len(argv) == 2 and argv[0] == "--gate":
        gate_path = Path(argv[1]).resolve()
    elif argv:
        print("usage: check_release_gate_mutations.py [--gate <path>]", file=sys.stderr)
        return 2

    src = CHECKER.read_text(encoding="utf-8")

    failures = check(CHECKER)
    if failures:
        print(f"FAILED: {len(failures)} of {len(CASES)} cases", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(f"release-gate contracts hold: {len(CASES)} cases on real workflow files")

    # Best effort, and reported either way. In the kit master directory the
    # canonical gate sits beside this file and is checked; in a vendored
    # deployment it lives under .github/workflows and the repository's own
    # tier-1 test is what checks it there.
    if gate_path.is_file():
        d = write({"release_gate.yml": gate_path.read_text(encoding="utf-8")})
        try:
            proc = run(CHECKER, d)
            if proc.returncode != 0:
                print(
                    f"FAILED: the canonical gate at {gate_path} does not satisfy "
                    f"the checker.\n{proc.stdout}\n{proc.stderr}",
                    file=sys.stderr,
                )
                return 1
            print(f"  canonical gate at {gate_path.name} satisfies rule 1")
        finally:
            shutil.rmtree(d, ignore_errors=True)
    else:
        print(
            f"  NOT CHECKED: no release_gate.yml beside this file ({gate_path}), "
            f"so rule 1 was exercised against fixtures only. In a vendored copy "
            f"this is expected; the repository's own tier-1 test runs the "
            f"checker against .github/workflows."
        )

    survived: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="kit_relgate_mut_"))
    try:
        for name, mutate in MUTANTS.items():
            mutant_src = mutate(src)
            if mutant_src == src:
                survived.append(
                    f"{name}: the mutation did not apply, so this mutant proves "
                    f"nothing. The pattern has drifted from the body."
                )
                continue
            path = tmp / "mutant.py"
            path.write_text(mutant_src, encoding="utf-8", newline="\n")
            broken = check(path)
            if not broken:
                survived.append(f"{name}: SURVIVED, every case still passed")
            else:
                print(f"  mutant denied by {len(broken)} case(s): {name}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if survived:
        print(f"\n{len(survived)} mutant(s) not caught:", file=sys.stderr)
        for s in survived:
            print(f"  {s}", file=sys.stderr)
        return 1
    print(f"all {len(MUTANTS)} mutants denied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
