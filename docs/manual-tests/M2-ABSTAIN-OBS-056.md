# Manual test — M2-ABSTAIN-OBS-056, the local abstention rate

**Ticket:** `M2-ABSTAIN-OBS-056` — abstentions are recorded with candidates, scores, threshold and the near-miss (already true since `M2-ABSTAIN-RET-053`); a local, on-demand abstention rate is derivable over a window; changing the threshold later never alters the stored values of a past turn.
**Version under test:** `0.2.44`
**Time:** about 30 minutes, plus a first stack build. Reuses `M2-ABSTAIN-RET-053`'s corpus and questions rather than building new ones — this ticket adds a read over what that one already stores.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `api/src/askwell/observability.py`'s `abstention_rate(session, window=500)`: it counts the `abstained` flag already written to every `ask_asked` row in `audit_interactions` by `askwell.ask` (`M2-ABSTAIN-RET-053`), over the most recent `window` rows, and reports `covered` (how many rows it actually read) alongside `abstained` (how many of those were `true`). It reads no other column — not the stored `threshold`, not `retrieved_chunks`, and never the live `Settings.retrieval_score_threshold` — so nothing about a later configuration change can alter what a past turn reports.

**Where this stops on purpose.** There is no dashboard, no settings-screen surface, and nothing transmitted (there is no telemetry — C1). The function is the whole surface this ticket builds; nothing in `web/` or any HTTP route calls it. This walkthrough calls it directly, inside the running `api` container, the same way `podman compose exec api askwell-verify` already reaches into the container for a check with no HTTP surface of its own.

---

## Before you start

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf` and `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65`. Only the embedding weights are needed.

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

Confirm the threshold this run starts at:

```
grep ASKWELL_RETRIEVAL_SCORE_THRESHOLD .env
```

**You should see:** `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65` (or nothing, in which case the code's own default of `0.65` is in force). Note the value so it can be restored later — this document changes it deliberately, the same as `M2-ABSTAIN-RET-053` Part D.

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

**You should see:** lint, format, typecheck and test stages finish without red error text.

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

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready` on the port from `ASKWELL_EMBEDDING_PORT`.

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

## Part A — before anything is asked, the rate reports nothing

### 8. Confirm no `ask_asked` rows exist yet

```
scripts/dev.sh psql
```

```sql
SELECT count(*) FROM audit_interactions WHERE kind = 'ask_asked';
```

**You should see:** `0`. Keep this `psql` session open in its own terminal for later steps.

### 9. Compute the rate against an empty log

In a new terminal:

```bash
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.observability import abstention_rate

async def main():
    engine = build_engine(load_settings())
    async with session_factory(engine)() as session:
        print(await abstention_rate(session))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `AbstentionRate(covered=0, abstained=0)`. `.rate` on that value is `None` (checked directly by `test_no_interactions_reports_no_rate`, not observable from this printed form alone) — the ticket's own "a `0.0` here would claim a healthy corpus that was never tested" rule.

---

## Part B — a small mix of answered and abstained turns

### 10. Write one file with a clear, narrow fact

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/notice-period.txt", "w") as f:
    f.write(
        "Section 4.2 Termination. Either party may terminate this agreement by "
        "giving ninety days' written notice to the other party.\n"
    )
print("done")
PY
```

**You should see:** the script print `done`.

### 11. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 12. Add the file

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `notice-period.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** a card move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 13. Ask two questions the corpus answers, and one it does not

Click **Ask**. Type and send, one at a time, waiting for each turn to finish before sending the next:

```
How much notice is required to terminate the agreement?
```

```
What section covers termination?
```

```
What is the capital of France?
```

**You should see:** the first two stream in real answer text citing `notice-period.txt`. The third shows named progress briefly, then a blank space beneath the question — no answer text — matching `M2-ABSTAIN-RET-053`'s Part C behaviour (or, since `M2-ABSTAIN-BE-054`/`055`, the rendered "nothing in your files answers this" abstention state if your checkout has both of those tickets built).

### 14. Confirm the mix in the interaction log

In the `psql` session:

```sql
SELECT payload ->> 'question' AS question, payload ->> 'abstained' AS abstained
FROM audit_interactions WHERE kind = 'ask_asked' ORDER BY occurred_at;
```

**You should see:** three rows — `abstained = false` for the two termination questions, `abstained = true` for the France question. (`audit_interactions` has no bare `question`/`abstained` columns — every field `askwell.ask` records lives inside the `payload` JSONB column, which is exactly what `abstention_rate`'s own query in `api/src/askwell/observability.py` reads.)

### 15. Compute the rate over these three turns

```bash
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.observability import abstention_rate

async def main():
    engine = build_engine(load_settings())
    async with session_factory(engine)() as session:
        print(await abstention_rate(session))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `AbstentionRate(covered=3, abstained=1)`. This is the ticket's own scenario — "ask several questions including two that abstain... confirm it reflects those" — with one abstention instead of two, since Part A of this document starts from one narrow document rather than the wider corpus a "two abstentions" scenario would need; the count either way is read from real stored flags, not asserted.

### 16. Compute the rate over a narrower window

```bash
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.observability import abstention_rate

async def main():
    engine = build_engine(load_settings())
    async with session_factory(engine)() as session:
        print(await abstention_rate(session, window=1))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `AbstentionRate(covered=1, abstained=1)` — the single most recent row (the France question, `ORDER BY occurred_at DESC`), `covered` telling you plainly that only one of the three rows in the log was actually read. This is the ticket's "very long window... reports what it covered" edge case, exercised from the narrow end: a `window` smaller than the log is still honest about how much of it was read, the same property `test_window_bounds_the_query_and_reports_what_it_covered` checks at the wide end.

---

## Part C — the threshold changes; the stored history does not

### 17. Note the score the answered question is riding on

```sql
SELECT payload ->> 'threshold' AS threshold, payload -> 'retrieved_chunks'
FROM audit_interactions WHERE kind = 'ask_asked' ORDER BY occurred_at DESC LIMIT 3;
```

**You should see:** `threshold = 0.65` on all three rows, each with its own stored candidate scores.

### 18. Stop native inference and the stack

In the inference terminal, `Ctrl-C`. Then:

```
podman compose down
```

(No `-v` — keep the indexed document and the three logged turns.)

### 19. Raise the threshold past the score the answered questions scored

Open `.env`, find `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65`, and raise it well past what step 17 showed:

```
ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.99
```

### 20. Bring the stack back up and ask one more question

```
podman compose up -d
scripts/dev.sh inference
```

Wait for the embedding role to report `ready`, then in the browser:

```
How much notice is required to terminate the agreement?
```

**You should see:** the same question that answered in step 13 now abstains — a blank turn, no answer text — since `0.99` is past the real score.

### 21. Compute the rate again

```bash
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.observability import abstention_rate

async def main():
    engine = build_engine(load_settings())
    async with session_factory(engine)() as session:
        print(await abstention_rate(session))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `AbstentionRate(covered=4, abstained=2)` — the new abstained turn added to the count, the three earlier rows unchanged.

### 22. Confirm the three earlier rows still carry the threshold that actually produced them

```sql
SELECT payload ->> 'question' AS question, payload ->> 'abstained' AS abstained,
       payload ->> 'threshold' AS threshold
FROM audit_interactions WHERE kind = 'ask_asked' ORDER BY occurred_at;
```

**You should see:** the two originally-answered rows and the first abstained row still reading `threshold = 0.65` — the value in force when each of them actually ran. Only the newest row (step 20) reads `0.99`. Nothing about running `abstention_rate` in steps 15, 16 or 21, and nothing about the configuration change in step 19, rewrote any of the earlier three — the ticket's headline rule, watched directly rather than only trusted from `test_changing_the_threshold_later_never_alters_a_stored_turn`.

### 23. Confirm the audit chain is still intact

```
podman compose exec api askwell-verify
```

**You should see:** both chains reported intact, including the new rows this document's turns just added — abstention records are ordinary chained interactions, not a separate, weaker store.

### 24. Put the threshold back

Restore `.env` to the value noted in **Before you start** (`0.65`), then repeat step 20's bring-up so the stack is left in its normal configuration.

---

## Known gaps

- **No settings-screen surface.** The ticket's own "Surfaced later by the trace (M5) and by `states-and-edge-cases.md` §6" line is honoured literally — nothing in `web/` renders this number anywhere. Every value in this document was read by calling `abstention_rate` directly inside the container, not by clicking to a screen that shows it.
- **The "very long window" edge case is exercised only from the narrow end.** Step 16 proves `covered` is honest when `window` is smaller than the log; producing a log with more than 500 real rows (the default `window`, and the case `test_window_bounds_the_query_and_reports_what_it_covered` covers with 7 seeded rows against a `window=3`) is impractical by clicking through a browser one question at a time, and this document does not attempt it — it is covered by `scripts/dev.sh test-db`.
- **A turn with a genuinely empty `retrieved_chunks` list is not produced here.** This corpus's one document is ready and searchable throughout, so every turn's `retrieved_chunks` in this document has at least a near-miss candidate — a truly empty list (the ticket's other named edge case, corpus with nothing indexed yet, or every candidate excluded before scoring) is exercised by `test_a_turn_with_no_candidates_is_counted_not_omitted` against a directly inserted row, not reproduced end-to-end here.
- **`AbstentionRate.rate`'s `None`-vs-`0.0` distinction is not directly observable from the printed dataclass.** Step 9 prints `AbstentionRate(covered=0, abstained=0)`; confirming `.rate is None` on that value (rather than assuming it from `covered == 0`) is what `test_no_interactions_reports_no_rate` checks, not this walkthrough.
