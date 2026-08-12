"""Tier-1 drift guard: vendored process-kit copies match the pinned manifest.

Usage example (TDD anchor)::

    text = (_ROOT / ".claude/hooks/role_review_gate.py").read_text(
        encoding="utf-8"
    )
    assert _sha256(_kit_body(text)) == MANIFEST["role_review_gate.py"].body_sha256

The shared process kit (canonical masters at the coordination level) is
vendored into this repository as derived copies. A copy carries a
provenance header, a line ``END KIT PROVENANCE``, and then the artifact
body verbatim. This test recomputes each vendored body's sha256 and
asserts it equals the value this repository pinned when it vendored the
kit.

What that does and does not prove, stated exactly, because the strong
form of the claim is false and a counterexample sits in this very file.
It proves a committed copy cannot be silently HAND-EDITED: the body
changes, the recomputed hash stops matching, and CI goes red. It does
NOT prove a copy is CURRENT with the kit, because the manifest below is
an inlined frozen copy rather than a live read of the master. A
repository that has fallen behind stays green until someone moves a pin,
which was exactly the state of the two plan-checker entries for three
days. The env-located shared tools are checked only when their variable
is set (see below), so in a clone that never configured them they are not
drift-guarded in ordinary CI.

THAT LIMIT IS NOT THEORETICAL, and lane ITA-4 measured how far it can
go. Comparing every pin below against the kit README's manifest table
found three rows behind: ``review-policy.md`` at 0.2.7 against 0.2.11,
``incident-analyst.md`` at 0.2.10 against 0.2.11, and
``check_plan_kit_mutations.py`` at 0.2.3 against 0.2.10. This suite was
green throughout, exactly as the paragraph above says it would be, and
the third row was the one that mattered: the DEPLOYED plan checker had
been upgraded to 0.2.10 while the mutation companion that proves it can
still fail was left at 0.2.3. Nothing here could see that, because both
halves were internally consistent. All three are adopted as of
2026-08-01 and every pin below now equals the canonical table. The
currency check itself is registered rather than added, because a live
read needs a locator for the kit master and the locator family is
charter material (``ITC-20260801-0900``).

The fixture is the manifest (kit ``README.md``), inlined here so the test
needs no cross-repo filesystem access and cannot deadlock a push. A MIXED
manifest (per-file body hashes and versions, not one kit-wide hash) is
expected and correct, and the pins below are per file:

- 0.2.16: ``role_review_gate.py``, the SECOND fail-open removed from this
  one body. ``INC-20260802-1450-shared``: an unterminated heredoc opener
  made the stripper drop every remaining line of a guarded command, so a
  real ``git push`` on the next line was never seen. Its 0.2.8 history is
  the first one: author decision LEDGER-ENVVAR gave every workspace one
  variable, ``COORD_INCIDENT_LEDGER``, and an ABSENT ledger DENIES a push
  where 0.2.6 read absence as does-not-apply. itaca sat at 0.2.6 for a day
  after the fix existed and so carried a gate that could FAIL OPEN
  (``ITC-20260730-0215``, DD-44). The entry below carries the
  measurement.
- 0.2.9: ``write_attestation.py``, the INC-20260729-2355 guard. Its own
  entry below carries the detail.
- 0.2.14 and 0.2.13: the release path, four rows in one adoption.
  ``release_gate.yml`` and the NEW ``release_caller.yml`` at 0.2.14,
  ``check_release_gate.py`` and its companion at 0.2.13. The publish job
  moved OUT of the gate and into the caller, because PyPI Trusted
  Publishing cannot match a job inside a reusable workflow
  (``ITC-20260730-0270``, measured twice on this repository's v0.2.0 tag).
  The caller is a TEMPLATE and is vendored as ``.yml.template``, so the
  workflow copied from it is this repository's own file rather than a
  pinned body; the entries below say why.
- 0.2.6, the release-integrity promotion. It is HISTORY for the two hook
  bodies above, and for three of the five artifacts it introduced, which
  moved to 0.2.13 and 0.2.14 in the release-path adoption above. It
  remains the current pin for exactly two,
  ``check_version_identity.py`` and its mutation companion. The
  vocabulary change is the whole of it for the two existing bodies:
  ``write_attestation.py`` gains ``numerical-analyst`` and
  ``integration-reviewer`` in ``KNOWN_PASSES``, and the gate's deny
  message names the two new lenses. No control flow moved and no allow
  or deny decision changed. Read that for what it is: a recordable pass
  is still not a REQUIRED pass, and the gate still never reads the
  ``passes`` field. What changed is that the honest answer became
  expressible.
- 0.2.5: ``snap.sh`` alone, the false-success defect this repository
  found and routed up. 0.2.5 was closed rather than extended, so it
  keeps its own label while everything promoted beside it is 0.2.6;
  the label is already cited by name in plan entry
  ``ITC-20260728-2010`` and a label whose contents change after it is
  cited makes the citation say something it no longer means.
- 0.2.11: ``review-policy.md``, adding the INERTNESS rule (BRF-061 item
  16). A reproduction that cannot show it exercised the claimed path is
  not evidence, so a probe carries what proves it touched the code it
  names, beside its verdict.
- 0.2.11: ``incident-analyst.md``, carrying THREE changes across three
  kit versions. 0.2.8 renamed the ledger variable the charter names to
  ``COORD_INCIDENT_LEDGER`` (author decision LEDGER-ENVVAR), 0.2.10
  added the section forbidding that seat from using Bash to mutate git
  state, and 0.2.11 adds the two frontmatter keys ``model: opus`` and
  ``effort: low`` so the seat's model and effort come from its charter
  rather than from whoever spawns it. Three artifacts move together for
  this one entry: the stamped of-record copy, the runtime charter tied
  to it by ``test_the_runtime_agent_body_matches_the_of_record_copy``,
  and this pin.
- 0.2.2: both side-effect-guard artifacts.
- 0.2.10: the kit plan checker AND its mutation companion, which reached
  it separately and a week apart. The two are deployed OUTSIDE this
  repository, under the directory ``ITACA_PLAN_VALIDATOR`` names, so
  each pin moves only with the deployed copy it names; that is the rule
  below, and it is why the checker's pin could sit at 0.2.10 while the
  companion's sat at 0.2.3.

  The reason it sat there was not the one this file used to give. The
  text here said "per-file versions, as the kit ships them", which
  asserted that the KIT still shipped a 0.2.3 companion, and lane ITA-4
  measured that false: the kit ships both at 0.2.10. What was true is
  worse. The deployed checker had been upgraded and the artifact that
  proves it can still fail had not, so for that window the guard on the
  guard was seven versions behind, and no test in this file could see it
  because each half was self-consistent with its own pin.

  The checker's 0.2.10 body is the fix for ``ITC-20260727-1612``: an
  empty plan directory now exits 2 with ``CANNOT VERIFY`` instead of
  printing ``no entries`` and exiting zero. Measured at the deployed
  path: empty exits 2, a missing directory still exits 1, and the real
  ledger validates with a nonzero entry count and 0 bad. Measured again
  on 2026-08-01 after deploying the 0.2.10 companion: it reports ``0
  check(s) could not fail``, and its case list now includes "an empty
  plan directory refuses with CANNOT VERIFY", which is precisely the
  case ``ITC-20260730-0205`` recorded as ABSENT from the companion while
  the checker's own fix was already shipped. The counts themselves are
  not recorded here: the ledger is outside this repository and grows, so
  a number written down reads as an expectation and drifts the same day.
- 0.1.0: ``check_incidents.py``, unchanged.

The rule that decides both of those, stated once so the asymmetry is not
mistaken for an oversight: a pin for an artifact deployed OUTSIDE this
repository moves only together with the deployed copy it names. The
``snap.sh`` pin moved to 0.2.5 because the deployed copy already
carries that body: it was written when the defect was fixed, and this
repository's pin was the half left behind, which is why the suite at
``0d0dadd`` was red on exactly this one test before the pin moved. The
plan-checker pins were the other half of the same rule: for three days
they did NOT move, because their deployed copies had not, and they moved
only in the commit that re-vendored those copies. A reader who repoints
``ITACA_PLAN_VALIDATOR`` at a directory holding a different kit version
will see this suite fail; that is configuration, not drift, and the
remedy the failure message suggests (re-vendor) is the wrong one for it.

The vendored copies carry a per-copy ``note:`` line ("derived copy ...");
the header, including that line, is not hashed, so restamping it does not
affect the body sha256.

Two vendoring shapes are covered:

- committed copies (the hooks, the of-record agent charter, the two
  side-effect-guard artifacts under ``.claude/kit``) are always present,
  always checked, and are additionally required to still CARRY their
  provenance stamp, so that deleting the header cannot quietly downgrade
  a stamped-copy check into a hash-only one; and
- shared tools located by an environment variable (the incident checker
  and the kit plan checker) are checked when configured and skipped when
  not, so a clone with no configuration still runs a green suite. These
  may legitimately be deployed raw, so the stamp requirement above is not
  applied to them. This skip is NOT the same rule the push gate follows:
  since kit 0.2.8 an unset ``COORD_INCIDENT_LEDGER`` DENIES a push, while
  an unset locator here only means this suite cannot check that pin. A
  suite that refused to run on an unconfigured clone would gate nothing
  and stop everything; a gate that allowed a push on one gated nothing
  and stopped nothing.

``snap.sh``, the snapshot script for the ``_private`` trees, has no
locator variable of its own, so it is drift-checked best-effort where it
happens to sit beside a configured plan validator (``_snap_if_present``)
rather than through the env-located path above. One consequence worth
naming rather than discovering: CI sets neither locator, so this pin is
NOT exercised there. The 0.2.4 body's false-success defect, in which an
unset ``COORD_SHARED_LEDGER_TREE`` reported a snapshot it did not take
instead of skipping, is fixed in the 0.2.5 body pinned below and was
registered by the sister repository as
``PLN-20260728-1615-snap-shared-tree-false-success``.

One vendored artifact lives OUTSIDE the two ``.claude`` directories:
``release_gate.yml`` is a reusable GitHub workflow and must sit under
``.github/workflows/`` to be callable at all. It is pinned like any
other copy, and ``test_no_unpinned_artifact_hides_in_the_vendored_dirs``
was widened for it on two counts, because it would otherwise have
escaped on both: the directory is not swept, and ``.yml`` was not in the
suffix list. The widening for that directory is deliberately
marker-based rather than suffix-based, since ``ci.yml`` and
``release.yml`` are this repository's own files and pinning them would
be false.

The ``.md`` charter closes its provenance with an HTML ``-->`` after the
marker line; that delimiter is part of the header, not the body, so it is
dropped before hashing (the declared body-sha256 is computed that way).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from gate_locator import ledger_env  # one reader of the gate's ledger variable

_ROOT = Path(__file__).resolve().parents[1]
_MARKER = "END KIT PROVENANCE"


@dataclass(frozen=True)
class Pin:
    """The manifest entry a vendored copy must reproduce."""

    body_sha256: str
    kit_version: str


# The kit README manifest, inlined as the fixture. Per-file versions
# differ and span several kit versions, which is the manifest being per
# file rather than a lag; see the module docstring.
#
# It said "with two DELIBERATE deviations marked in place below", which
# was true until lane ITA-4 closed them, so the warning is corrected
# rather than left describing deviations that no longer exist. Measured
# on 2026-08-01 by a throwaway comparison against the kit README's
# table: all 21 pins equal it, hash and version, in both directions.
# That measurement is NOT repeatable from this repository and nothing
# maintains it, which is exactly the gap OQ-53 raises; read it as a
# dated observation and not as a currency guarantee.
#
# The rule it was protecting still stands and is the reason this comment
# is not simply deleted: a deviation IS legitimate, for a pin naming an
# artifact deployed OUTSIDE this repository, which moves only with the
# deployed copy it names. When one exists it is marked in place. So do
# not resync this wholesale from the master; reconcile row by row, and
# for a deployed artifact move the deployment first.
MANIFEST: dict[str, Pin] = {
    # 0.2.8, author decision LEDGER-ENVVAR, and the reason this pin moved at
    # the last moment before a tag. itaca sat at 0.2.6, whose ledger check
    # returns "not blocked" when the variable is unset, so on a clone that
    # configured nothing the incident half of this gate did not gate: it
    # could FAIL OPEN. 0.2.8 gives every workspace one variable,
    # COORD_INCIDENT_LEDGER, and an ABSENT one denies. The rename is the
    # visible half and the fail-open removal is the load-bearing one.
    #
    # 0.2.16 is the SECOND fail-open removed from this body, and it is why
    # this row was vendored alone, ahead of everything else in that batch.
    # `INC-20260802-1450-shared`: an unterminated heredoc opener made
    # `_strip_heredocs` drop every remaining line of the command, and a real
    # `git push` went with them. Two lines, no heredoc anywhere:
    #
    #     git commit -m "see the <<EOF form"
    #     git push origin main
    #
    # MEASURED HERE against this repository's own deployed 0.2.8 body before
    # the pin moved: that command and two reductions of it produced NO
    # DECISION AT ALL, which is not a weaker refusal but no refusal, while
    # the control (a bare unattested push) denied. On the 0.2.16 body all
    # four deny.
    #
    # The premise that made the old body read as safe is also false, and it
    # is worth carrying here because it is what a reviewer would lean on:
    # the design note says an unbalanced quote makes the parse fail and the
    # raw-text fallback catches the push. `shlex.split(..., posix=False)`
    # does NOT raise on every unbalanced quote, so a stripping bug yields a
    # CLEAN PARSE with the push missing from it. The fallback is not a net,
    # and every branch of the stripper has to be correct on its own.
    #
    # 0.2.16 also gives the stripper a POWERSHELL branch
    # (`ITC-20260801-2245`), so a commit whose MESSAGE describes a push is no
    # longer denied as a push and the `git commit -F <file>` workaround can
    # be retired. NO DENY PROSE MOVED at 0.2.16, which matters because this
    # repository pins several deny phrases by hand; `tests/test_push_gate.py`
    # and `tests/test_review_gate.py` are unchanged in verdict across this
    # row.
    #
    # 0.2.18 is the THIRD change to this body that removes a way for a push
    # to escape a question, and the first that asks a question of something
    # outside this machine. A release-grade push is REFUSED unless the commit
    # each version tag names has a concluded, successful CI result on the
    # remote; RED, RUNNING, UNKNOWN and a query that could not be made all
    # DENY. `INC-20260810-2140-shared` is what paid for it next door, a v0.7.0
    # tag published fifteen seconds after its branch with seven of eight jobs
    # still running and five of them red, and `INC-20260810-2350-itaca` is
    # this repository's own half of the same cause, which this row closes.
    #
    # THE DECISION TABLE IS NOT IN THIS BODY, which is why the row below it
    # exists and why the two must be vendored together. The gate SHELLS OUT to
    # `ci_state.py`, reads its documented exit contract, and maps anything
    # outside that contract to UNKNOWN. An ABSENT `ci_state.py` is a REFUSAL
    # with `[ci-config]` and never a skip, so vendoring this row without the
    # next one denies every release-grade push and does it with a message
    # that reads like a gate defect.
    #
    # 0.2.18 adds three arms and NO test in this repository reaches two of
    # them, which is stated here rather than left for a reader to assume
    # coverage: `[ci-budget]` and `[ci-tag]`. The gate's own companion prints
    # them as unreached rather than counting them denied, and `[ci-tag]` is
    # marked unreachable-today in the master's own comment because `[scope]`
    # refuses first. `tests/test_push_gate.py` reaches `[ci-config]`,
    # `[ci-unknown]` and the release-grade classification, and says so.
    #
    # MEASURED HERE against this repository's own deployed body, before and
    # after: on the 0.2.16 body a release-grade push naming a tag on a commit
    # with no CI result was ALLOWED through this arm entirely, because the arm
    # did not exist; on the 0.2.18 body the same push denies. That run is the
    # guard evidence in `INC-20260810-2350-itaca` and is not restated here.
    #
    # NO DENY PROSE THAT THIS REPOSITORY PINS BY HAND MOVED at 0.2.18: the
    # `[review]`, `[release]`, `[config]`, `[ledger]` and `[incident]`
    # messages `tests/test_push_gate.py` and `tests/test_review_gate.py`
    # assert on are unchanged in verdict and in the fragments those tests
    # quote.
    # The declared value agreed with the master body on recomputation.
    "role_review_gate.py": Pin(
        "acd1766cc0425036a96ec825ecf0f1e50660101d7763f97639e31dd088314ada", "0.2.18"
    ),
    # 0.2.18, NEW, and the row whose ABSENCE the row above turns into a
    # refusal. `ci_state.py` answers one question about one SHA in four
    # states, RUNNING, GREEN, RED and UNKNOWN, with UNKNOWN never green:
    # no network, no `gh`, an expired token, no run found yet, a conclusion
    # it does not recognize, a full page that may be truncated, and any
    # exception raised inside the mechanism are all UNKNOWN. It shells out
    # to `gh`, whose absence is UNKNOWN rather than an error.
    #
    # IT HAS TWO CALLERS ON OPPOSITE SIDES OF THE PUSH, and this repository
    # now wires BOTH, which is the whole of lane ITA-15. The gate above calls
    # it BEFORE a release-grade push and denies on anything but GREEN. The
    # closing sequence calls it AFTER an ordinary push and refuses to say
    # closed on anything but GREEN, which is `INC-20260811-1745-itaca`, the
    # BRANCH half that the gate arm cannot reach: that arm's own companion
    # passes on `an ordinary branch push on a RED commit is not this arm's
    # business`, and the three red pushes to `main` that produced the record
    # had no tag in sight.
    #
    # It is vendored into `.claude/hooks` and not `.claude/kit` because
    # `_ci_state_body` looks BESIDE THE GATE first and only then walks its
    # search list, so the pair sits together and the resolution never depends
    # on that list being right about this repository.
    #
    # WHAT THIS REPOSITORY DOES NOT DO WITH IT, said once so a reader does
    # not go looking: `detached_gate.py` is NOT vendored, so the closing
    # sequence runs `poll` and reports, rather than `await` run detached.
    # A close over a still-queued run therefore reports NOT VERIFIED instead
    # of waiting, which is the strict half of the contract without the half
    # that makes waiting affordable. Registered rather than done here.
    # Both declared values agreed with the master bodies on recomputation.
    "ci_state.py": Pin(
        "39977e44aae1cb4116fb2bce3b672ac21b03ec3a5d75f64244eb70eb2f89b3ab", "0.2.18"
    ),
    "ci_state_mutations.py": Pin(
        "7e1135337732252f7afffc5c7367769035e54bbe06a7d31df7dcfd7e2a362746", "0.2.18"
    ),
    # 0.2.20, NEW, and the one row in this batch that CHANGES HOW A SESSION
    # BEHAVES, so it is wired knowingly rather than dropped in. A PreToolUse
    # hook refusing exactly two shapes, both mechanically decidable:
    #
    #   ARM 1, a status-bearing command piped into a line filter. A
    #   pipeline's exit status is the LAST element's, so `pytest | tail`
    #   reports the status of `tail`. STATUS_BEARING is deliberately SHORT
    #   (pytest, mypy, ruff, git push, plus check_*.py, *_mutations.py and
    #   verify_*.py by pattern), because the arm is about status and not
    #   about danger.
    #
    #   ARM 2, a heredoc whose body carries a backslash or a control byte.
    #   NOT a heredoc ban: twelve tracked files across the three trees carry
    #   heredocs, and the kit fixed a heredoc defect at 0.2.1 by correcting
    #   rather than forbidding. A quoted delimiter is exempt from the
    #   backslash half, since that is the form that survives.
    #
    # WHAT IT COSTS THIS SESSION, measured elsewhere and taken on trust here
    # rather than rediscovered: it refuses `pytest | tail` and
    # `check_*.py | head`, which is how this repository's own sessions have
    # read long output. Run them unpiped, or redirect to a file and read the
    # status from the process. That is the behavior the guard exists to
    # produce, so the friction is the point rather than a side effect.
    #
    # THREE FALSE POSITIVES ACROSS TWO REPOSITORIES, all one class: a
    # checker named as DATA rather than executed, for example as a grep
    # argument. Heredoc bodies and quoted spans are blanked before it scans,
    # so an unquoted checker filename in a grep is the remaining case. That
    # miss is stated in the body itself rather than hidden, which is why it
    # is repeated here instead of being discovered by the next lane.
    #
    # It gives a mechanism to two `CLAUDE.md` Execution rules that had one
    # each in prose only: arm 2 answers the heredoc bullet, which said in
    # place that it had NO MECHANISM FILE, and arm 1 gives the pipe-status
    # bullet a second mechanism beside the `version-control` skill.
    #
    # THAT SENTENCE PREVIOUSLY CLAIMED THE BULLETS MOVED WITH THIS ROW AND
    # THEY DID NOT. Four reviewer lenses found it independently in ITA-17
    # round one: the charter went on saying no mechanism existed and that
    # the vendoring was still registered as future work, in the same commit
    # that vendored and wired it, while this comment asserted an edit the
    # diff did not contain. The bullets are corrected now. It is recorded
    # rather than quietly fixed because the failure is the one this lane's
    # own new rule names: a success line asserting something the change did
    # not do.
    #
    # ARM 1 IS NARROWER THAN THE BULLET IT ANSWERS, on this repository's
    # primary shell. `LINE_FILTERS` matches `head|tail|wc` only, so
    # PowerShell's `Select-Object` and `Measure-Object` are not refused
    # although they lose a status the same way. Routed as
    # `ITC-20260811-2250`, the execution guard's line filters are bash-only
    # while it is wired for both shells; the control case in
    # `tests/test_execution_guard.py` is labeled a KNOWN GAP rather than an
    # exemption, so it does not read as design intent.
    # Both declared values agreed with the master bodies on recomputation.
    "execution_guard.py": Pin(
        "f309785a0c417d12be475e6f07e91458c91e5731bade1c814c67a1ee49565390", "0.2.20"
    ),
    "execution_guard_mutations.py": Pin(
        "e01c203503877fe8c1ad03af3c1faf8686ff92cff5049bf3969b08dc7dda2ffd", "0.2.20"
    ),
    # 0.2.17, NEW, and VENDORED WITHOUT BEING WIRED, which is a state this
    # repository normally refuses and so is stated rather than left to be
    # noticed. `detached_gate.py` runs a long gate in a process that outlives
    # the caller and answers from a FILE, which is what makes `ci_state.py
    # await` affordable: a lane session cuts a command at ten minutes, and
    # every mechanism that answers "did the gate pass" by WAITING inherits a
    # limit it cannot see.
    #
    # `.claude/tools/closing_ci_check.py` still POLLS and reports, so a close
    # over a still-queued run says NOT VERIFIED rather than waiting. That is
    # the strict half of the kit's closing contract without the half that
    # makes waiting cheap, and it is the most likely reason a session would
    # start routing around the closing step. Wiring it is the open half of
    # `ITC-20260811-2110`, kept open deliberately: the body is drift-pinned
    # and available here, and changing what the closing check does is a
    # design change that has not been reviewed.
    # The declared value agreed with the master body on recomputation.
    "detached_gate.py": Pin(
        "86ac1759c867c6a215e9ccc44779bd4e4954efa058c54b1b3e05cbc3e70831f7", "0.2.17"
    ),
    # 0.2.9, the INC-20260729-2355 guard: the attestation refuses while
    # TRACKED files carry uncommitted changes, and reports untracked paths
    # instead of refusing on them. RECOMPUTED from the master body with
    # `_kit_body`/`_normalize` from this file, not copied from the
    # master's declared value, which is STALE: the master's header
    # declares kit-version 0.2.9 beside the 0.2.6 body-sha256. That
    # mismatch is a defect in the master's header and is routed to the
    # coordination level; the body itself is the 0.2.9 guard and hashes
    # as pinned here. The recompute-not-copy rule is the same one the
    # 0.2.7 entries below already record.
    #
    # 0.2.15 adds ATTEST-SCOPE and moves NO allow or deny decision. A pass
    # may carry its own commit scope as `name@<range>`, and the record
    # gains `pass_scope` and `uncovered`. The BARE form is unchanged, so a
    # consumer whose skills still write a flat `<passes>` list is not
    # broken by this re-vendor, and this lane attested in exactly that bare
    # form. The gate reads `commits` and `refs` and has never read
    # `passes`, which is why a new field beside `passes` cannot change what
    # the gate allows: `tests/test_push_gate.py` and
    # `tests/test_review_gate.py` are unchanged in verdict across this row.
    #
    # It comes from lane ITA-2G declaring against itself, in PROSE, that
    # two of its commits carried no lens at all, because the record could
    # not express that. Adopting the scoped form in the `role-review` and
    # `handoff` skills is OPTIONAL in the adoption brief and is registered
    # rather than done here (`ITC-20260801-2200`), so this row vendors a
    # capability this repository does not yet exercise.
    # The declared value agreed with the master body on recomputation.
    "write_attestation.py": Pin(
        "6c70a673f88d0eebffcdbc048e90db7e1f064ec6af0e49d0b75b517435f982ec", "0.2.15"
    ),
    # 0.2.15, NEW: the pre-push receipt, and the one row of this batch with
    # real consumer configuration. The pre-push tier re-ran a full suite it
    # had already run green minutes earlier; measured here that suite is
    # 12.1 minutes and the whole hook 12.5 to 13, and CI then runs it three
    # more times. The cost that matters is not the duplication, it is that
    # a step that expensive gets routed around with `--no-verify`
    # eventually, which is the outcome this artifact exists to prevent.
    #
    # EVERY UNKNOWN STATE RUNS THE SUITE. Absent, empty, truncated,
    # malformed, key-mismatched, expired, clock moved backwards, and any
    # exception raised inside the mechanism: all of them RUN. There is
    # deliberately no path in which a defect in this file skips a suite, so
    # a defect here costs time and never safety. Note the asymmetry with
    # `COORD_INCIDENT_LEDGER`, which is deliberate and is stated in the
    # artifact body as well as here: there an ABSENT configuration DENIES a
    # push, here an ABSENT receipt means DO THE WORK. Both are the
    # fail-CLOSED direction for their own guard and they point opposite
    # ways; making them consistent would break one.
    #
    # itaca wraps `pytest-full` and NOT `mypy-full`, decided in this lane:
    # mypy on this repository is seconds rather than minutes, and
    # `ITC-20260730-2355` already registers that `mypy-full` is the
    # byte-identical command a second time, so giving the duplicate a
    # mechanism of its own would make that item harder to act on.
    #
    # 0.2.16 makes the receipt authorize only the tree the suite actually ran
    # against. Two defects, measured as one design because their invariants
    # were the same sentence: the key stored was RECOMPUTED after the child
    # exited (`ITC-20260801-2320`), and a receipt was written for a run whose
    # own verdict was still pending, because pre-commit declares "files were
    # modified by this hook" AFTER the exit status the wrapper reads
    # (`ITC-20260802-0620`). A guarded command that MODIFIES the working tree
    # now writes no receipt at all and says so.
    #
    # LATENT HERE and recorded as such: this repository's full suite leaves
    # the tree clean, so nothing should behave differently today. The day a
    # test starts writing into the tree, the push gets slower and prints the
    # reason instead of silently skipping a suite over content it never
    # measured.
    #
    # EVERY EXISTING RECEIPT IS INVALIDATED by this row, because component 4
    # of the key is this body's own hash. The first push after it lands runs
    # the full suite; that is the designed behavior and not a defect to
    # diagnose. No configuration moves: the wrapper's invocation, the receipt
    # path and the gitignore row are unchanged.
    # Both declared values agreed with the master bodies on recomputation.
    "prepush_receipt.py": Pin(
        "e44bde8efa27e0bed50db5e10903871936d688c55d833f4c707f29e3ec67aa94", "0.2.16"
    ),
    "prepush_receipt_mutations.py": Pin(
        "228d9e359c55a0d14f2e890b7130d405d279a63273b5d6710b429844af58f633", "0.2.16"
    ),
    # 0.2.14 for the two workflow bodies and 0.2.13 for the checker pair,
    # which is one adoption and four rows: kit 0.2.12 moved the publish job
    # OUT of the gate and into the caller, 0.2.13 fixed a startup defect the
    # rehearsal found in 0.2.12's own body, and 0.2.14 is prose only,
    # replacing two NOT VERIFIED BY EXECUTION notes with the runs that
    # verified them. The mixed versions are the manifest being per file, not
    # a lag.
    #
    # WHY THE PUBLISH JOB MOVED, because a reader of this pin will ask. PyPI
    # Trusted Publishing matches `job_workflow_ref`, the file CONTAINING the
    # publishing job, and the sigstore attestation the same action uploads
    # carries `workflow_ref`, the ENTRY POINT. PyPI checks both against one
    # configured publisher, so with a reusable workflow no publisher value
    # satisfies both. Both halves were measured on this repository's own
    # v0.2.0 tag (`ITC-20260730-0270`), which is why v0.2.0 shipped by hand.
    #
    # Every one of the four hashes below was RECOMPUTED from the master body
    # with `_kit_body`/`_normalize` from this file, per the recompute-not-copy
    # rule the 0.2.7 entries state, and all four agreed with the kit README's
    # declared value AND with the master's own header. That is three
    # independent sources agreeing, which is what makes copying safe here and
    # is not the case elsewhere in this manifest.
    "release_gate.yml": Pin(
        "1081d686ccf6b89a4af612ebc9c4ea3202a52a27068c00459a82e07187751511", "0.2.14"
    ),
    # The publishing caller, vendored as `.yml.template` rather than `.yml`
    # so GitHub does not run it and `check_release_gate.py` does not scan it.
    # It is a TEMPLATE: `.github/workflows/release.yml` was copied from this
    # body and edited, and that copy is this repository's own file and is
    # deliberately NOT pinned here. What binds the copy is the checker, run
    # against this directory by `tests/test_release_integrity.py`. Pinning
    # the copy instead would have frozen this repository's own gate commands
    # inside a kit hash.
    "release_caller.yml": Pin(
        "be93714d94cb36780d9b30374e6c28c760c303c13fe5b706bb8ca800d07ee395", "0.2.14"
    ),
    # 0.2.7, the HUB-6 promotion. Two of the three guards
    # INC-20260729-0854-shared needs, plus the review policy they are
    # stated in. Every hash below was RECOMPUTED from the master with
    # `_kit_body`/`_normalize` from this file, not copied from the kit
    # README: the lane brief refuses the manifest as a source because the
    # two shipped-surface bodies changed three times during the
    # promotion. The recomputation agreed with all nineteen declared
    # entries, which is the check having been run, not skipped.
    #
    # The two shipped-surface rows have since moved to 0.2.18 and sit
    # below with their own entry; the probe-closure pair is what remains
    # of this promotion at 0.2.7.
    "check_probe_closure.py": Pin(
        "5b4a76ea8e94d6185cd200d0f0324e6501967d1d959c94e5a0e0f31019c142a2", "0.2.7"
    ),
    "check_probe_closure_mutations.py": Pin(
        "59f3f3c120d7b834bae78b047b2e76d638952a4fb749783b78caba9214767b9c", "0.2.7"
    ),
    # 0.2.11 added one paragraph, the INERTNESS rule (BRF-061 item 16): a
    # reproduction that cannot show it exercised the claimed path is not
    # evidence, so every probe carries what proves it touched the code it
    # names, beside its verdict.
    #
    # 0.2.15 adds two more sections and changes no existing rule. DESIGN
    # BEFORE EDIT states, with its measurement, that an edit made under
    # review pressure carries a written statement of what it changes and
    # what it cannot break; ITA-2E proved it in a controlled comparison and
    # ITA-4 adopted it unasked. The round-two distinction inside the
    # recursion cap is the load-bearing one: a round-two finding ABOUT
    # round one's fix is the fix not being done, so it is FIXED in round
    # two rather than registered, and only NEW ground is registered. GATE,
    # PUSH, RELEASE, the ordering rule and probe closure are untouched in
    # meaning. `check_review_rounds.py` below is that rule's mechanism.
    #
    # itaca's `develop` skill POINTS at the design-before-edit section
    # rather than restating it, which is that skill's own convention and
    # the whole reason the rule went into the shared policy.
    #
    # 0.2.16 adds three things and moves no existing rule in meaning. The
    # PROPERTY SENTENCE sits INSIDE design before edit, which is why the
    # `develop` skill's pointer carries it without being edited: a fix
    # recorded in a round ledger states, in one sentence written BEFORE the
    # edit, the invariant it establishes. Beside it, the round ledger's
    # locator convention goes into the recursion cap, and a new section CITE
    # AN ID WITH ITS TITLE arrives with `check_citations.py`.
    # The declared value agreed with the master body on recomputation.
    "review-policy.md": Pin(
        "e0617a4f6f4a70de5dfe55a66e38efc2faaf1e312a4e543c7f6a21e10f1bbf6f", "0.2.16"
    ),
    # 0.2.15, NEW: the two-round cap, mechanised. The policy has stated the
    # cap since 0.2.7 and nothing enforced it, and the naive mechanism
    # ("two rounds, then register whatever is left") is WRONG in the exact
    # case the cap is most likely to meet. Lane ITA-4 is the evidence: its
    # round-one FIXES were themselves defective, six guards did not guard,
    # one false-fired, and it introduced a fresh defect in the same commit
    # that guarded the old one. Under a flat count all of that would have
    # shipped, documented as known. So the checker refuses a ledger that
    # REGISTERS a finding about a previous round's fix, refuses a third
    # round with no named authority, and refuses a ledger that certifies
    # nothing.
    #
    # The LEDGER FORMAT is PROPOSED and not settled, on the precedent
    # `check_probe_closure.py` set, and the checker's own docstring says
    # so. This lane recorded its round ledger in that format as the first
    # consumer use of it; a lane that finds the format wrong corrects it by
    # kit promotion, never by hand-editing this copy.
    #
    # 0.2.16 adds RULE 8 and a LOCATOR, and rule 8 REDDENS EXISTING LEDGERS
    # deliberately: a `fixed` row must carry `property=`, one sentence
    # stating the invariant the fix establishes.
    #
    # MEASURED 2026-08-02 by
    #
    #     python .claude/kit/check_review_rounds.py \
    #         --root "$ITACA_MANAGEMENT_ROOT" --all
    #
    #     ---- ITA-11-followup_rounds.ledger ----   REFUSED: 22 violation(s)
    #     ---- ITA-11_rounds.ledger ----            REFUSED: 22 violation(s)
    #     2 ledger(s) checked, 2 refused                          EXIT 1
    #
    # Every one of the 44 violations is rule 8, and each ledger carries 22
    # `fixed` rows, which is the same number by construction. The invocation
    # is written out because a count with no invocation beside it cannot be
    # re-run, and a first version of this note recorded "22 and 24" and
    # "forty-five invariants" from a reading rather than from this output.
    #
    # BOTH ARE LANE ITA-11'S WORK and only one says so in its `lane:` field:
    # `ITA-11_rounds.ledger` declares `lane: ITA-11` and
    # `ITA-11-followup_rounds.ledger` declares `lane: ITC-20260802-0330`,
    # the plan item it reviews. The filename convention and the `lane:`
    # field are not the same thing, which is worth knowing before wiring
    # anything that assumes they are.
    #
    # THEY ARE NOT RETROFITTED, which is this repository's call and is
    # recorded here because it decides what tier 1 can run. The policy says
    # writing the sentence after the fix is not the mechanism, and the whole
    # value of the field is at the moment of writing; inventing 44
    # invariants for fixes another lane made would produce a record that
    # reads as evidence and is not. So they stay as closed historical
    # records, `--all` is NOT wired, and `tests/test_review_rounds.py` runs
    # the LANE form against a ledger written under rule 8 from its first
    # line. Wiring `--all` needs those two resolved and is registered as
    # `ITC-20260802-1715`.
    #
    # The locator adds NO environment variable, on the precedent
    # `prepush_receipt.py` set: `--root <dir> --lane <id>` resolves
    # `<root>/<lane>_rounds.ledger`, and what an absent root means at a gate
    # is each repository's charter call. itaca's is written in CLAUDE.md and
    # is a SKIP that must be announced, never a denial.
    # Both declared values agreed with the master bodies on recomputation.
    "check_review_rounds.py": Pin(
        "b09fdec02dc0674a540bb5429c6343a8d4b7747fc286232dcb54f9b6e4508c4e", "0.2.16"
    ),
    "check_review_rounds_mutations.py": Pin(
        "9da4b72e42fa1369d5c55c114a6096336001a1f905dbea5d69f6627501d81e26", "0.2.16"
    ),
    # 0.2.16, NEW: the spawn guard that judges a spawn by the CALL.
    # `ITC-20260802-0200` is written against THIS repository's own
    # `test_no_spawn_site_bypasses_child_env`, which decided the question by
    # reading a fixed window of lines after each `subprocess.run(`, and lane
    # ITA-11 round two met both of that shape's failure directions in one
    # commit: a neighbor's `env=` sixteen lines away excused two real
    # offenders, and a correct call whose argv was written one element per
    # line was reported as an offender seventeen lines from its own opening.
    #
    # The window guard is RETIRED in the same commit that vendors this, and
    # that is the decision the adoption brief hands to this repository rather
    # than taking: two guards claiming the same coverage teach a reader to
    # trust neither, and the one being retired has both failure directions
    # reachable while this one has neither. What the retirement must not lose
    # is the ACCOUNTING, so the replacement asserts a floor on the checker's
    # own checked-count line; `tests/test_spawn_env.py` carries both.
    #
    # MEASURED 2026-08-02 by `python .claude/kit/check_spawn_env.py tests`
    # on first run, before any edit: `checked 79 module(s), 32 spawn
    # call(s), 8 unguarded, 0 unverifiable`, EXIT 1. All eight were `git`
    # spawns, which the retired guard never looked at because it only ever
    # considered `sys.executable`. They were fixed in the same commit
    # rather than registered, because a wired checker that is red wires
    # nothing. The same invocation now reports 80 modules and 33 spawn
    # calls, 0 unguarded: this lane's own module is the difference.
    # Both declared values agreed with the master bodies on recomputation.
    "check_spawn_env.py": Pin(
        "b5db024d0e110f379bc9c019ed2ef117e14a952b95895593d81a2e394a3c7619", "0.2.16"
    ),
    "check_spawn_env_mutations.py": Pin(
        "133ffcab519c483d598aa6ab9cb67feeb22546b4b2a85aaa0f063851646d713b", "0.2.16"
    ),
    # `check_citations.py` and its companion are rows 4 and 5 of the kit
    # 0.2.16 adoption and are DELIBERATELY ABSENT from this manifest. They
    # are the one pair lane ITA-12 could not vendor, and the reason is
    # recorded here rather than in a lane document, because the next lane to
    # read this file is the one that will try again.
    #
    # The master's body carries an EM DASH and an EN DASH, in the character
    # class of an `lstrip` that removes a heading's separator, at FILE line
    # 262 of `check_citations.py` (body line 255; the file line is what a
    # reader opens the master at). The class holds a space, a colon, a
    # hyphen, a period, the en dash and the em dash. IT IS NOT QUOTED HERE,
    # and that is not squeamishness: this file is itself walked by the dash
    # guard, so quoting it would redden the very check the note is about.
    # Confirmed by CODE POINT, U+2013 and U+2014, rather than by rendered
    # output, which cannot tell the two from a hyphen.
    #
    # THE MASTER IS NOT IN THIS TREE, deliberately, so those line numbers
    # cannot be checked from a clone of this repository: they are of kit
    # 0.2.16's `check_citations.py` as published, and a reader confirms
    # them in the kit repository rather than here. They go stale silently
    # on the next master revision, which is one more reason this row waits
    # on a kit promotion rather than on anything local.
    #
    # That is functional and harmless everywhere except here: CLAUDE.md
    # states "Never use em dashes or en dashes anywhere, in any file. No
    # exceptions", and `tests/test_house_style.py` walks every vendored
    # body for exactly that.
    # Vendoring the pair turns that walk RED on a file this repository is
    # forbidden to hand-edit, so the two guards would contradict each other
    # and one of them would have to be weakened.
    #
    # AN EXEMPTION WAS CONSIDERED AND REFUSED. This repository has already
    # decided this question in the opposite direction: `release.yml.template`
    # is a vendored kit body that reached the tree exempt from the dash walk
    # BY ACCIDENT, and the walk was widened to reach it rather than the
    # exemption being kept, with CLAUDE.md's "No exceptions" cited in the
    # comment that did it. The kit has honored that before too, at 0.2.15,
    # when four British spellings inside bodies this walk scans were changed
    # for it. So the defect is routed to the coordination level, and the two
    # rows are vendored by the lane that adopts the fixed master. The
    # `--mode` decision the adoption brief asks for is taken anyway and is
    # written in CLAUDE.md, so the next lane vendors and wires rather than
    # deciding.
    #
    # MEASURED, so the scope is not guessed: of the eleven 0.2.16 masters,
    # `check_citations.py` is the ONLY one carrying either character, and its
    # own companion is clean.
    # 0.2.15, NEW: the version-control skill. It carries the push sequence
    # as a template and adds NO mechanism, which is why it is the lowest
    # blast radius row in the whole batch. It exists because the push step
    # failed five distinct ways across two lanes and none of them was about
    # the code: a redirection flag after `git push` in one command string,
    # pytest and mypy off PATH, a PowerShell PATH assignment sent to a bash
    # shell, and a background task killed twice.
    #
    # It is the one pinned copy that lives OUTSIDE the two ruff-excluded
    # vendored directories, under `.claude/skills/`, so the directory sweep
    # in `test_no_unpinned_artifact_hides_in_the_vendored_dirs` does not
    # reach it. What drift-checks it is this pin plus its COMMITTED row,
    # which assert positively that the path exists and hashes as declared,
    # rather than asserting the absence of anything.
    #
    # 0.2.21, adopted in ITA-17 after this pin was HELD at 0.2.15 earlier in
    # the same lane. The hold and its release are both recorded, because the
    # reasoning was sound and its premise expired within the hour, which is
    # worth more to a later reader than a clean-looking pin.
    #
    # THE HOLD: ITA-14 exists to adopt 0.2.17 and its recorded justification
    # was already stale, "the version-control skill is UNSELECTABLE in itaca
    # until this lands", because ITA-15 had made it selectable by splitting
    # the stamp from the deployed body. What remained at 0.2.17 was content.
    # And a further kit revision of this artifact's own "If the push is
    # denied" section was pending, which lists four denial categories while
    # the 0.2.18 gate can print six more. Adopting 0.2.17 would have vendored
    # one artifact twice in a week.
    #
    # THE RELEASE: that revision shipped as 0.2.21, promoted specifically so
    # that no repository vendors this artifact twice. So adopting now IS the
    # "once" the hold was protecting; the hold was discharged rather than
    # overruled. 0.2.21 carries the six CI denial sub-kinds AND section 6,
    # read CI for the SHA you pushed. `ITC-20260811-2300` records it.
    #
    # TWO FILES, AND THAT IS NOW THE KIT RULE rather than this repository's
    # local arrangement: `OQ-56`, answered by the author on 2026-08-11. A kit
    # artifact carrying frontmatter and deployed as a live skill is vendored
    # as the stamped copy of record here plus the body alone at the deployed
    # path, tied by `test_the_runtime_skill_body_matches_the_of_record_copy`.
    # This repository's own arrangement was promoted, and the alternative it
    # had proposed, teaching the guard to skip the banner, was refused with
    # its reason: the loader is Claude Code's, so the guard would pass while
    # the skill stayed unloadable.
    #
    # MEASURED WHILE PROMOTING, and worth carrying because it is the case
    # against trusting a version header: the master reached 0.2.17 and NOT
    # ONE deployment took it. This repository's of-record copy and the
    # coordination level's own deployed skill both still hashed to the 0.2.15
    # body, and nothing in any of the three trees compares a deployed skill
    # body against its master. That is the currency gap `OQ-53` names, met
    # again on a different artifact.
    # The declared value agreed with the master body on recomputation.
    "version-control.md": Pin(
        "a4a219dea812abef16cfed55cac02a83d2f7d1d1525238cc9ee87bd46400ec59", "0.2.21"
    ),
    # 0.2.13 turned two rules into six, and the sixth is the one the
    # rehearsal paid for: GitHub EVALUATES the `description` of a
    # `workflow_call` input, so 0.2.12's worked example killed every run at
    # startup with no job to attribute it to. Rule 1 now refuses expression
    # syntax in any such description.
    #
    # 0.2.15 is MESSAGES AND COMMENTS ONLY (`ITC-20260730-2320`). Rules 5
    # and 6 gain a suggested fix and rule 5 prints the covered set beside
    # the uncovered leg, which is the worst of the five defects that record
    # carried: the three-part error rule both libraries hold, broken inside
    # the guard that protects the release path, on the two refusals a
    # maintainer actually hits. Beside it, `Rules 4's` became `Rule 4's`,
    # four British spellings inside bodies that `tests/test_house_style.py`
    # scans became American, and an OLD_CALLER comment that had aged was
    # corrected.
    #
    # NO RULE'S VERDICT MOVES, and that claim is measured rather than
    # trusted: every live check over this repository's own workflows gives
    # the same verdict as it did at 0.2.13. Guard evidence moved from 40
    # cases and 28 mutants to 44 and 33, all denied, measured here on
    # adoption and not taken from the changelog. The one place a verdict
    # COULD have moved is the `licence` fixture whose job name is asserted
    # in a mutant's expected message, and the companion is what says
    # whether the expectation moved with it.
    # Both declared values agreed with the master bodies on recomputation.
    "check_release_gate.py": Pin(
        "465caa08e9ce041f3fc359b41701fffcb649ec223a194a533c8d89c8c593f6a2", "0.2.15"
    ),
    "check_release_gate_mutations.py": Pin(
        "c03575afa540d63c73a75209c8a1521950f53a6a57c0c66cc2f00a3f0f3c6d39", "0.2.15"
    ),
    "check_version_identity.py": Pin(
        "d9fd719a92bc82cd8c81ab60888bcae4eeed320af89bced74b2602350afe68bd", "0.2.6"
    ),
    "check_version_identity_mutations.py": Pin(
        "49f0dd3c2dd3ef257761ecbac32c5c0d3f56937f5d735080040843f6aeebf58a", "0.2.6"
    ),
    # 0.2.10, and the jump from 0.2.4 carries TWO changes, not one: 0.2.8
    # renamed the ledger variable the charter tells the analyst to read to
    # COORD_INCIDENT_LEDGER (author decision LEDGER-ENVVAR), and 0.2.10 adds
    # the section forbidding that seat from using Bash to mutate git state
    # (INC-20260729-2355-itaca, ITC-20260730-0180).
    #
    # RECOMPUTED from the master body, not copied from the master's declared
    # value, which is STALE for the third time in this manifest: the master's
    # header declares e093721f... beside a body that hashes to the value
    # below, and e093721f... is not the current body NOR the body with the
    # 0.2.10 section removed, so it is left over from some earlier edit. That
    # is a defect in the master's header, routed to the coordination level as
    # ITC-20260730-0210, and the vendored copy's own header carries the
    # recomputed value because the stamped-copy check asserts header equals
    # pin. The `write_attestation.py` entry above records the same class one
    # artifact over, and the recompute-not-copy rule the 0.2.7 entries state
    # is what caught it here. Cross-check that the recomputation is right and
    # not the mismatch: the same function reproduces the 0.2.4 pin exactly
    # from the body this commit replaces.
    # 0.2.11 adds two frontmatter keys and nothing else: `model: opus` and
    # `effort: low`, so the seat's model and reasoning effort are declared
    # by its charter rather than inherited from whoever spawns it. The
    # 0.2.11 body's declared value AGREED with the master body on
    # recomputation, which the three entries above could not say.
    "incident-analyst.md": Pin(
        "e61e50c5f15543b9edbc6e19e319cf5ea742a231b9fbe3efbacc32a91754229e", "0.2.11"
    ),
    # 0.2.11, and it is an ADOPTION rather than a lagging pin moving: this
    # repository had never vendored this artifact at all, which
    # `ITC-20260730-2140` recorded as the one row of three that was an
    # absence and not staleness. It is the isolation mechanism for
    # REV007-003: one detached worktree per reviewer lens, so a lens never
    # receives the live tree as cwd. Two recorded failures share that
    # structural cause, a reviewer running `git restore` in the live tree
    # and destroying a lane's uncommitted edits, and two Bash-holding
    # lenses corrupting each other's measurements (`ITC-20260730-0250`).
    #
    # 0.2.15 fixes three defects, two of them measured by lanes of this
    # repository, and it is the one row of that batch with an INTERFACE
    # change. `open` now prints FIVE tab-separated fields per lens, not
    # two, because the diff, the paths and the findings moved OUT of the
    # worktree into a sidecar beside it. `ITC-20260801-1600`: those three
    # files were untracked-but-not-ignored inside the worktree, so a
    # house-style walk that asks git for tracked plus untracked files
    # SCANNED THEM, and `RR_DIFF.patch` contains the diff, so a diff
    # touching a file that quotes the author's name made every lens report
    # a red that does not exist on the reviewed ref. The worktree is now a
    # pristine checkout under ANY consumer's scanning discipline, which is
    # why the alternative of exempting the filenames here was rejected: it
    # puts a kit artifact's name into this repository's guard and a
    # repository that forgets inherits the false red silently.
    # `ITC-20260801-0130`: `close` removed each worktree inside the loop
    # that collected its findings and aborted on the first git failure, so
    # one lens still running stranded every worktree after it AND their
    # findings were never collected. It now collects everything first,
    # continues past a failure, and exits 1 naming each one. The third
    # defect was found by executing the promotion's own fixture: the shared
    # temp root was keyed on the repository's directory NAME alone, so two
    # checkouts with the same basename shared a root.
    #
    # That last one is why `close` MUST be run with the OLD body before
    # this pin moves: a worktree opened under the old root is not found
    # under the new one. ITA-11 ran it and measured no worktrees to close.
    # ITA-12 ran it again for the same reason and measured the same thing,
    # with `git worktree list` reporting the main checkout alone, so no
    # state was carried across this body change either.
    #
    # 0.2.16 fixes `ITC-20260802-0010`, and the finding's own correction is
    # what shapes the repair. The fallback is not the boundary: `git worktree
    # remove --force` takes a busy tree on its own, so the real limit is the
    # COLLECTION. Two halves therefore. The rmtree fallback is GATED on git's
    # own registration, so a directory git still lists as a worktree is never
    # taken and stays a reported failure with exit 1; and the findings file
    # is RE-READ immediately before its sidecar would be removed, with the
    # newer bytes collected and the SIDECAR KEPT when they differ.
    #
    # WHAT THAT DOES NOT DO, and the `role-review` skill's sentence is held
    # to it: a successful forced removal still pulls the cwd out from under a
    # running lens, and nothing portable can detect that. The operator rule
    # "do not close until every lens has reported" is NOT retired; it is
    # reduced from protecting findings to protecting a working directory.
    # 0.2.17 fixes BRF-077 and moves nothing else: `close` printed
    # `len(collected)`, which counts WORKTREES, so it printed the same number
    # whether five lenses reported or none did. It now counts the lenses that
    # actually WROTE and NAMES the silent ones. The trap the fix had to clear
    # is that `open` seeds every findings file with a heading, so a byte-length
    # test would have counted a lens that never wrote a finding.
    #
    # ON THE RUN-CLOSE-FIRST PRECAUTION the 0.2.15 paragraph above records,
    # stated as what was actually done rather than as the ritual: `close` was
    # NOT run with the old body here, because there was nothing to close.
    # `git worktree list` at the moment of the re-vendor reported the main
    # checkout alone, so no worktree could be stranded by the body changing
    # under it. The precaution the 0.2.15 entry describes is specific to a
    # change in the TEMP-ROOT scheme, which 0.2.17 does not touch; it changes
    # what `close` COUNTS and prints. Recorded this way because "ran close
    # first" would have been a false claim and the reader of the next
    # re-vendor needs to know which of the two situations they are in.
    # The declared value agreed with the master body on recomputation.
    "review_runner.py": Pin(
        "f906c6c92b3b504ade3e4defcfe03803925b33f66128acf35101800bfab0025c", "0.2.17"
    ),
    # 0.2.19, and it is a POLICY change rather than a fix, which is why this
    # entry says who decided it. The author RETIRED the requirement that a
    # skill declaring `side-effects` must also set
    # `disable-model-invocation: true`, for all skills and with no exception,
    # on 2026-08-11. Her reasoning, recorded in `BRF-079`, is that the
    # verification stages downstream carry the safety level she requires for
    # more autonomy; the objection was put to her before she decided and she
    # decided with it on the table. This lane APPLIES the decision and does
    # not weigh it.
    #
    # WHAT THE GUARD ASSERTS NOW is strictly less than before and in one
    # direction only: every skill must CARRY a `side-effects` declaration,
    # with `none` a valid answer and SILENCE the thing refused. The
    # implication is gone; the declaration requirement, which is the half
    # that replaced a hardcoded allowlist, is untouched.
    #
    # THE ADOPTION BRIEF SAID THIS HALF WOULD FIND NOTHING TO FIX AND THAT
    # WAS FALSE HERE, measured rather than trusted, and the correction is
    # kept because it is the whole reason the row above this one moved. The
    # brief's claim was that all six skills already declare `side-effects`,
    # so 0.2.19 is a pure removal. The FIRST run of the 0.2.19 body in this
    # tree, before anything was edited, was
    #
    #     UNDECLARED .claude\skills\version-control\SKILL.md: carries no
    #     side-effects declaration
    #     checked 6 skill(s), 5 declaring, 1 undeclared          EXIT 1
    #
    # and `test_no_side_effecting_skill_is_model_invocable` asserts exit 0,
    # so adopting this row alone would have reddened CI. The skill DOES
    # declare `side-effects: none`; it was unreadable, not silent, because
    # the deployed file was the STAMPED copy and `_frontmatter` reads
    # frontmatter only when `---` is line 1. The 0.2.2 body never saw it,
    # since under the implication form a skill declaring nothing was not the
    # guard's business, which is precisely the hole 0.2.19's docstring says
    # it closes. The repair is the incident-analyst arrangement, applied by
    # `test_the_runtime_skill_body_matches_the_of_record_copy`.
    #
    # MEASURED on adoption, in both directions, because a policy relaxation
    # is exactly the shape whose adoption can be vacuous. After the split and
    # the five removals, the 0.2.19 body reports `checked 6 skill(s), 6
    # declaring, 0 undeclared`, EXIT 0. The 0.2.2 body run against that SAME
    # tree refuses all five with `declares side-effects but does not set
    # disable-model-invocation: true`, EXIT 1, which is what says the removal
    # was gated on this row moving and is not free.
    # Both declared values agreed with the master bodies on recomputation.
    "check_side_effect_guard.py": Pin(
        "0e8c7315dd316570e44a294faefabda7971c9c7a228e5c7ac4b48dbee7aec30e", "0.2.19"
    ),
    "check_side_effect_guard_mutations.py": Pin(
        "67321ce237a4314a988424cff2b7bac22bc9eba6db9862806c66127c606b7bc9", "0.2.19"
    ),
    # 0.2.18, COORD-17, and it changes WHERE a directory may sit and never
    # what may sit under it: the `egg-info` exemption was anchored at the
    # archive root, so a src-layout project's `src/<name>.egg-info/PKG-INFO`
    # missed it and one real repository carried seven permanent false
    # findings. itaca is not src-layout in the way that triggers it, so this
    # row is expected to cost nothing here and is vendored because the body
    # drifted anyway rather than because this repository needed it.
    #
    # MEASURED, so "costs nothing" is not a prediction: the checker's verdict
    # over this repository's own artifact is unchanged across the row.
    # Both declared values agreed with the master bodies on recomputation.
    "check_shipped_surface.py": Pin(
        "f5dffb534da98061352a941cf5e9ca1de907afc4b0fcf059a7fe7d0a4b33a49b", "0.2.18"
    ),
    "check_shipped_surface_mutations.py": Pin(
        "09b94846024e803116f2308a6aecccc6d70e91da021104fa459ef06c0d486daa", "0.2.18"
    ),
    "check_incidents.py": Pin(
        "f6d3430a6d0ee44b4843f7d297a3454ce40d34cd83dc182a2ef840952c5c9c0a", "0.1.0"
    ),
    "snap.sh": Pin(
        "0835e6ae1bd43d05e213a88552bcd94a1b91ebec946f9dabb5411d7595b265d1", "0.2.5"
    ),
    # Both at 0.2.10, and the companion only reached it now. The comment
    # here used to say "per-file versions, as the kit ships them: the
    # checker is at 0.2.10 and its companion at 0.2.3", which asserted a
    # fact about the KIT and was measured false: the kit ships both at
    # 0.2.10 and has since 0.2.11's manifest at the latest. The 0.2.3 pin
    # was correct under the deployed-copy rule and wrong about its reason.
    # What was actually true is worse than a stale version number: the
    # DEPLOYED checker was upgraded to 0.2.10 and its mutation companion
    # was left at 0.2.3, so for the whole of that window the artifact
    # proving this checker can still fail was seven versions behind the
    # checker. That is the guard-guarding-the-guard going stale, which is
    # the failure class the incident rule exists for, and no test could
    # see it because both halves were self-consistent.
    #
    # Measured on adoption: the deployed companion now hashes to the
    # canonical value, and it runs 0 check(s) could not fail. Its case
    # list gained "an empty plan directory refuses with CANNOT VERIFY",
    # which is the case `ITC-20260730-0205` recorded as absent from the
    # companion while the checker's own empty-walk fix was already
    # shipped, so this adoption closes that gap as well.
    "check_plan_kit.py": Pin(
        "a6eca8d542e6189b6b14cde0d4eb92e3f2850f8a21b3dd26a8fc30c06829c39c", "0.2.10"
    ),
    "check_plan_kit_mutations.py": Pin(
        "19e0082627371279642723f35d7f78af0e59577eda3ff751cc658332dc8151ad", "0.2.10"
    ),
}

# Committed vendored copies: (manifest key, repo-relative path).
COMMITTED: list[tuple[str, str]] = [
    ("role_review_gate.py", ".claude/hooks/role_review_gate.py"),
    ("write_attestation.py", ".claude/hooks/write_attestation.py"),
    # Beside the gate, which is where `_ci_state_body` looks first. The
    # gate treats an absent body as a REFUSAL rather than a skip, so these
    # two rows and the gate row above are one vendoring and not three.
    ("ci_state.py", ".claude/hooks/ci_state.py"),
    ("ci_state_mutations.py", ".claude/hooks/ci_state_mutations.py"),
    # A second PreToolUse hook, so it sits with the first, and its companion
    # beside it exactly as the ci_state pair does.
    ("execution_guard.py", ".claude/hooks/execution_guard.py"),
    ("execution_guard_mutations.py", ".claude/hooks/execution_guard_mutations.py"),
    # A kit TOOL rather than a hook, so it sits under `.claude/kit`. NOT
    # `.claude/tools`, which holds this repository's OWN scripts
    # (`closing_ci_check.py`) and is deliberately not swept by
    # `test_no_unpinned_artifact_hides_in_the_vendored_dirs` below; a
    # vendored body there would escape that sweep.
    ("detached_gate.py", ".claude/kit/detached_gate.py"),
    ("incident-analyst.md", ".claude/kit/incident-analyst.md"),
    ("check_side_effect_guard.py", ".claude/kit/check_side_effect_guard.py"),
    (
        "check_side_effect_guard_mutations.py",
        ".claude/kit/check_side_effect_guard_mutations.py",
    ),
    ("check_release_gate.py", ".claude/kit/check_release_gate.py"),
    (
        "check_release_gate_mutations.py",
        ".claude/kit/check_release_gate_mutations.py",
    ),
    ("check_version_identity.py", ".claude/kit/check_version_identity.py"),
    (
        "check_version_identity_mutations.py",
        ".claude/kit/check_version_identity_mutations.py",
    ),
    ("release_gate.yml", ".github/workflows/release_gate.yml"),
    ("release_caller.yml", ".github/workflows/release.yml.template"),
    ("check_shipped_surface.py", ".claude/kit/check_shipped_surface.py"),
    (
        "check_shipped_surface_mutations.py",
        ".claude/kit/check_shipped_surface_mutations.py",
    ),
    ("check_probe_closure.py", ".claude/kit/check_probe_closure.py"),
    (
        "check_probe_closure_mutations.py",
        ".claude/kit/check_probe_closure_mutations.py",
    ),
    ("review-policy.md", ".claude/kit/review-policy.md"),
    ("review_runner.py", ".claude/kit/review_runner.py"),
    ("prepush_receipt.py", ".claude/kit/prepush_receipt.py"),
    (
        "prepush_receipt_mutations.py",
        ".claude/kit/prepush_receipt_mutations.py",
    ),
    ("check_review_rounds.py", ".claude/kit/check_review_rounds.py"),
    (
        "check_review_rounds_mutations.py",
        ".claude/kit/check_review_rounds_mutations.py",
    ),
    ("check_spawn_env.py", ".claude/kit/check_spawn_env.py"),
    (
        "check_spawn_env_mutations.py",
        ".claude/kit/check_spawn_env_mutations.py",
    ),
    # The STAMPED copy, and it moved here in lane ITA-15 from the deployed
    # path. It is the incident-analyst arrangement applied one artifact
    # over, for the same reason and now with a measurement behind it: a
    # DEPLOYED file whose reader expects frontmatter on line 1 cannot carry
    # a prepended provenance header. `test_the_runtime_skill_body_matches_
    # the_of_record_copy` ties the two, exactly as the agent charter's test
    # does, so the runtime copy still cannot be edited without this test
    # catching it.
    ("version-control.md", ".claude/kit/version-control.md"),
]


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _kit_body(text: str) -> str:
    """The bytes-as-text the body-sha256 is computed over.

    For a stamped copy: everything after the ``END KIT PROVENANCE`` line.
    For an ``.md`` HTML-comment header, the closing ``-->`` line that
    follows the marker belongs to the header, not the body, and is
    dropped. For an unstamped shared tool deployed raw (no marker), the
    whole file is the body.
    """
    norm = _normalize(text)
    if _MARKER not in norm:
        return norm
    after = norm.split(_MARKER, 1)[1]
    after = after.split("\n", 1)[1] if "\n" in after else ""
    if after.startswith("-->\n"):
        after = after[len("-->\n") :]
    elif after == "-->":
        after = ""
    return after


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _header_fields(text: str) -> dict[str, str]:
    """The provenance header's ``key: value`` fields, or empty if unstamped.

    Works for both comment syntaxes: ``# key: value`` for ``.py``/``.sh``
    and bare ``key: value`` inside the ``.md`` HTML comment. Only the lines
    before the marker are read.
    """
    norm = _normalize(text)
    if _MARKER not in norm:
        return {}
    fields: dict[str, str] = {}
    for line in norm.split(_MARKER, 1)[0].splitlines():
        stripped = line.lstrip("#").strip()
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            fields[key.strip().lower()] = value.strip()
    return fields


def _assert_matches_manifest(
    key: str, path: Path, *, require_stamp: bool = False
) -> None:
    """The load-bearing check: body hash, and header fields when stamped.

    ``require_stamp`` is passed for COMMITTED copies, which must carry
    their provenance header. Without it the header assertions below are
    opt-in: an unstamped file skips them, and because ``_kit_body`` falls
    back to "no marker means the whole file is the body", DELETING the
    provenance block leaves the body hash correct and the suite green.
    That would silently downgrade a stamped-copy check to a hash-only one
    and discard the only in-repo record of which kit version a copy is at.
    Env-located tools are legitimately deployed raw, so they do not set it.
    """
    pin = MANIFEST[key]
    text = path.read_text(encoding="utf-8")
    if require_stamp:
        assert _MARKER in _normalize(text), (
            f"{path} has lost its kit provenance stamp (no {_MARKER!r} line). "
            f"A committed vendored copy must keep its header: without it the "
            f"kit-version and body-sha256 assertions below do not run at all. "
            f"Re-vendor from the kit; do not strip the header."
        )
    computed = _sha256(_kit_body(text))
    assert computed == pin.body_sha256, (
        f"{path} body sha256 {computed} != pinned {pin.body_sha256}. The "
        f"vendored copy has drifted from kit {key}; re-vendor from the kit, "
        f"do not hand-edit the copy."
    )
    header = _header_fields(text)
    if header:
        # A stamped copy must also carry a header consistent with the
        # manifest, so an edit that fixes the body but not the header (or
        # vice versa) still fails.
        assert header.get("body-sha256") == pin.body_sha256, (
            f"{path} header body-sha256 {header.get('body-sha256')} != pinned "
            f"{pin.body_sha256}"
        )
        assert header.get("kit-version") == pin.kit_version, (
            f"{path} header kit-version {header.get('kit-version')} != pinned "
            f"{pin.kit_version}"
        )


@pytest.mark.parametrize("key,rel", COMMITTED, ids=[k for k, _ in COMMITTED])
def test_a_committed_kit_copy_matches_the_manifest(key: str, rel: str) -> None:
    """Every committed vendored copy reproduces its pinned body hash."""
    path = _ROOT / rel
    assert path.is_file(), f"vendored kit copy missing at {path}"
    _assert_matches_manifest(key, path, require_stamp=True)


def test_the_runtime_agent_body_matches_the_of_record_copy() -> None:
    """The loaded agent must not drift from its stamped drift-of-record copy.

    The runtime ``.claude/agents/incident-analyst.md`` carries no header
    so its loader sees frontmatter on line 1; the stamped copy under
    ``.claude/kit`` is what the manifest check above reads. This ties the
    two together so the runtime cannot be edited without the drift test
    catching it.
    """
    runtime = _ROOT / ".claude" / "agents" / "incident-analyst.md"
    of_record = _ROOT / ".claude" / "kit" / "incident-analyst.md"
    assert runtime.is_file(), (
        f"the runtime agent charter is missing at {runtime}; the "
        f"incident-analyst agent will not load. Materialize it from the "
        f"of-record copy at {of_record} (its body, with the header dropped)."
    )
    assert of_record.is_file(), (
        f"the drift-of-record copy is missing at {of_record}; the runtime "
        f"charter has nothing to be checked against. Re-vendor it from the kit."
    )
    runtime_body = _normalize(runtime.read_text(encoding="utf-8"))
    of_record_body = _kit_body(of_record.read_text(encoding="utf-8"))
    assert runtime_body == of_record_body, (
        f"{runtime} has drifted from its drift-of-record copy {of_record}. "
        f"The runtime charter is a DERIVED kit copy, not a source: the fix is "
        f"to re-vendor {of_record} from the kit and rewrite the runtime file "
        f"from that body. Do not hand-edit either, and do not sync the "
        f"of-record copy to the runtime one, which would defeat the pin. Run "
        f"pytest -vv to see the full body diff."
    )
    assert _sha256(runtime_body) == MANIFEST["incident-analyst.md"].body_sha256, (
        f"{runtime} body sha256 {_sha256(runtime_body)} != pinned "
        f"{MANIFEST['incident-analyst.md'].body_sha256}. The runtime charter "
        f"has drifted from kit incident-analyst.md; re-vendor from the kit, "
        f"do not hand-edit the copy."
    )


def test_the_runtime_skill_body_matches_the_of_record_copy() -> None:
    """The deployed version-control skill must not drift from its record.

    The same arrangement as the agent charter above and adopted for the
    same structural reason, which lane ITA-15 measured rather than
    predicted. The deployed ``SKILL.md`` used to BE the stamped copy, so
    its first line was ``<!--`` and its frontmatter began on line 11. Kit
    0.2.19's ``check_side_effect_guard.py`` reads frontmatter only when
    ``---`` is the first line, so it read an empty map, and under 0.2.19
    an empty map is a REFUSAL where under 0.2.2 it was silently not the
    guard's business. Measured on adoption: ``5 declaring, 1 undeclared``,
    exit 1, on a body this repository is forbidden to hand-edit.

    So the stamp moved to ``.claude/kit/version-control.md`` and the
    deployed file became the body alone. Neither file was edited: both
    still reproduce the same pinned hash, which is what the assertions
    below check in both directions.

    THE UNDERLYING DEFECT IS THE KIT'S AND IS NOT FIXED BY THIS, which is
    said here so the next reader does not mistake a local arrangement for
    a repair. The kit prescribes prepending a provenance header to a
    vendored copy AND ships a guard that requires frontmatter on line 1;
    those two conventions contradict each other for any artifact that is
    both stamped and deployed, and every consumer will meet it. Routed to
    the coordination level rather than absorbed silently.
    """
    runtime = _ROOT / ".claude" / "skills" / "version-control" / "SKILL.md"
    of_record = _ROOT / ".claude" / "kit" / "version-control.md"
    assert runtime.is_file(), (
        f"the runtime version-control skill is missing at {runtime}; the "
        f"skill will not load. Materialize it from the of-record copy at "
        f"{of_record} (its body, with the header dropped)."
    )
    assert of_record.is_file(), (
        f"the drift-of-record copy is missing at {of_record}; the runtime "
        f"skill has nothing to be checked against. Re-vendor it from the kit."
    )
    runtime_body = _normalize(runtime.read_text(encoding="utf-8"))
    of_record_body = _kit_body(of_record.read_text(encoding="utf-8"))
    assert runtime_body == of_record_body, (
        f"{runtime} has drifted from its drift-of-record copy {of_record}. "
        f"The runtime skill is a DERIVED kit copy, not a source: the fix is "
        f"to re-vendor {of_record} from the kit and rewrite the runtime file "
        f"from that body. Do not hand-edit either, and do not sync the "
        f"of-record copy to the runtime one, which would defeat the pin."
    )
    assert runtime_body.startswith("---\n"), (
        f"{runtime} must open with its frontmatter on line 1, and starts "
        f"{runtime_body[:20]!r} instead. A prepended provenance header puts "
        f"the frontmatter out of reach of both the skill loader and kit "
        f"check_side_effect_guard.py, which reads a header-first file as "
        f"declaring nothing and refuses it. The stamped copy belongs at "
        f"{of_record}, not here."
    )
    assert _sha256(runtime_body) == MANIFEST["version-control.md"].body_sha256, (
        f"{runtime} body sha256 {_sha256(runtime_body)} != pinned "
        f"{MANIFEST['version-control.md'].body_sha256}. The runtime skill has "
        f"drifted from kit version-control.md; re-vendor from the kit, do not "
        f"hand-edit the copy."
    )


def _env_located() -> list[tuple[str, Path]]:
    """(manifest key, path) for shared tools that MUST exist when configured.

    Skipped entirely when neither variable is configured: a clone that
    never set them still runs a green suite. Note the asymmetry with the
    push gate, which since kit 0.2.8 DENIES on an unset ledger; the
    module docstring says why the two differ.
    Each tool is located by its OWN variable: the incident checker by the one
    the push gate resolves, READ from the gate through
    ``tests/gate_locator.py`` rather than written here, and the plan checker
    (and its companion) by ITACA_PLAN_VALIDATOR.

    Reading it matters more here than in the modules that also read it,
    because this one's drift mode is SILENT. A hardcoded name that the kit
    later renamed would make this function return no incident entry, and the
    caller would then take ``pytest.skip``: the incident checker's drift pin
    would simply stop being checked, with CI green. The same defect one module
    over produced a red test, which is strictly better. snap.sh is
    deliberately NOT here: it has no
    locator variable of its own, so binding it to the plan-validator
    directory would be a false coupling (a correctly configured plan
    validator whose directory happens not to hold snap.sh would fail a
    check that is not about the plan validator). It is drift-checked
    best-effort by ``_snap_if_present`` instead, and a locator variable for
    it is a registered kit item.
    """
    located: list[tuple[str, Path]] = []
    ledger = os.environ.get(ledger_env())
    if ledger:
        base = Path(ledger)
        checker = base if base.suffix == ".py" else base / "check_incidents.py"
        located.append(("check_incidents.py", checker))
    validator = os.environ.get("ITACA_PLAN_VALIDATOR")
    if validator:
        target = Path(validator)
        if target.suffix == ".py":
            # ITC-20260727-1542. A `.py` value NAMES THE CHECKER, and the
            # parent is never substituted for it. The old derivation took
            # `target.parent` and looked for `check_plan_kit.py` inside it,
            # so a value naming a retired `check_plan_entries.py` resolved to
            # the version-matched sibling and this suite stayed green while
            # the plan skill resolved the same variable to a file that does
            # not exist and validation silently skipped.
            #
            # Restricting the repair to values that do not EXIST was measured
            # insufficient by a reviewer: a value naming a real but wrong file
            # (the directory also holds the sister repository's
            # `check_plan.py`) was still reinterpreted, so the drift check
            # certified a checker the plan skill would never run. Naming the
            # configured path itself in both cases lets the caller's is_file
            # and manifest assertions report the real error.
            #
            # This matches `_resolve` in tests/test_plan_validator.py, which
            # has always read the `.py` form this way. The companion still
            # sits beside the checker, which is what `.parent` is for here.
            located.append(("check_plan_kit.py", target))
            located.append(
                (
                    "check_plan_kit_mutations.py",
                    target.parent / "check_plan_kit_mutations.py",
                )
            )
        else:
            located.append(("check_plan_kit.py", target / "check_plan_kit.py"))
            located.append(
                ("check_plan_kit_mutations.py", target / "check_plan_kit_mutations.py")
            )
    return located


def _snap_if_present() -> tuple[str, Path] | None:
    """snap.sh beside the plan validator, only if it is actually there.

    Best-effort: snap.sh has no locator of its own, so it is checked where
    it happens to sit and never asserted-present, which keeps a false
    coupling to ITACA_PLAN_VALIDATOR from reddening a correct config.
    """
    validator = os.environ.get("ITACA_PLAN_VALIDATOR")
    if not validator:
        return None
    target = Path(validator)
    directory = target.parent if target.suffix == ".py" else target
    snap = directory / "snap.sh"
    return ("snap.sh", snap) if snap.is_file() else None


def test_env_located_shared_tools_match_the_manifest() -> None:
    """Check the env-located shared tools against the manifest when configured."""
    located = _env_located()
    if not located:
        pytest.skip(
            f"neither {ledger_env()} nor ITACA_PLAN_VALIDATOR is set; "
            "env-located kit tools are not configured here"
        )
    for key, path in located:
        assert path.is_file(), (
            f"{key} is configured but missing at {path}. A set-but-unreachable "
            f"shared tool is a configuration error, not a clean skip."
        )
        _assert_matches_manifest(key, path)


def test_the_derivation_never_reinterprets_a_py_value_as_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falsify the derivation fix itself, hermetically.

    ``ITC-20260727-1542``. This is the only BEHAVIOR change in that repair,
    and on this machine the ambient ``ITACA_PLAN_VALIDATOR`` is a directory,
    so the ``.py`` branch never runs and the fix was covered by nothing: a
    reviewer measured the new line as unexecuted and confirmed that deleting
    it left the suite green. The test below is the falsifier that was
    missing, and it does not depend on how any machine is configured.

    Two shapes are checked, both of which the old derivation resolved to the
    sibling checker and so certified a file the plan skill would never run:

    1. a ``.py`` value naming a file that does not exist;
    2. a ``.py`` value naming a file that DOES exist but is not the kit
       checker, which is the shape that survived the first repair (the
       directory beside it holds the sister repository's ``check_plan.py``,
       so this is reachable by one plausible typo).
    """
    beside = tmp_path / "check_plan_kit.py"
    beside.write_text("# a valid-looking sibling\n", encoding="utf-8")

    for name, exists in (("retired.py", False), ("check_plan.py", True)):
        configured = tmp_path / name
        if exists:
            configured.write_text("# real file, wrong checker\n", encoding="utf-8")
        monkeypatch.setenv("ITACA_PLAN_VALIDATOR", str(configured))
        monkeypatch.delenv(ledger_env(), raising=False)
        located = dict(_env_located())
        assert located["check_plan_kit.py"] == configured, (
            f"the derivation resolved ITACA_PLAN_VALIDATOR={configured} to "
            f"{located['check_plan_kit.py']}, reinterpreting a .py value as "
            f"its parent directory and so certifying a checker beside the "
            f"configured path instead of the configured path itself. That is "
            f"the structural cause of ITC-20260727-1542, where the sibling "
            f"happened to be version-matched and this suite stayed green "
            f"while plan validation silently skipped."
        )


def test_a_configured_locator_names_something_that_exists() -> None:
    """A locator naming nothing must fail, never be reinterpreted.

    ``ITC-20260727-1542``. ``ITACA_PLAN_VALIDATOR`` was set to a retired
    ``check_plan_entries.py``, a file present in no tree. ``_env_located``
    derived a DIRECTORY from a ``.py`` value by taking its parent, that
    parent happened to hold a version-matched ``check_plan_kit.py``, and so
    this suite stayed green. The consequence was one-sided, which is what
    makes it worth a guard rather than a correction: the test was fine and
    the plan skill was not, because it resolved the same variable to
    ``.../check_plan_entries.py/check_plan_kit.py`` and plan validation had
    been silently skipping. A guard reporting green while the behavior it
    guards is absent is the failure class the incident rule exists to catch.

    The variable was repaired the same day. The repair is not the fix: the
    derivation trusted a path it never checked, so the next mistyped value
    would have failed in exactly the same way. This test checks the
    CONFIGURED value itself, so no parent directory can stand in for it.
    """
    # All THREE members of the locator family, not two. A reviewer measured
    # that ITACA_MANAGEMENT_ROOT was the one member no test read from the live
    # environment, so a root pointed at a path that does not exist skipped
    # green while handoffs and ledger entries would go somewhere nobody reads.
    # That is ITC-20260727-1542 one variable over.
    configured = [
        (name, Path(value))
        for name in (
            ledger_env(),
            "ITACA_PLAN_VALIDATOR",
            "ITACA_MANAGEMENT_ROOT",
        )
        if (value := os.environ.get(name))
    ]
    if not configured:
        pytest.skip(
            f"no member of the locator family is set ({ledger_env()}, "
            "ITACA_PLAN_VALIDATOR, ITACA_MANAGEMENT_ROOT); there is no "
            "configured locator to check"
        )
    missing = [f"{name}={path}" for name, path in configured if not path.exists()]
    assert not missing, (
        f"a configured shared-tool locator names a path that does not exist: "
        f"{missing}. This is a configuration error and not a skip. Note the "
        f"failure mode this guards (ITC-20260727-1542): when the value ends in "
        f"'.py', the directory derived from it is the PARENT, so a value naming "
        f"nothing can still resolve to a valid checker beside it and green this "
        f"suite while the plan skill resolves the same value to nothing. Point "
        f"the variable at the directory holding the checker, or at the checker "
        f"itself, and make sure that path exists."
    )


def test_snap_script_matches_the_manifest_where_it_is_deployed() -> None:
    """Drift-check snap.sh best-effort; it has no locator of its own."""
    found = _snap_if_present()
    if found is None:
        pytest.skip("snap.sh is not present beside a configured plan validator")
    key, path = found
    _assert_matches_manifest(key, path)


def test_the_run_reports_which_pins_it_could_not_check() -> None:
    """Name the unchecked pins, so a skip is an inventory and not a shrug.

    The env-located manifest entries are reachable only through an
    environment locator, and CI sets none, so they are routinely unchecked
    there. A pin nobody reads can be moved to anything and the suite stays
    green, which is the failure this repository already names elsewhere as
    reading a checker's exit code without reading its entry count. This
    test never fails on a legitimately unconfigured clone; it exists so the
    run states WHICH pins went unread rather than emitting a bare skip.
    """
    checked = {key for key, _ in COMMITTED}
    checked.update(key for key, path in _env_located() if path.is_file())
    snap = _snap_if_present()
    if snap is not None:
        checked.add(snap[0])
    unchecked = sorted(set(MANIFEST) - checked)
    assert checked, "no manifest entry was checked at all; the fixture is inert"
    if unchecked:
        pytest.skip(
            f"{len(checked)} of {len(MANIFEST)} pinned kit artifacts were "
            f"verified in this run. NOT verified, because their locator is "
            f"unset or the file is absent: {unchecked}. These pins are "
            f"unread here and a wrong value in them would not redden this run."
        )


def test_no_unpinned_artifact_hides_in_the_vendored_dirs() -> None:
    """A new artifact under a vendored dir must be pinned, or it escapes both.

    ``.claude/hooks`` and ``.claude/kit`` are excluded from ruff because
    everything in them is a drift-pinned vendored copy, and COMMITTED is a
    fixed list, not a glob. So a future file dropped there would be neither
    linted nor drift-checked. Pin that every artifact under them is a
    committed manifest entry, closing that gap before it opens.

    The sweep covers ``.md``, ``.sh``, ``.yml`` and ``.yaml`` as well as
    ``.py``. Checking only ``.py`` reproduced the gap one suffix over:
    ``.claude/kit`` already holds a pinned ``.md`` (the of-record
    incident-analyst charter), so a second ``.md`` dropped beside it would
    have escaped both layers, which is the exact shape this test exists to
    prevent. ``.yml`` was added when kit 0.2.6 introduced a vendored
    workflow; it does not live under these directories today, but the
    suffix gap is closed here rather than left for the copy that does.

    ``.github/workflows`` is swept too, and by a DIFFERENT rule: not every
    file there is a vendored copy (``ci.yml`` and ``release.yml`` are this
    repository's own), so the sweep keys on the kit provenance marker
    instead of the suffix. Any file carrying that marker must be a pinned
    COMMITTED entry. This is the gap that let ``release_gate.yml`` escape
    on two counts at once, wrong directory and wrong suffix, and nothing
    would have reminded anyone: the vendored-directory sweep passes
    whether or not that file is pinned.
    """
    committed = {(_ROOT / rel).resolve() for _, rel in COMMITTED}
    for vendored_dir in (".claude/hooks", ".claude/kit"):
        for suffix in ("*.py", "*.md", "*.sh", "*.yml", "*.yaml"):
            for artifact in (_ROOT / vendored_dir).glob(suffix):
                assert artifact.resolve() in committed, (
                    f"{artifact} is under a ruff-excluded vendored directory "
                    f"but is not a pinned COMMITTED kit copy; add it to the "
                    f"manifest and the drift test, or it is neither linted nor "
                    f"drift-checked."
                )
    # The MARKER rule, for directories that hold a MIX of vendored copies
    # and this repository's own files, where a suffix sweep would be wrong.
    #
    # `.claude/tools` joined this list in ITA-17, on an architect finding.
    # It holds `closing_ci_check.py`, which this repository wrote and which
    # must NOT be pinned, so the directory cannot be swept by suffix. But it
    # is also one of the places the gate's own `CI_STATE_SEARCH` looks, so a
    # vendored body could legitimately be dropped there and would escape
    # both layers exactly as `release_gate.yml` once did.
    marker_swept = (_ROOT / ".github" / "workflows", _ROOT / ".claude" / "tools")
    for folder in marker_swept:
        for artifact in sorted(folder.glob("*")):
            if not artifact.is_file():
                continue
            if _MARKER not in _normalize(artifact.read_text(encoding="utf-8")):
                continue
            assert artifact.resolve() in committed, (
                f"{artifact} carries the kit provenance marker but is not a "
                f"pinned COMMITTED kit copy. A vendored body in a directory "
                f"that also holds this repository's own files escapes the "
                f"suffix sweep above, so it is pinned by this marker rule "
                f"instead; add it to the manifest and to COMMITTED."
            )
