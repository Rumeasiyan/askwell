# Manual test — M2-EVAL-TEST-066, the conflicting-source subset and worst-case reporting discipline

**Ticket:** `M2-EVAL-TEST-066` — ten conflicting-source tasks over fixture
documents that genuinely disagree, scored on whether both positions are
presented, cited, and neither silently preferred, plus a reporting rule
that the harness never prints a mean without its worst case.
**Version under test:** `0.2.50` — see the note in `docs/decisions.md`'s
entry for this ticket on why this lands with no version bump (tests/eval,
no user-visible behaviour change, same as `M2-EVAL-TEST-064`/`-065`).
**Time:** about 20 minutes with the stack already up and native inference
already running; add a first image build and stack start otherwise.
**Who can run it:** a terminal, the Postgres stack up, native inference
running on the host. No browser — `eval/` has no UI.

**What is being checked.** `eval/conflict.py` (reuses `eval.grounded`'s
`seed_corpus`/`_ask_one`, adds `_ensure_superseded` and `conflict_score`),
`eval/suites/conflicting_sources.v1.json` (ten tasks, `pass_bar: 0.75`,
`mode: "conflict"`), `eval/tests/test_conflict.py` (the scoring logic, no
database or model needed), and `eval/results.py`'s new
`format_mean_worst` (the only place the harness renders a mean, now used by
both the category line and every per-task line in `format_summary`).
`eval/bench.py` dispatches a suite whose `mode` is `"conflict"` to
`run_conflict_suite_sync`.

**Where this stops on purpose.** This walkthrough checks that the suite
*runs and reports* the 0.75 number, that a genuine conflict, a
false-conflict-on-wording, and a superseded pair are each scored the way
the ticket's acceptance criteria describe, and that the reporting rule
actually holds — not that your currently-loaded model clears 0.75 today.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before, follow `M2-EVAL-TEST-065`'s "Before
you start" and "Cold start" sections first (`.env`, `build-api`, `check`,
`podman compose up -d`, `db upgrade head`, `scripts/dev.sh inference`).

---

## Part A — the suite runs and reports mean paired with worst-of-3

### 1. Run the conflict suite

```
scripts/dev.sh eval --suite conflicting_sources.v1
```

This seeds the fixture corpus, including the two new conflict documents and
the superseded pair, through the real `add()` → `ingest.process()` path — a
no-op re-add if you already ran the grounded or abstention suites in this
database.

**You should see:** a summary block ending with something like:

```
suite: conflicting_sources.v1 (conflicting-sources)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 0.75  mean: <a number>  worst-of-3: <a number>
  return-window: mean: <n>  worst-of-3: <n>
  express-shipping-fee: mean: <n>  worst-of-3: <n>
  ... (10 lines total)

written to /app/eval/results/conflicting_sources.v1-<timestamp>.json
```

Every line that names a mean also names a worst-of-3 — the "every
category's output shows mean and worst case together" acceptance
criterion, and the per-task line format changed from `mean=<n> worst=<n>`
to the same `format_mean_worst` string the category line uses, so there is
exactly one place in the codebase that decides what that string looks
like.

### 2. Read one failing task's reason

Open the written JSON:

```
cat eval/results/conflicting_sources.v1-*.json | python3 -m json.tool | less
```

Find a task whose `mean` is below `1.0` and read its `runs[*].output`.

**You should see:** for a genuine-conflict task (e.g. `return-window`), a
run that scored `0.0` either presented only one of "thirty days"/"forty-five
days" with no `Conflicting sources on ...:` line (silently preferred one
source), or presented both values without citing both
`conflict_2025.pdf`/`conflict_2026.pdf`. For the two `expect_conflict:
false` tasks, a `0.0` run means the answer wrongly opened with `Conflicting
sources on ...:` for a fact that does not actually disagree (over-detection)
or restated it with a `Conflicting sources` line about hours it never
disagreed on. Either way the reason is legible directly from the stored
answer text — nothing needs re-running to see why a task failed.

---

## Part B — the false-conflict and superseded edge cases

### 3. Confirm the false-conflict fixture states one value two ways

```
grep -n "gift card" eval/fixtures/generate_corpus.py
```

**You should see:** `CONFLICT_2025_PAGES` and `CONFLICT_2026_PAGES` both
say Meridian Loom gift cards "never expire" — different wording, same
value. `gift-card-expiry-false-conflict` in
`eval/suites/conflicting_sources.v1.json` sets `"expect_conflict": false`
and a single `position_values` entry, `"never expire"` — a run that
presents this as a conflict scores `0.0` (over-detection), per
`conflict_score` in `eval/conflict.py`.

### 4. Confirm the superseded pair is a real document relationship, not a prompt trick

```
scripts/dev.sh psql -c \
  "SELECT filename, superseded_by IS NOT NULL AS superseded FROM documents WHERE filename LIKE 'store_hours%';"
```

**You should see:** `store_hours_2025.pdf` with `superseded = t`,
`store_hours_2026.pdf` with `superseded = f`. This is the same
`superseded_by` column `askwell.sources.add`'s own version-detection path
sets — `eval.conflict._ensure_superseded` set it directly here, because
building it through a second `add()` at the same path has nowhere to run
from in a corpus every suite shares (`docs/decisions.md`'s entry for this
ticket). `askwell.retrieve` already excludes a superseded document from
every candidate query, so `store-closing-time-superseded`'s task only ever
sees `store_hours_2026.pdf` — there is nothing for it to conflict with, and
the task exists to confirm the answer is a plain, single-position one
("9 PM"), not that anything special had to detect the absence of a
conflict.

---

## Part C — the reporting rule itself

### 5. Confirm the harness structurally cannot print a mean-only summary

```
scripts/dev.sh run python3 -c "
from eval.results import format_mean_worst
try:
    format_mean_worst(0.9)
except TypeError as error:
    print('refused:', error)
"
```

**You should see:** `refused: format_mean_worst() missing 1 required
positional argument: 'worst'` — `format_mean_worst` has two required
parameters with no default, so there is no call a future call site could
make that supplies a mean and omits the worst case. This is the ticket's
own "Attempt to print a mean-only summary and confirm the harness refuses"
testing note, and it is also asserted directly in
`eval/tests/test_results.py::test_format_mean_worst_has_no_way_to_omit_worst_case`.

### 6. Run the offline eval tests

```
scripts/dev.sh run pytest /app/eval/tests -q
```

**You should see:** all tests pass, including `test_conflict.py` (seven
tests covering the genuine-conflict, false-conflict, and missing-citation
scoring paths), the new `test_suite.py` cases for `mode: "conflict"`, and
`test_results.py`'s new reporting-discipline tests. This suite is not yet
wired into `scripts/dev.sh check` (`M2-EVAL-TEST-063`'s own note, still
true) — run it explicitly.
