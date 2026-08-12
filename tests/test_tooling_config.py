"""Tooling-config guard: local hooks and CI run the same ruff (REQ-96).

REQ-80 owns lint and format; REQ-96 promises the pre-commit hooks are a
local mirror of the CI lint job. Three declarations have to agree for
that to be true, and each is checked here: the ruff pinned in the
``[dev]`` extra, the ruff-pre-commit ``rev`` (whose ``vX.Y.Z`` tag
installs ``ruff==X.Y.Z``), and the ruff actually importable in the
environment running this suite. Agreeing on a version is not enough, so
both sides of the mirror are checked too: the CI lint job still runs
both ruff commands, and the hooks still declare both ruff ids with
nothing narrowing what they read. A hook that lints nothing is the same
divergence wearing a matching version number.

The two checks that read ``pyproject.toml`` need ``tomllib``. That used
to make them conditional: against the former 3.10 floor they ran on the
3.13 leg alone and both 3.10 legs skipped them, so the mirror was
verified on one interpreter out of three. The 3.11 floor (REQ-83) puts
``tomllib`` in the standard library on every supported interpreter, so
they now run on every leg with no skip, like the rest of this module.

Markdown exclusion is a project convention, not a requirement: ``.md``
files are prose plus illustrative samples, not sources ``ruff format``
owns, and no ITACA Markdown block is collected as a doctest. The
rationale lives next to the setting in ``pyproject.toml``.
"""

import importlib.metadata
import importlib.util
import itertools
import json
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from hook_entry import (
    assert_is_the_vendored_receipt,
    marker_expression,
    split_wrapper,
)

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RUFF_REPO = "astral-sh/ruff-pre-commit"
RUFF_HOOKS = {"ruff-check", "ruff-format"}
CI_RUFF_COMMANDS = ("ruff check .", "ruff format --check .")
# An allowlist, not a denylist: any other key (args, stages, exclude,
# files, alias) narrows what the hook reads, and a hook that lints
# nothing passes just as quietly as one that is gone.
ALLOWED_KEYS = {"repo", "rev", "hooks", "id"}


def _repo_entries() -> list[str]:
    """Split the config into the items of its top-level ``repos:`` list.

    Splitting on item boundaries rather than on a ``repo:`` line keeps the
    guard indifferent to key order and to quoting inside an entry; nested
    ``- id:`` hook lines sit deeper and never start an item.
    """
    lines = PRE_COMMIT.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = {
        i: len(found.group(1))
        for i, line in enumerate(lines)
        if (found := re.match(r"( *)-\s", line))
    }
    if not starts:
        return []
    outermost = min(starts.values())
    bounds = [i for i, indent in starts.items() if indent == outermost]
    bounds.append(len(lines))
    return ["".join(lines[a:b]) for a, b in itertools.pairwise(bounds)]


def _ruff_repo_block() -> str:
    """Return the one ``repos:`` item that declares the ruff hooks."""
    owned = [entry for entry in _repo_entries() if RUFF_REPO in entry]
    assert len(owned) == 1, (
        f".pre-commit-config.yaml must declare exactly one {RUFF_REPO} repo "
        f"entry, found {len(owned)}; merge the ruff hooks into a single "
        "repos: item pinned to one rev, since that entry is the local "
        "mirror of the CI lint job (REQ-96)."
    )
    return owned[0]


def _pre_commit_ruff_rev() -> str:
    """Return the ruff version the hook installs.

    A ``pre-commit autoupdate --freeze`` rev is a commit sha carrying the
    readable tag in a trailing ``# frozen:`` comment, so that comment is
    the version source whenever it is present.
    """
    block = _ruff_repo_block()
    frozen = re.search(r"^\s*rev:.*#\s*frozen:\s*v?([0-9A-Za-z.]+)", block, flags=re.M)
    if frozen:
        return frozen.group(1)
    found = re.search(r"""^\s*rev:\s*["']?v?([0-9A-Za-z.]+)""", block, flags=re.M)
    assert found, (
        f"the {RUFF_REPO} entry in .pre-commit-config.yaml has no readable "
        "rev; give it `rev: vX.Y.Z` matching the ruff pin in the pyproject "
        "[dev] extra."
    )
    return found.group(1)


def _pyproject() -> dict[str, Any]:
    parsed: dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return parsed


def _dev_ruff_pin() -> str:
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    specs = [spec for spec in dev if re.match(r"ruff(?=$|[=<>~!\[; ])", spec)]
    assert len(specs) == 1, (
        f"the pyproject [dev] extra must list exactly one ruff spec, found "
        f"{specs}; write it as `ruff==X.Y.Z`."
    )
    exact = re.fullmatch(r"ruff==([0-9A-Za-z.]+)", specs[0])
    assert exact, (
        f"the pyproject [dev] ruff spec {specs[0]!r} is not an exact pin; a "
        "range lets CI install a different linter than the pre-commit hook "
        "runs (REQ-96), so write it as `ruff==X.Y.Z`."
    )
    return exact.group(1)


def _ci_gate_commands() -> list[str]:
    """Every command CI's release-gate call actually runs.

    CI no longer spells its checks as `run:` steps: it calls the
    vendored reusable release gate and passes the gate set as a JSON
    array. Reading the parsed gate entries is a STRONGER check than the
    previous text search, because it confirms the command is a gate the
    workflow will execute rather than a string that happens to appear
    somewhere in the file.
    """
    workflow: Any = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    commands: list[str] = []
    for job in workflow.get("jobs", {}).values():
        gates = job.get("with", {}).get("gates")
        if not gates:
            continue
        for entry in json.loads(gates):
            if "run" in entry:
                commands.append(entry["run"])
    assert commands, (
        "the CI workflow passes no `gates` to the release gate, so this "
        "guard has nothing to read and the lint commands below would be "
        "unchecked (REQ-95, REQ-96)."
    )
    return commands


def test_ci_lint_job_runs_both_ruff_commands() -> None:
    commands = " && ".join(_ci_gate_commands())
    missing = [cmd for cmd in CI_RUFF_COMMANDS if cmd not in commands]
    assert not missing, (
        f"the CI gate set no longer runs {missing}; restore it in the `gates` "
        "input, or the pre-commit hooks below mirror a job that stopped "
        "checking what they check (REQ-95, REQ-96)."
    )


def test_pre_commit_declares_both_ruff_hooks_unnarrowed() -> None:
    block = _ruff_repo_block()
    ids = set(re.findall(r"^\s*-\s+id:\s*([\w-]+)", block, flags=re.M))
    assert ids == RUFF_HOOKS, (
        f"the {RUFF_REPO} hooks are {sorted(ids)} but the CI lint job runs "
        f"{list(CI_RUFF_COMMANDS)}; declare exactly {sorted(RUFF_HOOKS)} so "
        "the local mirror covers both (REQ-96)."
    )
    keys = {
        found.group(1)
        for line in block.splitlines()
        if (found := re.match(r"\s*-?\s*([A-Za-z_]+):", line.split("#")[0]))
    }
    narrowing = sorted(keys - ALLOWED_KEYS)
    assert not narrowing, (
        f"the {RUFF_REPO} entry carries {narrowing}, which narrows what the "
        "hooks read or when they run; drop it so both hooks lint the whole "
        "tree from [tool.ruff] in pyproject.toml, as the CI job does "
        "(REQ-96)."
    )


# The contract modules the COMMIT tier must keep. Marking one of these
# `slow` would buy seconds by moving the repository's own invariants off
# the gate a developer actually feels, which is the trade this list exists
# to refuse. Each pins something that is cheap to check and expensive to
# discover late: the NumPy-only import policy, the vendored kit bodies, the
# house style and identifier rules, the locator family's resolution, and
# this file, which pins the tiers themselves.
_COMMIT_TIER_CONTRACT_MODULES = (
    "tests/test_import_policy.py",
    "tests/test_kit_drift.py",
    "tests/test_house_style.py",
    "tests/test_management_root.py",
    "tests/test_tooling_config.py",
    "tests/test_review_gate.py",
    "tests/test_side_effect_guard.py",
    # Added with kit 0.2.16. The spawn walk over `tests` and `itaca` costs
    # 0.46 s, and this module is the REPLACEMENT for the retired window
    # guard that used to be a declared commit-tier guard below. This row is
    # what stops the replacement being marked slow later and quietly
    # leaving the gate the retired one was promoted onto.
    "tests/test_spawn_env.py",
    # Added with kit 0.2.16, and the argument is the same one, which is why
    # leaving it out was a round-one finding from three lenses at once.
    # This module holds the ONLY application of the two-round cap to a real
    # ledger, plus the hermetic locator pair, and it has no module-level
    # `slow` today, so its place in the commit tier was an accident of
    # absence rather than a declaration. Measured: five commit-tier tests,
    # about 1.6 s wall including collection. The count is given rather than
    # a per-test list, because a list of three figures for five members is
    # a number in a unit the reader cannot infer, which is the defect this
    # lane's own worst findings were.
    "tests/test_review_rounds.py",
)

# The list above is MODULE granularity, and that is not enough. A module
# satisfies it by contributing any one test, so a cheap guard inside a
# module marked slow WHOLESALE is invisible to it, and both modules named
# below are marked that way for reasons that have nothing to do with these
# tests. Measured 2026-08-01: none of the four was collected by the commit
# tier, and lane ITA-11 broke the first one, committed, and learned it from
# a reviewer instead of from the gate.
#
# Each entry is a guard over the REPOSITORY'S OWN HYGIENE rather than over
# library behavior, and each catches a defect that an ordinary edit
# introduces. Adding one is a decision: it must carry `@pytest.mark.fast`,
# its measured cost, and the reason it belongs at the cheapest gate.
#
# ON COST, stated exactly because the first version of this comment
# overclaimed it. The durations below are MEASUREMENTS, not an enforced
# threshold: nothing refuses a 0.9 s entry. What IS enforced is the same
# three-second per-test budget every commit-tier test carries, which
# reaches these tests only since the `slow and not fast` repair in
# tests/conftest.py; before that repair a `fast` test was exempt, which a
# reviewer measured with a 3.5 s probe that passed silently.
#
# WHAT THEY COST THE TIER, and the number is the SUM OF THEIR OWN
# DURATIONS measured inside the tier, 0.08 + 0.05 + 0.50, about 0.6 s
# against a p95 target of 30 s. It was four entries and 0.01 s more until
# kit 0.2.16 retired the first one; see the note on that entry below.
#
# It is not a before-and-after difference of tier wall time, and two
# earlier attempts at that were both wrong. The first was a single sample
# each and reported "no measurable cost". The second was a minimum of
# three each and reported 0.9 s; a reviewer replicated the method and got
# 0.2 s, with a run-to-run spread of about 5 s. A method whose noise is
# ten times the quantity cannot resolve it in either direction, so the
# additive cost is measured directly instead and the tier-level
# difference is left unclaimed.
#
# The one cheap test in these modules deliberately NOT promoted is
# `test_a_push_with_no_resolvable_repo_denies_with_the_repo_kind` (0.11 s).
# It is cheap enough and it is about the GATE'S BEHAVIOR rather than about
# this repository's hygiene, so it fails the criterion above. Cheapness is
# a precondition here, never the reason.
_COMMIT_TIER_GUARD_TESTS = (
    # `test_push_gate.py::test_no_spawn_site_bypasses_child_env` was the
    # first entry here, at 0.01 s. It is RETIRED at kit 0.2.16 and its
    # entry goes with it, because this list is exactly the set of tests
    # carrying `@pytest.mark.fast` and the check below asserts that in both
    # directions. Its replacement, `tests/test_spawn_env.py`, needs no
    # marker: it has no module-level `slow`, so it is in the commit tier by
    # default, and it is named in _COMMIT_TIER_CONTRACT_MODULES above so it
    # cannot be moved off that tier without the move being deliberate.
    # 0.06 s. The helper the retired guard was about.
    "tests/test_push_gate.py::test_a_child_process_does_not_start_coverage",
    # 0.06 s. A byte order mark is written by one PowerShell round trip and
    # is invisible in a diff viewer; this repository has done it twice.
    "tests/test_release_integrity.py::test_no_tracked_file_carries_a_byte_order_mark",
    # 0.34 s. The identifier boundary over the versioned tree, which needs
    # no build and so has no reason to wait for the push.
    "tests/test_release_integrity.py::TestIncident0854Guards"
    "::test_guard_1_the_versioned_tree_carries_no_forbidden_identifier",
    # The three below are the known-limitations gate (ITA-2D), and all
    # three measured under 0.005 s: they are pure string work over one
    # already-read file, with no subprocess and no build. They live in a
    # `slow` module and would otherwise inherit that marker, which is what
    # this list exists to make deliberate in the other direction too.
    #
    # They are in the COMMIT tier rather than only at the push because the
    # thing they guard is written by hand in prose. A release note is
    # edited in the same commits as the code it describes, so the moment
    # the disclosure stops matching is a commit, and finding out at the
    # push means finding out after the edit is cold.
    #
    # 0.00 s. The rule itself, seven cases in both directions. This is the
    # only one of the three that would still mean something on a tree whose
    # CHANGELOG was replaced wholesale.
    "tests/test_release_integrity.py::test_the_known_limitations_rule_accepts_and_refuses",
    # 0.00 s. The section bound, which the case list above cannot reach.
    "tests/test_release_integrity.py"
    "::test_a_section_cannot_borrow_the_next_release_s_limitations",
    # 0.00 s. Added in ITA-2D round two, and it is here because the case
    # list STOPPED proving this: with the post-tag exemption in place the
    # h4 case passed by being exempt rather than by the heading matching,
    # so a mutant recognizing only h3 headings survived the whole list
    # clean. This asserts the collector directly, which is the only form
    # the exemption cannot answer for.
    "tests/test_release_integrity.py"
    "::test_the_heading_match_is_level_agnostic_at_the_collector",
    # 0.00 s. The working notes, so the tag is never the first time anyone
    # is asked for the disclosure.
    "tests/test_release_integrity.py::test_the_unreleased_notes_disclose_known_limitations",
)


def _commit_tier_selection() -> str:
    """The marker expression the commit hook ACTUALLY runs (REQ-96).

    REQ-96 promises the pre-commit hooks are a local mirror of CI. The
    selection is the whole of what makes the commit hook a SUBSET rather
    than the suite, so it is the part of that promise this file must read
    from the carrier.

    READ from `.pre-commit-config.yaml`, never written here. The two
    guards below spawn pytest to measure the commit tier, and a literal
    copy of the expression would let them measure a tier the hook does not
    run: the day the hook's selection changes, both would keep reporting
    on the old one and stay green. That is the same defect one level up
    that `_COMMIT_TIER_CONTRACT_MODULES` exists to catch.
    """
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entry = next(
        hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
        if hook["id"] == "pytest-fast"
    )
    _wrapper, argv = split_wrapper(entry)
    return marker_expression(argv)


def _local_hook_stages() -> dict[str, list[str]]:
    """Every local hook id mapped to the stages it declares."""
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    stages: dict[str, list[str]] = {}
    for repo in config["repos"]:
        if repo.get("repo") != "local":
            continue
        for hook in repo["hooks"]:
            stages[hook["id"]] = hook.get("stages", [])
    return stages


def test_the_commit_tier_runs_only_the_fast_subset() -> None:
    """The commit hook must select, or it is the whole suite again.

    BRF-063's diagnosis, and the reason this guard is worth more than the
    config line it checks: the hook was NAMED `pytest-fast` and ran the
    entire suite plus a full `mypy --strict` on every commit, because its
    entry carried no selection at all. A name is not a mechanism, and
    nothing failed when the two disagreed.
    """
    stages = _local_hook_stages()
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entries = {
        hook["id"]: hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
    }
    assert "pytest-fast" in entries, (
        "the commit tier has no pytest hook, so a commit runs no tests at "
        "all. Restore `pytest-fast` with the `not slow` selection."
    )
    entry = entries["pytest-fast"]
    # PARSED, and every disjunct read. A substring check passed for any
    # expression containing the words; checking only the first two tokens
    # then passed `not slow or slow`, which selects the WHOLE suite, and
    # two reviewers measured that (1662 collected against 1579). Refusing
    # the head and ignoring the tail is the same defect one term along, so
    # the terms after the first are read and constrained.
    selection = _commit_tier_selection()
    head, _, tail = selection.partition(" or ")
    assert head.split() == ["not", "slow"], (
        f"the commit hook selects {selection!r}, which does not begin by "
        f"EXCLUDING the slow tier, so it runs the FULL suite on every "
        f"commit. That is the exact defect BRF-063 measured: a hook named "
        f'fast that was not. Select the subset with -m "not slow".'
    )
    widened = {term.strip() for term in tail.split(" or ")} - {""}
    assert widened <= {"fast"}, (
        f"the commit hook selects {selection!r}, widening the tier with "
        f"{sorted(widened)}. Only `or fast` may widen it, for tests declared "
        f"in _COMMIT_TIER_GUARD_TESTS with a measured cost and a reason. Any "
        f"other term readmits a population nothing here has budgeted, and "
        f"`or slow` readmits the entire suite while looking like a narrowing."
    )
    assert "--no-cov" in entry, (
        f"the commit hook runs {entry!r} with coverage on. Coverage is the "
        f"pre-push tier's job; at commit time it buys nothing and costs "
        f"every commit."
    )
    assert stages.get("pytest-fast") == ["pre-commit"], (
        f"the commit hook declares stages {stages.get('pytest-fast')!r}. Pin "
        f"it to pre-commit so it cannot silently become the push tier too."
    )


def test_the_push_tier_runs_the_whole_suite_and_blocks() -> None:
    """Marking a test `slow` must move it, never excuse it.

    This is the load-bearing half of the tier split. `slow` is only
    legitimate because everything it removes from the commit gate still
    runs, with coverage, at a gate that blocks. If the pre-push hook were
    deleted, `slow` would silently become "does not run locally at all",
    and the marker would be an exemption rather than a routing decision.
    """
    stages = _local_hook_stages()
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entries = {
        hook["id"]: hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
    }
    assert "pytest-full" in entries, (
        "there is no pre-push pytest hook, so nothing local runs the tests "
        "the `slow` marker removed from the commit tier. Either restore it "
        "or stop marking tests slow; a marker with no blocking tier behind "
        "it is an exemption."
    )
    assert stages.get("pytest-full") == ["pre-push"], (
        f"the full-suite hook declares stages {stages.get('pytest-full')!r}; "
        f"it must be pre-push, or it is back on every commit."
    )
    # Kit 0.2.15 lets this entry be WRAPPED in the pre-push receipt, which
    # skips a command already passed on an identical tree and environment.
    # Everything below is a claim about WHAT ACTUALLY RUNS, so it reads the
    # PARSED command and not the entry string. The first repair here split
    # on `" -- "` and searched substrings, and a reviewer measured that a
    # wrapper carrying the receipt's name inside a quoted argument passed
    # every assertion while running another program entirely.
    wrapper, argv = split_wrapper(entries["pytest-full"])
    if wrapper is not None:
        assert_is_the_vendored_receipt(wrapper)
    # EQUALITY, not a list of refusals. The first repair here refused `-m`
    # and `--deselect`, and a reviewer measured that `pytest --co` passes
    # it: the tier would collect and run nothing while a guard whose whole
    # purpose is "the blocking tier runs the WHOLE suite" stayed green.
    # Enumerating the ways to run less is a denylist, and this file already
    # states one level up why an allowlist is the only safe shape.
    #
    # An addition here is not forbidden, it is a DECISION, and the previous
    # version of this comment said so and asked the next editor to give the
    # reason in the same edit. This is that edit and this is that reason.
    #
    # THE ONE NARROWING, `-m "not guardproof"`, is the author's decision of
    # 2026-08-11 answering BRF-076: a push must not be allowed to carry a
    # change that breaks BEHAVIOR, and proving that a guard is well built
    # answers a different question, which only changes when the guard
    # changes. It DOES reduce what this tier sees, and pretending otherwise
    # would be the dishonest way to write this. What it does not reduce is
    # what a push is allowed to carry: every marked test is a mutation
    # proof or the tier-speed assertion, none of them exercises library
    # behavior, and all of them run in CI on three legs on every push.
    #
    # WHAT COMPENSATES, at the strength it actually has: since ITA-15 a lane
    # closing its work runs `.claude/tools/closing_ci_check.py`, which
    # refuses to let the work be reported closed over a red, running or
    # unknown CI (INC-20260811-1745-itaca). That is an instruction whose
    # ANSWER is mechanical, not an enforcement that a session ran it, and
    # nothing here makes a red CI block a push. An earlier version of this
    # comment claimed it "blocks the lane CLOSING"; a V and V lens measured
    # that as stronger than the mechanism.
    # `test_the_guardproof_marker_has_a_tier_behind_it` below is what keeps
    # that true, and `test_no_undeclared_test_uses_the_guardproof_marker`
    # is what keeps the marker from being reached for to make a red push
    # green.
    #
    # Everything else stays refused by the same equality. Coverage cannot be
    # dropped, because `--no-cov` is not in this list; `-k`, `-x` and `--co`
    # are not either. The literal is an allowlist and adding to it is again
    # a decision that has to be argued in this comment.
    assert argv == ["pytest", "-m", "not guardproof"], (
        f"the pre-push hook's effective command is {argv!r} and not exactly "
        f"['pytest', '-m', 'not guardproof']. This is the only local gate "
        f"that sees the slow tests and the only one that enforces the 90 "
        f"percent floor (REQ-75). The single permitted narrowing is the "
        f"`guardproof` marker, and it is permitted because a red CI now "
        f"blocks the close. Nothing else may be added: no -k, no -x, no "
        f"--co, no --no-cov, no second marker. If an argument is genuinely "
        f"needed, add it here with the reason it does not narrow what a push "
        f"is allowed to carry."
    )


def test_the_guardproof_marker_has_a_tier_behind_it() -> None:
    """A marker with no tier behind it is an exemption, not a routing call.

    The exact argument this file already makes for `slow`, applied to the
    marker that carries a weaker claim and therefore needs it more. `slow`
    moves a test to pre-push, which BLOCKS; `guardproof` moves it to CI,
    which does not block the push. So the thing that must be true is that CI
    actually runs it: every leg must run a bare `pytest`, with no marker
    selection of its own. If a leg ever narrowed its run the same way the
    pre-push tier now does, a `guardproof` test would run NOWHERE and the
    marker would silently become an exemption.

    That is not hypothetical here. It is one string edit away in a file this
    lane also touched, and nothing else in the suite would notice.
    """
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    gates: list[str] = []
    for job in workflow["jobs"].values():
        raw = (job.get("with") or {}).get("gates")
        if not raw:
            continue
        gates.extend(gate["run"] for gate in json.loads(raw))
    pytest_gates = [run for run in gates if "pytest" in run]
    assert pytest_gates, (
        "no CI gate runs pytest at all, so nothing runs the tests the "
        "`guardproof` marker removed from the pre-push tier. Either restore "
        "them to pre-push or give CI a pytest gate; a marker with no tier "
        "behind it is an exemption."
    )
    # AT LEAST ONE BARE `pytest`, not EVERY gate bare. The property is that
    # CI runs EVERYTHING, and one unrestricted run establishes it; extra
    # gates are additive and cannot subtract from it.
    #
    # The first version required every pytest gate to be exactly `pytest`,
    # which was right when there was one and became wrong in ITA-18: the
    # budget guard now needs its own ISOLATED step, because
    # `budget_isolation.py` refuses to measure a tier from inside a suite.
    # Under the old assertion, adopting that mechanism would have failed
    # this guard, and the tempting fix would have been to drop the isolated
    # step, which is the measurement defect the mechanism exists to prevent.
    bare = [run for run in pytest_gates if run.strip() == "pytest"]
    assert bare, (
        f"no CI gate runs a BARE `pytest`; they are {pytest_gates}. The "
        f"`guardproof` marker is only legitimate because CI runs everything "
        f"the pre-push tier skips, and a narrowed run cannot establish that. "
        f"Additional targeted gates are fine, but one must be unrestricted."
    )


@pytest.mark.parametrize(
    "entry,expected",
    [
        (
            "python .claude/kit/other_wrapper.py --note "
            '".claude/kit/prepush_receipt.py guard --label pytest-full" '
            "-- pytest",
            "which resolves to",
        ),
        (
            "python .claude/kit/prepush_receipt.py status --label pytest-full "
            "-- pytest",
            "subcommand",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard -- pytest",
            "carries no --label",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard --label -- pytest",
            "and no value",
        ),
        (
            "sh -c .claude/kit/prepush_receipt.py guard --label x -- pytest",
            "not a Python interpreter",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard --label pytest-full "
            "--repo /tmp/elsewhere -- pytest",
            "which is not this repository",
        ),
        (
            "python .claude/kit/prepush_receipt.py guard --label pytest-full "
            "--quiet -- pytest",
            "Only --label and --repo are allowed",
        ),
    ],
    ids=[
        "quoted-name",
        "status",
        "no-label",
        "empty-label",
        "not-python",
        "other-repo",
        "unknown-option",
    ],
)
def test_a_wrapper_that_is_not_the_receipt_is_refused(
    entry: str, expected: str
) -> None:
    """Prove the wrapper check can still fail, on the shapes that defeated it.

    The first version of the check above searched the entry STRING, and a
    reviewer measured that the first case here satisfied all seven of its
    assertions across two modules while the program actually executed was
    `other_wrapper.py`. A guard that cannot refuse the thing it names is
    the failure class this repository registers most, so the refusal is
    asserted rather than assumed.

    EACH CASE ASSERTS ITS OWN MESSAGE, and that is not decoration. A bare
    `pytest.raises(AssertionError)` says only that SOMETHING refused, so
    every case would keep passing if one early assertion started catching
    all of them, with the ids still claiming seven distinct reasons. A
    reviewer traced the ordering by hand and found it correct today; this
    is what keeps it correct after the next edit.

    Every case is a wrapper that a reader would plausibly write and that
    must not stand in front of the blocking suite.
    """
    wrapper, argv = split_wrapper(entry)
    assert wrapper is not None, f"the fixture {entry!r} is not even wrapped"
    assert argv[:1] == ["pytest"], "every fixture wraps the real suite"
    with pytest.raises(AssertionError, match=re.escape(expected)):
        assert_is_the_vendored_receipt(wrapper)


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["pytest", "-m", "not slow", "-q"], "carries no `-m`"),
        (["pytest", "-m", "not slow", "-m", "fast"], "2 `-m` options"),
        (["pytest", "-q", "-m"], "ends with `-m`"),
    ],
    ids=["no-selection", "two-selections", "dangling"],
)
def test_the_selection_reader_refuses_what_it_cannot_answer(
    argv: list[str], expected: str
) -> None:
    """The helper both tier guards depend on, falsified directly.

    Two of these are real hazards rather than shapes. pytest honors the
    LAST of several `-m` options while a reader of the config sees the
    first, so a second selection would make both tier guards measure a
    tier the hook does not run, which is the exact defect the helper
    exists to remove. And a missing selection means the hook runs the
    whole suite on every commit, which is BRF-063.

    The first case is deliberately a valid argv with the `-m` REMOVED, so
    the test cannot pass merely because the input was malformed.
    """
    if expected == "carries no `-m`":
        argv = [token for token in argv if token != "-m" and token != "not slow"]
    with pytest.raises(AssertionError, match=re.escape(expected)):
        marker_expression(argv)


def test_the_selection_reader_answers_the_ordinary_case() -> None:
    """The control, so the refusals above are not refusing everything.

    The second form is the one a reviewer measured false-firing: the
    interpreter's own `-m pytest` is a `-m` token and is not a marker
    selection, so counting both refused an ordinary command line as
    ambiguous.
    """
    assert marker_expression(["pytest", "-m", "not slow or fast", "-x"]) == (
        "not slow or fast"
    )
    assert (
        marker_expression(["/usr/bin/python3", "-m", "pytest", "-m", "fast", "-q"])
        == "fast"
    )
    assert (
        marker_expression(
            [r"C:\repo\.venv\Scripts\python.exe", "-m", "pytest", "-m", "not slow"]
        )
        == "not slow"
    )


def test_an_unwrapped_entry_parses_as_unwrapped() -> None:
    """The branch nothing else reaches, and inverting it hides the check.

    Every caller guards the wrapper assertions with `if wrapper is not
    None`, so a `split_wrapper` that returned a wrapper for an unwrapped
    entry, or None for a wrapped one, would silently skip the whole
    receipt check while every other test stayed green. A reviewer
    measured that no test exercised this branch: the module's doctests do
    not run, since the suite collects no `--doctest-modules`.
    """
    assert split_wrapper("pytest") == (None, ["pytest"])
    assert split_wrapper("mypy") == (None, ["mypy"])
    # A `--` that is part of an option, not a separator, does not split.
    assert split_wrapper("pytest --no-cov") == (None, ["pytest", "--no-cov"])
    # The wrapped form, so this test measures the DISTINCTION and not just
    # one side of it.
    assert split_wrapper("python r.py guard --label x -- pytest") == (
        ["python", "r.py", "guard", "--label", "x"],
        ["pytest"],
    )


def test_the_real_entry_passes_the_same_check() -> None:
    """The control: the refusals above are not refusing everything.

    A parametrized refusal test passes just as happily when the assertion
    it calls rejects every input, including the correct one, so the live
    entry is driven through the same function as the positive case.
    """
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entry = next(
        hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
        if hook["id"] == "pytest-full"
    )
    wrapper, argv = split_wrapper(entry)
    assert wrapper is not None, (
        f"the pre-push entry {entry!r} is not wrapped at all, so this control "
        f"is measuring nothing. If the wrapper was deliberately removed, "
        f"remove this test with it."
    )
    assert argv[:1] == ["pytest"], (
        f"the live entry wraps {argv!r}, so the refusals above and this "
        f"control are not comparing the same shape."
    )
    assert_is_the_vendored_receipt(wrapper)


def test_the_coverage_floor_is_declared_with_its_value() -> None:
    """REQ-75: the 90 percent floor, asserted on the CARRIER not the mention.

    THREE REVIEWERS INDEPENDENTLY CAUGHT THE ABSENCE OF THIS TEST, and one
    proved it by mutation: with `--cov-fail-under=90` deleted from
    `addopts`, every guard in this repository stayed green while the
    requirement trace reported REQ-75 as reached. It read as reached only
    because the string `REQ-75` had appeared in an assertion MESSAGE, which
    is the trace's whole notion of reached, so the ratchet did not notice an
    improvement; it reacted to a comment.

    REQ-75 names a THRESHOLD, so the value is asserted and not merely the
    flag. The pre-push tier check beside this one asserts the floor is not
    disabled there; this asserts it exists at all.
    """
    addopts = _pyproject()["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--cov-fail-under=90" in addopts, (
        f"pyproject's pytest addopts is {addopts!r}, which does not carry "
        f"`--cov-fail-under=90`. REQ-75 is the 90 percent coverage floor and "
        f"this is the only place it exists; without it the suite reports "
        f"coverage and enforces nothing, and the requirement trace still "
        f"lists REQ-75 as reached."
    )


def test_the_contract_modules_stay_in_the_commit_tier() -> None:
    """A cheap invariant must not be moved off the gate developers feel.

    The `slow` marker is a routing decision and it is available to any
    module, which makes it available as a way to make a red commit green.
    These modules are the ones where that trade is refused: each is under
    four seconds and each pins something the repository cannot afford to
    discover at push time.
    """
    # ONE collection for all of them. Seven subprocesses cost 4.36 s and
    # tripped this repository's own commit-tier budget, which then failed the
    # aggregate test that runs the subset: the guard was paying more than the
    # thing it guards. Collecting once and reading the node ids is the same
    # question asked once.
    selection = _commit_tier_selection()
    argv = [
        sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-cov",
        "-m", selection, "-p", "no:cacheprovider", "tests",
    ]  # fmt: skip
    done = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(ROOT), env=child_env()
    )
    assert done.returncode == 0, (
        f"collecting the commit tier's own selection failed, so this guard "
        f"cannot say which modules run there:\n{done.stdout[-2000:]}"
    )
    collected = done.stdout.replace("\\", "/")
    for relative in _COMMIT_TIER_CONTRACT_MODULES:
        assert (ROOT / relative).is_file(), (
            f"{relative} is named as a commit-tier contract module but does "
            f"not exist; either it was renamed, in which case update this "
            f"list deliberately, or a guard was deleted."
        )
        # MEASURE THE SELECTION, never the source. Two earlier versions read
        # the file: the first matched `pytest.mark.slow` as a substring and
        # failed against its own assertion text, and the second matched a
        # `pytestmark` line, which a reviewer defeated six ways. Two of the
        # six need nobody to do anything wrong: `ruff format` produces a
        # multiline list the moment a second marker joins `slow`, and a
        # marker applied in `pytest_collection_modifyitems` never appears in
        # the module at all. Asking pytest what the tier would collect is
        # immune to all six, because it is the question the tier asks.
        assert f"{relative}::" in collected, (
            f"{relative} contributes NO test to the commit tier: everything "
            f"in it is marked slow, however that marking is spelled. It is "
            f"on the contract list precisely because it is cheap and "
            f"load-bearing. If it became genuinely slow, that is the "
            f"finding: make it fast again, or take it off this list "
            f"deliberately and say why. Marking one test inside it slow is "
            f"fine and is not what this refuses."
        )
    # Per TEST, for the guards a module-level marker would otherwise hide.
    # Same collection, same question, one notch finer.
    for node in _COMMIT_TIER_GUARD_TESTS:
        assert node in collected, (
            f"{node} is NOT collected by the commit tier's own selection "
            f"({selection!r}). It is a guard over this repository's hygiene "
            f"that costs under half a second, and it lives in a module marked "
            f"slow wholesale for reasons that have nothing to do with it. "
            f"Restore `@pytest.mark.fast` on it, or take it off this list "
            f"deliberately and say why a cheap guard should wait for the "
            f"push. Lane ITA-11 broke the first entry, committed, and learned "
            f"it from a reviewer, because this gate could not see it."
        )


# TWO probe modules, and the split is the point rather than tidiness. The
# parametrize-id case must live in a module with NO module-level marker,
# or the test carries the real `slow` marker and is exempt for a correct
# reason; the first version of this probe put it in the marked module and
# the guard below caught the fixture, not the mechanism.
_BUDGET_PROBE_MARKED = """
import time
import pytest

pytestmark = pytest.mark.slow


@pytest.mark.fast
def test_fast_inside_a_slow_module_is_budgeted() -> None:
    time.sleep(3.5)


def test_a_genuinely_slow_module_member_is_exempt() -> None:
    time.sleep(3.5)
"""

_BUDGET_PROBE_UNMARKED = """
import time
import pytest


@pytest.mark.parametrize("case", ["slow"])
def test_an_unmarked_test_whose_case_id_is_a_marker_name(case: str) -> None:
    time.sleep(3.5)
"""


@pytest.mark.slow
def test_the_commit_tier_budget_reaches_exactly_who_it_should() -> None:
    """The falsifier the budget repair shipped without, on three populations.

    A reviewer measured that the repair's only evidence was a docstring
    narrating a measurement, and that reverting the repair left the whole
    suite green: the four declared `fast` guards cost 0.01 to 0.5 s, so
    nothing in the suite could tell the two versions apart.

    Three cases, one run, because the budget is a session-level verdict:

    1. a `fast` test inside a module marked `slow` MUST be refused. It is
       the population the marker creates, and it was exempt.
    2. an UNMARKED test whose parametrize id is the string `slow` MUST be
       refused. `report.keywords` holds parametrize ids, so the first
       repair exempted this one while fixing case 1.
    3. an ordinary member of the slow module MUST be exempt, or the
       marker has stopped routing anything and the tier is the suite.

    The probe lives under `tests/` and not in `tmp_path`, deliberately:
    this conftest's hooks are what is under test, and they apply to this
    directory. It is removed in a `finally` and its absence is asserted.
    """
    probe_dir = ROOT / "tests" / "_budget_probe"
    probe_dir.mkdir(exist_ok=True)
    (probe_dir / "test_marked.py").write_text(_BUDGET_PROBE_MARKED, encoding="utf-8")
    (probe_dir / "test_unmarked.py").write_text(
        _BUDGET_PROBE_UNMARKED, encoding="utf-8"
    )
    argv = [
        sys.executable, "-m", "pytest", "-m", "not slow or fast",
        "-q", "--no-cov", "-p", "no:cacheprovider", str(probe_dir),
    ]  # fmt: skip
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, cwd=str(ROOT), env=child_env()
        )
    finally:
        # rmtree, not rmdir: the child run leaves a `__pycache__` inside,
        # and an rmdir that raises here would leave a stray test module in
        # the suite's own directory for every later run to collect.
        shutil.rmtree(probe_dir, ignore_errors=True)
    assert not probe_dir.exists(), f"the probe directory survived at {probe_dir}"

    output = done.stdout + done.stderr
    assert done.returncode != 0, (
        f"the budget did not refuse a 3.5 s test in the commit tier at all, "
        f"so it is enforcing nothing:\n{output[-3000:]}"
    )
    assert "test_fast_inside_a_slow_module_is_budgeted" in output, (
        f"a `fast` test inside a module marked slow was NOT budgeted. That "
        f"is the population the marker creates, and exempting it makes "
        f"`fast` a way to put an arbitrarily slow test on every developer's "
        f"commit.\n{output[-3000:]}"
    )
    assert "test_an_unmarked_test_whose_case_id_is_a_marker_name" in output, (
        f"an UNMARKED test was exempted because its parametrize id is the "
        f"word `slow`. The budget must read MARKERS, not the keywords "
        f"namespace, which holds ids, fixture names and class names.\n"
        f"{output[-3000:]}"
    )
    assert "test_a_genuinely_slow_module_member_is_exempt" not in output, (
        f"an ordinary member of a module marked slow was budgeted, so the "
        f"marker has stopped routing and the commit tier is the whole "
        f"suite.\n{output[-3000:]}"
    )


def test_no_undeclared_test_uses_the_fast_marker() -> None:
    """The other direction: collected-by-`fast` must equal the declared list.

    The contract check above asserts list -> collected, so it catches a
    guard that LOST its marker. Nothing asserted collected -> list, so a
    fifth `@pytest.mark.fast` added later would enter the commit tier with
    neither a measured cost nor a stated reason, which the list's own
    preamble declares mandatory. `fast` is the only route into that tier
    that a module-level marker does not govern, so it is the one that
    needs both directions.

    IT RUNS IN THE COMMIT TIER, and the first version of it did not. That
    version carried `slow` on an argument a reviewer measured false: it
    said the sibling above "already spends about four seconds" and that a
    second collection "would break the three-second per-test budget". The
    budget is PER TEST, not aggregate, so two collections in two tests
    break nothing; measured warm, the sibling is 1.74 s and this is
    1.65 s, against a 3.0 s per-test budget and a tier of about 18 s
    against a 30 s p95.

    The consequence of that false argument was not the seconds. It put the
    guard that closes a hole one tier LATER than the edit that opens it:
    an undeclared `fast` marker would have entered the commit tier and
    been caught only at the push. A guard belongs at the gate where the
    mistake it catches is made.
    """
    argv = [
        sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-cov",
        "-m", "fast", "-p", "no:cacheprovider", "tests",
    ]  # fmt: skip
    done = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(ROOT), env=child_env()
    )
    assert done.returncode == 0, (
        f"collecting `-m fast` failed, so this guard cannot say which tests "
        f"carry the marker:\n{done.stdout[-2000:]}"
    )
    # The trailing `[case]` is stripped, because the unit of admission is
    # the TEST and not the case. Comparing raw node ids deadlocked a
    # legitimate change: parametrizing a declared guard makes collection
    # yield `...::test_x[a]` while the list holds `...::test_x`, firing
    # BOTH assertions at once and forcing every parameter id into a list
    # whose stated unit is one guard with one measured cost.
    collected = {
        re.sub(r"\[.*\]$", "", line.strip())
        for line in done.stdout.replace("\\", "/").splitlines()
        if "::" in line and line.strip().startswith("tests/")
    }
    declared = set(_COMMIT_TIER_GUARD_TESTS)
    undeclared = sorted(collected - declared)
    assert not undeclared, (
        f"these tests carry `@pytest.mark.fast` and are not in "
        f"_COMMIT_TIER_GUARD_TESTS: {undeclared}. The marker admits a test to "
        f"the commit tier, which every developer pays for on every commit, so "
        f"admission is a decision that is written down with its measured cost "
        f"and its reason. Add the entry, or drop the marker."
    )
    missing = sorted(declared - collected)
    assert not missing, (
        f"these tests are declared commit-tier guards but do not carry "
        f"`@pytest.mark.fast`: {missing}. The sibling contract check may pass "
        f"anyway if their module stops being slow, which would make this list "
        f"silently inert."
    )


#: Every test admitted to the `guardproof` marker, with what it proves.
#: The marker REMOVES a test from the only local tier that blocks a push, so
#: admission is a decision that is written down, exactly as
#: `_COMMIT_TIER_GUARD_TESTS` above records admission in the other direction.
#:
#: WHY THIS LIST EXISTS AT ALL, recorded because the omission is the finding:
#: `pyproject.toml` claimed "tests/test_tooling_config.py refuses an
#: undeclared use for that reason" from the moment the marker was created,
#: and no such refusal existed. FOUR of the five reviewer lenses in round one
#: found it independently. A claimed guard that does not exist is worse than
#: an absent one, because it is the sentence the next editor leans on before
#: marking a behavior test. The claim is now true.
#:
#: THE RULE FOR ADDING A ROW: the test's subject must be a GUARD'S OWN
#: MACHINERY, not behavior. A mutation companion asserting that a checker can
#: still fail qualifies. A slow behavior test does not, whatever it costs;
#: `slow` is the marker for cost, and it routes to a tier that still blocks.
_GUARD_PROOF_TESTS = (
    # The mutation companions: each runs a checker's own mutants.
    "tests/test_closing_ci_check.py::test_the_closing_check_can_still_fail",
    "tests/test_execution_guard.py::test_the_execution_guard_can_still_fail",
    "tests/test_plan_validator.py::test_the_plan_checker_can_still_fail",
    "tests/test_push_gate.py::test_the_push_gate_can_still_fail",
    "tests/test_prepush_receipt.py::test_the_receipt_can_still_fail",
    "tests/test_release_integrity.py::test_the_release_gate_checker_can_still_fail",
    "tests/test_release_integrity.py::test_the_version_identity_checker_can_still_fail",
    "tests/test_release_integrity.py::TestIncident0854Guards::test_guard_1_can_still_fail",
    "tests/test_release_integrity.py::TestIncident0854Guards::test_guard_3_can_still_fail",
    "tests/test_review_rounds.py::test_the_round_cap_checker_can_still_fail",
    "tests/test_side_effect_guard.py::test_the_side_effect_guard_can_still_fail",
    "tests/test_spawn_env.py::test_the_spawn_checker_can_still_fail",
    # Not a mutation companion, and admitted on the same rule rather than an
    # exception to it: its subject is the TIER, which is machinery. It also
    # cannot run in the tier it measures without recursing.
    "tests/test_tooling_config.py::test_the_commit_tier_subset_is_actually_fast",
)


@pytest.mark.slow
def test_no_undeclared_test_uses_the_guardproof_marker() -> None:
    """Collected-by-`guardproof` must equal the declared list, both ways.

    MARKED `slow` IN ITA-17, and the demotion is a loss that is recorded
    rather than presented as neutral. The sibling below argues that a guard
    belongs at the gate where the mistake it catches is made, and the
    mistake here (adding `@pytest.mark.guardproof`) is made while editing a
    test file, so the commit tier was the right home. It runs at pre-push
    instead, which still BLOCKS, and in CI.

    WHY: this test spawns a full `--collect-only`, and it was the THIRD such
    subprocess in the commit tier. `ITC-20260811-2120` registered the
    problem when there were three; it then fired for real and blocked this
    lane's own commit, at 3.03s here and 3.25s on
    `test_the_contract_modules_stay_in_the_commit_tier`, which this lane did
    not touch. Two reviewer lenses had measured the same class earlier in
    the day. Removing the collection this lane ADDED is the change that
    undoes what this lane did, rather than raising a budget its own message
    forbids raising or demoting a test somebody else owns.

    THE REAL FIX IS STILL OPEN and is `ITC-20260811-2120`: collect ONCE for
    `-m "fast or guardproof"` and attribute each node to its marker, so one
    subprocess serves both registries. That is a design change and this is a
    lane closing at night, so it is registered rather than attempted here.

    The exact shape of `test_no_undeclared_test_uses_the_fast_marker` above,
    pointed at the marker that needs it MORE. `fast` admits a test to a tier
    that costs developers time; `guardproof` removes one from the only local
    tier that blocks a push, so an undeclared use is not a cost mistake, it
    is a test that stops gating.

    Both directions, for the reasons the sibling states: collected minus
    declared catches a behavior test being marked to get a red push through,
    which is the failure `pyproject.toml` names; declared minus collected
    catches a row left behind after a test is renamed or the marker dropped,
    which would make this list silently inert.
    """
    argv = [
        sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-cov",
        "-m", "guardproof", "-p", "no:cacheprovider", "tests",
    ]  # fmt: skip
    done = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(ROOT), env=child_env()
    )
    assert done.returncode == 0, (
        f"collecting `-m guardproof` failed, so this guard cannot say which "
        f"tests carry the marker:\n{done.stdout[-2000:]}"
    )
    collected = {
        re.sub(r"\[.*\]$", "", line.strip())
        for line in done.stdout.replace("\\", "/").splitlines()
        if "::" in line and line.strip().startswith("tests/")
    }
    declared = set(_GUARD_PROOF_TESTS)
    undeclared = sorted(collected - declared)
    assert not undeclared, (
        f"these tests carry `@pytest.mark.guardproof` and are not in "
        f"_GUARD_PROOF_TESTS: {undeclared}. The marker REMOVES a test from the "
        f"pre-push tier, the only local gate that blocks, so it must never be "
        f"reached for to make a red push green. Admit it here with the reason "
        f"its subject is a guard's machinery rather than behavior, or drop the "
        f"marker and let it run at pre-push."
    )
    missing = sorted(declared - collected)
    assert not missing, (
        f"these tests are declared guard proofs but do not carry "
        f"`@pytest.mark.guardproof`: {missing}. Either the marker was dropped, "
        f"in which case they now run at pre-push and the row should go, or the "
        f"test was renamed and this list is silently inert."
    )


def _budget_isolation() -> Any:
    """Load the vendored `budget_isolation.py` by path.

    Loaded rather than imported because `.claude/kit` is not on `sys.path`
    and must not be put there: every other kit body in this repository is
    invoked as a SUBPROCESS, and adding a vendored directory to the import
    path would make any of them importable by accident. This one is
    documented as an import, so it is loaded explicitly and only here.
    """
    spec = importlib.util.spec_from_file_location(
        "budget_isolation", ROOT / ".claude" / "kit" / "budget_isolation.py"
    )
    assert spec is not None and spec.loader is not None, (
        "could not load .claude/kit/budget_isolation.py; the budget guard "
        "below cannot decide whether it is isolated."
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.slow
@pytest.mark.guardproof
def test_the_commit_tier_subset_is_actually_fast() -> None:
    """Measure the aggregate, because no per-test rule can see it.

    `tests/conftest.py` bounds each unmarked test at three seconds, which
    stops one slow test from landing unmarked. It cannot see a thousand
    fast tests adding up to a slow tier, and that is the shape this budget
    would actually drift into.

    So this runs the real commit-tier selection in a subprocess and
    measures it. It is itself marked `slow`, for two reasons: it costs
    about what the subset costs, and a fast-tier test that runs the fast
    tier would recurse.

    The budget here is the WALL time of one run against the p95 target of
    30 seconds. A single sample is not a p95, and this test does not
    pretend otherwise: it is a ceiling that catches drift, and the p95 is
    measured deliberately when the tiers change. The margin is generous
    for that reason.

    NOT YET ROUTED THROUGH `budget_isolation.py`, and the reason is a
    dependency this lane could not take. ITA-18 vendored that body, which
    is the right mechanism: a budget guard measures its tier only in the
    conditions that tier runs in, and inside the full suite this test spawns
    its child after minutes of artifact building, so the child pays cold
    imports against a budget that never expected them.

    WHAT BLOCKS THE WIRING, measured rather than assumed. Its contract is
    that in CI an undeclared skip is a CONFIGURATION ERROR rather than a
    skip, so wiring it REQUIRES a CI step that runs this test alone with
    `KIT_BUDGET_ISOLATED=1`. Adding that step to `ci.yml` alone fails
    `test_house_style.py::test_every_gate_call_passes_the_same_checks_and_toolchain`,
    which requires the three release-gate calls to carry identical inputs,
    so it would also have to go into `release.yml`'s two calls. That is the
    release path, which ITA-18 was told not to touch.

    Registered as `ITC-20260812-0030`. Until then this measures in every
    session it is collected in, which is exactly the defect the mechanism
    exists to remove, and the 60 s ceiling is generous for that reason.
    """
    # `child_env()` strips the COV_CORE_* variables. Without it the nested
    # run inherits the parent's coverage subprocess hooks, which is how a
    # spawned pytest has aborted here AFTER every test passed; the whole
    # suite is under coverage when this test runs, and this is the one
    # test in the file that spawns pytest rather than a checker.
    # The argument list is built FIRST, and that used to be load-bearing
    # rather than cosmetic: the retired
    # `test_push_gate.py::test_no_spawn_site_bypasses_child_env` scanned a
    # 14-line window from each spawn site and reported this call as
    # bypassing the helper when the arguments were inlined, because
    # `env=child_env()` fell outside the window. That pressure is gone at
    # kit 0.2.16: `check_spawn_env.py` judges the CALL, so an `env=` a
    # hundred lines from its own opening parenthesis is still on its own
    # call. The shape is kept because it reads better, not because a guard
    # requires it.
    selection = _commit_tier_selection()
    argv = [
        sys.executable, "-m", "pytest",
        "-m", selection, "-q", "--no-cov", "-p", "no:cacheprovider",
    ]  # fmt: skip
    started = time.monotonic()
    done = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(ROOT), env=child_env()
    )
    elapsed = time.monotonic() - started
    assert done.returncode == 0, (
        f"the commit-tier subset does not pass on its own:\n{done.stdout[-3000:]}"
    )
    assert elapsed < 60.0, (
        f"the commit-tier subset took {elapsed:.1f}s in this run, against a "
        f"p95 target of 30 s and a drift ceiling of 60 s. The subset has "
        f"grown into the tier it was split out of. Find what got slow "
        f"(pytest --durations=25 -m {selection!r}) and mark it or fix it; "
        f"do not raise this ceiling."
    )


def test_pre_commit_declares_no_global_skip() -> None:
    text = PRE_COMMIT.read_text(encoding="utf-8")
    skipping = sorted(set(re.findall(r"^(exclude|files):", text, flags=re.M)))
    assert not skipping, (
        f".pre-commit-config.yaml sets a top-level {skipping}, which hides "
        "part of the tree from every hook while CI still lints all of it; "
        "remove it so the local mirror stays whole (REQ-96)."
    )


def test_installed_ruff_matches_the_pre_commit_rev() -> None:
    try:
        installed = importlib.metadata.version("ruff")
    except importlib.metadata.PackageNotFoundError:
        pytest.fail(
            "ruff is not installed in this environment, so the REQ-96 mirror "
            'cannot be verified; run `pip install -e ".[dev]"` before pytest.'
        )
    rev = _pre_commit_ruff_rev()
    assert installed == rev, (
        f"this environment has ruff {installed} but the pre-commit hook "
        f'installs {rev}; run `pip install -e ".[dev]"` so local runs '
        "enforce the same rule set as CI (REQ-96)."
    )


def test_dev_ruff_pin_matches_pre_commit_rev() -> None:
    dev_pin, rev = _dev_ruff_pin(), _pre_commit_ruff_rev()
    assert dev_pin == rev, (
        f"REQ-96 mirror broken: the pyproject [dev] extra installs ruff "
        f"{dev_pin} while the pre-commit hook runs ruff {rev}; move both to "
        "one version in the same commit."
    )


def test_ruff_excludes_markdown_from_the_formatter_scope() -> None:
    excluded = _pyproject()["tool"]["ruff"].get("extend-exclude", [])
    assert "*.md" in excluded, (
        "[tool.ruff] extend-exclude must list '*.md' so a later ruff release "
        "cannot extend the formatter over prose and illustrative samples; "
        f"got {excluded}. The rationale is next to the setting in pyproject."
    )


def test_the_mypy_missing_import_exemption_stays_scoped_to_generated_modules() -> None:
    """`ignore_missing_imports` may not widen past the modules that earn it.

    Two overrides carry it, for two different and narrow reasons:
    `pandas` is an optional lazily imported bridge whose stubs are not a
    dependency (REQ-84), and `itaca.core._version` is GENERATED by
    setuptools-scm and gitignored, so it is absent from any tree that
    has not been built.

    The second is the one that needs a guard. Without the override,
    `mypy --strict` fails on a fresh clone or a detached worktree for a
    reason the developer did not cause, and the obvious remedy for that
    noise is a blanket `ignore_missing_imports` at `[tool.mypy]` or a
    wildcard over `itaca.*`. Either would silently exempt the whole
    package from the gate REQ-78 states, and nothing else would notice.
    So the exemption is pinned to exactly the modules that justify it,
    and this fails if it ever grows or moves to the top level.
    """
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy = config["tool"]["mypy"]

    # The gate itself, first. Pinning the exemption while `strict` or
    # `files` can move is guarding the lock and not the door.
    assert mypy.get("strict") is True, (
        "pyproject.toml no longer sets strict = true under [tool.mypy]; "
        "REQ-78 states mypy --strict on the public API."
    )
    assert mypy.get("files") == ["itaca"], (
        f"[tool.mypy] files is {mypy.get('files')!r}, not ['itaca']; "
        f"narrowing it removes packages from the gate without removing the "
        f"gate."
    )

    # Every knob that can suppress an error, not just the one this
    # repository happens to use. An override reaching the same weakening
    # by `follow_imports = "skip"` or `ignore_errors` over `itaca.*`
    # would leave the exemption set below untouched while mypy stopped
    # seeing most of the package.
    suppressors = ("ignore_missing_imports", "ignore_errors", "follow_imports")
    for knob in suppressors:
        assert knob not in mypy, (
            f"pyproject.toml sets {knob} at [tool.mypy], which applies it to "
            f"EVERY module in the package and turns the REQ-78 gate off "
            f"wholesale. Scope it to the module that needs it instead."
        )
    assert "disable_error_code" not in mypy, (
        "pyproject.toml disables error codes at [tool.mypy], repository-wide."
    )

    suppressing: set[tuple[str, str]] = set()
    for override in mypy.get("overrides", []):
        used = tuple(knob for knob in suppressors if override.get(knob))
        if not used and not override.get("disable_error_code"):
            continue
        for module in override["module"]:
            for knob in used:
                suppressing.add((module, knob))
            if override.get("disable_error_code"):
                suppressing.add((module, "disable_error_code"))

    assert suppressing == {
        ("pandas", "ignore_missing_imports"),
        ("pandas.*", "ignore_missing_imports"),
        ("itaca.core._version", "ignore_missing_imports"),
    }, (
        f"the mypy error suppression covers {sorted(suppressing)}. It is "
        f"allowed for the optional pandas bridge (REQ-84) and for the "
        f"generated, gitignored itaca/core/_version.py, by missing-import "
        f"only, and for nothing else. A wildcard over itaca.* by any knob "
        f"would turn the strict gate off for the package it exists to check."
    )


# The suite spawns interpreters to exercise tools it cannot import: mypy
# on a snippet, and `build` on the repository. Those tools have to be in
# the extra the contributing guide and CI install, or the test errors on
# every machine but the author's. That is ITACA-015's defect class, whose
# fix added one package and no guard, so it recurred the moment a test
# spawned `build`. Discovering the spawn sites is what makes the rule
# survive the next tool.
_SPAWNED_MODULE = re.compile(r'sys\.executable,\s*"-m",\s*"([a-zA-Z_][\w.]*)"')
_STDLIB_SPAWNS = frozenset({"pytest", "pip", "venv", "json.tool"})


def _requirement_names(requirements: list[str]) -> set[str]:
    return {
        re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower() for line in requirements
    }


def test_every_module_the_suite_spawns_is_declared_in_the_dev_extra() -> None:
    """A tool the suite runs but nobody installs is a test that only passes here.

    `pytest` and `pip` are exempt because whatever ran this file already
    provides them.
    """
    declared = _requirement_names(
        _pyproject()["project"]["optional-dependencies"]["dev"]
    )
    spawned: dict[str, str] = {}
    for path in sorted((ROOT / "tests").rglob("*.py")):
        for module in _SPAWNED_MODULE.findall(path.read_text(encoding="utf-8")):
            spawned.setdefault(module, path.relative_to(ROOT).as_posix())
    # Pinned as a SET, not a floor. The pattern recognizes one syntactic
    # shape, so a tool spawned as a console script or through a variable
    # is invisible to it while the floor stays satisfied by the two sites
    # already here. A difference either way is a deliberate edit.
    # `pytest` joined the set on 2026-07-30 with the tier split: the
    # aggregate commit-tier measurement in this file spawns the fast subset
    # in a subprocess, because wall time is the thing it exists to measure
    # and it cannot measure that from inside the same run. It is the
    # deliberate edit this assertion's own message asks for, not a
    # widening: the docstring above already exempted pytest from the
    # installation half, since whatever ran this file provides it.
    assert set(spawned) == {"mypy", "build", "pytest"}, (
        f"the spawn-site scan found {spawned}; if a tool was added, declare "
        "it in the [dev] extra and add it here, and if one moved out of the "
        "recognized shape, widen the pattern rather than the exemption"
    )
    missing = {
        module: site
        for module, site in spawned.items()
        if module not in _STDLIB_SPAWNS and module not in declared
    }
    assert not missing, (
        f"the suite spawns {missing} (module: spawn site) but the [dev] extra "
        f"declares {sorted(declared)}; a tool the tests run must be installed "
        'by `pip install -e ".[dev]"`, or the test errors wherever the author '
        "did not already have it (ITACA-015's class)."
    )


def test_the_vendored_budget_isolation_decides_the_way_its_contract_says() -> None:
    """The mechanism ITC-20260811-2120 needs, proven to work in this tree.

    ITA-18 vendored `budget_isolation.py` and did NOT wire it into
    `test_the_commit_tier_subset_is_actually_fast`, because wiring requires
    a CI step that would have to be added to the release path as well; that
    is `ITC-20260812-0030`. A body vendored and called by nothing is the
    shape this repository already names for `ITACA-006`, so it is exercised
    here instead: loadable, and correct on the two decisions that matter.

    ONE ITEM MEASURES, a suite SKIPS. Those are the two branches a consumer
    depends on, and the boundary between them is the body's own constant
    rather than anything this test restates.

    NOT ASSERTED HERE: the CI branch, where an undeclared skip becomes a
    CONFIGURATION ERROR. Reaching it means setting `CI` in this process,
    which would change the behavior of anything else reading it in the same
    session. It is the branch `ITC-20260812-0030` will exercise for real
    when the isolated step exists.
    """
    module = _budget_isolation()
    assert module.reason_to_skip(1) is None, (
        "an isolated invocation must MEASURE. If this returns a reason, the "
        "budget guard would never run anywhere and the mechanism deletes the "
        "guard it exists to protect."
    )
    suite = module.reason_to_skip(1500)
    assert suite, (
        "a suite-sized session must SKIP, or the guard measures a tier under "
        "conditions that tier never runs in, which is ITC-20260802-2200."
    )
    assert "isolation" in suite and "KIT_BUDGET_ISOLATED" in suite, (
        f"the skip reason must name the remedy, or a reader sees a skip with "
        f"no way to act on it: {suite!r}"
    )
