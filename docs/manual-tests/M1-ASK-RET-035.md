# Manual test — M1-ASK-RET-035, hybrid retrieval with reciprocal rank fusion

**Ticket:** `M1-ASK-RET-035` — dense search and lexical search run over indexed chunks, fused by reciprocal rank fusion; both sides' own scores and the threshold in force are retained; superseded/deleted documents are excluded; a source-scoped question stays inside its source.
**Version under test:** `0.2.16`
**Time:** about 45 minutes, plus a first stack build. Needs the `bge-m3` embedding weights (see **Before you start**) — without them this ticket cannot be exercised at all, unlike earlier tickets where a model-free part was possible.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `api/src/askwell/retrieve.py`'s `retrieve()`: a dense cosine search over `chunks.embedding`, a lexical search over `chunks.content_tsv`, both capped at `Settings.retrieval_candidate_count` and joined against `documents` to exclude anything `deleted_at` or `superseded_by`, then fused by reciprocal rank fusion (`_fuse`, pure and already covered by `test_retrieve.py`'s unit tests against fabricated rows). Every candidate keeps its own dense and lexical score — null on whichever side missed it — and the fused result carries `Settings.retrieval_score_threshold` as configured at that call, not recomputed later.

**Where this stops on purpose.** There is **no Ask screen and no `/ask` (or any retrieval) endpoint at all**. `api/src/askwell/app.py` registers `session`, `roots`, `sources`, `ingest` and `interface` — nothing named `retrieve` or `ask`. `web/app/page.tsx` is the shell's home route, not the three-column Ask screen `docs/ux/ask.md` describes; there is nothing on it that calls this code. `retrieve()` is called today only from `api/tests/test_retrieve_records.py`, directly, against a real database. This walkthrough therefore does everything the browser can do for real — nominating a folder, adding real documents, watching them reach `ready` with real embeddings — and then, for the retrieval itself, drops to a Python script run inside the API container that imports `askwell.retrieve` and calls `retrieve()` directly, the same way the automated test does. That is not a workaround this document invented; it is the only path that exists yet.

---

## Before you start

You need the `bge-m3` embedding weights this install is configured for — retrieval with no vectors at all would only exercise the lexical half, and the ticket's own acceptance criteria (a paraphrase with no shared wording) specifically need the dense half.

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf`.
- If you do not already have this file, stop here — this ticket cannot be manually walked without it. Rely on `scripts/dev.sh test-db`, which is what `docs/BRAIN.md`'s own verification note for this ticket used.

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder above, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note there was nothing to remove.

### 2. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 3. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_retrieve.py`.

### 4. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 5. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 6. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role is up (`ready`, port from `ASKWELL_EMBEDDING_PORT`).

### 7. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — index two real documents, through the browser

### 8. Write the test material

One file carries a reference number nowhere else in the corpus; the other carries a clause a paraphrased question shares no wording with — the ticket's own two acceptance criteria.

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/invoice-notes.txt", "w") as f:
    f.write(
        "Invoice INV-2024-0917 is overdue. Finance flagged it during the "
        "monthly reconciliation and a reminder was sent to the supplier.\n"
    )
with open("/app/askwell-test-material/termination-clause.txt", "w") as f:
    f.write(
        "Either party may terminate this agreement on ninety days written "
        "notice delivered to the other party's registered address.\n"
    )
with open("/app/askwell-test-material/picnic-notes.txt", "w") as f:
    f.write("The quarterly team picnic is scheduled for Friday afternoon in the car park.\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop all three files

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag all three files onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** three cards move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 11. Confirm all three reached `ready`, with vectors

```
scripts/dev.sh psql
```

```sql
SELECT filename, status FROM documents ORDER BY filename;
```

**You should see:** three rows, all `status` = `ready`.

```sql
SELECT d.filename, count(*) AS total, count(c.embedding) AS embedded
FROM documents d JOIN chunks c ON c.document_id = d.id
GROUP BY d.filename ORDER BY d.filename;
```

**You should see:** `total` = `embedded` for every row — nothing indexed without a vector.

Keep this `psql` session open; note each document's `id` for later:

```sql
SELECT id, filename, source_id FROM documents ORDER BY filename;
```

---

## Part B — retrieve, from a terminal script (the only way in that exists)

### 12. Write the retrieval script

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio

from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.retrieve import retrieve


async def main() -> None:
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    client = InferenceClient(settings)

    async with factory() as session:
        print("--- reference number ---")
        result = await retrieve(session, client, settings, "0917")
        for c in result.candidates[:3]:
            print(c.chunk_id, round(c.score, 5), c.dense_score, c.lexical_score, c.content[:60])

        print("--- paraphrase, no shared wording ---")
        result = await retrieve(session, client, settings, "when can we end the contract early")
        for c in result.candidates[:3]:
            print(c.chunk_id, round(c.score, 5), c.dense_score, c.lexical_score, c.content[:60])

        print("--- threshold captured ---")
        print("threshold in force:", result.threshold, "configured:", settings.retrieval_score_threshold)

    await engine.dispose()


asyncio.run(main())
PY
```

**You should see:** two headed blocks of candidates, each row showing a chunk id, fused score, dense score, lexical score and the start of its content, followed by a `threshold in force` line.

### 13. Confirm the reference number finds its chunk

Look at the `--- reference number ---` block.

**You should see:** the top row's content start with `Invoice INV-2024-0917 is overdue`, and its lexical score be a positive number (not `None`) — the digits in `0917` matched the full-text index even though the dense side had no reason to rank it first.

### 14. Confirm the paraphrase finds its chunk with no shared wording

Look at the `--- paraphrase, no shared wording ---` block. "when can we end the contract early" shares no word with "terminate", "agreement", "ninety days" or "written notice".

**You should see:** the top row's content start with `Either party may terminate this agreement`, and its dense score be a number close to but under `1.0` — found by meaning, not by any matching word.

### 15. Confirm the threshold is captured, not recomputed

**You should see:** `threshold in force: 0.65 configured: 0.65` (or whatever `ASKWELL_RETRIEVAL_SCORE_THRESHOLD` is set to in your `.env`) — the same figure `Settings` holds right now, captured on the `RetrievalResult` returned from the call rather than looked up again afterward.

---

## Part C — superseded and deleted documents are excluded

### 16. Mark the picnic document deleted, and confirm the query changes without any code change

Back in the open `psql` session:

```sql
UPDATE documents SET deleted_at = now() WHERE filename = 'picnic-notes.txt';
```

Re-run a broad query from the terminal:

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio

from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.retrieve import retrieve


async def main() -> None:
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    client = InferenceClient(settings)
    async with factory() as session:
        result = await retrieve(session, client, settings, "picnic team afternoon")
        print("candidates:", len(result.candidates))
        for c in result.candidates:
            print(c.chunk_id, c.content[:60])
    await engine.dispose()


asyncio.run(main())
PY
```

**You should see:** `candidates: 0` — the deleted document's own chunk, which would otherwise be the obvious top hit for this exact wording, does not appear at all.

Restore it so the rest of the corpus is unaffected by this step:

```sql
UPDATE documents SET deleted_at = NULL WHERE filename = 'picnic-notes.txt';
```

### 17. Supersede the invoice document, and confirm it stops being retrieved by the query alone

```sql
-- capture the invoice document's own id first
SELECT id FROM documents WHERE filename = 'invoice-notes.txt';
```

```sql
-- using a throwaway uuid as the "newer" document is enough here: this step
-- checks that a non-null superseded_by excludes a document, not what the
-- newer document itself contains
UPDATE documents SET superseded_by = gen_random_uuid()
WHERE filename = 'invoice-notes.txt';
```

Re-run the reference-number query from step 12:

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio

from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.retrieve import retrieve


async def main() -> None:
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    client = InferenceClient(settings)
    async with factory() as session:
        result = await retrieve(session, client, settings, "0917")
        print("candidates:", len(result.candidates))
    await engine.dispose()


asyncio.run(main())
PY
```

**You should see:** `candidates: 0` — the only chunk containing `0917` is gone from the result the moment its document is marked superseded, with no change to the chunk row itself.

Revert, so the corpus is back to the state the rest of this document assumes:

```sql
UPDATE documents SET superseded_by = NULL WHERE filename = 'invoice-notes.txt';
```

---

## Part D — a source-scoped question stays inside its source

### 18. Add a second, separate source with an overlapping phrase

Back on the add-source screen (`/sources/add/`), nominate a second folder — reuse the **Settings** screen from step 7, type a new path, e.g. `/home/you/external/quantum-plus/askwell/askwell-test-material-2`, click **Nominate**.

```
mkdir -p askwell-test-material-2
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material-2/other-notice.txt", "w") as f:
    f.write("Either party may terminate this other agreement on thirty days notice.\n")
print("done")
PY
```

Go back to `/sources/add/`, drag `other-notice.txt` in from the second folder, and click **Add it**. Wait for it to reach a settled state with no red error text.

### 19. Get both sources' ids

```sql
SELECT s.id AS source_id, d.filename FROM sources s
JOIN documents d ON d.source_id = s.id
WHERE d.filename IN ('termination-clause.txt', 'other-notice.txt');
```

**You should see:** two different `source_id` values, one per filename.

### 20. Query scoped to the first source only

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
import uuid

from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.retrieve import retrieve

SOURCE_ID = uuid.UUID("PASTE-THE-FIRST-SOURCE-ID-HERE")


async def main() -> None:
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    client = InferenceClient(settings)
    async with factory() as session:
        result = await retrieve(
            session, client, settings, "party may terminate on notice", source_id=SOURCE_ID
        )
        print("candidates:", len(result.candidates))
        for c in result.candidates:
            print(c.chunk_id, c.content[:60])
    await engine.dispose()


asyncio.run(main())
PY
```

(Replace `PASTE-THE-FIRST-SOURCE-ID-HERE` with the `source_id` from step 19 that goes with `termination-clause.txt`.)

**You should see:** only `termination-clause.txt`'s chunk in the output — `other-notice.txt`'s chunk, which matches the wording just as well, does not appear, because it belongs to the other source.

---

## Known gaps

- **No Ask screen and no retrieval endpoint.** `docs/ux/ask.md` §5's "Retrieving" and "Answered" states describe a screen with nothing behind it yet. Every candidate in this document was read from a Python script's `print` output, not from a rendered source card — filed as the natural next dependency for `M2` (answer composition and abstention), not a gap in this ticket.
- **No trace or interaction record.** `docs/audit-log.md` §7 says retrieved chunks and scores go into the interaction record; nothing writes an interaction record yet, because nothing composes an answer yet. `RetrievalResult` carries everything that record will need (`candidates`, `threshold`) but nothing consumes it.
- **No abstention.** The threshold is captured on every call (step 15) but never compared against a score — a question with no good match still returns whatever `_fuse` ranked highest, however weak. Deciding whether that clears the bar is `M2`, explicitly out of this ticket's scope.
- **No reranking.** Ordering is fusion-only, as the ticket states; `M1-ASK-RET-036` is what would reorder these candidates by an actual cross-encoder pass.
- **Query embedding failure is not exercised.** If `client.embed` raises, `retrieve()` has no special handling — it is not caught in `retrieve.py`, so a script calling it directly would see the exception propagate. Nothing in `docs/states-and-edge-cases.md` names this case yet for retrieval specifically; worth a follow-up issue once `M2` gives it somewhere to surface.
