# Manual test — M1-INDEX-ING-032, embedding batches with retry and visible failure

**Ticket:** `M1-INDEX-ING-032` — chunks are embedded in bounded batches, a transient failure retries with backoff, a persistent failure is visible in the library with its error and a working retry, and a document is marked indexed only once every one of its chunks has a vector.
**Version under test:** `0.2.13`
**Time:** about 45 minutes, plus a first stack build. Add another 20 minutes if you also work through Part B, which needs a real embedding model.
**Who can run it:** Part A needs only a terminal and a browser — no model weights. Part B needs the `bge-m3` GGUF weights this install is configured to use (see **Before you start**).

**What is being checked.** `api/src/askwell/embed.py` is the pipeline's third and final stage. For each of a document's chunks with no vector yet, it sends content to the native inference process in groups of `ASKWELL_EMBEDDING_BATCH_SIZE` (16 by default), retries a failing batch up to three times with a short linear backoff, and only marks the document `ready` once every chunk has an embedding. A batch that exhausts its retries fails the whole document through to the pipeline's existing per-document retry and failure surface — the same "Try again" button `M1-EXTRACT-VAL-030` built for extraction failures, unchanged, now also rendering an embedding failure.

**Where this stops on purpose.** Nothing yet *reads* `chunks.embedding` — retrieval and reranking are `M1-ASK-RET-035`/`036`, still unbuilt. "Reaches `ready`" here means "has a vector on every chunk," not "can be asked a question about." There is also still no library screen (`web/app/library/page.tsx` is the placeholder empty state) and no source viewer, so this walkthrough reads outcomes from the add-source screen's own progress line and failure list, and from the database directly, the same way `M1-INDEX-ING-031`'s manual test did.

---

## Before you start

You need a terminal and Podman for everything in this document. Part B additionally needs the embedding model this install is configured for:

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf` — `bge-m3`, verified MIT-licensed and ungated (`docs/decisions.md`, C9).
- Askwell does not yet document how to fetch model weights — bundling and download arrive in Phase 7 (`docs/build-plan.md`). If you do not already have a `bge-m3` GGUF at that path, **skip Part B** and rely on Part A plus the automated `test-db` suite (`scripts/dev.sh test-db`), which is what `docs/BRAIN.md`'s own verification note for this ticket did.
- If you do have the weights, place the file at the path above (or point `ASKWELL_EMBEDDING_MODEL_PATH` in `.env` at wherever you put it) before step 6.

### 1. Build a small test file

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

One plain-text file is enough — this ticket is about the embedding stage, not extraction or chunking, which `M1-INDEX-ING-031`'s manual test already covers. Make it long enough to span more than one batch, so the batching itself is exercised rather than assumed:

```bash
scripts/dev.sh run python3 - <<'PY'
sentence = "Askwell reads this file locally and never sends it anywhere without being asked. "
with open("/app/askwell-test-material/policy-notes.txt", "w") as f:
    f.write(sentence * 400)
print("done")
PY
```

**You should see:** the script print `done` with no traceback.

```
ls -la askwell-test-material
```

**You should see:** `policy-notes.txt`, a few tens of KB.

### 2. Point Askwell at your files

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder you just created, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 3. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note that there was nothing to remove.

### 4. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 5. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_embed.py`.

### 6. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 7. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 8. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type this into the **Nominate a folder** field — with your own path —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — a persistent failure, visible and retryable, with no model running at all

Nothing in this part needs the embedding model. Leaving it stopped is not an inconvenience here — it is the "inference process is down" edge case the ticket names, produced for free.

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop the file

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `policy-notes.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** the card move to **Queued**, then a progress line as extraction and chunking run for real underneath it.

### 11. Watch it fail, three times, without your doing anything

Wait roughly 30–40 seconds (three attempts, each preceded by `RETRY_DELAY_SECONDS` = 10s, plus three in-batch retries of about 2–6s apiece inside the first attempt).

**You should see:** the card's status text change to something naming the `embed` stage, and — the important part — a red line appear under it reading close to:

> `policy-notes.txt could not be read while embed: InferenceUnavailable: The assistant is stopped. Tried 3 times.`

next to a **Try again** button.

**Never** silently dropped, per the ticket's own bar: the file stays named, on screen, with a reason and a control — it does not just vanish from the queue.

### 12. Confirm the database agrees

```
scripts/dev.sh psql
```

```sql
SELECT d.status, j.state, j.stage, j.attempts, j.error
FROM documents d JOIN ingest_jobs j ON j.document_id = d.id
WHERE d.filename = 'policy-notes.txt';
```

**You should see:** `status` = `attention`, `state` = `failed`, `stage` = `embed`, `attempts` = `3`, and `error` naming `InferenceUnavailable`.

```sql
SELECT count(*) AS total, count(embedding) AS embedded FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'policy-notes.txt');
```

**You should see:** `total` several (the file is long enough to chunk into more than one row) and `embedded` = `0` — nothing was left half-embedded; the document simply has no vectors yet.

### 13. Confirm the retry button actually re-queues, and that it replays the whole pipeline

Back in the browser, click **Try again** on the failed card.

**You should see:** the button read "Trying again…", then the failure line disappear and the card return to a running state (it will fail again in another ~30–40 seconds, since inference is still stopped — that is expected and is what step 14 confirms).

```
podman compose logs worker --since 2m
```

**You should see:** `extract_text_completed` and `chunk_completed` logged again for this document, followed by `embed_batch_retrying` — the retry re-runs the pipeline from `extract`, not from wherever `embed` left off, exactly as `docs/decisions.md`'s entry for this ticket describes (chunking is cheap and idempotent, so there is nothing worth resuming mid-batch).

Let it fail a second time, then move on — Part A's point is made: the failure is visible, named, and retryable, and the retry genuinely does something rather than being decorative.

---

## Part B — a transient failure that clears, and a document that reaches `ready`

**Needs `bge-m3` weights at `ASKWELL_EMBEDDING_MODEL_PATH`.** Skip this part if you do not have them; see **Before you start**.

### 14. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal. Wait for it to report the embedding role is up (`ready`, port from `ASKWELL_EMBEDDING_PORT`).

### 15. Retry the document that is still failed from Part A

Back in the browser, click **Try again** once more.

**You should see:** the failure line disappear, the card show progress, and — this time — the card settle on being listed as complete, with no red text. The live line at the top of the page should stop naming any queued or running work.

### 16. Confirm every chunk has a vector of the right width

```sql
SELECT count(*) AS total, count(embedding) AS embedded FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'policy-notes.txt');
```

**You should see:** `total` = `embedded` — no chunk left behind.

```sql
SELECT vector_dims(embedding) FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'policy-notes.txt')
LIMIT 1;
```

**You should see:** `1024` — `ASKWELL_EMBEDDING_DIMENSIONS`, matching `bge-m3`'s own output width.

```sql
SELECT status FROM documents WHERE filename = 'policy-notes.txt';
```

**You should see:** `ready`.

### 17. A transient mid-batch failure — stop inference between batches, not before either one

Add a second copy so there is a fresh document to watch:

```bash
scripts/dev.sh run python3 - <<'PY'
sentence = "A second file, long enough to need more than one embedding batch on its own. "
with open("/app/askwell-test-material/policy-notes-2.txt", "w") as f:
    f.write(sentence * 400)
print("done")
PY
```

Drag `policy-notes-2.txt` onto the add-source window the same way as step 10, with inference still running from step 14.

Watch the card's progress line on the add-source page — `embed.run` reports `done`/`total` chunks back to `ingest_jobs` after every batch, and the page renders that as motion. As soon as you see it move past the first fraction (proof the first batch finished and a second is now in flight), switch to the terminal running `scripts/dev.sh inference` and press **Ctrl-C** to stop it, then immediately restart it (`scripts/dev.sh inference` again) — aim to have it back within about 10–15 seconds, comfortably inside the pipeline's three-attempt, 10-second-backoff window.

**You should see, in the worker logs:** `embed_batch_retrying` for the batch that was in flight when inference stopped, then — once inference answers again — the batch completing and the document reaching `ready` the same as step 15. The document is never left half-indexed by this: `documents.status` does not become `ready` until every chunk is embedded, and a batch that failed mid-flight is retried, not counted as done.

If your timing misses the window and the document lands in `attention` instead, that is fine — it demonstrates the same "not lost" property from Part A instead, since inference is back up by the time you read this. Click **Try again** and confirm it completes.

---

## Known gaps

- **No library screen and no source viewer.** `web/app/library/page.tsx` is still the placeholder empty state (`docs/build-plan.md`). "Visible in the library" for this ticket is, in practice, visible on the add-source screen's own failure list — the same surface `M1-EXTRACT-VAL-030` built — because that is the only rendered surface that exists. `docs/ux/library.md` §5's "needs attention" state is not yet a real screen to click through.
- **No in-repo path to download the embedding model.** `.env.example` names the file and `docs/decisions.md` records that its licence was verified, but nothing documents *how* to fetch `bge-m3-FP16.gguf` — that arrives with Phase 7's bundling. Part B is therefore optional in this document, matching `docs/BRAIN.md`'s own note that this ticket's real-model walkthrough has never been run in the reference dev environment either, for the same reason.
- **The dimension-mismatch-at-startup edge case is not walked through here.** It needs editing `ASKWELL_EMBEDDING_DIMENSIONS` and restarting only the worker to watch it crash loudly rather than embed anything — mechanically simple, but it leaves the stack in a state you then have to remember to revert before continuing this document, so it is left to the automated coverage in `api/tests/test_embed_records.py` (`check_dimension` against a real deployed width, and against a mismatched one) instead.
- **The empty-chunk second line of defence is not walked through here either.** Triggering it manually means bypassing the chunker with a direct `UPDATE chunks SET content = ''`, which is exactly the "should never happen" case the code comments describe — covered by `test_embed_records.py`, not repeated by hand here.
- **No re-embed on a model change.** Named as an explicit non-goal in the ticket itself: swapping `ASKWELL_EMBEDDING_MODEL_PATH` is a configuration change plus a manual re-index until `M7`.
- **Retrieval is not exercised.** A `ready` document has vectors; nothing yet queries them. `M1-ASK-RET-035`/`036` are what would make "searchable" a claim this walkthrough could actually test with a question and an answer.
