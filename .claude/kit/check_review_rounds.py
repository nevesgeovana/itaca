# ITACA / pyflightstream shared process kit
# kit-version: 0.2.15
# artifact: check_review_rounds.py
# body-sha256: 6d57387bdf9206b7811b40ce5a277d5bb4e050d3875e8ec7e3a9d0f1c9abb929
# canonical-source: BUILT for the kit (0.2.15, HUB-11) as the mechanism for the recursion cap that review-policy.md has stated since 0.2.7 and nothing enforced. Its load-bearing rule comes from lane ITA-4, whose round-one FIXES were themselves defective: six guards did not guard, one false-fired, and it introduced a fresh defect in the same commit that guarded the old one, all of it seen only by round two. A flat two-rounds-then-register cap would have shipped every one of them. Records: coordination/DESIGN_HUB-11_kit_batch.md item 4.
# note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
# END KIT PROVENANCE (body verbatim below)
#!/usr/bin/env python3
"""The two-round review cap, and what a round-two finding actually is.

Usage:
    python check_review_rounds.py --ledger <path>

Exit codes: 0 clean, 1 a violation, 2 configuration error.

WHAT THIS IS FOR
----------------

``review-policy.md`` has capped reviews at two rounds since kit 0.2.7 and
nothing enforced it. The obvious mechanism is "two rounds, then register
whatever is left". THAT MECHANISM IS WRONG, and this file exists because the
evidence arrived one day before it was built.

Lane ITA-4 ran two rounds. Its round-one FIXES were themselves defective: six
guards it wrote did not guard, one false-fired on correct code, and it
introduced a fresh defect in the same commit that added the guard against the
old one, with the lane's central fix passing green on a tree that was never
built. Round two saw all of it. Under a flat count, round two would have been
register-only and every one of those would have shipped, documented as known.

So the count is not the rule. The rule is about WHAT A ROUND-TWO FINDING IS:

- a finding ABOUT A PREVIOUS ROUND'S FIX is THE FIX NOT BEING DONE. It
  belongs to the round it was found in, and it is FIXED there. It buys no
  further round and it is not deferred.
- a finding on NEW GROUND is what gets REGISTERED as a plan item, and the
  lane closes.

A fix made in the final round is verified by its own evidence, the failing
measurement before it and the passing one after, per the INERTNESS rule in
the policy. That evidence is what replaces the round the cap forbids.

THE LEDGER FORMAT
-----------------

Line oriented, ``#`` comments and blank lines ignored. Settings first, then
one row per finding::

    lane: ITA-4
    rounds: 2
    # authority: only for a third round, and it names who authorised it

    finding: FND-046 | round=1 | ground=new          | fixed
    finding: FND-054 | round=1 | ground=new          | registered
    finding: FND-101 | round=2 | ground=about:FND-046 | fixed
    finding: FND-102 | round=2 | ground=new          | registered
    finding: FND-103 | round=2 | ground=new          | withdrawn |
        reason=the reviewer read a stale copy of the file

Grounds: ``new``, or ``about:<id>`` naming a finding from a STRICTLY earlier
round that was ``fixed``. Dispositions: ``fixed``, ``registered``,
``withdrawn``. A ``withdrawn`` row must carry a non-empty ``reason=``.

PROPOSED, NOT SETTLED. This format was written from three lanes' data
(ITA-2B, ITA-2E, ITA-4). The next lane is entitled to correct it, and
correcting it is a kit promotion rather than a local edit.

THE RULES
---------

1. ``lane`` and ``rounds`` must be present, and ``rounds`` must be a positive
   integer.
2. ``rounds`` must equal the highest round any finding carries, and every
   round from 1 to that number must carry at least one finding. A declared
   count no row supports is a ledger disagreeing with itself, and a gap is a
   round that did not happen.
3. More than two rounds requires ``authority``, naming who authorised it.
   This is the escalation lane ITA-2E actually performed: it reached the cap,
   stopped, asked the author, and recorded her authorisation rather than
   counting a third round. A mechanism that cannot express what already
   happened would be refused by the first lane that met it.
4. THE LOAD-BEARING RULE. A finding whose ground is ``about:<id>`` may not be
   ``registered``. It is the previous round's fix not being done.
5. An ``about:<id>`` must resolve: the id must exist in this ledger, at a
   strictly earlier round, and must have been ``fixed``. A reference to a
   registered or withdrawn finding is not a finding about a FIX.
6. A finding id may appear once. A repeated id silently replaces a verdict.
7. The ledger must carry at least one finding. An empty ledger certifying a
   review is the vacuous pass this class of guard exists to refuse.

WHAT THIS DOES NOT DO
---------------------

It does not read the review and cannot know whether a finding was classified
honestly. It checks that the lane's own record is internally consistent,
which is the half a machine can hold.

ONE ESCAPE IS NAMED RATHER THAN CLOSED. A lane can mark an ``about:`` finding
``withdrawn`` with a reason and escape rule 4. Nothing here can tell a real
withdrawal from a convenient one. The reason is required so that the claim is
at least WRITTEN, in the record a reader opens, rather than being made
silently. A lane using it to escape rule 4 has defeated the mechanism, not
passed it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

USAGE = "usage: check_review_rounds.py --ledger <path>"

DISPOSITIONS = ("fixed", "registered", "withdrawn")
SETTINGS = ("lane", "rounds", "authority")
CAP = 2


class ConfigError(Exception):
    """The check could not run. Never reported as a clean ledger."""


@dataclass
class Finding:
    ident: str
    line: int
    round: int | None = None
    ground: str | None = None
    disposition: str | None = None
    reason: str = ""
    raw: str = ""


@dataclass
class Ledger:
    settings: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


def parse(path: Path) -> Ledger:
    """Read the ledger. A row this cannot understand is a VIOLATION later,
    never a row silently dropped."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    ledger = Ledger()
    # A row may be wrapped onto a following indented line, so joined first.
    joined: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[:1].isspace() and joined:
            joined[-1] = (joined[-1][0], joined[-1][1] + " " + raw.strip())
            continue
        joined.append((number, raw.strip()))
    for number, line in joined:
        key, _, rest = line.partition(":")
        key = key.strip().lower()
        if key in SETTINGS:
            ledger.settings[key] = rest.strip()
            continue
        if key != "finding":
            raise ConfigError(
                f"line {number}: unknown line {line!r}; expected one of "
                f"{SETTINGS} or a finding row"
            )
        parts = [p.strip() for p in rest.split("|")]
        ident = parts[0]
        finding = Finding(ident=ident, line=number, raw=line)
        for part in parts[1:]:
            if not part:
                continue
            if "=" in part:
                name, _, value = part.partition("=")
                name = name.strip().lower()
                value = value.strip()
                if name == "round":
                    finding.round = int(value) if value.isdigit() else None
                elif name == "ground":
                    finding.ground = value
                elif name == "reason":
                    finding.reason = value
                else:
                    # An unknown field is refused rather than ignored. A
                    # ledger whose fields are silently dropped produces a
                    # clean verdict over less than it was given, which is
                    # this level's own most repeated failure.
                    raise ConfigError(
                        f"line {number}: unknown field {name!r} on finding "
                        f"{ident!r}; expected round, ground or reason"
                    )
            elif part in DISPOSITIONS:
                finding.disposition = part
            else:
                finding.disposition = finding.disposition or f"?{part}"
        ledger.findings.append(finding)
    return ledger


def check(ledger: Ledger) -> list[str]:
    """Every violation, in the order the rules are numbered."""
    v: list[str] = []
    lane = ledger.settings.get("lane", "")
    rounds_raw = ledger.settings.get("rounds", "")
    if not lane:
        v.append("rule 1: no `lane` setting; the ledger does not say what it "
                 "certifies. Add `lane: <id>`.")
    rounds = int(rounds_raw) if rounds_raw.isdigit() else 0
    if rounds < 1:
        v.append(f"rule 1: `rounds` is {rounds_raw!r}, not a positive "
                 "integer. Add `rounds: <n>` naming how many review rounds "
                 "ran.")

    if not ledger.findings:
        v.append("rule 7: the ledger carries no finding row, so it certifies "
                 "nothing. A review with no findings is recorded as a finding "
                 "row with `ground=new` and `withdrawn`, or it is not "
                 "recorded here at all.")
        return v

    seen: dict[str, Finding] = {}
    for f in ledger.findings:
        if not f.ident:
            v.append(f"line {f.line}: a finding row with no id. Write "
                     "`finding: <id> | round=<n> | ground=<new|about:id> | "
                     "<disposition>`.")
            continue
        if f.ident in seen:
            v.append(f"rule 6: finding id {f.ident!r} appears twice, at lines "
                     f"{seen[f.ident].line} and {f.line}. Give the second one "
                     "its own id; a repeated id silently replaces a verdict.")
            continue
        seen[f.ident] = f
        if f.round is None or f.round < 1:
            v.append(f"line {f.line}: finding {f.ident} has no usable "
                     "`round=`. Write `round=1` for the first review round.")
        if f.disposition not in DISPOSITIONS:
            v.append(f"line {f.line}: finding {f.ident} has disposition "
                     f"{f.disposition!r}; expected one of {DISPOSITIONS}. "
                     "Add the disposition as a bare word in its own field.")
        if not f.ground:
            v.append(f"line {f.line}: finding {f.ident} has no `ground=`. "
                     "Write `ground=new`, or `ground=about:<id>` naming the "
                     "earlier finding whose FIX this one is about.")
        elif f.ground != "new" and not f.ground.startswith("about:"):
            v.append(f"line {f.line}: finding {f.ident} has ground "
                     f"{f.ground!r}; expected `new` or `about:<id>`.")
        if f.disposition == "withdrawn" and not f.reason:
            v.append(f"line {f.line}: finding {f.ident} is `withdrawn` with "
                     "no `reason=`. A withdrawal is the one disposition this "
                     "checker cannot police, so it must at least be written "
                     "down. Add `reason=<why it was not real>`.")

    highest = max((f.round or 0) for f in ledger.findings)
    if rounds >= 1 and highest != rounds:
        v.append(f"rule 2: `rounds: {rounds}` but the highest round on any "
                 f"finding is {highest}. The declared count and the rows "
                 "disagree; correct whichever is wrong.")
    if rounds >= 1:
        present = {f.round for f in ledger.findings}
        missing = [n for n in range(1, rounds + 1) if n not in present]
        if missing:
            v.append(f"rule 2: round(s) {missing} carry no finding. A round "
                     "that found nothing did not happen; lower `rounds` or "
                     "record what it found.")
    if rounds > CAP and not ledger.settings.get("authority"):
        v.append(f"rule 3: {rounds} rounds exceeds the cap of {CAP} and no "
                 "`authority` is named. The cap is two rounds; a third exists "
                 "only when someone authorised it. Add "
                 "`authority: <who authorised it, and when>`, or fold the "
                 "third round's findings into round 2 as `about:` fixes.")

    for f in ledger.findings:
        if not f.ground or not f.ground.startswith("about:"):
            continue
        target_id = f.ground[len("about:"):].strip()
        target = seen.get(target_id)
        if target is None or target is f:
            v.append(f"rule 5: finding {f.ident} is `about:{target_id}`, "
                     "which is not a finding in this ledger. An `about:` "
                     "names the EARLIER finding whose fix this one is about; "
                     "if it is not about a fix, write `ground=new`.")
            continue
        if target.round is not None and f.round is not None \
                and target.round >= f.round:
            v.append(f"rule 5: finding {f.ident} (round {f.round}) is "
                     f"`about:{target_id}`, which is round {target.round}. "
                     "An `about:` names a STRICTLY earlier round; two "
                     "findings in one round are both `ground=new`.")
        elif target.disposition != "fixed":
            v.append(f"rule 5: finding {f.ident} is `about:{target_id}`, "
                     f"which was {target.disposition!r} rather than `fixed`. "
                     "An `about:` is a finding about a FIX; there is no fix "
                     "here. Write `ground=new`.")
        if f.disposition == "registered":
            v.append(f"rule 4: finding {f.ident} is about "
                     f"{target_id}'s fix and is REGISTERED. That is the "
                     "previous round's fix not being done, and it belongs to "
                     "this round: fix it here, with the failing measurement "
                     "before and the passing one after. Registering it is "
                     "exactly what shipped six guards that did not guard.")
    return v


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "--ledger":
        print(USAGE, file=sys.stderr)
        return 2
    path = Path(argv[2])
    try:
        ledger = parse(path)
        violations = check(ledger)
    except ConfigError as exc:
        # A CONFIG error is never reported as a clean ledger.
        print(f"CONFIG: {exc}", file=sys.stderr)
        return 2
    lane = ledger.settings.get("lane", "(unnamed)")
    rounds = ledger.settings.get("rounds", "?")
    print(f"lane {lane}, {rounds} round(s), {len(ledger.findings)} finding(s)")
    if violations:
        print(f"REFUSED: {len(violations)} violation(s)")
        for item in violations:
            print(f"  - {item}")
        return 1
    print("VERIFIED: rules 1 to 7 all ran against this ledger.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
