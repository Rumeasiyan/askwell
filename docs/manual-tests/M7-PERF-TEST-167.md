# Manual test — M7-PERF-TEST-167, the answer budgets on a real corpus

**Ticket:** `M7-PERF-TEST-167` — measure the performance budgets on a realistic corpus
**Version under test:** `0.7.5`
**Time:** about 90 minutes on `--docs 80` (the default corpus size); much longer if you pass a
bigger `--docs` to chase the ticket's own 200,000-chunk regime
**Who can run it:** anyone who can paste a line into a terminal. Steps 8–11 are clicking in a
browser and reading a stopwatch; the rest is pasting commands and reading their output.

**What is being checked.** `docs/ux/ask.md` §7 states four numbers: a step label inside 400ms of
submitting a question, a first answer token inside 3s, a full answer at a 20s median and a 60s
95th percentile — all on the `standard` profile — plus an ingestion-throughput number that feeds
the queue estimate a real user sees while adding files. This ticket built the harness that
measures those numbers against a corpus larger than the eval fixtures, not the harness assuming
they hold. This walkthrough runs that harness for real and checks its own honesty rules: a number
that was not actually measured must read as *not measured*, never as a pass, and a missed budget
must name the stage responsible.

**The one thing to watch for throughout.** Nothing here may copy, move, modify or delete a file of
yours — `eval/fixtures/generate_perf_corpus.py` only ever writes into a folder you point it at,
and Askwell reads the corpus where it lands, same as any other source.

---

## Before you start

You need a terminal and Podman. `eval/fixtures/generate_perf_corpus.py` has no dependency beyond
the Python standard library, so it is the one script in this walkthrough you run with the host's
own `python3` rather than inside a container — everything that touches `askwell.*` or `httpx`
still goes through `scripts/dev.sh`, per `AGENTS.md` §5's "do not invoke the host's Python".

### 1. Make a place for the corpus to land

```
mkdir -p ~/askwell-test/material
cd ~/external/quantum-plus/askwell
```

### 2. Point Askwell at that folder

If you have never run Askwell before, create its settings file:

```
cp -n .env.example .env
```

Open `.env` in any text editor. Find `ASKWELL_ROOTS_MOUNT=` and set it, replacing `you` with your
own username:

```
ASKWELL_ROOTS_MOUNT=/home/you/askwell-test/material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

### 3. Generate the corpus

```
python3 eval/fixtures/generate_perf_corpus.py \
    --out-dir ~/askwell-test/material/perf-corpus \
    --questions-out .run/perf-questions.json
```

**You should see:** `wrote 80 documents (3 pages each) to /home/you/askwell-test/material/perf-corpus`
and `wrote 80 questions to .run/perf-questions.json`. List the folder —

```
ls ~/askwell-test/material/perf-corpus | wc -l
```

**You should see:** `80`.

This is the default, documented in the script's own module docstring as a compromise: it runs in
one sitting. The ticket's own 200,000-chunk scenario is named there as *the finding a bigger run
would produce*, not a bar this walkthrough must clear — if you want to chase it, re-run step 3
with `--docs 2000 --pages-per-doc 6` and expect ingestion, not generation, to take hours.

---

## Cold start

### 4. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note that there was nothing to
remove. Either is fine.

### 5. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api` and `worker` reported started, then
migration lines from the second command. Wait about thirty seconds after `up -d` returns before
continuing.

### 6. Nominate the folder

Open a browser at `http://127.0.0.1:8000`. Click **Settings** in the left strip, scroll to
**Folders Askwell may read**, type the same path as step 2 into **Nominate a folder** —

```
/home/you/askwell-test/material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

### 7. Read this machine's probed profile

Still on **Settings**, find the hardware profile panel.

**You should see:** one of **Light**, **Standard**, **Accelerated** or **Workstation**, with the
reasoning Askwell probed it from (RAM and whether a GPU was found). Write down which one it says —
you will pass it to `--profile` in step 10. `docs/ux/ask.md` §7 only states numbers for
**Standard**; if this machine did not probe as Standard, that is fine and expected — it is one of
the ticket's own edge cases, handled in step 11.

---

## Add the corpus and time it against Askwell's own estimate

### 8. Walk to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the page headed **"Ask your own material"**, a panel saying nothing has been
added yet, and a button reading **Add a source**. Click it.

**You should see:** the page changes to one headed **"Add a source"**.

### 9. Add the perf corpus as a folder, and start a stopwatch

Click **Choose a folder**, and in the picker select `perf-corpus` inside
`~/askwell-test/material`. Start a stopwatch (your phone is fine) the moment you confirm the
selection.

**You should see:** the card move through **Detecting** to a count — **"80 files, ... "** or
similar — then straight to queued, since the folder you chose already carries the path Askwell
needs (no "Which folder are these files in?" prompt, unlike a browser drag-drop — a folder chosen
through the picker already states its own location).

Underneath, small grey text appears and keeps updating — this is `queueSentence`/`estimateSentence`
(`web/components/add/add-screen.tsx`), reading the same `GET /ingest` estimate `eval/answer_latency.py`
will read from the outside in step 10.

**Write down the stated estimate** (e.g. "About 6 minutes left — based on the last batch on this
machine.", or a stated reason it has none yet on a first-ever ingestion).

### 10. Watch it drain, and compare

Leave the tab open and glance back every minute or two. When the small text stops updating and
no failures are listed, stop the stopwatch.

**You should see:** the elapsed real time and the estimate from step 9 in the same neighbourhood —
this is a rough sanity check, not a precision one; `docs/success-metrics.md` does not state a
tolerance, so use judgement. If the two are wildly apart (an order of magnitude off), that is a
finding worth a GitHub issue against `askwell.ingest._estimate`, not something to quietly note and
move past.

If any file appears under a **Failed** heading, read the reason — a zero-byte or corrupt PDF is a
gap in the corpus generator, not this ticket's own harness, but record it either way.

---

## Run the harness

### 11. Measure the four budgets and the per-stage breakdown

Replace `<profile>` with what you wrote down in step 7:

```
scripts/dev.sh answer-latency \
    --profile <profile> \
    --corpus-dir /home/you/askwell-test/material/perf-corpus \
    --questions-file /run/askwell/perf-questions.json \
    --skip-ingest
```

`--skip-ingest` is correct here — you already ingested the corpus by hand in steps 8–10, through
the same `POST /roots`/`POST /sources` path the script would otherwise drive itself, and the
ticket's own testing note only asks for one ingestion pass, timed by hand. `--questions-file`
points at `/run/askwell/perf-questions.json` because that is where `.run/perf-questions.json` on
the host lands *inside* this command's own container (`scripts/dev.sh` mounts `.run/` at
`/run/askwell`) — the script's own docstring explains why the questions file cannot sit under
`ASKWELL_ROOTS_MOUNT` instead.

**If your machine's probed tier is not `standard`:** run the command anyway with your own tier.

**You should see, if the tier matches what `probe_hardware()` reads right now:** a cold pass and a
warm pass, each printing per-question lines, then a summary block per pass showing
`first_step_ms`, `first_token_ms` and `full_answer_ms` — each with a `p50`/`p95`/`n` — and a
`budget:` line.

- **On `standard`:** `budget: PASS {...}` or `budget: MISS {...}`. On a miss, the next line names
  `dominant stage` (`retrieve` or `compose`) — this is the acceptance criterion "a missed budget
  names the stage responsible", made concrete. Read the ticket's own real-world example: on a
  large enough corpus, `retrieve` dominating is *evidence*, not a defect to file.
- **On any other tier:** `budget: docs/ux/ask.md §7 states no budget for '<profile>'` — this is
  correct, not a bug. `docs/ux/ask.md` §7 states numbers only for `standard`; every other tier is
  measured and printed the same way, but deliberately carries no pass/fail line.

**You should also see**, at the very end, `written to eval/results/answer-latency-<profile>-<timestamp>.json`.

### 12. If the tier does not match

If step 11 instead printed `not measured: this machine probes as the '<x>' tier ... not '<profile>'`
and exited non-zero — **that is correct, not a failure of this walkthrough.** It is the ticket's
own edge case: *"A profile the test machine cannot run — reported as not measured, never as a
pass."* Confirm no results file was written for that run:

```
ls eval/results/ | tail -5
```

**You should see:** no new file with a timestamp matching this attempt. Record in your notes which
profile(s) this machine could and could not measure — the ticket's own known gap is one machine
per profile, so a second machine is needed to cover the others, not a retry here.

### 13. Read the results file and the stage breakdown

```
cat eval/results/answer-latency-*-*.json | python3 -m json.tool | less
```

**You should see:** top-level `profile`, `model`, `date`, `ingestion` (with `documents`,
`elapsed_seconds`, `docs_per_second` — the ingestion throughput number, measured against the same
`GET /ingest` estimate the screen showed you), and `cold`/`warm` sections. Inside each, confirm
`stage_breakdown` carries `retrieve` and `compose`, each with a `median_ms` and `n` read from
`GET /ask/{message_id}/trace` (`docs/decisions.md`, 2026-09-22 — the per-stage numbers are the one
part of this report read from the server's own timings rather than this script's wall clock).
Confirm `cold` and `warm` differ (or are at least reported separately) — this is the ticket's own
cold-vs-warm edge case, and the two must never be merged into one number.

---

## Confirm the felt experience by hand

### 14. Ask one question yourself

Back in the browser, on the **Ask** screen, type one of the questions the corpus generator wrote
(open `.run/perf-questions.json` in an editor and copy one `question` value — it names an
invented company, e.g. "What is Aldergate Logistics's onboarding period?") and submit it.

**You should see:** a step label (e.g. "Searching your files.") appear close to instantly, tokens
begin streaming well inside what felt like a few seconds, and the finished answer names the
invented company's number — the same fact `generate_perf_corpus.py` wrote into that document's
PDF — with a citation to `policy_000NN.pdf`. This is the ticket's own last check: *"ask a question
by hand and confirm the felt experience matches"* the numbers step 11 printed. If the felt wait is
obviously worse than the printed `p50`, say so — a script measuring the same network path a person
just watched is the whole premise here, and a mismatch between the two is a finding.

---

## Cleanup

```
podman compose down -v
rm -rf ~/askwell-test eval/fixtures/perf_corpus eval/fixtures/perf_corpus_questions.json .run/perf-questions.json
```

Results files under `eval/results/` are the record this ticket asks for ("results are recorded
per release") — leave them, or move them out before deleting, rather than deleting them as part of
routine cleanup.

---

## Known gaps

Deliberately not built by this ticket — do not report these as defects:

- **One machine, one tier, per run.** `--profile` is checked against this machine's actual probed
  tier and refuses a mismatch (step 12). Measuring every tier means running this walkthrough on
  one physical machine per tier — the ticket's own stated known gap, not something this script
  works around.
- **No automatic release-recording step.** "Results recorded per release" (the acceptance
  criterion) means the JSON file this script writes under `eval/results/`, committed or attached
  by hand when a release is cut. Nothing wires that into `scripts/dev.sh` release tooling yet.
- **No UI surface for these numbers.** The four budgets and the stage breakdown are read from a
  JSON file and a terminal, not from any screen in `web/`. This ticket is a measurement harness,
  not a dashboard.
- **The 200,000-chunk regime is not run by default.** `--docs 80` (the default) produces roughly
  1,000–2,000 chunks; reaching the ticket's own scenario needs `--docs 2000 --pages-per-doc 6`
  passed explicitly, and an ingestion run measured in hours. This walkthrough does not require it —
  optimisation from that finding is explicitly out of scope for this ticket.
- **Pure logic only is covered by the automated suite.** `eval/tests/test_answer_latency.py`
  covers SSE event pairing, percentile summarisation, stage attribution and the budget verdict
  with no running stack — `scripts/dev.sh test -k test_answer_latency`. It does not and cannot
  cover the live network/ingestion path this walkthrough exercises; that split is deliberate,
  matching `eval/tests/test_voice_latency.py`'s own.
