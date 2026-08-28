# Manual test — M1-CONV-BE-177: Store a one-line summary and a source count with every turn

## What this ticket built

`api/src/askwell/agent/summarize.py` — `summarize_turn` produces a `TurnSummary` (one-line
`summary`, and `source_count`: a distinct-document count, or `None` if the turn abstained) once,
from the turn's own answer text and the citation rows it actually wrote. `api/src/askwell/ask.py`'s
`_run_generation` calls it after generation finishes and writes both values into `messages.summary`
and `messages.source_count` in the same `INSERT ... ON CONFLICT` as the answer itself — one
transaction, never touched again. The migration
(`20260828_22d97a766e29_turn_summary_and_source_count.py`) adds both columns, nullable, with a
check constraint that `source_count` is never negative.

**Nothing renders these values on screen yet.** `web/components/ask/ask-state.tsx` says so in its
own comment: past-turn collapse, the summary line and the source count are `M1-CONV-FE-178`, not
built. So the walkthrough below asks real questions through the real UI, then reads the two stored
values the only way currently possible — `scripts/dev.sh psql` — which is a documented project
command, not a bypassed endpoint.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m1-conv-be-177`.
- `podman compose up -d`, then `scripts/dev.sh build-api && podman compose up -d` (not `restart`)
  if this is a rebuild, then `scripts/dev.sh db upgrade head` to apply the new columns.
- A native `llama.cpp` process running on the host (`scripts/dev.sh inference`), model configured.
  Without it, generation fails with `InferenceUnavailable` before any answer is produced and none
  of the walkthrough below is reachable — run Part 1 (automated) only in that case.
- Two indexed PDFs, `ready`, each containing a fact you can check by eye (a stated notice period,
  a stated payment term), and a subject the two PDFs plainly do **not** cover.

## Part 1 — automated suite, read the output

```
scripts/dev.sh test
scripts/dev.sh test-db
```

**What you should see:** `test` includes `api/tests/test_summarize.py` — pure, no database or
inference, covering: a grounded answer's distinct-document count, an abstained answer producing
`source_count = None`, a partial (stopped) answer's summary carrying the "(stopped before
finishing)" suffix, a failed turn's summary naming the failure with no count, and the fallback
path used only when `summarize_turn` itself raises. `test-db` includes the matching cases in
`api/tests/test_ask_api.py`: a grounded answer storing a summary and a count of `1`, an abstained
answer storing no count at all, deleting a cited source leaving a past turn's stored count
unchanged, a stopped turn's summary marked partial, a failed turn's summary naming the failure, an
audit-write failure recomputing the summary to match the rolled-back failure, and a
restart-interrupted turn getting the fallback summary. Read the actual pass count printed — do not
assume it matches an earlier run.

## Part 2 — cold start, click-through

1. Open a browser to `http://127.0.0.1:8000/`. **What you should see:** Askwell's shell loads —
   composer at the bottom, an empty provenance margin on the right, sidebar with Library, Add a
   source, Memory, Settings.
2. If the two PDFs are not indexed yet, click **Add a source**, add both, and wait for each to
   reach `ready` — its row in the ingest progress list stops showing a spinner. Then return to the
   Ask screen.
3. In the composer, ask a question the first PDF plainly answers (e.g. "How long is the notice
   period?") and press **Enter**. **What you should see:** the named steps run in order, then the
   answer streams token by token, ending in a complete sentence citing the fact.
4. Ask a second question the same or the other PDF answers. **What you should see:** the same
   streaming behaviour, a second complete answer.
5. Ask a third question either PDF answers.
6. Ask a fourth question **neither PDF covers at all** (e.g. about a topic absent from both
   documents). **What you should see:** the answer states plainly that the files do not cover
   this — no invented answer (C5).
7. **Restart Askwell entirely**: `podman compose down && podman compose up -d`, and start
   `scripts/dev.sh inference` again if it does not survive the restart on your machine.
8. Return to `http://127.0.0.1:8000/` (a fresh conversation is fine — nothing renders past-turn
   history yet; this step exists to prove the stored values survive a full restart, which the next
   step reads back from the database).

## Part 3 — the stored values, `scripts/dev.sh psql`

The ticket's actual acceptance criterion has no on-screen surface yet (`M1-CONV-FE-178`), so it is
read directly here, against the four turns from Part 2.

1. ```
   scripts/dev.sh psql -c \
     "SELECT id, left(content, 40) AS answer_starts, summary, source_count
      FROM messages WHERE role = 'assistant' ORDER BY created_at;"
   ```
   **What you should see:** each of the first three rows carries a short description of its
   answer and a `source_count` of `1` (each PDF answered from itself, so one document cited). The
   fourth row's `summary` says the files did not cover the question, and `source_count` is
   **blank/`NULL`** — not `0`. Confirm the difference explicitly:
   ```
   scripts/dev.sh psql -c \
     "SELECT count(*) FILTER (WHERE source_count IS NULL) AS abstained,
             count(*) FILTER (WHERE source_count = 0) AS zero_cited
      FROM messages WHERE role = 'assistant';"
   ```
   **What you should see:** `abstained = 1`, `zero_cited = 0`.

2. **Delete one of the two PDFs and confirm past counts do not move.** Note the first three rows'
   `source_count` values from step 1, then in the library delete one of the two indexed PDFs (or,
   if the library UI does not yet support deletion for your build, delete the `documents` row
   directly via `psql`). Re-run the query from step 1.
   **What you should see:** every one of the first three rows still shows the exact `summary` and
   `source_count` it had before the deletion — a deleted source does not shrink a past count.

3. **Stop an answer mid-stream and confirm it still gets a summary, marked partial.** Ask a new
   question, and while tokens are still streaming, click **Stop** (or press the stop control the
   Ask screen exposes).
   ```
   scripts/dev.sh psql -c \
     "SELECT summary, source_count FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
   ```
   **What you should see:** a `summary` describing whatever was produced before the stop, ending
   in "(stopped before finishing)", and — if any claims were cited before the stop —
   `source_count` reflecting the citations actually made, not `NULL` unless nothing was cited yet.

4. **Add a new document and confirm no past summary changes.** Add a third PDF that would have
   answered the fourth question from Part 2 (the one that abstained), wait for it to reach
   `ready`, then re-run the query from step 1 for that same row.
   **What you should see:** the fourth turn's `summary` still says the files did not cover it —
   unchanged by material added after the fact.

5. Clean up:
   ```
   scripts/dev.sh psql -c \
     "TRUNCATE conversations, messages, citations, audit_interactions CASCADE;"
   ```

## Known gaps

- **Nothing renders the summary or source count on screen.** `M1-CONV-FE-178` builds the
  collapsed-turn view; until then every value in Part 3 is read via `psql`, which is this ticket's
  documented data touchpoint, not a workaround.
- **No web-search marker.** A turn that used web search carries no indication of that yet
  (`M6.5-WEB-FE-192`).
- **No follow-up suggestions.** `M1-CONV-FE-180`, unrelated to this ticket's own scope.
- **Summaries are not editable and there is no plan for that** — stated in the ticket's own Testing
  Notes, not a gap found here.
- If no native `llama.cpp` process is available, Parts 2 and 3 are unreachable — generation fails
  with `InferenceUnavailable` before any turn is produced, the same limitation every ticket since
  `M0-MODEL-BE-019` has recorded.
