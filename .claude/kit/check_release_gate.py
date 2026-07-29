# ITACA / pyflightstream shared process kit
# kit-version: 0.2.6
# artifact: check_release_gate.py
# body-sha256: a0ef06b1aa031245e0354eadfbe120e69e38515ce3184eb2ea0b1d68adf34eb3
# canonical-source: BUILT for the kit (0.2.6). The vendored release_gate.yml fixes the release path that USES it; this checker is what proves no other path exists. Without it a repository can vendor the gate, keep its old ungated release.yml, and stay green, which is the class this level registers most: a guard that reports nothing.
# note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
# END KIT PROVENANCE (body verbatim below)
#!/usr/bin/env python3
"""Refuse any path from a git ref to a package index that is not gated.

Usage:
    python check_release_gate.py --workflows <dir> [--gate release_gate.yml]

Exit codes: 0 clean, 1 a violation, 2 configuration error.

WHY A SCANNER AND NOT ONLY THE WORKFLOW
---------------------------------------

The vendored ``release_gate.yml`` fixes the release path that calls it. Its
body is drift-pinned, so a hand-edit reddens the tier-1 test. Neither of those
sees the failure that actually happens: a repository vendors the gate, keeps
its old ``release.yml`` beside it, and the tag push still starts the ungated
one. Every hash matches, every test is green, and the protection is worth
nothing. This checker closes exactly that, and it is the reason the fix is two
artifacts rather than one.

THE TWO RULES
-------------

1. STRUCTURE. Inside the gate workflow, the publishing job's transitive
   ``needs`` closure must cover EVERY other job in the file. Not a named list
   of gates: every job. A named list ages the moment a job is added, and the
   job most likely to be added is a new gate. Stated as "everything", a job
   that publish does not depend on cannot be introduced silently.

2. EXCLUSIVITY. No workflow file OTHER than the gate may publish. Other
   workflows reach a package index only by calling the gate
   (``uses: ./.github/workflows/<gate>``). A second publishing workflow is
   refused whatever its own ``needs`` say, because "publish is gated" has to be
   a property of the repository and not of one file in it.

WHAT COUNTS AS PUBLISHING
-------------------------

A step that uses one of PUBLISH_ACTIONS, or whose ``run`` matches one of
PUBLISH_COMMANDS. Both lists are printed on every run, including the clean
one, so a reader can see what was looked for rather than inferring coverage
from a silent pass. A repository that publishes some other way must add to the
kit's list, in the kit, and re-vendor.

STATED RESIDUAL: uploading a built distribution as a GitHub release asset is
not treated as publishing here. It is a real distribution channel and it is
deliberately out of scope rather than overlooked; widening the vocabulary to
``gh release upload`` would flag the common case of attaching build logs.

Requires PyYAML. If it is not importable this exits 2 and verifies NOTHING,
rather than degrading to a regex scan that would pass a file it could not
read. A checker that silently weakens is the defect it is here to catch.
"""

from __future__ import annotations

import sys
from pathlib import Path

USAGE = "usage: check_release_gate.py --workflows <dir> [--gate release_gate.yml]"

PUBLISH_ACTIONS = ("pypa/gh-action-pypi-publish",)
PUBLISH_COMMANDS = (
    "twine upload",
    "flit publish",
    "poetry publish",
    "hatch publish",
    "uv publish",
)


class ConfigError(Exception):
    """The check could not run. Never reported as a clean tree."""


def _load_yaml():
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ConfigError(
            "PyYAML is not importable, so no workflow file was parsed and "
            "nothing was verified. Add pyyaml to this repository's development "
            "dependencies. This exits 2 rather than falling back to a text "
            "scan, because a checker that quietly weakens is the failure it "
            f"exists to catch. ({exc})"
        ) from exc
    return yaml


def parse(path: Path):
    yaml = _load_yaml()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"{path.name} could not be parsed as YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path.name} does not parse to a mapping, so its jobs cannot be read"
        )
    return data


def jobs_of(doc: dict) -> dict:
    jobs = doc.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def needs_of(job: dict) -> list[str]:
    raw = job.get("needs")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [n for n in raw if isinstance(n, str)]
    return []


def job_uses(job: dict) -> str | None:
    """A job-level ``uses:``, which runs a whole other workflow.

    A job that calls a reusable workflow has no ``steps`` at all, so reading
    only steps made every such job look like it publishes nothing. That is a
    silent hole in the exclusivity rule, not a limitation: a workflow could
    reach a package index entirely through a called workflow and this checker
    would have printed a clean line about it.
    """
    ref = job.get("uses")
    return ref.strip() if isinstance(ref, str) and ref.strip() else None


def publishes(job: dict) -> str | None:
    """The reason this job publishes, or None."""
    steps = job.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses")
        if isinstance(uses, str):
            for action in PUBLISH_ACTIONS:
                if uses.split("@", 1)[0].strip() == action:
                    return f"uses {action}"
        run = step.get("run")
        if isinstance(run, str):
            flat = " ".join(run.split())
            for command in PUBLISH_COMMANDS:
                if command in flat:
                    return f"runs {command!r}"
    return None


def closure(jobs: dict, start: str) -> set[str]:
    """Every job reachable from `start` through `needs`, transitively."""
    seen: set[str] = set()
    stack = list(needs_of(jobs.get(start) or {}))
    while stack:
        name = stack.pop()
        if name in seen or name not in jobs:
            continue
        seen.add(name)
        stack.extend(needs_of(jobs[name]))
    return seen


def check(workflows: Path, gate_name: str) -> tuple[list[str], list[str]]:
    """Return (violations, report lines). Raises ConfigError if unrunnable."""
    if not workflows.is_dir():
        raise ConfigError(
            f"{workflows} is not a directory, so no workflow was read and "
            f"nothing was verified. Pass the path of the repository's "
            f".github/workflows directory."
        )
    files = sorted(p for p in workflows.iterdir()
                   if p.suffix in (".yml", ".yaml") and p.is_file())
    report = [
        f"scanned {len(files)} workflow file(s) in {workflows}",
        f"  publish actions looked for : {', '.join(PUBLISH_ACTIONS)}",
        f"  publish commands looked for: {', '.join(repr(c) for c in PUBLISH_COMMANDS)}",
    ]
    if not files:
        # A DISTINCT outcome, not a silent vacuous pass. An empty directory and
        # a fully gated repository must not print the same thing.
        report.append(
            "  OUTCOME: no workflow files at all. Nothing publishes, and "
            "nothing was verified about a release path that does not exist."
        )
        return [], report

    violations: list[str] = []
    publishers: list[tuple[str, str, str]] = []  # (file, job, reason)
    unresolved: list[tuple[str, str, str]] = []  # jobs calling another workflow
    parsed = {path.name: jobs_of(parse(path)) for path in files}
    for fname, jobs in parsed.items():
        for name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            reason = publishes(job)
            if reason:
                publishers.append((fname, name, reason))
                continue
            ref = job_uses(job)
            if not ref:
                continue
            # A LOCAL call is resolvable: read the called file's own jobs and
            # inherit its publishing status, so `uses: ./.github/workflows/x.yml`
            # where x.yml publishes is caught. An EXTERNAL call is not
            # resolvable from here and is REPORTED rather than assumed benign.
            local = ref.split("@", 1)[0].strip()
            if local.startswith("./.github/workflows/"):
                called = local.rsplit("/", 1)[-1]
                if called == gate_name:
                    # The SANCTIONED route, and the whole point of the design:
                    # a caller reaches the index only through the gate. Counting
                    # it as a second publisher would refuse the one arrangement
                    # rule 2 prescribes.
                    continue
                for cname, cjob in parsed.get(called, {}).items():
                    if isinstance(cjob, dict) and publishes(cjob):
                        publishers.append(
                            (fname, name, f"calls {called}:{cname}, which publishes")
                        )
                        break
            else:
                unresolved.append((fname, name, ref))

    report.append(f"  publishing job(s) found    : {len(publishers)}")
    for f, j, r in publishers:
        report.append(f"    {f}:{j} ({r})")
    if unresolved:
        report.append(
            f"  NOT RESOLVABLE from here   : {len(unresolved)} job(s) call a "
            f"workflow outside this directory, so whether they publish was not "
            f"determined"
        )
        for f, j, r in unresolved:
            report.append(f"    {f}:{j} uses {r}")

    gate = workflows / gate_name
    if not publishers:
        report.append(
            "  OUTCOME: no publishing job in any workflow. This repository has "
            "no release path to gate; rule 1 is still applied below if the "
            "gate file is present."
        )

    # ---- rule 2: exclusivity.
    outside = [(f, j, r) for f, j, r in publishers if f != gate_name]
    if outside:
        for f, j, r in outside:
            violations.append(
                f"{f}:{j} publishes ({r}) but is not the vendored release gate "
                f"({gate_name}). A second publishing path makes the gate "
                f"advisory: the tag push starts this workflow too, and every "
                f"hash and every drift test stays green while it does. Delete "
                f"it and call the gate with `uses: "
                f"./.github/workflows/{gate_name}` and `publish: true`."
            )
    if publishers and not gate.is_file():
        violations.append(
            f"this repository publishes but has no vendored {gate_name}. The "
            f"release path is whatever those workflows do, which is the state "
            f"ITACA-006 and PYFS-018 both report."
        )

    # ---- rule 1: structure of the gate itself.
    if gate.is_file():
        gate_jobs = jobs_of(parse(gate))
        if not gate_jobs:
            violations.append(f"{gate_name} declares no jobs at all")
        else:
            pub = [n for n, j in gate_jobs.items()
                   if isinstance(j, dict) and publishes(j)]
            if not pub:
                violations.append(
                    f"{gate_name} has no publishing job, so it is not the release "
                    f"gate this check can reason about. Either it was replaced, "
                    f"or the publish step was removed and the callers still name "
                    f"it."
                )
            for name in pub:
                covered = closure(gate_jobs, name)
                uncovered = sorted(set(gate_jobs) - covered - {name})
                if uncovered:
                    violations.append(
                        f"{gate_name}:{name} publishes without depending on "
                        f"{', '.join(uncovered)}. Every job in the gate must be "
                        f"in the publishing job's transitive `needs` closure. "
                        f"Both libraries' own release.yml had exactly this shape "
                        f"before kit 0.2.6, publish needing build and build "
                        f"needing nothing, so a tag push uploaded while the tests "
                        f"were still running in a different workflow."
                    )
            report.append(
                f"  {gate_name}: {len(gate_jobs)} job(s), publishing job(s) "
                f"{pub or 'none'}"
            )
    else:
        report.append(f"  {gate_name}: absent from {workflows}")

    # State which rules actually RAN. The success line used to read "publish
    # depends on every gate, and nothing else publishes" unconditionally, so a
    # directory with no gate file and no publisher printed a guarantee about a
    # structure it had never looked at. A checker that describes coverage it
    # does not have is the failure this file exists to catch, one level up.
    ran = [f"rule 2 (exclusivity) over {len(files)} workflow file(s)"]
    ran.append(
        f"rule 1 (structure) over {gate_name}" if gate.is_file()
        else f"rule 1 (structure) NOT RUN: no {gate_name} here to examine"
    )
    if unresolved:
        ran.append(
            f"{len(unresolved)} externally-called job(s) NOT examined"
        )
    report.append("  VERIFIED: " + "; ".join(ran))

    return violations, report


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0
    opts: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if not argv[i].startswith("--"):
            print(f"unrecognized argument {argv[i]!r}\n{USAGE}", file=sys.stderr)
            return 2
        if i + 1 >= len(argv):
            # Distinct from "unrecognized", for the same reason the sibling
            # checker says so: the two mistakes have different remedies.
            print(f"option {argv[i]!r} needs a value\n{USAGE}", file=sys.stderr)
            return 2
        opts[argv[i][2:]] = argv[i + 1]
        i += 2
    unknown = set(opts) - {"workflows", "gate"}
    if unknown or "workflows" not in opts:
        print(
            f"{'unknown option(s) ' + ', '.join(sorted(unknown)) if unknown else '--workflows is required'}"
            f"\n{USAGE}",
            file=sys.stderr,
        )
        return 2

    try:
        violations, report = check(
            Path(opts["workflows"]).resolve(), opts.get("gate", "release_gate.yml")
        )
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2

    # Printed ALWAYS, clean or not. A checker whose passing run says nothing
    # is read as coverage it may not have.
    for line in report:
        print(line)
    # The report is stdout and the violations are stderr, so without this the
    # two streams interleave by buffer flush and a reader sees REFUSED before
    # the inventory that explains it.
    sys.stdout.flush()
    if violations:
        print(f"\nREFUSED: {len(violations)} ungated release path(s)", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print("\nno ungated release path found, within what the VERIFIED line above "
          "actually examined")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
