# Manual test — M1-ASK-RET-036, reranking pass over the top candidates

**Ticket:** `M1-ASK-RET-036` — a cross-encoder reranker reorders the top fused candidates; both score sets (fused and rerank) are retained, never mixed; the reranked order is what `retrieve()` returns; with the reranker unavailable, retrieval still returns fusion-ordered results and says so.
**Version under test:** `0.2.17`
**Time:** about 45 minutes, plus a first stack build. Needs both the `bge-m3` embedding weights **and** the `bge-reranker-v2-m3` reranker weights (see **Before you start**) — the second is new to this ticket. Without them, the degradation path (Part C) is still fully exercisable; the promotion path (Part B) is not.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `api/src/askwell/retrieve.py`'s `_rerank()`, called from `retrieve()` after fusion: it sends the top `Settings.rerank_candidate_count` fused candidates to `InferenceClient.rerank`, reorders them by the reranker's own score, appends the untouched remainder of the fused list after (unscored), and returns three new facts on `RetrievalResult` — `reranked`, `rerank_duration_ms`, `rerank_skipped_reason` — so a caller can tell whether the order it received is the reranker's or fusion's.

**Where this stops on purpose.** There is still **no Ask screen and no `/ask` (or any retrieval) endpoint at all** — the same gap `docs/manual-tests/M1-ASK-RET-035.md` recorded, unchanged by this ticket. `api/src/askwell/app.py` registers `session`, `roots`, `sources`, `ingest` and `interface` — nothing named `retrieve` or `ask`. `web/app/page.tsx` still shows the empty "Ask your own material" state with no composer. This walkthrough does everything the browser can do for real — nominating a folder, adding real documents, watching them reach `ready` — and then, for retrieval and reranking themselves, drops to a Python script run inside the API container that imports `askwell.retrieve` and calls `retrieve()` directly, exactly as `M1-ASK-RET-035`'s own manual test did and exactly what `docs/BRAIN.md`'s verification note for this ticket also fell back to.

---

## Before you start

You need both model files this install is configured for:

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf` and `ASKWELL_RERANKER_MODEL_PATH=~/.local/share/askwell/models/bge-reranker-v2-m3-FP16.gguf`.
- If you do not have the reranker weights, skip to **Part C** once the stack is up — the degradation path needs no model at all, since it tests the case where the reranker cannot be reached. Rely on `scripts/dev.sh test-db` for the promotion behaviour (`test_retrieve_records.py`'s near-identical-passages test), which is what `docs/BRAIN.md`'s own verification note for this ticket used in the same situation.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_rerank.py`.

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

Leave this running in its own terminal for the rest of this document. Wait for it to report **both** the embedding and reranking roles are up (`ready`, on the ports from `ASKWELL_EMBEDDING_PORT` and `ASKWELL_RERANKER_PORT`). If you have no reranker weights, this step reports embedding ready and reranking absent — that is expected; proceed and use Part C only.

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

## Part A — index a corpus of near-identical passages, through the browser

The ticket's own Real-World Example Scenario is a corpus of similar contracts where only one supplier's passage is the right answer. Five files, four wrong suppliers and one right one, all sharing the same wording pattern so fusion alone cannot tell them apart.

### 8. Write the five supplier files

```bash
scripts/dev.sh run python3 - <<'PY'
suppliers = ["Aldergate", "Bramwell", "Crestview", "Draycott", "Meridian"]
for name in suppliers:
    with open(f"/app/askwell-test-material/{name.lower()}-payment-terms.txt", "w") as f:
        f.write(
            f"{name} Supplies Ltd. Payment terms: net 30 days from invoice date, "
            f"paid by bank transfer to the account on file for {name}.\n"
        )
print("done")
PY
```

**You should see:** the script print `done`.

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop all five files

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag all five files onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** five cards move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 11. Confirm all five reached `ready`, with vectors

```
scripts/dev.sh psql
```

```sql
SELECT filename, status FROM documents ORDER BY filename;
```

**You should see:** five rows, all `status` = `ready`.

Keep this `psql` session open.

---

## Part B — reranking promotes the right passage (needs the reranker weights)

Skip this part if you have no `bge-reranker-v2-m3` weights; go to Part C.

### 12. Ask a question that only Meridian's passage genuinely answers

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
        result = await retrieve(session, client, settings, "What are Meridian's payment terms?")
        print("reranked:", result.reranked, "duration_ms:", result.rerank_duration_ms)
        for c in result.candidates[:5]:
            print(round(c.score, 5), c.rerank_score, c.content[:55])

    await engine.dispose()


asyncio.run(main())
PY
```

**You should see:** `reranked: True` with a `duration_ms` value. Because all five passages share almost identical wording, the fused (RRF) scores printed will be close together or tied — the point of this scenario. Every row shows a non-`None` `rerank_score`, since all five fall inside the default `rerank_candidate_count` window (10).

### 13. Confirm the right passage is first

**You should see:** the top row's content start with `Meridian Supplies Ltd.` — the passage that actually names Meridian, promoted above the other four suppliers even though fusion alone ranked them near-identically. The other four rows keep lower `rerank_score` values than the top row.

### 14. Confirm the fused score was not overwritten

Look at the `score` column (the fused RRF score, printed first) versus `rerank_score` (printed second) on the same row.

**You should see:** two different numbers on the top row — a small RRF fraction (well under `1.0`, `RRF_K = 60`) next to a cross-encoder score in a different, unrelated range. Neither is derived from the other; both are the real, separately-measured values `Candidate` carries.

---

## Part C — the reranker unavailable, retrieval still answers

This is the path every install without the reranker weights already demonstrates by default, and it is also the one `docs/BRAIN.md`'s own verification note used, since no native reranker process was available in that environment either.

### 15. Make the reranker unreachable

If native inference (step 6) is already running with no reranker weights configured, skip straight to step 16 — the reranker is already unreachable. Otherwise, stop the inference process (`Ctrl-C` in its terminal) or comment out `ASKWELL_RERANKER_MODEL_PATH` in `.env` and restart it without that role.

### 16. Ask the same question again

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
        result = await retrieve(session, client, settings, "What are Meridian's payment terms?")
        print("reranked:", result.reranked)
        print("rerank_duration_ms:", result.rerank_duration_ms)
        print("rerank_skipped_reason:", result.rerank_skipped_reason)
        print("candidates:", len(result.candidates))
        for c in result.candidates[:5]:
            print(round(c.score, 5), c.rerank_score, c.content[:55])

    await engine.dispose()


asyncio.run(main())
PY
```

**You should see:** the call still returns a result — no exception, no hang. `reranked: False`, `rerank_duration_ms: None`, and `rerank_skipped_reason` naming why (`"reranker unavailable: ..."`), not silently blank. Every `rerank_score` in the printed rows is `None`. `candidates` is still `5` — fusion order, not an empty or truncated list.

### 17. Confirm the order is fusion's, not arbitrary

Compare the order of suppliers in this output against what fusion alone would give (near-tied RRF scores).

**You should see:** an order that does not necessarily put Meridian first — this is the whole point of the degradation being honest: with no reranker, there is no reason to expect the right passage lands at the top, and `reranked: False` says so rather than pretending otherwise.

---

## Part D — run-to-run ordering is stable

### 18. Run the Part B (or Part C, if that is the only one available to you) script three times in a row

Re-run whichever script you used in step 12 or step 16, three times without changing anything.

**You should see:** the same order of candidates, and the same scores, on all three runs — no reshuffling of the near-tied entries between runs. (Under fusion order alone, entries that tie on RRF score keep the order the database returned them in, which is deterministic per query; under reranked order, `InferenceClient.rerank`'s own stable sort keeps tied cross-encoder scores in their fused-rank order — neither path is allowed to vary run to run.)

---

## Known gaps

- **No Ask screen and no retrieval endpoint.** Unchanged from `M1-ASK-RET-035`'s own manual test — `docs/ux/ask.md` §5's "Retrieving" and "Answered" states still describe a screen with nothing behind it. Every candidate and score in this document was read from a Python script's `print` output, not a rendered source card.
- **No threshold applied.** `RetrievalResult.threshold` is still only captured, never compared against a score — including the reranked score. Deciding whether a reranked score clears the bar is `M2`, explicitly out of this ticket's scope. A weak best match still becomes an answer once `M2` composes one.
- **No trace or interaction record.** `rerank_duration_ms` and the two score sets have nowhere to be written yet — no trace writer or interaction record exists (`M2`/`M4`). This document reads them from a script instead.
- **A real cross-encoder pass (Part B) needs weights this environment may not have.** The repository's own CI and `docs/BRAIN.md`'s verification note for this ticket had no native `llama.cpp` reranker process available either, and proved the promotion behaviour with a fake client in `test_retrieve_records.py` instead. If you could not run Part B, that is the same gap, not a regression.
- **No deployment-profile variation.** `rerank_candidate_count` and `rerank_timeout_seconds` are each one global default; the profile-specific config `docs/architecture.md` §6 describes does not exist yet, so this document cannot demonstrate a light-profile bound being tighter than a full-profile one.
