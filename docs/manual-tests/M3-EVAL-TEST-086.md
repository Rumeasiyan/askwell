# Manual test — M3-EVAL-TEST-086, the memory-application eval subset

**Ticket:** `M3-EVAL-TEST-086` — fifteen tasks at a 0.85 bar proving that a
stored memory fact actually changes a later answer, that a superseded fact
stops applying, that memory is cited when used, and that memory never
licenses inventing a claim the documents do not support.
**Version under test:** `0.4.0`.
**Time:** about 25 minutes, with the stack already up and native inference
already running; add a first image build and stack start otherwise.
**Who can run it:** a terminal, the Postgres stack up, native inference
running on the host, `psql` access via `scripts/dev.sh psql`. No browser —
`eval/` has no UI, same as every ticket in this line
(`M2-EVAL-TEST-063`/`-066`).

**What is being checked.** `eval/memory_apply.py` (`seed_memory_fixture`,
`memory_score`, `run_memory_suite`), `eval/suites/memory_apply.v1.json`
(fifteen tasks, `pass_bar: 0.85`, `mode: "memory"`),
`eval/tests/test_memory_apply.py` (the scoring logic, no database or model
needed), `eval/bench.py`'s dispatch of `mode: "memory"` to
`run_memory_suite_sync`, and `.github/workflows/eval.yml`'s gate now
running `memory_apply.v1` as its fourth suite.

**Where this stops on purpose.** This walkthrough checks that the subset
seeds its own fixture facts through the real write paths
(`answer_clarification`, `correct_memory_fact`, `write_memory_fact`), runs,
and reports each of the four task kinds' failure modes legibly — and that
removing memory retrieval collapses the score, which is the ticket's own
proof that the subset measures what it claims to. It does not check that
your currently-loaded model clears 0.85 today.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before, follow `M2-EVAL-TEST-065`'s "Before
you start" and "Cold start" sections first (`.env`, `build-api`, `check`,
`podman compose up -d`, `db upgrade head`, `scripts/dev.sh inference`).

---

## Part A — cold start: index the fixture corpus, seed memory facts, run the subset

### 1. Confirm the database has no fixture memory facts yet

```
scripts/dev.sh psql -c "SELECT subject, superseded_by IS NULL AS active FROM memory ORDER BY subject;"
```

If this is a fresh database, **you should see:** `0 rows`. If a prior run
of this suite (or `conflicting_sources.v1`, which shares the same fixture
corpus) already seeded it, that is fine — step 3 below is written to be
idempotent, so continue.

### 2. Run the memory suite

```
scripts/dev.sh eval --suite memory_apply.v1
```

This seeds the fixture corpus (`eval.grounded.seed_corpus`, a no-op re-add
if another suite already ran in this database), then seeds every fixture
memory fact through the product's own write paths — five "apply" facts and
three "supersede" facts via a fixture `clarifications` row answered through
`askwell.review.answer_clarification`, the three supersede facts then
corrected once via `askwell.memory.correct_memory_fact`, and seven
free-standing "no_invent"/"irrelevant" facts via
`askwell.memory.write_memory_fact(origin="manual")`.

**You should see:** a summary block ending with something like:

```
suite: memory_apply.v1 (memory-application)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 0.85  mean: <a number>  worst-of-3: <a number>
  return-window-current: mean: <n>  worst-of-3: <n>
  shipping-fee-current: mean: <n>  worst-of-3: <n>
  ... (15 lines total)

written to /app/eval/results/memory_apply.v1-<timestamp>.json
```

Every line names a mean paired with a worst-of-3, same reporting discipline
as every other suite since `M2-EVAL-TEST-066`.

### 3. Confirm the fixture facts actually landed, and how

```
scripts/dev.sh psql -c "SELECT subject, origin, superseded_by IS NULL AS active FROM memory ORDER BY subject;"
```

**You should see:** 15 subjects. The five `_APPLY_SEEDS` subjects
(`return-window-policy`, `shipping-fee-policy`, `loyalty-points-policy`,
`trade-in-credit-policy`, `support-response-policy`) each with exactly one
`active = t` row. The three `_SUPERSEDE_SEEDS` subjects
(`affiliate-rate-policy`, `restock-day-policy`, `warranty-cost-policy`)
each with **two** rows — one `active = f` (the original value, its
`superseded_by` pointing at the row below it) and one `active = t` (the
corrected value) — since seeding answers the clarification first and
corrects it a second time. The seven manual subjects
(`termination-notice-context`, `sick-day-context`, `q2-revenue-context`,
`guest-vpn-context`, `unrelated-fact-1/2/3`) each with one `active = t` row
and `origin = 'manual'`.

### 4. Read a failing task's diagnostic

Open the written JSON:

```
cat eval/results/memory_apply.v1-*.json | python3 -m json.tool | less
```

Find a task whose `mean` is below `1.0` and read its `runs[*].error`.

**You should see:** one of five distinct diagnostics, never an
undifferentiated failure — `invented_content` or
`abstained_without_proof` (the four `no_invent` tasks),
`grounded_answer_disrupted` (the three `irrelevant` tasks),
`no_application`, `superseded_fact_still_applied`, or `not_cited` (the
eight `apply`/`supersede` tasks). `superseded_fact_still_applied` appearing
specifically on `affiliate-rate-superseded`, `restock-day-superseded`, or
`warranty-cost-superseded` — never on a plain `apply` task, which has no
superseded value to fall back to — is the ticket's own edge case: a fact
that should be superseded but is not, scored distinctly from a general
application failure.

---

## Part B — removing memory retrieval collapses the score

This is the subset's own proof that it measures what it claims to: the
ticket's stated cold-start check is "delete all memory and run again — the
score should collapse."

### 5. Delete every memory row

```
scripts/dev.sh psql -c "DELETE FROM memory;"
```

**You should see:** `DELETE 18` (or however many rows step 3 showed,
active and superseded together).

### 6. Run the suite again

```
scripts/dev.sh eval --suite memory_apply.v1
```

Because `seed_memory_fixture`'s guard checks `WHERE subject = :subject`
with no `active` filter, and every row from step 5 is gone, this reseeds
all fifteen fixture facts from scratch — the eight `apply`/`supersede`
facts land at their *current* (unsuperseded) value directly this time,
since nothing pre-existing blocks the clarification-answer seed.

**You should see:** the `apply` and `supersede` tasks still score at or
near `1.0` (the fact is present again, just seeded fresh) — this step
alone does **not** collapse the score. The point of this section is step 7.

### 7. Delete memory again, but do not let the suite reseed it

```
scripts/dev.sh psql -c "DELETE FROM memory;"
scripts/dev.sh run python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from eval.grounded import seed_corpus

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    await seed_corpus(factory, settings)
    await engine.dispose()

asyncio.run(main())
"
scripts/dev.sh run python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from eval.memory_apply import _run_memory_task
from eval.suite import load_suite, resolve_suite_path

async def main():
    settings = load_settings()
    suite = load_suite(resolve_suite_path('memory_apply.v1'))
    engine = build_engine(settings)
    factory = session_factory(engine)
    for task in suite.tasks:
        result = await _run_memory_task(factory, settings, task)
        print(task.id, [run.score for run in result.runs])
    await engine.dispose()

asyncio.run(main())
"
```

This indexes the fixture corpus (so document-grounded content is still
there) but calls the per-task runner directly, skipping
`seed_memory_fixture` — memory stays empty throughout.

**You should see:** every `apply`/`supersede` task score `0.0` on every run
(`no_application` — nothing to apply), every `irrelevant` task still score
`1.0` (those never depended on memory), and every `no_invent` task's score
is unaffected (abstention holds with or without memory — memory was never
what made those pass). The `apply`/`supersede` collapse — 8 of 15 tasks
going from near-`1.0` to `0.0` — is the proof the ticket asks for: the
subset's score is actually driven by memory retrieval, not by the
documents or the model's general behaviour alone.

### 8. Restore the fixture facts for anything else you want to try

```
scripts/dev.sh eval --suite memory_apply.v1
```

Running the suite normally reseeds everything step 5/7 deleted.

---

## Part C — supersession: confirm the correction actually flips which tasks pass

### 9. Confirm the affiliate-rate fact is currently at its corrected value

```
scripts/dev.sh psql -c \
  "SELECT fact, superseded_by IS NULL AS active FROM memory WHERE subject = 'affiliate-rate-policy' ORDER BY created_at;"
```

**You should see:** two rows — `... eight percent (March 2025).` with
`active = f`, and `... eleven percent (January 2026); this supersedes the
eight percent figure.` with `active = t`.

### 10. Run just the two affiliate-rate tasks worth of evidence

The suite has no per-task filter flag, so run the fixture suite and check
the written JSON for `affiliate-rate-superseded`:

```
scripts/dev.sh eval --suite memory_apply.v1
cat eval/results/memory_apply.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
for task in report['task_results']:
    if task['task_id'] == 'affiliate-rate-superseded':
        print(json.dumps(task, indent=2))
"
```

**You should see:** `runs[*].output` mentioning "eleven percent", never
scoring `0.0` with the `superseded_fact_still_applied` diagnostic. This
confirms the ticket's own supersession testing note: the correction that
ran during seeding is what the task now measures, not the original value.

---

## Part D — the offline scoring tests

### 11. Run the eval test suite

```
scripts/dev.sh run pytest /app/eval/tests -q
```

**You should see:** all tests pass, including
`eval/tests/test_memory_apply.py`'s cases — the fifteen-task/0.85-bar
shape check, each of the five diagnostics (`no_application`,
`superseded_fact_still_applied`, `not_cited`, `invented_content`,
`abstained_without_proof`, `grounded_answer_disrupted`), and that a
superseded value mentioned in passing alongside the current one still
passes once the current value and its citation are both present.

### 12. Confirm `scripts/dev.sh check` also covers it

```
scripts/dev.sh check
```

**You should see:** the lint/format/typecheck/test stages finish without
red error text, including `eval/tests/test_memory_apply.py` — this suite's
scoring tests run unmarked, no database or model needed, same as
`test_conflict.py` and `test_abstain.py` before it.

---

## Part E — the CI gate now runs a fourth suite

### 13. Confirm the workflow names the new suite

```
grep -n "memory_apply.v1\|grounded_qa.v1\|abstention.v1\|conflicting_sources.v1" .github/workflows/eval.yml
```

**You should see:** all four suite names in the `for SUITE in ...` loop,
and the job name and comment above it updated to say "memory application"
rather than the prior three-suite wording — the "Integration into the
gate" acceptance criterion.

---

## Cleanup

```
rm -f eval/results/*.json
```

(Only remove result files you generated in this walkthrough — check
`git status` first if `eval/results/` had prior content you did not
create.)

The fixture memory facts and corpus documents are left in place —
`M2-EVAL-TEST-066`'s corpus and this ticket's memory facts are shared
fixtures other suites reuse, and every seed is idempotent, so leaving them
is the same state the next suite run would produce anyway.

---

## Known gaps

- **Fifteen tasks is a small sample**, per the ticket's own stated known
  gap — five `apply`, three `supersede`, four `no_invent`, three
  `irrelevant`. English only.
- **No standalone per-task runner.** The suite has no `--task <id>` flag;
  Part C isolates one task's result by filtering the written JSON after a
  full run, not by running that task alone. Confirming a single task's
  behaviour still means running all fifteen.
- **Part B's "skip seeding" check uses a hand-written Python snippet**, not
  a `scripts/dev.sh eval` flag — there is no shipped way to run the harness
  against an empty-memory database short of deleting memory and calling
  `eval.memory_apply._run_memory_task` directly, which is what step 7
  does. If this check is needed often, a `--skip-memory-seed` flag would
  remove the hand-rolled snippet; nothing in the code today asks for one.
- **CI itself is not re-run by this document.** Part E confirms the
  workflow file names the fourth suite; it does not push a commit and
  watch the self-hosted runner execute it, since that runner is a specific
  registered machine this walkthrough does not assume access to.
- **Model quality is not asserted.** This document confirms the subset
  seeds, runs, scores each failure mode distinctly, and collapses without
  memory. Whether the currently-loaded model actually clears the 0.85 bar
  is whatever `mean`/`worst-of-3` step 2 prints — not a pass/fail this
  document enforces.
