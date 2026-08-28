# Manual test — M1-CITE-BE-042: Claim-level citation extraction into the citations table

## What this ticket built

`api/src/askwell/agent/claims.py` — `segment_claims` reads the growing answer text as sentences
and turns each one that carries a trailing `[index]` marker into a `Claim`; `locate_quoted_span`
finds the claim's own words verbatim inside the source chunk. `api/src/askwell/ask.py`'s
`_run_generation` now recomputes `segment_claims` after every streamed token and writes one
`citations` row per index a claim names, sharing one `claim_ordinal` for a two-passage claim, with
`quoted_span` populated for the first time.

**Nothing in the web app renders a citation yet** — the margin still shows `Shell`'s permanent
empty state (`M1-CITE-FE-043`, not built). This ticket's own Testing Notes describe opening "the
source viewer through the library," which does not exist yet either — `web/app/library/page.tsx`
is still its placeholder empty state. So the walkthrough below does everything a user actually
can by clicking, then — because the ticket's whole point is that citations exist as **queryable
data**, not as anything on screen — checks that data the only two ways currently possible: the
browser's own Network panel (still something a user opens by clicking, not a raw request) and a
database shell, `scripts/dev.sh psql`, which is a documented project command, not a bypassed
endpoint. Both are called out explicitly below rather than silently substituted.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m1-cite-be-042`.
- `podman compose up -d`, then `scripts/dev.sh build-api && podman compose up -d` (not
  `restart`) if this is a rebuild.
- A native `llama.cpp` process running on the host (`scripts/dev.sh inference`) with a model
  configured — without it, generation fails with `InferenceUnavailable` before any token is
  streamed, and none of the citation behaviour below is reachable. If no model is available in
  your environment, run Part 1 (automated) only and read "What this does not prove."
- At least one source added and indexed to `ready` (`M1-ADD-*`/`M1-INDEX-*`), containing a
  passage with a clear factual answer — the ticket's own example is a 45-day payment term or a
  named notice period.

## Part 1 — automated suite, read the output

```
scripts/dev.sh test
scripts/dev.sh test-db
```

**What you should see:** `test` includes `api/tests/test_claims.py` — 11 tests, pure, no
database or inference — covering marked-vs-unmarked sentences, two-passage claims sharing one
ordinal, ordinals only advancing on marked sentences, a growing prefix revealing only completed
sentences, and quoted-span matching including the not-found case. `test-db` includes the new
cases in `api/tests/test_ask_api.py`: three factual claims producing three citation rows against
real chunks, a two-passage claim producing two rows at one ordinal, a trailing non-factual
sentence producing no extra row, and citations still resolving via a real join after `trace` is
wiped. At the time this was written: 436 passed / 1 skipped (`test`), 173 passed (`test-db`).

## Part 2 — cold start, click-through

1. Open a browser to `http://127.0.0.1:8000/`. **What you should see:** Askwell's shell loads —
   composer at the bottom, an empty provenance margin on the right, sidebar with Library, Add a
   source, Memory, Settings.
2. If no source is indexed yet, click **Add a source** in the sidebar, add a file containing a
   fact you can check by eye (a contract clause, a stated term), and wait for it to reach
   `ready` — its row in the ingest progress list stops showing a spinner. Then click the
   Askwell wordmark or **back** to return to the Ask screen.
3. Open the browser's DevTools (`F12` or right-click → Inspect) and switch to the **Network**
   tab before asking — this is how step 5 below is checked; it is not a substitute for anything
   a user would otherwise click.
4. Click into the composer, type a question with a known factual answer from the source you
   added (e.g. "How long is the notice period?"), and press **Enter**.
   **What you should see:** a named step appears first ("Searching your files."), then
   ("Reading N sources." or similar), then ("Writing your answer."), then the answer's tokens
   appear in the transcript one at a time, ending with a complete sentence or two.
5. In the Network tab, find the `POST /ask` request (or `GET /ask/{id}/stream` if it reconnected)
   and open its **EventStream** / response panel.
   **What you should see:** interleaved `step`, `token`, `citation` and `done` events. Each
   `citation` event carries `claim_ordinal`, `index`, `chunk_id`, `document_id`, `page_from`,
   `page_to`, and `quoted_span` — a `citation` event should appear once the sentence containing
   its claim has finished streaming, not only after the whole answer is done.
6. Ask a second question whose answer plausibly draws on two different passages for one
   sentence (or, if the corpus is small, accept whatever the model actually produces).
   **What you should see:** if a claim cites two passages, two `citation` events share the same
   `claim_ordinal` with different `index`/`chunk_id`.
7. Count the factual-sounding sentences in the rendered answer against the number of `citation`
   events with distinct `claim_ordinal`s in the Network panel.
   **What you should see:** a sentence that only restates the question or is a closing remark
   ("Let me know if you need anything else.") produced no `citation` event; every sentence that
   states a fact did.

## Part 3 — the data itself, `scripts/dev.sh psql`

The ticket's real acceptance criterion — "three citation rows referencing real chunks with
quoted spans that appear in those chunks" — has no on-screen surface yet, so it is checked here
directly, against the same message id the transcript in step 4 produced.

1.
   ```
   scripts/dev.sh psql -c \
     "SELECT c.claim_ordinal, c.chunk_id, left(c.quoted_span, 60) AS quoted_span, left(ch.content, 60) AS chunk_starts
      FROM citations c JOIN chunks ch ON ch.id = c.chunk_id
      ORDER BY c.claim_ordinal;"
   ```
   **What you should see:** one row per citation, `claim_ordinal` matching what the Network tab
   showed, and `quoted_span` — where not `NULL` — a substring that is visibly inside `ch.content`
   when you read both columns.

2. Confirm the quoted span really sits in the chunk, not just resembles it:
   ```
   scripts/dev.sh psql -c \
     "SELECT chunk_id, quoted_span, position(quoted_span in content) > 0 AS found_in_chunk
      FROM citations c JOIN chunks ch ON ch.id = c.chunk_id
      WHERE quoted_span IS NOT NULL;"
   ```
   **What you should see:** `found_in_chunk` is `t` for every row.

3. **Force trace rotation and confirm citations still resolve** (the ticket's own edge case —
   citations are real rows, independent of the trace blob):
   ```
   scripts/dev.sh psql -c \
     "UPDATE messages SET trace = '{}'::jsonb WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
   scripts/dev.sh psql -c \
     "SELECT m.id, c.claim_ordinal, c.chunk_id FROM messages m JOIN citations c ON c.message_id = m.id
      WHERE m.role = 'assistant' ORDER BY m.created_at DESC LIMIT 5;"
   ```
   **What you should see:** the same citation rows, unaffected by the message's `trace` having
   just been wiped to `{}`.

4. **A deleted document's chunk still resolves** (no cascade delete on the citation's foreign
   key, deliberately):
   ```
   scripts/dev.sh psql -c \
     "SELECT document_id FROM chunks WHERE id = (SELECT chunk_id FROM citations LIMIT 1);"
   ```
   note the `document_id`, then delete that document's row and re-run the join from step 1.
   **What you should see:** the citation row and its `chunk_id` are unchanged — deleting the
   `documents` row does not touch `citations` or `chunks` (only a real re-index of the same
   source would remove the chunk itself).

5. Clean up:
   ```
   scripts/dev.sh psql -c \
     "TRUNCATE conversations, messages, citations, audit_interactions CASCADE;"
   ```

## Known gaps

- **Nothing renders citations on screen.** The margin still shows `Shell`'s permanent empty
  state; source cards arrive with `M1-CITE-FE-043`. Steps 5–7 of Part 2 use the browser's Network
  panel because there is no other way yet to see a citation as a user — this is not a defect
  of this ticket, it is explicitly out of scope.
- **The library's source viewer does not exist.** The ticket's own Testing Notes describe opening
  it to confirm a cited passage; `web/app/library/page.tsx` is still an empty-state placeholder,
  so that check is done against `chunks.content` directly (Part 3, step 1) instead.
- **No systematic "was every claim cited" check.** This ticket only guarantees that every claim
  segmented from the model's own markers produced a citation row — not that the model's marker
  placement itself is reliable. That measurement is `M1-CITE-TEST-045`; the miss/over-flag rate
  of the underlying prompt convention is `M2`'s eval suite.
- **Claim segmentation is prompt-driven and imperfect by construction** — a model that puts a
  marker somewhere other than immediately before the sentence's closing punctuation, or writes a
  multi-clause sentence as one "claim," will segment differently than intended. This is stated
  in the ticket's own Assumptions, not a bug found here.
- If no native `llama.cpp` process is available, none of Part 2 or Part 3 is reachable —
  generation fails with `InferenceUnavailable` before the first token, the same limitation every
  ticket since `M0-MODEL-BE-019` has recorded.
