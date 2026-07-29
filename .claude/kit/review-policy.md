<!--
ITACA / pyflightstream shared process kit
kit-version: 0.2.7
artifact: review-policy.md
body-sha256: d3845ed17ef14d013ee2ffc8350f61bf0c0f585f63fc93c19e172d0a8afbd561
canonical-source: BUILT for the kit (0.2.7) from the author's product-owner decision REVIEW-TIERS, answered 2026-07-29, which asked to become a kit promotion so that it binds every repository rather than the one that raised it. The three moments were renamed from TIER 1/2/3 to GATE/PUSH/RELEASE the same day, because both libraries already use tier 1/2/3 for TEST tiers and this artifact's first level contains all three of them; the file was renamed with them, for what the artifact IS rather than for the labels it currently uses. It also carries guard 3 of INC-20260729-0854-shared, the probe-closure rule, promoted from one checkpoint's decision into a rule for every checkpoint.
note: derived copy; canonical master at the coordination level. Do not hand-edit; the tier-1 drift test recomputes the body sha256 and fails on divergence. Changes are made in the kit and re-vendored.
END KIT PROVENANCE (body verbatim below)
-->
# The review policy: three moments, the ordering rule, the recursion cap, and probe closure

Authority: the author's product-owner seat, `REVIEW-TIERS`, answered
2026-07-29, recorded in the coordination logbook. She asked for it to become a
kit promotion so that it binds every repository rather than the one that
raised it. It is a POLICY artifact: it decides who reads what and when, and
one of its four rules carries a checker beside it.

Adopted FROM THE NEXT LANE in each repository, never mid-lane. Changing the
rule inside a running lane buys one more review round about the rule change,
which is the loop this is cutting.

## The three moments are GATE, PUSH and RELEASE, and they were called tiers for a day

Recorded because the rename is the kind of thing a later reader will assume was
always so, and because the reason generalizes past this artifact.

They were TIER 1, TIER 2 and TIER 3 when this was drafted. Both libraries
already use tier 1, 2 and 3 for TEST tiers, and this artifact's first level
CONTAINS all three of those: it is the suite plus the type checker plus the
linter plus every existing guard. So "this is tier 1" had two readings that
were both true and not compatible, and the wider one swallowed the narrower.
An integration review raised it; the author renamed it the same day.

Prefixing them as "review-tier 1" was considered and REFUSED. A prefix works
only while everyone writes it out, and the first commit message saying "tier 2"
brings the ambiguity straight back. That is a convention, and the point of a
rename is to get a mechanism instead: two vocabularies that cannot be confused
because they share no word.

It was asked and answered while NO repository had vendored this file. A day
later it would have been a body change, a new hash and a re-vendor in two
repositories, which is the same reasoning the kit applies to a label already
cited by name.

THE FILENAME MOVED TOO, from `review-tiers.md` to `review-policy.md`, and that
was a separate call with its own reason. A file called `review-tiers.md` whose
body never says "tier" is a small lie of exactly the kind this rename was
fixing. Naming it for its current labels, something like `review-moments.md`,
would put the next relabel back in this position; naming it for what the
artifact IS survives a relabel, because it will be the review policy whatever
the three moments come to be called. The cost is that the manifest key changes
with it, and that cost is only small NOW, for the same reason the rename is.

## The measurement the decision rests on

Recorded because a decision without its evidence becomes a preference the
first time someone disagrees with it.

Over ten days one library was 81 commits and 48700 lines added: 32.3 percent
library tests, 30.3 percent library code, 22.5 percent documentation and
requirements, and 10.9 percent process, CI and guards.

The instinct that the work had become infrastructure was WRONG ON VOLUME and
RIGHT ON ATTENTION. In the last 24 hours of that period one guard saga was 913
lines of 9678, under 10 percent, and it was four of the last six commits. Code
arrives in few large blocks and process arrives in many short rounds, and every
round costs a human read. The policy is aimed at the rounds, not at the lines.

## GATE, every commit

Machine only. No human and no agent reads prose. The suite, the type checker,
the linter, and every guard the repository already carries.

Green or red is the whole output. GATE has no findings, only failures.

## PUSH, once before a push, fixed scope, ONE round

The question is exactly one: does the code do what its commit message says it
does.

Only a finding that CHANGES BEHAVIOUR, or that MISDESCRIBES it, may stop the
push. A text inconsistency is registered as a plan item and stops nothing.

One round. Not one round per finding, and not one round per file.

## RELEASE, only before a tag

The full panel: every lens, the artifact boundary, and a review OF the guards
rather than only through them.

A release is the only moment at which the expensive read is worth its price,
because it is the only moment at which the result becomes permanent for someone
who is not in the room.

## The agent assignment

DERIVED from the decision rather than stated in it, and open to correction on
the first lane that finds it wrong. Both libraries carry the same five role
reviewers.

| Lens | Moment | Why |
|---|---|---|
| `qa-engineer` | PUSH | produced the false closure, and the two tests that passed against pre-fix code |
| `vv-engineer` | PUSH | produced the guard that stayed green on the commit that shipped the defect |
| `architect-reviewer` | PUSH | produced the STABLE requirements amended without an amendment |
| `tech-writer` | RELEASE | produced the spelling sweep and the citation corrections |
| `api-designer` | RELEASE | produced surface findings that are real and are not worth a release-week read |

The three at PUSH are there because those three produced every finding that
changed an outcome in the lane this was decided from. The two at RELEASE are
there because theirs were real and none of them changed an outcome.

## The ordering rule

A TEXT finding never precedes a BEHAVIOUR finding, in any report, at any moment.

This is an ordering rule and not a scheduling one: it applies inside RELEASE as
well, where both kinds are in scope. Pedantry about how a comment is worded
while the code itself is not yet tested is backwards, and a report that opens
with the comment teaches the reader that the report is not about the code.

## The recursion cap

A review of a GUARD FIX does not spawn another review of the guard. Two rounds
maximum.

The saga this came from took four. Rounds two and three found real defects, and
that is not evidence that unbounded rounds are good: it is evidence that the
FIRST round was scoped wrong, reviewing the fix instead of the artifact the fix
was about. The cap forces the scoping error to surface as a cap breach rather
than as three more rounds.

## Probe closure, and the checker beside this file

This is guard 3 of `INC-20260729-0854-shared`, promoted here from a decision
made for one checkpoint into a rule for every checkpoint. It is the cheapest of
that incident's three guards and the one this level most needed.

THE RULE. A probe counts as CLOSED only if it REPRODUCED against the tree where
the defect existed. Two executions, in sequence, and they are not alternatives:

1. every probe runs against the reviewed base and MUST reproduce. One that does
   not is a BROKEN PROBE, and its finding stays open regardless of what the
   current tree says;
2. every probe runs against the current tree and none may reproduce.

WHY THIS FRAMING. The question is not which tree to test. It is what
distinguishes "the fix works" from "the probe never worked", and exactly one
measurement separates those. A probe reporting a finding closed looks identical
whether the code changed or the probe was always inert.

MEASURED, not supposed. One review round found TWO tests that passed against
pre-fix code: one whose fixture contained no delimiter at all, and one that
turned on an identifier neither tree imports. Both were green and both proved
nothing. In the same checkpoint, execution A ran 33 probes against the reviewed
base and all 33 reproduced, which is the mechanism demonstrated on a real
population rather than on an argument.

COST. Two executions instead of one, on what is already the most expensive
check in a release plan. Accepted deliberately: a checkpoint that cannot tell a
working fix from a broken probe is the same defect it exists to catch, one
level up.

THE MECHANISM. `check_probe_closure.py`, beside this file, reads a checkpoint's
probe ledger and refuses a closure that skipped step 1, a ledger whose two bases
are the same commit, and a ledger that certifies nothing. Its format is
documented in its own docstring and is PROPOSED rather than settled: it was
written from one checkpoint's data and the next checkpoint is entitled to
correct it.

UNRESOLVED, and deliberately left so: whether a call of this class belongs to
the author's seat or to the coordination level. It was answered once by her,
and one instance answered does not settle the ownership.

## What this artifact does NOT do

It does not make any lens fire. It says which lens is expected when, and a
repository still has to wire its own reviewers, exactly as the attestation
vocabulary made an honest answer expressible without making any pass required.

It is also NOT YET SAID WHERE AN OPERATOR READS IT. The push gate's review-deny
message is what a person actually sees at the moment of pushing, and it still
names five lenses with no moment attached. The kit's own 0.2.6 changelog argues
that a vocabulary the gate never mentions is a lens nobody knows to run, and
that argument applies here unchanged. This artifact shipped at 0.2.7 without
that half, DELIBERATELY and for one version: the gate is the most load-bearing
body in the kit and its deny prose is pinned by hand in a test, so changing it
is its own promotion with its own review. It is a NAMED item of 0.2.8, with an
owner, and it rides beside the gate's stale canonical-source line, which has
been waiting since 0.2.6 for a promotion with another reason to touch that
file. Deferring with a number is not the same as forgetting, and this paragraph
is what makes the difference checkable.

It does not apply to a workspace with no continuous integration. GATE is
defined as machine-only, and a repository with no CI has no GATE to speak of;
saying so here is better than a policy that silently describes a level that does
not exist.

## The costs, written because a decision recorded without its cost is a
conclusion

FIRST, and measured. A RELEASE lens co-raised a genuine product question about
what a source distribution ships, which is not pedantry. Moving that lens to
RELEASE means questions of that shape surface later in every lane. It is
mitigated only partly by RELEASE running before the tag, which is while
release-scope questions are still answerable.

SECOND. An interface lens at RELEASE means a public signature can be built wrong
and be caught when changing it is most expensive.

THIRD. Adopting from the next lane means the lane in flight finishes under the
old process, which is deliberate and is the cost of not spending a round on the
rule itself.
