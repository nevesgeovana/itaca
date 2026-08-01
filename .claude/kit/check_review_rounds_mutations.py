# ITACA / pyflightstream shared process kit
# kit-version: 0.2.15
# artifact: check_review_rounds_mutations.py
# body-sha256: 368c985b7bee0c2a72919dc0feda7c3e454b8f0b26fd1d47c1f04e1143e20f07
# canonical-source: BUILT for the kit (0.2.15, HUB-11) as the guard evidence for check_review_rounds.py. Case 1 and case 2 are the two REAL shapes: lane ITA-4's round two, which found six defective round-one fixes, and the same lane's round two as a flat two-rounds-then-register cap would have recorded it. If case 2 ever stops being refused, this checker has stopped being able to tell the rule from the count.
# note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
# END KIT PROVENANCE (body verbatim below)
#!/usr/bin/env python3
"""Guard evidence for check_review_rounds.py, on real ledger files.

Run:  python check_review_rounds_mutations.py

Every case writes a real ledger to a temporary file and runs the real CLI,
asserting the exit code AND a phrase only the intended refusal produces. The
message matters as much as the code here: the kit has twice been bitten by a
case asserting a phrase the report prints unconditionally, so a needle that
sits on the violation's own wording is the standard rather than a nicety.

Two cases are HISTORY rather than design, and they are the two that matter:

- ``ita4_round_two`` is lane ITA-4's actual shape, six round-two findings
  about round-one fixes, all fixed in round two. It must be ACCEPTED.
- ``flat_cap_would_have_shipped_it`` is the same lane under the naive
  mechanism, those six findings REGISTERED instead. It must be REFUSED. If
  it ever stops being refused, this checker has stopped expressing the rule
  and is expressing a count.

Exit 0 when every case holds and every mutant is denied, 1 otherwise.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

MODULE = Path(__file__).resolve().parent / "check_review_rounds.py"

GOOD_TWO_ROUNDS = """
lane: ITA-2E
rounds: 2

finding: FND-071 | round=1 | ground=new | fixed
finding: FND-072 | round=1 | ground=new | registered
finding: FND-080 | round=2 | ground=about:FND-071 | fixed
finding: FND-081 | round=2 | ground=new | registered
"""

ITA4_ROUND_TWO = """
# Lane ITA-4 as it actually ran: round one's fixes were themselves
# defective, and round two fixed them rather than registering them.
lane: ITA-4
rounds: 2

finding: FND-046 | round=1 | ground=new | fixed
finding: FND-015 | round=1 | ground=new | fixed
finding: FND-056 | round=1 | ground=new | fixed
finding: FND-054 | round=1 | ground=new | fixed
finding: FND-067 | round=1 | ground=new | fixed
finding: R2-01 | round=2 | ground=about:FND-046 | fixed
finding: R2-02 | round=2 | ground=about:FND-015 | fixed
finding: R2-03 | round=2 | ground=about:FND-056 | fixed
finding: R2-04 | round=2 | ground=about:FND-054 | fixed
finding: R2-05 | round=2 | ground=about:FND-067 | fixed
finding: R2-06 | round=2 | ground=new | registered
"""

FLAT_CAP = ITA4_ROUND_TWO.replace(
    "finding: R2-01 | round=2 | ground=about:FND-046 | fixed",
    "finding: R2-01 | round=2 | ground=about:FND-046 | registered",
)

THIRD_ROUND = """
lane: ITA-2B
rounds: 3

finding: A | round=1 | ground=new | fixed
finding: B | round=2 | ground=about:A | fixed
finding: C | round=3 | ground=new | registered
"""

THIRD_ROUND_AUTHORISED = THIRD_ROUND.replace(
    "rounds: 3",
    "rounds: 3\nauthority: the author, 2026-08-01, asked before it was opened",
)

CASES: list[tuple[str, str, int, str]] = [
    ("good_two_rounds", GOOD_TWO_ROUNDS, 0, "VERIFIED"),
    ("ita4_round_two", ITA4_ROUND_TWO, 0, "VERIFIED"),
    ("flat_cap_would_have_shipped_it", FLAT_CAP, 1,
     "six guards that did not guard"),
    ("third_round_unauthorised", THIRD_ROUND, 1, "rule 3"),
    ("third_round_authorised", THIRD_ROUND_AUTHORISED, 0, "VERIFIED"),
    ("empty_ledger", "lane: X\nrounds: 1\n", 1, "certifies nothing"),
    ("no_lane", "rounds: 1\n\nfinding: A | round=1 | ground=new | fixed\n",
     1, "does not say what it certifies"),
    ("rounds_not_a_number",
     "lane: X\nrounds: two\n\nfinding: A | round=1 | ground=new | fixed\n",
     1, "not a positive"),
    # The needle is the highest-round sentence and not the bare string
    # "rule 2", and that is a finding this file made against itself: rule 2
    # produces TWO messages, and the round-gap one also fires on this ledger,
    # so a needle of "rule 2" was satisfied while the count comparison was
    # deleted. The mutant survived until the needle moved onto the
    # violation's own wording, which is the same correction the kit made in
    # check_release_gate_mutations and in check_shipped_surface.
    ("declared_count_disagrees",
     "lane: X\nrounds: 2\n\nfinding: A | round=1 | ground=new | fixed\n",
     1, "the highest round on any finding is"),
    ("round_with_no_findings",
     "lane: X\nrounds: 3\nauthority: the author\n\n"
     "finding: A | round=1 | ground=new | fixed\n"
     "finding: C | round=3 | ground=new | registered\n",
     1, "did not happen"),
    ("duplicate_id",
     "lane: X\nrounds: 1\n\nfinding: A | round=1 | ground=new | fixed\n"
     "finding: A | round=1 | ground=new | registered\n",
     1, "rule 6"),
    ("about_names_nothing",
     "lane: X\nrounds: 2\n\nfinding: A | round=1 | ground=new | fixed\n"
     "finding: B | round=2 | ground=about:ZZZ | fixed\n",
     1, "not a finding in this ledger"),
    ("about_names_the_same_round",
     "lane: X\nrounds: 2\n\nfinding: A | round=1 | ground=new | fixed\n"
     "finding: B | round=2 | ground=new | fixed\n"
     "finding: C | round=2 | ground=about:B | fixed\n",
     1, "STRICTLY earlier round"),
    ("about_names_a_registered_finding",
     "lane: X\nrounds: 2\n\nfinding: A | round=1 | ground=new | registered\n"
     "finding: B | round=2 | ground=about:A | fixed\n",
     1, "there is no fix here"),
    ("withdrawn_needs_a_reason",
     "lane: X\nrounds: 1\n\nfinding: A | round=1 | ground=new | withdrawn\n",
     1, "cannot police"),
    ("withdrawn_with_a_reason",
     "lane: X\nrounds: 1\n\nfinding: A | round=1 | ground=new | withdrawn | "
     "reason=the reviewer read a stale copy\n",
     0, "VERIFIED"),
    ("no_ground",
     "lane: X\nrounds: 1\n\nfinding: A | round=1 | fixed\n",
     1, "has no `ground=`"),
    ("unknown_disposition",
     "lane: X\nrounds: 1\n\nfinding: A | round=1 | ground=new | deferred\n",
     1, "expected one of"),
    ("unknown_field_is_refused_not_ignored",
     "lane: X\nrounds: 1\n\nfinding: A | round=1 | ground=new | fixed | "
     "severity=P1\n",
     2, "unknown field"),
    ("unknown_line_is_refused_not_ignored",
     "lane: X\nrounds: 1\nreviewers: three\n\n"
     "finding: A | round=1 | ground=new | fixed\n",
     2, "unknown line"),
    ("wrapped_row_is_one_row",
     "lane: X\nrounds: 1\n\nfinding: A | round=1 | ground=new | withdrawn |\n"
     "    reason=wrapped onto a second line\n",
     0, "VERIFIED"),
]

MUTANTS: list[tuple[str, str, str, str]] = [
    ("an about: finding may be registered",
     'if f.disposition == "registered":\n            v.append(f"rule 4:',
     'if False:\n            v.append(f"rule 4:',
     "flat_cap_would_have_shipped_it"),
    ("the cap is not enforced",
     "if rounds > CAP and not ledger.settings.get(\"authority\"):",
     "if False:",
     "third_round_unauthorised"),
    ("an authority is not required, so none is ever named",
     "rounds > CAP and not ledger.settings.get(\"authority\")",
     "rounds > CAP and True",
     "third_round_authorised"),
    ("an about: may point at a later or equal round",
     "if target.round is not None and f.round is not None \\\n                and target.round >= f.round:",
     "if False:",
     "about_names_the_same_round"),
    ("an about: need not resolve",
     "if target is None or target is f:",
     "if False and target is f:",
     "about_names_nothing"),
    ("an about: may point at something that was never fixed",
     'elif target.disposition != "fixed":',
     "elif False:",
     "about_names_a_registered_finding"),
    ("an empty ledger certifies a review",
     "if not ledger.findings:",
     "if False:",
     "empty_ledger"),
    ("a repeated id is accepted",
     "if f.ident in seen:",
     "if False:",
     "duplicate_id"),
    ("the declared round count is not compared to the rows",
     "if rounds >= 1 and highest != rounds:",
     "if False:",
     "declared_count_disagrees"),
    ("a round with no findings is accepted",
     "if missing:",
     "if False:",
     "round_with_no_findings"),
    ("a withdrawal needs no reason",
     'if f.disposition == "withdrawn" and not f.reason:',
     "if False:",
     "withdrawn_needs_a_reason"),
    ("an unknown field is silently dropped",
     '                    raise ConfigError(\n                        f"line {number}: unknown field {name!r} on finding "',
     '                    _ = ConfigError(\n                        f"line {number}: unknown field {name!r} on finding "',
     "unknown_field_is_refused_not_ignored"),
]


def run_case(module: Path, text: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="review-rounds-") as tmp:
        ledger = Path(tmp) / "rounds.txt"
        ledger.write_text(text, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(module), "--ledger", str(ledger)],
            capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr


def main() -> int:
    if not MODULE.is_file():
        print(f"CONFIG: {MODULE} not found beside this file", file=sys.stderr)
        return 2
    print(f"check_review_rounds guard evidence, {len(CASES)} cases, "
          f"{len(MUTANTS)} mutants")
    failed = []
    for name, text, code, needle in CASES:
        got, out = run_case(MODULE, text)
        ok = got == code and needle in out
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}: exit {got} "
              f"(expected {code}), needle {'found' if needle in out else 'MISSING'}")
        if not ok:
            failed.append(name)
            print("      " + out.strip().replace("\n", "\n      ")[:600])
    if failed:
        print(f"\n{len(failed)} case(s) failed on the real module; the "
              "mutants are not run, because a mutation result over a broken "
              "baseline says nothing.")
        return 1

    source = MODULE.read_text(encoding="utf-8")
    survivors: list[str] = []
    crash_denials: list[str] = []
    with tempfile.TemporaryDirectory(prefix="review-rounds-mutants-") as tmp:
        for i, (label, old, new, case_name) in enumerate(MUTANTS):
            if source.count(old) != 1:
                print(f"  [FAIL] mutant {i} ({label}): the text it replaces "
                      f"occurs {source.count(old)} times, not once")
                survivors.append(label)
                continue
            mutant = Path(tmp) / f"mutant_{i}.py"
            mutant.write_text(source.replace(old, new), encoding="utf-8")
            text, code, needle = next(
                (t, c, n) for nm, t, c, n in CASES if nm == case_name)
            got, out = run_case(mutant, text)
            denied = not (got == code and needle in out)
            # A mutant detected only because the mutated body CRASHED is
            # weaker evidence than one detected by a changed verdict: the
            # case proves the line is load bearing, not that the check is
            # what produced the refusal. Named rather than hidden, because
            # this kit already corrected a mutant criterion that counted a
            # crash as a detection without saying so.
            kind = "crash" if "Traceback" in out else "verdict"
            if denied:
                crash_denials.append(label) if kind == "crash" else None
            print(f"  [{'denied ' if denied else 'SURVIVED'}] {label} "
                  f"-> {case_name} gave exit {got} (expected {code}), "
                  f"by {kind}")
            if not denied:
                survivors.append(label)

    if survivors:
        print(f"\n{len(survivors)} mutant(s) SURVIVED: {survivors}")
        return 1
    print(f"\nAll {len(CASES)} cases hold and all {len(MUTANTS)} mutants "
          "are denied. The guard can still fail.")
    if crash_denials:
        print(f"{len(crash_denials)} of them were denied BY A CRASH rather "
              f"than by a changed verdict: {crash_denials}. That proves the "
              "line is load bearing and does not prove the check is what "
              "produced the refusal. Stated rather than counted silently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
