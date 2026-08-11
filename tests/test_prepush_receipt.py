"""The pre-push receipt: what it must refuse, and that it can still fail.

Usage example (TDD anchor)::

    done = subprocess.run(
        [sys.executable, str(_RECEIPT), "status", "--label", "pytest-full",
         "--", "pytest"],
        capture_output=True,
        text=True,
        env=child_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr

The pre-push tier runs the suite MINUS the `guardproof` guard proofs, with
coverage, plus `mypy --strict`. Measured on this repository on 2026-08-01,
BEFORE that split: 12.1 minutes for the suite alone, 12.5 to 13 for the
whole hook, against about 16 seconds for the commit tier, and CI then runs
the same suite on three legs. The receipt (kit 0.2.15) stops it re-running
on content that already passed it.

Those minutes are what the receipt was built for and they are no longer
what the tier costs: the `guardproof` split of 2026-08-11 moved about
twelve minutes of mutation proofs into CI, and the tier is now about five
minutes. The 2026-08-01 figure is kept rather than replaced because it is
the measurement that JUSTIFIED this artifact; the receipt is not less
useful at five minutes, and a reader comparing the two should know which
tier each was measured on.

THE REASON IS NOT THE DUPLICATION, it is the fragility. In two lanes the
push step failed five separate ways and none was about the code. A step
that expensive and that fragile gets routed around eventually, and the
way it gets routed around is `--no-verify`. That is the outcome the
artifact exists to prevent, which is why it adds no environment variable
that skips it and why this repository added none either.

WHAT IS ASSERTED HERE, and what deliberately is not. The mechanism's
whole acceptance criterion is that EVERY unknown state runs the suite:
absent, empty, truncated, malformed, key-mismatched, expired, clock moved
backwards, any exception inside the mechanism. Proving that is the
companion's job, on real git repositories, and it is invoked below rather
than trusted. What this module adds is the half a companion cannot see:
that the receipt is wired to THIS repository's own pre-push tier and
answers about it.

THE THREE-ANSWER CHECK, and a claim this module made about itself and
had to withdraw. It first said the brief's RUN then SKIP then RUN
sequence "cannot be reproduced as a test", because the SKIP leg needs a
green run of the 12-minute suite. A reviewer measured that this is false
and named the shape: a throwaway git repository and a trivial command
give all three answers in under a second, and the fixture being written
by the mechanism is the point rather than the objection, because the key
is derived from content that the test then changes. That test is
`test_the_three_answers_on_a_throwaway_repository` below.

What is NOT reproduced here is the same sequence against THIS repository's
own 12-minute tier. That measurement was taken by hand in lane ITA-11 and
its output is in the lane's plan entry: WOULD RUN with no receipt, SKIP
after the suite passed (1641 passed, EXIT 0, 665.3 s), WOULD RUN with one
tracked file changed, and SKIP again once its bytes were restored.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import child_env  # tests/ is on sys.path under pytest prepend mode
from hook_entry import assert_is_the_vendored_receipt, split_wrapper

_ROOT = Path(__file__).resolve().parents[1]
_KIT = _ROOT / ".claude" / "kit"
_RECEIPT = _KIT / "prepush_receipt.py"
_RECEIPT_MUTATIONS = _KIT / "prepush_receipt_mutations.py"
_RECEIPT_PATH = _ROOT / ".claude" / ".prepush_receipt.json"
_PRE_COMMIT = _ROOT / ".pre-commit-config.yaml"
_GITIGNORE = _ROOT / ".gitignore"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=child_env(),
        cwd=str(_ROOT),
    )


def test_the_vendored_receipt_is_present() -> None:
    """A checker loaded by path fails loudly if it is missing."""
    for artifact in (_RECEIPT, _RECEIPT_MUTATIONS):
        assert artifact.is_file(), f"vendored kit artifact missing at {artifact}"


def test_the_receipt_is_wired_to_this_repository_s_blocking_tier() -> None:
    """The artifact must WRAP the pre-push suite, not merely sit beside it.

    A vendored mechanism nothing invokes is the shape this repository
    already names for `ITACA-006`, one level up. The sibling test in
    `tests/test_tooling_config.py` asserts the wrapped command is still
    the whole suite with coverage; this asserts the wrapper is there at
    all and is the vendored copy rather than some other path.
    """
    config = yaml.safe_load(_PRE_COMMIT.read_text(encoding="utf-8"))
    entries = {
        hook["id"]: hook["entry"]
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo["hooks"]
    }
    entry = entries["pytest-full"]
    wrapper, argv = split_wrapper(entry)
    assert wrapper is not None, (
        f"the blocking tier runs {entry!r}, which is not wrapped at all, so "
        f"it does not go through the vendored pre-push receipt. Wrap it as "
        f"`python .claude/kit/prepush_receipt.py guard --label pytest-full "
        f"-- pytest`, or the suite runs a second time on content that "
        f"already passed it."
    )
    # PARSED and positional, never a substring. The first version of this
    # test searched the entry string for the receipt's path and for
    # `--label pytest-full`, and a reviewer measured that both needles sit
    # happily inside a quoted argument of an entirely different program.
    label = assert_is_the_vendored_receipt(wrapper)
    assert label == "pytest-full", (
        f"the blocking tier's receipt carries the label {label!r} and not "
        f"the hook id 'pytest-full'. A non-empty label is not enough: the "
        f"label is part of the key, so two hooks sharing one would "
        f"authorize each other's skip, and a label that drifts from its "
        f"hook id makes that collision invisible to a reader."
    )
    assert argv[:1] == ["pytest"], (
        f"the wrapped command is {argv!r}. The receipt must stand in front "
        f"of the suite itself; wrapping anything else means the blocking "
        f"tier blocks on something other than the tests."
    )


def test_the_receipt_file_can_never_be_committed() -> None:
    """`.gitignore` must cover it, and git must agree that it does.

    Not needed for the key, which excludes the path by exact name. Needed
    because two independent walks in this repository read tracked plus
    untracked-but-not-ignored paths, the shipped-surface scan and the
    house-style scan, and both would otherwise open a local state file
    that records this machine's HEAD and command line.

    Asserted through `git check-ignore` rather than by reading the
    `.gitignore` text, because the text is a mention and git's answer is
    the carrier. A pattern that is present but shadowed by a later
    negation would satisfy the mention and not the behavior.
    """
    assert ".claude/.prepush_receipt.json" in _GITIGNORE.read_text(encoding="utf-8"), (
        "the receipt path is not named in .gitignore"
    )
    done = subprocess.run(
        ["git", "check-ignore", "-q", ".claude/.prepush_receipt.json"],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        env=child_env(),
    )
    assert done.returncode == 0, (
        f"git does not ignore .claude/.prepush_receipt.json (check-ignore "
        f"exit {done.returncode}). The receipt is local session state, like "
        f"the role-review attestation beside it, and it must never enter the "
        f"repository or the walks that read untracked files.\n"
        f"{done.stdout}{done.stderr}"
    )


@pytest.mark.slow
def test_status_answers_without_writing_anything(tmp_path: Path) -> None:
    """`status` reports the verdict and must leave the receipt untouched.

    MEASURED 2.17 s, marked for the same reason as the sibling above and
    with the same consequence: it still runs at pre-push and in CI, and
    it still blocks.

    This is the subcommand the operator uses to ask whether the next push
    will be fast, and it is how the adoption's three-answer measurement
    was taken. If it wrote a receipt, that measurement would be creating
    the state it reports on.

    Both states are exercised, because a `status` that writes nothing is
    trivially true when there is nothing to write: once with NO receipt,
    where the file must not appear, and once with one, where its bytes
    must not move. The verdict is asserted exactly rather than as "one of
    the two appeared"; an either-or assertion cannot tell a correct
    verdict from its opposite.
    """
    root = tmp_path / "probe"
    root.mkdir()
    _init_repo(root)
    receipt = root / ".claude" / ".prepush_receipt.json"

    assert "WOULD RUN" in _ask(root, "status")
    assert not receipt.is_file(), (
        "`status` created a receipt on a tree that had none, so merely "
        "asking the question authorized the skip it was asking about"
    )

    _ask(root, "guard")
    before = receipt.read_bytes()
    assert "SKIP" in _ask(root, "status")
    assert receipt.read_bytes() == before, (
        "`status` rewrote the receipt. It must never write: at minimum a "
        "rewritten timestamp would extend the four-hour ttl every time an "
        "operator asked whether the next push would be fast."
    )


def _git(root: Path, *args: str) -> None:
    """Run one git command in the throwaway repository.

    ``env=child_env()`` sits on the same call, which is not decoration:
    ``tests/test_push_gate.py`` reads a window of lines from each
    ``subprocess.run(`` and refuses a spawn site that does not pass an
    explicit environment. The first version of this helper spread three
    spawns over a loop and put the environment out of that window, and
    the whole suite went red for it. Every spawn here is deliberately one
    short call so the guard sees what it needs to see.

    The two ``-c`` overrides make the fixture independent of whoever runs
    it. A global ``commit.gpgsign`` or ``core.hooksPath`` would otherwise
    fail these tests for a reason that has nothing to do with the
    receipt. This is a throwaway repository built by a test, not this
    repository's own signing policy.
    """
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=",
            *args,
        ],
        check=True,
        capture_output=True,
        env=child_env(),
    )


def _init_repo(root: Path) -> None:
    """A throwaway git repository with one commit, for the tests below."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "ita11@example.invalid")
    _git(root, "config", "user.name", "ita11")
    (root / "tracked.txt").write_text("original\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "base")


def _ask(root: Path, mode: str) -> str:
    """Run the receipt in ``guard`` or ``status`` over a trivial command."""
    argv = [
        sys.executable,
        str(_RECEIPT),
        mode,
        "--label",
        "probe",
        "--repo",
        str(root),
        "--",
        sys.executable,
        "-c",
        "pass",
    ]
    done = subprocess.run(
        argv, capture_output=True, text=True, env=child_env(), cwd=str(root)
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout.splitlines()[0]


@pytest.mark.slow
def test_the_three_answers_on_a_throwaway_repository(tmp_path: Path) -> None:
    """RUN, then SKIP, then RUN again when one tracked file changes.

    MEASURED 2.88 s on an idle machine, against the commit tier's 3.0 s
    budget, and it FAILED that budget inside a loaded run. Marked rather
    than trimmed and never by raising the budget: it spawns git five
    times and the receipt five more, and every one of those spawns is a
    real state the mechanism has to answer about. The marker moves WHERE
    it runs, not whether; the pre-push tier and CI both run it and both
    block.

    The sequence the adoption brief asks for, asserted on the EXACT
    branch rather than on "one of the two verdicts appeared". A test that
    accepts either answer cannot tell a correct verdict from its
    opposite, which is what the weaker form of this check did.

    The fourth answer is the one worth the most and was not asked for:
    restoring the original bytes returns the verdict to SKIP. That is
    what makes the key CONTENT-derived rather than a one-shot token, and
    it is the property the whole mechanism rests on.

    Hermetic, in a repository this test creates, so it neither reads nor
    writes the receipt of the tree it runs in.
    """
    root = tmp_path / "probe"
    root.mkdir()
    _init_repo(root)

    assert "WOULD RUN" in _ask(root, "status"), "a tree with no receipt must run"
    # `startswith`, because "WOULD RUN," contains "RUN," and the two are
    # opposite answers: `status` never runs the command and `guard` must.
    first = _ask(root, "guard")
    assert first.startswith("prepush-receipt: RUN,"), (
        f"the first guard answered {first!r} instead of RUN. With no "
        f"receipt on the tree there is nothing that could authorize a skip."
    )
    assert (root / ".claude" / ".prepush_receipt.json").is_file(), (
        "a passing run wrote no receipt, so nothing was recorded and the "
        "next push pays for the suite again"
    )
    assert "SKIP" in _ask(root, "status"), (
        "an identical tree, environment and command did not authorize a "
        "skip, so the mechanism never skips and buys nothing"
    )

    original = (root / "tracked.txt").read_bytes()
    (root / "tracked.txt").write_bytes(original + b"one more line\n")
    assert "WOULD RUN" in _ask(root, "status"), (
        "one changed tracked file did not move the key. The receipt would "
        "then authorize a skip over content that was never tested, which is "
        "the one outcome this mechanism must never produce."
    )

    (root / "tracked.txt").write_bytes(original)
    assert "SKIP" in _ask(root, "status"), (
        "restoring the exact bytes did not restore the verdict, so the key "
        "is not derived from content and the receipt is a one-shot token"
    )


def test_a_receipt_that_exists_records_what_it_claims_and_no_more(
    tmp_path: Path,
) -> None:
    """A written receipt is a pass record with a usable timestamp and key.

    Written POSITIVELY, in a repository this test creates. The first
    version read the live tree's receipt and skipped when there was none,
    which is the ordinary state in CI and on every fresh clone, so it ran
    nowhere that matters. A reviewer measured it skipping in both of its
    runs.

    This does not re-derive the key; it checks that the record's own
    claims are the ones the mechanism reads back, so a receipt written
    into a shape this repository would misread is caught here rather than
    at a push.
    """
    root = tmp_path / "probe"
    root.mkdir()
    _init_repo(root)
    _ask(root, "guard")
    receipt = root / ".claude" / ".prepush_receipt.json"
    assert receipt.is_file(), "the guarded pass wrote no receipt to read"
    record = json.loads(receipt.read_text(encoding="utf-8"))
    assert isinstance(record, dict), "the receipt is not a JSON object"
    assert record.get("outcome") == "pass", (
        f"the receipt records outcome {record.get('outcome')!r}. Only a pass "
        f"is ever written; a failing run deletes the receipt instead."
    )
    assert record.get("exit_status") == 0, (
        f"the receipt records exit status {record.get('exit_status')!r} "
        f"beside a pass, which no run of the mechanism can produce."
    )
    assert isinstance(record.get("written_at"), (int, float)), (
        "the receipt has no usable timestamp, so its age cannot be read and "
        "the four-hour ttl cannot apply."
    )
    assert isinstance(record.get("key"), str) and record["key"], (
        "the receipt carries no key, so it authorizes nothing and would be "
        "refused at every push while looking like a valid record."
    )


@pytest.mark.slow
@pytest.mark.guardproof
def test_the_receipt_can_still_fail() -> None:
    """The mutation companion proves every unknown state still RUNS.

    MEASURED 54.7 s: it builds real git repositories in a temp directory,
    one per case and one per case per mutant, rather than reconstructing
    them. The marker moves WHERE it runs and never WHETHER; the pre-push
    tier and CI both run it and both block.

    Its cases are the specification's refusals: absent, empty, truncated,
    malformed, non-object, one uncommitted edit, one untracked file, one
    deleted file, a mutated environment fingerprint, a mutated self hash,
    a different argv, expired, negative age, a hand-written plausible
    receipt, and a receipt recording a non-zero exit. Every one must RUN.
    Two SKIP controls exist because a mechanism that never skips is not
    the mechanism, and a companion with no control would pass against a
    file that always runs the suite.

    Kit 0.2.16 adds three cases and two mutants to that list, for the fix
    that makes a receipt authorize only the tree the suite actually ran
    against: a guarded command that CREATES an untracked file must leave
    no receipt, the same for one that MODIFIES a tracked file, and the
    control that touches nothing must still SKIP. The compound mutant
    restores both 0.2.15 lines at once, because once the tree-modification
    check holds it returns before the write is reached and a mutant
    deleting only the pre-run key survives every case.
    """
    done = _run(str(_RECEIPT_MUTATIONS))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "all 17 mutants are denied" in done.stdout, (
        f"the receipt mutation companion did not report all 17 mutants "
        f"denied. Two opposite remedies: if a re-vendor changed the count, "
        f"move it here and in tests/test_kit_drift.py's manifest note "
        f"together; if it did not, a mutant SURVIVED, which means a defense "
        f"can be deleted and the mechanism still skips. Output:\n{done.stdout}"
    )
    assert "All 27 cases hold" in done.stdout, (
        f"the receipt mutation companion did not report 27 cases. The "
        f"mutants can be denied by a shrunken case list, so this count is "
        f"what catches a re-vendor that quietly dropped cases. If the kit "
        f"really changed it, move the pin; do not delete it. "
        f"Output:\n{done.stdout}"
    )
