# Manual test — M2-EVAL-TEST-065, the abstention subset with the 0.90 bar

**Ticket:** `M2-EVAL-TEST-065` — fifteen unanswerable questions over the
fixture corpus, scored on whether the turn abstains and whether the
abstention names what was searched, plus a guard test that the retrieval
threshold has not been quietly lowered.
**Version under test:** `0.2.50` (check `cat VERSION` — bump as this ticket
lands per `AGENTS.md` §7).
**Time:** about 30 minutes, plus a first image build and stack start.
**Who can run it:** a terminal, the Postgres stack up, and native inference
running on the host. No browser — `eval/` has no UI, and `eval/abstain.py`
seeds the corpus itself through the real `askwell.sources.add` code path
rather than a person clicking through the web app's add-source screen.

**What is being checked.** `eval/abstain.py` (reuses `eval.grounded`'s
`seed_corpus`/`_ask_one` to index the fixture corpus and drive one real
`askwell.ask` turn per task, then scores whether the answer starts with
`ABSTAIN_PREFIX` and contains `SEARCH_EVIDENCE`), `eval/suites/abstention.v1.json`
(fifteen tasks, `pass_bar: 0.90`, `mode: "abstain"`), and
`eval/tests/test_abstain.py` (the scoring logic plus the threshold-not-lowered
guard, no database or model needed). `eval/bench.py` dispatches a suite whose
`mode` is `"abstain"` to `run_abstain_suite_sync`.

**Where this stops on purpose.** This walkthrough checks that the suite
*runs and reports* the 0.90 number and that the suite and the guard test are
both actually sensitive to the things they exist to protect — it is not a
claim that your currently-loaded model clears 0.90 today. It also
deliberately reproduces the ticket's own two demonstrations: lowering the
threshold and weakening the abstention prompt each make the suite fail, on
purpose, as proof the suite is not decorative.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Find `POSTGRES_APP_PASSWORD` in `.env` and put any word after the `=` if it
is blank.

---

## Cold start

### 1. Build the image

```
scripts/dev.sh build-api
```

**You should see:** the image build finish with no red error text.

### 2. Run the read-only checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish clean,
including `eval/tests/test_abstain.py` — five tests covering the scoring
function, the suite's own shape (fifteen tasks, `abstain` mode, `0.90` bar),
and the threshold guard — run with no network and no database per
`AGENTS.md` §6.

### 3. Bring up the stack

```
podman compose up -d
```

**You should see:** containers report healthy (`podman compose ps`).

### 4. Migrate the database

```
scripts/dev.sh db upgrade head
```

**You should see:** Alembic apply migrations with no errors, ending at
`head`.

### 5. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave running in its own terminal. Wait for it to report the generation role
`ready`.

**You should see:** the socket path
`~/external/quantum-plus/askwell/.run/inference.sock`, then a state
transition to `ready`.

---

## Part A — the suite runs and reports a score against the 0.90 bar

### 6. Run the abstention suite

```
scripts/dev.sh eval --suite abstention.v1
```

This seeds the same five fixture documents the grounded suite uses, so the
first run takes a while (OCR for the scan) even though every task in this
suite is unanswerable from that corpus.

**You should see:** a summary block ending with something like:

```
suite: abstention.v1 (abstention)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 0.9  mean: <a number>  worst-of-3: <a number>
  sick-leave-policy: mean=<n> worst=<n>
  termination-notice-near-miss: mean=<n> worst=<n>
  ... (15 lines total)

written to /app/eval/results/abstention.v1-<timestamp>.json
```

Fifteen per-task lines is the ticket's "the suite reports a score against
the 0.90 bar" acceptance criterion. Whether your currently-loaded model
actually clears 0.90 is the signal this suite exists to produce, not a
defect in the suite if it does not.

### 7. Confirm every task genuinely has no answer in the corpus

Open `eval/suites/abstention.v1.json` and, for a handful of tasks, cross-check
against `eval/fixtures/generate_corpus.py`'s `HANDBOOK_A_PAGES` /
`HANDBOOK_B_PAGES` / `NOTICE_SCAN_LINES` / `SPEC_SECTIONS` / `FIGURES_ROWS`.

**You should see:** the "near-miss" tasks (e.g.
`termination-notice-near-miss`, `part-time-holiday-near-miss`,
`sensor-mk2-warranty-near-miss`) name a topic the corpus genuinely covers
adjacent material for — resignation notice periods exist, but not
termination notice; the Loomwear Sensor Mk3 has a warranty, but the fixture
never mentions a "Mk2" — while the corpus never states the actual fact
asked for. This is what makes them near-misses rather than ordinary
out-of-corpus questions.

### 8. Confirm the abstention names what was searched

```
cat eval/results/abstention.v1-*.json | python3 -m json.tool | less
```

Find any task's `runs[0].output`.

**You should see:** the answer starts with "Nothing in your files answers
this" and contains a sentence like "I searched 6 passages across 2
documents" naming a real count — the proof-of-search sentence
`compose_abstention` builds from `askwell.agent.abstain`
(`api/src/askwell/agent/abstain.py`), not a generic refusal. A run that
abstained without this sentence scored `0.0` per `abstain_score` in
`eval/abstain.py`, even though it correctly declined to answer.

### 9. Confirm the record carries model, prompt version and threshold

Still in the same JSON.

**You should see:** `"model"` set to the actual loaded model name,
`"profile"`, and `"prompt_versions"` including `abstention.v1` — the
ticket's "results recorded with threshold in force" requirement is carried
through the same `prompt_versions` mechanism `M2-EVAL-TEST-064` uses, plus
`Settings.retrieval_score_threshold`'s value determines every task's outcome
even though the number itself lives in configuration rather than the
result file — confirmed indirectly by Part B below actually moving the
score when that value changes.

---

## Part B — lowering the threshold makes the suite less sensitive, and the guard test catches the change itself

This part is exploratory and deliberately destructive to your local config —
follow the restore step.

### 10. Note the current guard value

```
grep -n "retrieval_score_threshold" api/src/askwell/config.py
```

**You should see:** `retrieval_score_threshold: float = Field(default=0.65, ge=0, le=1)`
— the value `eval/tests/test_abstain.py`'s
`test_retrieval_score_threshold_default_has_not_been_quietly_lowered` checks
against `RECORDED_DEFAULT = 0.65`.

### 11. Lower the threshold without recording a decision

Edit `api/src/askwell/config.py` and change the default to `0.2` (a value low
enough that borderline near-miss candidates that should abstain now clear
retrieval and get answered instead):

```python
retrieval_score_threshold: float = Field(default=0.2, ge=0, le=1)
```

### 12. Run the read-only checks again

```
scripts/dev.sh check
```

**You should see:** `test_retrieval_score_threshold_default_has_not_been_quietly_lowered`
fail — the guard test doing exactly what the ticket asks: catching a
threshold change with no accompanying `docs/decisions.md` entry, before it
ever reaches a live suite run.

### 13. Confirm the live suite score is also affected

```
scripts/dev.sh eval --suite abstention.v1
```

**You should see:** the mean score drop relative to step 6's run, or at
minimum some near-miss tasks that previously abstained now score `0.0`
because the model answered instead — the near-miss tasks are the ones
closest to the threshold boundary, so they move first. This is the ticket's
own "the score should drop" testing note made concrete.

### 14. Restore the threshold

```
git checkout -- api/src/askwell/config.py
```

```
grep -n "retrieval_score_threshold" api/src/askwell/config.py
```

**You should see:** the default back at `0.65`. Re-run `scripts/dev.sh check`
to confirm the guard test passes again before continuing.

---

## Part C — weakening the abstention prompt to allow a caveated guess fails the suite

### 15. Note the standing rule's current wording

```
cat api/src/askwell/agent/prompts/abstention.v1.md
```

**You should see:** the "Never" section, including "Never hedge into a
partial guess" and "Never offer a general-knowledge answer 'in case it
helps'".

### 16. Weaken it

Edit `api/src/askwell/agent/prompts/abstention.v1.md` and remove those two
lines from the "Never" section — or add a line explicitly permitting a
caveated guess, e.g. "A brief, clearly labelled best-guess is acceptable
when nothing is found."

### 17. Re-run the read-only checks

```
scripts/dev.sh check
```

**You should see:** `eval/tests/test_abstain.py` continues to pass (it only
checks the scorer's own logic and the suite's shape, not the live prompt
file's wording) — this weakening is caught by a *live model run*, not a
unit test, which is why Part C exists as its own step rather than folding
into step 12.

### 18. Re-run the live suite

```
scripts/dev.sh eval --suite abstention.v1
```

**You should see:** the mean score drop, and some `runs[].output` entries
in the written result file no longer starting with `ABSTAIN_PREFIX` — a
hedged guess instead, which `abstain_score` scores `0.0` per the ticket's
own "a hedged partial answer counts as a hallucination for scoring purposes"
rule, not partial credit.

### 19. Restore the prompt

```
git checkout -- api/src/askwell/agent/prompts/abstention.v1.md
```

```
scripts/dev.sh check
```

**You should see:** all checks pass again, confirming the file is back to
its committed state.

---

## Cleanup

```
rm -f eval/results/abstention.v1-*.json
```

(Check `git status` first if `eval/results/` had prior content you did not
create — only remove files this walkthrough generated.)

Stop the inference terminal with `Ctrl-C`. Bring the stack down if you do
not need it for anything else: `podman compose down`.

---

## Known gaps

- **Whether your loaded model actually clears 0.90 is not asserted by this
  walkthrough.** `abstention.v1` is not a strict (`pass_bar == 1.0`) suite
  in `eval/suite.py`'s sense, so `eval/bench.py` exits `0` regardless of the
  mean it reports — clearing the bar is a quality-gate concern
  (`docs/success-metrics.md`), not a pass/fail this document enforces.
- **No CI gate.** Nothing runs this suite automatically on push or blocks a
  PR on its score, same gap noted in `M2-EVAL-TEST-064`'s manual test.
- **English only**, per the ticket's own stated scope — no Tamil fixture
  content, consistent with `AGENTS.md` §1's v1-is-English-only line.
- **Empty-corpus and source-indexing abstention variants are not exercised
  here.** They are explicitly out of scope for this suite per its own
  docstring in `eval/abstain.py` — the fixture corpus is always fully
  indexed before this suite runs, so `reason_code` is always
  `below_threshold`. Those two variants have their own separate assertions
  elsewhere, not covered by this document.
- **Partial-answer scoring is out of scope**, per the ticket — it belongs
  to the grounded suite (`M2-EVAL-TEST-064`).
- **Parts B and C are destructive to local files until their restore steps
  run** — do not skip `git checkout --` in either part, and do not run this
  walkthrough against a machine you rely on for anything else mid-way
  through.
- **Fifteen tasks at a 0.90 bar tolerates at most one failure**, which is
  the ticket's own stated intended severity, not a defect to report if a
  single flaky task occasionally dips the mean below the bar on a given
  model.
</content>
