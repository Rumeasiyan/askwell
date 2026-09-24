# Release checklist — every gate, in one place

`M7-QA-TEST-168`. The one list that has to be true before an Askwell version is published.
Run it after `docs/release-procedure.md` step 2 (artefacts exist) and before step 4
(checksums). Record the result in `docs/release-log.md`, one entry per release, with the
evidence each gate names below.

**Why this exists.** A green test suite means the code is well-formed. It does not mean the
product does anything. Each gate below already had its own document. Nothing gathered them,
so a release could pass the four gates someone remembered and skip the fifth. This file is
the only place that says "all of them". A gate added later goes in here, or it is not a gate.

---

## How to read a result

**Every gate is pass or fail. None is a number.** A gate's row states its pass condition as
a condition. The evidence may contain numbers, but the result recorded is `PASS` or `FAIL`.
This matters most for the two eval categories with a bar of 1.00. **SQL safety at 0.9 is a
`FAIL`.** Web escalation discipline at 0.9 is a `FAIL`. On a ten-task suite, 0.9 reads as
nearly fine. It means one write got through, or Askwell went to the web on its own once.

The result marks, and what each does to the release:

| Mark | Means | Release |
| ---- | ----- | ------- |
| `PASS` | The gate ran on this exact `VERSION` and met its pass condition | Proceeds |
| `FAIL` | The gate ran and did not meet its pass condition | **Blocked** |
| `BLOCKED` | The gate could not be run: no eval runner, no second machine, no hardware for a tier | **Blocked**. A release does not go out unmeasured |
| `ACCEPTED` | Did not pass, and a known issue is accepted for this release under the rules below | Proceeds, with the acceptance in the record |

Four rules that are not negotiable within a release:

1. **A gate that cannot run blocks the release.** If the eval runner is down, the release
   waits for the runner. "Not measured" is never recorded as a pass. The same applies to a
   harness that prints `not measured` (`eval/answer_latency.py`, `eval/voice_latency.py`),
   and to a platform with no hardware to test on.
2. **An intermittent failure is a failure.** A walkthrough step that fails once in three
   attempts is a `FAIL`. For the maintainer it is intermittent. For someone who hits it on
   their first question, it is the product.
3. **A result belongs to one `VERSION`.** A pass recorded against `0.7.31` says nothing about
   `0.7.32`. Any change to the release commit after a gate ran means that gate runs again.
   The one exception is a change that is only the release record itself.
4. **A known issue is never carried silently.** If one is accepted, it goes in the release
   entry's `Accepted known issues` with three things: the issue number, why shipping with it
   is acceptable, and the follow-up that removes it. If any of those is missing, the gate is
   `FAIL`.

### What can be accepted, and what cannot

Some gates protect a constraint the product exists to keep. Those have no acceptance route.
Nothing is ever `ACCEPTED` against them:

- the eval categories **SQL safety** (C2), **web escalation discipline** (C10) and
  **abstention** (C5);
- the **offline** gate (C1);
- the **online-mode** gate (C1): only the authorised destination, only for the authorised
  conversation;
- the **restore** gate. `docs/release-procedure.md` step 3: a failed restore does not ship;
- a **security review** finding against any constraint C1–C10.

Every other gate can be `ACCEPTED`, under rule 4. The **notices** gate (C9) also needs an
entry in `docs/decisions.md`, as `docs/release-procedure.md` step 3b already requires.
Examples of a gap that can be accepted: a missed performance budget, a platform that could
not be covered, or a scored eval category such as grounded QA below its bar.

---

## The gates

Run them in this order. The cheap, mechanical gates come first, so a broken build is found
before a day goes into the manual ones.

| # | Gate | Pass condition | How to run it | Evidence lives in |
| - | ---- | -------------- | ------------- | ----------------- |
| G1 | **Version and changelog** | `VERSION` is the version being released. `CHANGELOG.md`'s top heading is that version. `api/tests/test_release_discipline.py` passes | `cat VERSION`; `head CHANGELOG.md`; `scripts/dev.sh run alembic heads` | Release entry: the version, the commit SHA every other gate ran against, and the schema revision `docs/release-procedure.md` §1 records |
| G2 | **Automated checks** | Every command exits 0 on the release commit, and CI (`.github/workflows/ci.yml`) is green for that SHA | `scripts/dev.sh check`; `scripts/dev.sh test-db`; `scripts/dev.sh web-check`; `bash scripts/guards.test.sh`; `bash scripts/gate.test.sh` | Release entry: the final summary line of each command, and the CI run URL |
| G3 | **Eval gate: eight categories, 165 tasks** | Every row of the eval table below reads `PASS`. All eight suites ran on the release commit, with the model and profile the release ships as default | Below the table | `docs/release-evidence/<version>/eval/`: the eight result JSON files |
| G4 | **Offline: the cable-unplugged test** | A `pass` entry for this `VERSION` in `docs/offline-test-log.md` | `docs/offline-release-test.md` | `docs/offline-test-log.md` |
| G5 | **Tested restore** | A `pass` entry for this `VERSION` in `docs/restore-test-log.md`, restored on a second machine | `docs/restore-release-test.md` | `docs/restore-test-log.md` |
| G6 | **Security review** | A `pass` entry for this `VERSION` in `docs/security-review-log.md` | `docs/security-review.md` | `docs/security-review-log.md` |
| G7 | **Performance** | On `standard`, the answer-latency harness prints `budget: PASS` for both passes, cold and warm: p50 < 20s and p95 < 60s (`docs/success-metrics.md`). The voice harness is within budget: ≤ 8s on `standard`, ≤ 3.5s on `accelerated` where that hardware exists. A `not measured` result is `BLOCKED` | `scripts/dev.sh answer-latency --profile standard ...` per `docs/manual-tests/M7-PERF-TEST-167.md`; `scripts/dev.sh voice-latency --profile <tier> ...` per `docs/manual-tests/M6-PERF-TEST-136.md`. Pass `--results-dir /app/docs/release-evidence/<version>/perf` to both | `docs/release-evidence/<version>/perf/` |
| G8 | **Licence and notices** | `scripts/dev.sh notices` exits 0. The regenerated `NOTICES.md` is committed and unchanged on a second run. Every bundled model's licence permits redistribution and commercial use and is not gated (C9) | `scripts/dev.sh notices`, then `git diff --exit-code NOTICES.md` | Release entry: the command's exit code, and the `NOTICES.md` commit |
| G9 | **Support boundary** | `SUPPORT.md` and `SECURITY.md` are present, and `api/tests/test_support_boundary.py` passes. The security route works: `gh api repos/Rumeasiyan/askwell/private-vulnerability-reporting` returns `{"enabled":true}`. Settings → About reaches the support boundary, the notices and the security policy with no network | The `gh api` call, plus walkthrough step W9.3 | Release entry: the `gh api` output, verbatim |
| G10 | **Artefacts and cold install** | An artefact exists for every platform being released. `docs/installing.md` works as written on a machine that has never seen Askwell, for each one. No platform is dropped silently: a platform that is not released is named in the entry | `docs/release-procedure.md` steps 2 and 7 | Release entry: platforms built, platforms installed on, and machine descriptions |
| G11 | **Manual regression walkthrough** | Every step of `docs/release-walkthrough.md` is `PASS`, from a cold install, on every platform being released. If some platform was not walked, the entry names it | `docs/release-walkthrough.md` | `docs/release-evidence/<version>/walkthrough-<platform>.md`: the filled-in script, one per platform |
| G12 | **Open defects** | Every open issue labelled `bug` has been read. Each one is fixed, or accepted under rule 4, or recorded as not affecting this release, with the reason. An open `bug` that also carries a `constraint:*` label cannot be accepted | `gh issue list --state open --label bug` | Release entry: the list, with a disposition for each issue |
| G13 | **Online mode: only the authorised destination** | A `pass` entry for this `VERSION` in `docs/online-test-log.md`: `scripts/verify-online-egress.sh` exits 0, and the independent capture shows traffic only to the authorised destination, only while its one conversation is online, stopping within a second of switching it off, and none from the sandbox. Exit `2` or no capture is `BLOCKED` | `docs/online-release-test.md` | `docs/online-test-log.md`, and the capture file |

### G3 — the eval table

The eight categories and bars are from `docs/build-plan.md`'s quality gate. Each suite file in
`eval/suites/` carries its own `pass_bar`. `api/tests/test_release_checklist.py` fails if this
table disagrees with those files.

| Category | Suite | Tasks | Pass condition |
| -------- | ----- | ----- | -------------- |
| Grounded document QA | `grounded_qa.v1` | 40 | `PASS` if mean ≥ 0.85 **and** worst-of-3 ≥ 0.70 |
| Abstention (unanswerable) | `abstention.v1` | 15 | `PASS` if mean ≥ 0.90. Never accepted, and never improved by lowering the retrieval threshold (C5) |
| Conflicting-source handling | `conflicting_sources.v1` | 10 | `PASS` if mean ≥ 0.75 |
| Text-to-SQL (execution-matched) | `text_to_sql.v1` | 40 | `PASS` if mean ≥ 0.80 |
| SQL safety | `sql_safety.v1` | 10 | **pass-or-fail.** `PASS` only if the harness prints `result: PASS`. Anything else is `FAIL`, whatever the number |
| Tool selection incl. parallel | `tool_selection.v1` | 25 | `PASS` if mean ≥ 0.85 |
| Memory application | `memory_apply.v1` | 15 | `PASS` if mean ≥ 0.85 |
| Web escalation discipline | `web_escalation.v1` | 10 | **pass-or-fail.** `PASS` only if the harness prints `result: PASS`. Anything else is `FAIL`, whatever the number |

**165 tasks.** `smoke.v1` checks the harness itself. It is not a category and is not part of
the gate.

Run each suite so its result is written straight into the evidence folder:

```
scripts/dev.sh eval --suite grounded_qa.v1 --results-dir /app/docs/release-evidence/<version>/eval
```

Repeat the command for each of the other seven suites. Read the printed summary for every
one of them.

**`eval/bench.py` exits 0 for a scored suite even when it is below its bar.** Only the two
strict suites turn a miss into a non-zero exit, and their `passed` field is `null` for every
other suite (`eval/results.py`). An exit code of 0 is therefore not a pass. For each scored
suite, compare `category_mean`, and `category_worst` where the row names one, against the
row above. Record the verdict yourself, with the number beside it, so the comparison can be
checked afterwards. Until #710 gives the gate a command that exits non-zero on a miss, this
hand comparison *is* the gate, and the abstention row (C5) is the one it protects.

Every result file records `prompt_versions`, `model` and `profile`. All eight must name the
same model and profile, and that must be the default the release ships. If one suite ran
against a different prompt version from the others, re-run it.

---

## Known holds on the next release

Open issues that already hold the first release run, so nobody discovers them on the day. Each
one is disposed of in the release entry under the gate named; none may be carried silently.

| Issue | Holds | Why |
| ----- | ----- | --- |
| #698 | G10, G11, G12 | No installer applies database migrations, so a cold install has no schema |
| #699 | G12 | The update feed reads `main`'s `VERSION`, so it advertises versions that were never released. It carries `constraint:local-first`, so it cannot be `ACCEPTED` |
| #689 | G9 | Private vulnerability reporting is off; the one security route `SECURITY.md` gives does not exist |
| #710 | G3 | `eval/bench.py` exits 0 for a scored suite below its bar. Not a hold by itself: G3 is compared by hand until it lands |
| #712 | G11 | No click reaches **Add a source** once anything is added: W4.3, W5.1, W5.2 and W5.4 are `FAIL` |
| #615 | G11 | Settings → Storage → **Export and prune** is a disabled button reading "Not built yet", a dead control, so W9.1 is `FAIL`; and there is no backup control, so W9.4 runs from a terminal |
| #737 | G13 | Every online send is refused until the disclosure wording is decided, so the online-mode gate's positive half cannot run: `BLOCKED`. #730 must land first, and a test enforces that order |

Remove a row in the change that closes its issue.

## Time

The ticket assumes one maintainer can run this in one to two working days. The main costs:

| Part | Hands-on | Wall clock |
| ---- | -------- | ---------- |
| G1, G2, G8, G9, G12 | about 1h | about 1h. `test-db` and `web-check` dominate |
| G3 eval | about 30 min to start the runs and read them | Several hours on CPU inference: 165 tasks × 3 runs. Can run unattended |
| G4 offline | about 2h | about 2h |
| G13 online mode | about 1h | about 1h, after G4 on the same machine |
| G5 restore | about 2h | about 3h, including the second machine |
| G6 security review | about 3h | about 3h |
| G7 performance | about 1h | about 2h, including corpus ingestion |
| G10, G11 walkthrough | about 4h per platform | about 4h per platform |

That is about two days on one platform. Each further platform adds about half a day. **If a
release needs more than two working days of hands-on time, split this checklist**, most
likely into a per-platform walkthrough run separately from the platform-independent gates.
Record that split in `docs/decisions.md` rather than skipping steps to fit the time.

---

## When a gate is added

A new release gate is added to the gate table above in the same change that creates it, with
its pass condition and where its evidence lives. A new milestone's headline path is added to
`docs/release-walkthrough.md` when the milestone lands. M8 has not landed, and its steps are
appended then.
