# Manual test — M2-EVAL-TEST-064, the grounded document QA suite

**Ticket:** `M2-EVAL-TEST-064` — forty grounded questions with known answers
over a fixture corpus, scored on both answer correctness and citation
correctness.
**Version under test:** `0.2.51` (check `cat VERSION` — bump as this ticket
lands per `AGENTS.md` §7).
**Time:** about 30 minutes, plus a first image build and stack start.
**Who can run it:** a terminal, the Postgres stack up, and native inference
running on the host. No browser — `eval/` has no UI, and `eval/grounded.py`
seeds the corpus itself through the real `add()` -> `ingest.process()` code
path rather than a person clicking through the web app's add-source screen.

**What is being checked.** `eval/grounded.py` (seeds
`eval/fixtures/corpus/` through `askwell.sources.add` + `askwell.ingest`,
then drives one real `askwell.ask` turn per task and scores both the answer
text and the citation it produced), `eval/fixtures/generate_corpus.py` (the
committed, reproducible fixture corpus), and
`eval/suites/grounded_qa.v1.json` (forty tasks, `pass_bar: 0.85`,
`mode: "grounded"`). `eval/bench.py` dispatches a suite whose `mode` is
`"grounded"` to `run_grounded_suite_sync` instead of the plain
`run_suite_sync` that `M2-EVAL-TEST-063` exercised.

**Where this stops on purpose.** The ticket's acceptance bar is "0.85 mean
and 0.70 worst-of-three" (`docs/success-metrics.md`'s eval-suite quality
gate), but this walkthrough only checks that the suite *runs and reports*
those two numbers per the stated acceptance criteria — it does not fail the
walkthrough if your currently-loaded model misses the bar. A model missing
the bar is exactly the signal this suite exists to produce, not a defect in
the suite itself.

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
including `eval/tests/test_grounded.py` — the citation-matching logic and
the "fixture corpus is committed and reproducible" check, run with no
network and no database per `AGENTS.md` §6.

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

## Part A — the fixture corpus is real and committed

### 6. Confirm the corpus is on disk and matches the generator

```
ls eval/fixtures/corpus/
python3 eval/fixtures/generate_corpus.py
git status eval/fixtures/corpus/
```

(Run `generate_corpus.py` with whatever Python has `python-docx`/`openpyxl`
available — inside the API image if your host lacks them:
`scripts/dev.sh run python /app/eval/fixtures/generate_corpus.py`.)

**You should see:** five files — `handbook_a.pdf`, `handbook_b.pdf`,
`notice_scan.pdf`, `spec.docx`, `figures.xlsx` — covering the ticket's own
scope list (digital PDFs, a scan, an Office document, a table). After
regenerating, `git status` shows no diff on the two PDFs that are
byte-reproducible; `spec.docx`/`figures.xlsx` may show as modified because
their zip containers stamp a save timestamp even when the content is
unchanged — the content match is what `test_fixture_corpus_is_committed_and_reproducible`
checks in step 2, not the raw bytes for those two.

### 7. Confirm no fact is answerable from general knowledge

Open `eval/fixtures/generate_corpus.py` and read `HANDBOOK_A_PAGES`,
`HANDBOOK_B_PAGES`, `NOTICE_SCAN_LINES`, `SPEC_SECTIONS`, `FIGURES_ROWS`.

**You should see:** every fact belongs to a fictional company, "Meridian
Loom", and a fictional product, the "Loomwear Sensor Mk3" — resignation
notice periods, VPN token expiry, a made-up whistleblower hotline number,
department revenue figures. Nothing here is a real-world fact a model could
answer without the corpus.

---

## Part B — the suite runs, seeding the corpus through the real add flow

### 8. Run the grounded suite

```
scripts/dev.sh eval --suite grounded_qa.v1
```

This can take a while the first time — it ingests five documents (OCR for
the scan) before asking anything.

**You should see:** a summary block ending with something like:

```
suite: grounded_qa.v1 (grounded-document-qa)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 0.85  mean: <a number>  worst-of-3: <a number>
  handbook-a-holiday-accrual: mean=<n> worst=<n>
  handbook-a-notice-period: mean=<n> worst=<n>
  ... (40 lines total)

written to /app/eval/results/grounded_qa.v1-<timestamp>.json
```

Forty per-task lines, each with a `mean` and a `worst`, is the ticket's core
"the suite runs and reports mean and worst-case" acceptance criterion.

### 9. Confirm the corpus was seeded through the normal add path, not a shortcut

```
scripts/dev.sh psql
```

Inside the psql shell:

```sql
select filename from documents order by filename;
select count(*) from chunks;
```

**You should see:** the five fixture filenames listed under `documents`,
and a non-zero `chunks` count — evidence that `askwell.sources.add` plus
`askwell.ingest.process` actually ran (chunking, embedding) rather than a
row being hand-inserted to fake grounding. Exit with `\q`.

### 10. Confirm citation correctness was scored, not only answer text

```
cat eval/results/grounded_qa.v1-*.json | python3 -m json.tool | less
```

Find the entry for task `handbook-a-holiday-accrual`. **You should see:**
each of its three `runs` carrying its own `score`, and — because the
combined score is half answer text, half citation match
(`eval/grounded.py`'s `_run_grounded_task`) — a run whose `output` contains
"eleven" but whose citation named the wrong document or the wrong passage
would show a score of `0.5`, not `1.0`. If every run in your result file
scored either `0.0` or `1.0` exactly, that is consistent with the model
citing correctly whenever it answered correctly for your currently-loaded
model — not evidence the citation check was skipped; re-check the file
carries `"citations"`-shaped detail per the scoring code in
`eval/grounded.py:125-138` if in doubt.

### 11. Confirm the two "answer appears in two places" tasks accept either citation

Find task `notice-scan-hotline-duplicate` in the same JSON — its
`expected_documents` in `eval/suites/grounded_qa.v1.json` lists both
`handbook_a.pdf` and `notice_scan.pdf`, since the whistleblower hotline
number appears in both fixtures.

**You should see:** the task did not automatically score `0.0` on the
citation half merely for citing `notice_scan.pdf` instead of
`handbook_a.pdf` (or vice versa) — either is accepted, per
`_citation_score`'s loop over `task.expected_documents`.

### 12. Confirm the table task and the scanned task are both present and exercised

Find `figures-textiles-revenue` (depends on `figures.xlsx`, a table) and
`notice-scan-retreat-location` (depends on `notice_scan.pdf`, OCR'd, no text
layer) in the result file.

**You should see:** both ran three times each like every other task — the
ticket's own edge cases ("a task depending on a table", "a scanned-source
task") are not placeholders, they produced real scores.

### 13. Confirm the record carries model and prompt version

Still in the same JSON.

**You should see:** `"model"` set to the actual loaded model name,
`"profile"`, and `"prompt_versions"` — the ticket's "results recorded with
model and prompt version" audit requirement.

---

## Part C — breaking chunking fails the table tasks (as the ticket predicts)

This part is exploratory — it confirms the suite is sensitive to a real
regression, not that a specific commit is broken.

### 14. Deliberately damage the fixture corpus's table

```
python3 - <<'PY'
import openpyxl
path = "eval/fixtures/corpus/figures.xlsx"
wb = openpyxl.load_workbook(path)
sheet = wb.active
sheet["A1"] = "garbled"
wb.save(path)
PY
```

### 15. Remove the old ingested copy and reseed

```
scripts/dev.sh psql
```

```sql
delete from chunks using documents where chunks.document_id = documents.id and documents.filename = 'figures.xlsx';
delete from documents where filename = 'figures.xlsx';
```

Exit with `\q`, then re-run:

```
scripts/dev.sh eval --suite grounded_qa.v1
```

**You should see:** the five `figures-*` tasks (`figures-textiles-revenue`,
`figures-logistics-headcount`, `figures-research-revenue`,
`figures-retail-tenure`, `figures-design-headcount`,
`figures-research-tenure-paraphrase`, `figures-retail-headcount-paraphrase`)
score noticeably lower than the run in step 8, while the `handbook-*` and
`spec-*` tasks are unaffected — the suite localizing a regression to the
category that broke, which is the whole point of having per-task lines
rather than one aggregate number.

### 16. Restore the fixture corpus

```
python3 eval/fixtures/generate_corpus.py
git checkout -- eval/fixtures/corpus/figures.xlsx
```

```
scripts/dev.sh psql
```

```sql
delete from chunks using documents where chunks.document_id = documents.id and documents.filename = 'figures.xlsx';
delete from documents where filename = 'figures.xlsx';
```

The next `scripts/dev.sh eval --suite grounded_qa.v1` run will reingest the
restored file.

---

## Cleanup

```
rm -f eval/results/grounded_qa.v1-*.json
```

(Check `git status` first if `eval/results/` had prior content you did not
create — only remove files this walkthrough generated.)

Stop the inference terminal with `Ctrl-C`. Bring the stack down if you do
not need it for anything else: `podman compose down`.

---

## Known gaps

- **Whether your loaded model actually clears 0.85 mean / 0.70 worst-of-three
  is not asserted by this walkthrough.** That is `docs/success-metrics.md`'s
  quality-gate number, checked when deciding a profile default, not a
  pass/fail this manual test enforces — `grounded_qa.v1` is not a strict
  (`pass_bar == 1.0`) suite, so `eval/bench.py` exits `0` regardless of the
  mean it reports.
- **No CI gate.** Nothing runs this suite automatically on push or blocks a
  PR on its score. Tracked under `M2-EVAL-DEPLOY-067`.
- **English only**, per the ticket's own stated scope — no Tamil fixture
  content, consistent with `AGENTS.md` §1's v1-is-English-only line.
- **No adversarial or long-context tasks** — the ticket's own stated
  assumption that forty tasks is enough to catch a meaningful regression at
  this scale is not itself tested here.
- **Abstention, conflict, SQL, tool and memory categories are out of
  scope** for this suite and this document — they land in their own
  `M2-EVAL-TEST-*` tickets.
- **Part C's damage is destructive to your local `figures.xlsx` and its
  ingested rows until step 16 restores them** — do not skip the restore
  step, and do not run Part C against a machine you rely on for anything
  else.
</content>
