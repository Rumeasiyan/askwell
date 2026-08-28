# Manual test — M2-EVAL-TEST-063, the eval harness runs offline

**Ticket:** `M2-EVAL-TEST-063` — port the eval harness: suite selection, three runs per task, mean and worst-of-three reporting, no network access, results recorded in a comparable format.
**Version under test:** `0.2.50`
**Time:** about 20 minutes, plus a first image build.
**Who can run it:** a terminal, plus native inference running on the host. No browser, no Postgres, no `web/` — this ticket has no UI.

**What is being checked.** `eval/bench.py` and the modules it drives —
`eval/suite.py` (loads `eval/suites/*.json`), `eval/runner.py` (three runs
per task via `askwell.inference.client.InferenceClient`, aborting the whole
suite rather than reporting partial scores if the model disappears mid-run),
`eval/scoring.py` (`contains_all`/`exact`), and `eval/results.py` (mean,
worst-of-three, the strict pass/fail path for a `pass_bar == 1.0` suite, and
the JSON written to `eval/results/`). The only suite that exists yet is the
fixture, `eval/suites/smoke.v1.json` — two trivial tasks, `pass_bar 0.5`, not
one of the eight real category suites (those start at `M2-EVAL-TEST-064`).

**Where this stops on purpose.** `scripts/dev.sh eval` runs the harness
inside the API image with `--network=none` and a bind-mounted socket — that
container flag *is* the offline guarantee for this command, so "disconnect
the machine" (`AGENTS.md` §5's release test) is redundant here: the container
already has no network device to unplug. What Part B below checks instead is
that pulling the model out from under the harness — the case a network cable
cannot simulate — fails the run cleanly.

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
is blank — the eval command builds the same API image other `scripts/dev.sh`
commands use, and the build stage reads `.env`, even though this run never
touches Postgres itself.

---

## Cold start

### 1. Build the image

```
scripts/dev.sh build-api
```

**You should see:** the image build finish with no red error text.

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without
red error text, including `eval/tests/test_runner.py`,
`eval/tests/test_suite.py`, `eval/tests/test_scoring.py`,
`eval/tests/test_results.py` and `eval/tests/test_prompt_versions.py`.

### 3. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait
for it to report the generation role `ready` on its configured port.

**You should see:** a line noting the socket path,
`~/external/quantum-plus/askwell/.run/inference.sock`, and a state
transition to `ready`.

---

## Part A — a suite runs, three times per task, mean and worst-of-three reported

### 4. Run the fixture suite

In a second terminal:

```
scripts/dev.sh eval --suite smoke.v1
```

**You should see:** a summary block ending with something like:

```
suite: smoke.v1 (harness-smoke)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 0.50  mean: 1.00  worst-of-3: 1.00
  capital-of-france: mean=1.00 worst=1.00
  two-plus-two: mean=1.00 worst=1.00

written to /app/eval/results/smoke.v1-<timestamp>.json
```

`runs per task: 3` and two per-task lines each showing a `mean` and a
`worst` — not one number — is the ticket's core acceptance criterion. If
either task's `mean` and `worst` differ, that is not a bug: it means the
three runs did not all score the same, which is exactly the case the
worst-of-three design exists to surface.

### 5. Confirm three runs actually happened, not one reported three times

```
cat eval/results/smoke.v1-*.json | python3 -m json.tool | head -60
```

**You should see:** `"runs_per_task": 3`, and for each task under `"tasks"`
a `"runs"` array with exactly three entries, each carrying its own `score`,
`output`, and `error` (`null` for the two that answered cleanly). Three
distinct entries, not a single result triplicated, is what makes the AGENTS.md
rule ("a suite may never be run once and reported as if run three times")
checkable after the fact rather than trusted on the harness's word.

### 6. Confirm the record carries model, prompt version and date

Still in the same JSON:

**You should see:** `"model"` set to the actual loaded model name (not a
name written into `eval/` code — `eval/runner.py`'s `_current_model_name`
reads it from the inference supervisor's own `state.json`), `"profile"`,
`"prompt_versions"` (an object — empty is fine if no `.vN.md` prompt files
exist yet under `api/src/askwell/agent/prompts/`), and `"started_at"` /
`"finished_at"` as real timestamps.

---

## Part B — the model is unavailable: the harness fails clearly, no results file

### 7. Stop native inference

Go to the terminal running `scripts/dev.sh inference` from step 3 and press
`Ctrl-C`. Wait for it to exit.

### 8. Run the suite again

```
scripts/dev.sh eval --suite smoke.v1
echo "exit code: $?"
```

**You should see:** no summary table, an error line to stderr along the
lines of `eval/bench.py: model unavailable: ...`, and `exit code: 1`.

### 9. Confirm no new results file was written

```
ls -t eval/results/*.json | head -3
```

**You should see:** the newest file is still the one from step 4/5 —
nothing newer with a timestamp after this step. A run that could not
measure anything must never produce a file a later comparison could
mistake for a real score of zero.

### 10. Restart inference for anything else you want to try

```
scripts/dev.sh inference
```

---

## Part C — an unknown suite name fails before touching the model

### 11. Ask for a suite that does not exist

```
scripts/dev.sh eval --suite does-not-exist
echo "exit code: $?"
```

**You should see:** `eval/bench.py: no suite named 'does-not-exist' in
.../eval/suites. Available: smoke.v1`, and `exit code: 2` — distinct from
the model-unavailable exit code in Part B, since these are different
failures with different fixes (a typo vs. a dead supervisor).

---

## Part D — a strict (`pass_bar == 1.0`) suite reports pass/fail, not a mean

There is no real strict suite yet (SQL safety and web-escalation land in
later `M2-EVAL-*` tickets), so this checks the harness's own logic rather
than a shipped suite.

### 12. Write a throwaway strict suite

```bash
cat > eval/suites/strict-fixture.v1.json <<'JSON'
{
  "name": "strict-fixture.v1",
  "category": "harness-smoke-strict",
  "pass_bar": 1.0,
  "tasks": [
    {
      "id": "two-plus-two",
      "prompt": "Answer with only the number. What is 2 + 2?",
      "scorer": "contains_all",
      "expected": "4"
    }
  ]
}
JSON
```

### 13. Run it

```
scripts/dev.sh eval --suite strict-fixture.v1
echo "exit code: $?"
```

**You should see:** `pass_bar: 1.00 (strict)  result: PASS` if the model
answered `4` cleanly all three runs, or `result: FAIL` the moment any single
run scored under `1.0` — never a number like `0.97`. If it failed, `echo`
should show a non-zero exit code (`report.strict and not report.passed`
returns `1`); if it passed, `0`.

### 14. Remove the throwaway suite

```
rm eval/suites/strict-fixture.v1.json
```

---

## Cleanup

```
rm -f eval/results/*.json
```

(Only remove result files you generated in this walkthrough — check
`git status` first if `eval/results/` had prior content you did not create.
`.gitkeep` is untouched by the command above.)

Stop the inference terminal with `Ctrl-C` if you no longer need it.

---

## Known gaps

- **No real suites.** `smoke.v1` is the harness's own fixture, two trivial
  tasks. The eight category suites totalling 165 tasks
  (`docs/build-plan.md`) — abstention, SQL safety, web-escalation discipline,
  and the rest — are `M2-EVAL-TEST-064` onward and do not exist yet. Nothing
  in this document exercises real grading quality; it exercises the harness
  that will run those suites once they land.
- **No CI gate.** Nothing currently runs `eval/bench.py` automatically on a
  push or blocks a PR on a suite's pass bar. That is `M2-EVAL-DEPLOY-067`.
- **`--results-dir` exists but is not exercised here** — `eval/bench.py`
  accepts it, and this walkthrough only ever uses the default
  `eval/results/`.
- **No suite has been observed exercising the web-search-refused path**
  mentioned in the ticket's stated assumption (M6.5's suite, asserting
  Askwell does not reach the web with the network down). That suite does
  not exist yet; this document only confirms the harness itself runs with
  no network access, via `--network=none` on the container the harness runs
  in (step 4 onward), not via a suite asserting a refusal.
