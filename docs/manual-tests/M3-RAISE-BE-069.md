# Manual test — M3-RAISE-BE-069, ranking and the cap of five per source

**Ticket:** `M3-RAISE-BE-069` — where a source produces more than five clarification candidates, rank them (contradictions first, then document identity, then abbreviations by corpus frequency, then low-confidence scans by document size), store the rank, ask only the top five, and record the rest to memory as low-confidence inferences naming their rank. The cap is user-adjustable, defaults to 5, and a change is a decisions record.
**Version under test:** `0.3.2`
**Time:** about 60–75 minutes, plus a first stack build and native inference startup. Builds on `M3-RAISE-BE-068`'s triggers — this ticket only adds ranking and the cap on top of candidates that ticket's own manual test already exercised individually.
**Who can run it:** a terminal, `psql` access via `scripts/dev.sh psql`, and native inference running on the host.

**What is being checked.** `askwell.clarify.raise_candidates` (`api/src/askwell/clarify.py`) runs once per source, the moment `askwell.ingest.refresh_source` finds nothing left outstanding for it. Every candidate that passes the three-test filter is sorted by `_rank_candidates` — trigger priority (`contradiction` < `document_identity` < `abbreviation` < `unreadable_scan`), then descending `_rank_weight` within a tier, then subject as a deterministic tie-break — and the first `get_clarification_cap(session)` (default 5, from the `settings` table) are inserted into `clarifications` with their 1-based `rank`. Everything ranked below the cap is inserted into `memory` as `origin = 'inferred'`, `confidence = 0.3`, with a fact naming its rank and the cap. `set_clarification_cap` is the only way the cap changes, and it always writes a `clarification_cap_changed` row to the decisions store.

**Where this stops on purpose.** No screen renders any of this yet — there is no `/clarifications` route and no settings control for the cap in `web/` as of this version (confirmed by searching `web/` for both). Every check below reads the database directly, the same way the ticket's own automated tests do (`api/tests/test_clarify.py`, `requires_db`). This is not a shortcut around "click, don't call an endpoint" — there is no UI path yet to click through, and inventing one for this walkthrough would test a screen that does not exist.

---

## Before you start

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf`. A document only reaches `status = 'ready'` — the trigger that fires `raise_candidates` — once it has been chunked and embedded, so you need the embedding model on this machine even though nothing here asks a question of the generation model.

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

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text.

### 3. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 4. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 5. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready` on its configured port.

### 6. Nominate the folder your material is in

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

### 7. Open a psql session and keep it open

```
scripts/dev.sh psql
```

Keep this terminal open for the rest of the walkthrough — every check below runs a query in it.

---

## Part A — ten candidates, cap of five, deterministic top five

### 8. Write a file with ten abbreviations of increasing frequency

```bash
scripts/dev.sh run python3 - <<'PY'
letters = "ABCDEFGHIJ"
lines = []
for index, letter in enumerate(letters):
    token = letter * 3
    occurrences = index + 2
    lines.append(" ".join(f"The {token} applies here." for _ in range(occurrences)))
with open("/app/askwell-test-material/abbrev-ten.txt", "w") as f:
    f.write("\n".join(lines) + "\n")
print("done")
PY
```

**You should see:** the script print `done`. This produces ten all-caps tokens — `AAA` through `JJJ` — occurring 2 through 11 times respectively, none of them in Askwell's common-abbreviation stoplist (`PDF`, `HTML`, `USA`, and similar) and none already in memory.

### 9. Add the file by clicking through the app

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `abbrev-ten.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** a card move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 10. Confirm the document reached `ready`

In the `psql` session:

```sql
SELECT filename, status FROM documents WHERE filename = 'abbrev-ten.txt';
```

**You should see:** one row, `status` = `ready`. This is the moment `raise_candidates` fired — the ticket's trigger point, not something you started by hand.

### 11. Confirm exactly five were asked, and which five

```sql
SELECT subject, rank FROM clarifications ORDER BY rank;
```

**You should see:** exactly five rows, in this order:

```
 subject | rank
---------+------
 JJJ     |    1
 III     |    2
 HHH     |    3
 GGG     |    4
 FFF     |    5
```

These are the five tokens with the highest occurrence counts (11, 10, 9, 8, 7) — abbreviations rank within their own tier by corpus frequency, and the four lower-frequency tokens (`EEE` down to `AAA`) lost the cap.

### 12. Confirm the questions read naturally

```sql
SELECT question FROM clarifications ORDER BY rank LIMIT 1;
```

**You should see:** a question of the shape `'JJJ' appears throughout. What does it mean?`.

### 13. Confirm the other five were inferred, not dropped

```sql
SELECT subject, origin, confidence, fact FROM memory ORDER BY subject;
```

**You should see:** five rows — `AAA`, `BBB`, `CCC`, `DDD`, `EEE` — each `origin` = `inferred`, each `confidence` = `0.300`, and each `fact` naming its rank and the cap, e.g. `'AAA' appears throughout. What does it mean? Not asked — ranked 10 of 10 for this source, below the cap of 5.` (subject `EEE`, the highest-ranked of the five that missed the cap, should read `ranked 6 of 10`).

### 14. Confirm both outcomes were logged as decisions

```sql
SELECT kind, count(*) FROM audit_decisions
WHERE kind IN ('clarification_raised', 'clarification_capped')
GROUP BY kind;
```

**You should see:** `clarification_raised` = 5, `clarification_capped` = 5.

---

## Part B — exactly five candidates: no capping at all

### 15. Write a file with exactly five abbreviations

```bash
scripts/dev.sh run python3 - <<'PY'
letters = "KLMNO"
lines = [f"{letter*3} and {letter*3} again." for letter in letters]
with open("/app/askwell-test-material/abbrev-five.txt", "w") as f:
    f.write("\n".join(lines) + "\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 16. Add it the same way as step 9, and wait for it to settle

### 17. Confirm all five were asked and none capped

```sql
SELECT count(*) FROM clarifications WHERE subject IN ('KKK', 'LLL', 'MMM', 'NNN', 'OOO');
```

**You should see:** `5`.

```sql
SELECT count(*) FROM memory WHERE subject IN ('KKK', 'LLL', 'MMM', 'NNN', 'OOO');
```

**You should see:** `0` — the acceptance criterion's own edge case: exactly five candidates produces no capping and nothing inferred by rank alone.

---

## Part C — running an equivalent import twice chooses the same five

Reusing step 8's exact tokens (`AAA`…`JJJ`) here would not be a clean test: five of them (`AAA`–`EEE`) are already sitting in `memory` as inferred facts after Part A, and the abbreviation trigger skips anything already in memory — so a second source using those same strings would silently see five candidates instead of ten, for the wrong reason. This part uses a fresh set of ten token strings instead, written identically into two separate sources.

### 18. Write two files with the same ten (fresh) tokens and the same frequencies

```bash
scripts/dev.sh run python3 - <<'PY'
letters = "ABCDEFGHIJ"
for suffix in ("one", "two"):
    lines = []
    for index, letter in enumerate(letters):
        token = letter * 4  # four-fold, not three, so these are new strings
        occurrences = index + 2
        lines.append(" ".join(f"The {token} applies here." for _ in range(occurrences)))
    with open(f"/app/askwell-test-material/abbrev-repeat-{suffix}.txt", "w") as f:
        f.write("\n".join(lines) + "\n")
print("done")
PY
```

**You should see:** the script print `done`. This produces `AAAA`…`JJJJ`, occurring 2 through 11 times, in two identical files.

### 19. Add both files as two separate sources

Add `abbrev-repeat-one.txt` the same way as step 9, wait for it to settle, then add `abbrev-repeat-two.txt` the same way, and wait for it to settle. Each add creates its own source row, so this genuinely exercises two independent runs of `raise_candidates`, not one.

### 20. Confirm both sources chose the same top five, in the same order

```sql
SELECT d.filename, c.subject, c.rank FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename IN ('abbrev-repeat-one.txt', 'abbrev-repeat-two.txt')
ORDER BY d.filename, c.rank;
```

**You should see:** the identical sequence for both filenames — `JJJJ, IIII, HHHH, GGGG, FFFF` at ranks 1 through 5. Nothing about the sort key (trigger, evidence counts, subject) varies with insertion order or timing, so two equivalent sources land on the same five.

---

## Part D — a contradiction outranks an abbreviation for the cap

### 21. Write two documents that disagree, plus five abbreviations, in one source

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/mixed-source", exist_ok=True)
with open("/app/askwell-test-material/mixed-source/handbook-2024.txt", "w") as f:
    f.write("The notice period is 30 days for all staff.\n")
with open("/app/askwell-test-material/mixed-source/policy-2025.txt", "w") as f:
    f.write("The notice period is 45 days for all staff.\n")
letters = "PQRST"
lines = []
for index, letter in enumerate(letters):
    token = letter * 3
    occurrences = index + 3
    lines.append(" ".join(f"The {token} applies here." for _ in range(occurrences)))
with open("/app/askwell-test-material/mixed-source/abbrevs.txt", "w") as f:
    f.write("\n".join(lines) + "\n")
print("done")
PY
```

**You should see:** the script print `done`. This gives one source six passing candidates: one contradiction (`the notice period`) and five abbreviations (`PPP` through `TTT`, occurrences 3 through 7).

### 22. Add the whole `mixed-source` folder as one source

On the "Add a source" page, point it at:

```
/home/you/external/quantum-plus/askwell/askwell-test-material/mixed-source
```

and click **Add it**. Wait for all three documents to settle.

### 23. Confirm the contradiction is ranked first and the lowest-frequency abbreviation lost the cap

```sql
SELECT subject, rank FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'handbook-2024.txt'
ORDER BY c.rank;
```

**You should see:** five rows. Row 1 is `the notice period` — a contradiction always sorts ahead of every abbreviation regardless of occurrence count, since trigger priority is compared before volume. The remaining four rows are `TTT, SSS, RRR, QQQ` (occurrences 7, 6, 5, 4) — `PPP` (occurrences 3, the lowest) is the one that lost the cap.

```sql
SELECT subject FROM memory WHERE subject = 'PPP';
```

**You should see:** one row.

---

## Part E — raising the cap is never silent, and takes effect on the next source

### 24. Raise the cap, through the real code path, and confirm it is recorded as a decision

There is no settings control for this yet (§ "Where this stops on purpose"), so drive the same function the product will call once one exists, against the running `api` container:

```bash
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.clarify import get_clarification_cap, set_clarification_cap

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        before = await get_clarification_cap(session)
        await set_clarification_cap(session, 7)
        after = await get_clarification_cap(session)
    print('before', before, 'after', after)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `before 5 after 7`.

In the `psql` session:

```sql
SELECT kind, payload FROM audit_decisions WHERE kind = 'clarification_cap_changed';
```

**You should see:** one row, `payload` containing `"previous": 5` and `"new": 7` — the validation rule that a cap change is "never raised silently" is a real, queryable record, not a comment.

### 25. Confirm a new source now asks more

```bash
scripts/dev.sh run python3 - <<'PY'
# Seven fresh token strings, none used earlier in this walkthrough — reusing
# an exact string already recorded in memory (Part A's "AAA".."EEE", Part
# D's "PPP") would hit the "already known" abbreviation filter and silently
# produce fewer than seven candidates.
tokens = ["UUUU", "VVVV", "WWWW", "XXXX", "YYYY", "ZZZZ", "UVWX"]
lines = []
for index, token in enumerate(tokens):
    occurrences = index + 2
    lines.append(" ".join(f"The {token} applies here." for _ in range(occurrences)))
with open("/app/askwell-test-material/abbrev-seven.txt", "w") as f:
    f.write("\n".join(lines) + "\n")
print("done")
PY
```

Add it the same way as step 9, and wait for it to settle.

```sql
SELECT count(*) FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'abbrev-seven.txt';
```

**You should see:** `7` — the raised cap took effect on this source, the first one scanned since step 24, exactly as the acceptance criterion says ("raising the cap in settings raises the number asked on the next source").

### 26. Confirm the cap cannot be lowered below one

```bash
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.clarify import set_clarification_cap

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        try:
            await set_clarification_cap(session, 0)
            print('no error raised — this is a bug')
        except ValueError as error:
            print('rejected:', error)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `rejected: clarification cap must be at least 1`.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No screen renders any of this.** `docs/ux/clarifications.md` §5's "capped" copy (*"Asking about the 5 that matter most. Askwell inferred the rest..."*) and the settings control for the cap are both specified but not built — this walkthrough verifies the data the screen will eventually read (`clarifications.rank`, the inferred `memory` rows, the capped count), not the screen itself. Do not report the absence of `/clarifications` or a settings toggle as a defect of this ticket.
- **The ranking reason is never shown**, by design — `docs/ux/clarifications.md` §8 settles this: showing why a question made the top five is out of scope, open, and not this ticket's to build.
- **Bulk patterns across similar columns are not exercised.** `docs/ux/clarifications.md` §8's "one question for all `*_cd` columns" idea is explicitly out of scope for this ticket and for M3 generally (column triggers arrive with M4's data sources).
- **The late-arriving-candidate edge case is not exercised.** The acceptance criteria describe a source producing candidates over time where a late high-ranking contradiction should displace an already-raised, unanswered lower-ranked question. `raise_candidates` is idempotent per source — once any row exists in `clarifications` for a source, it is never re-scanned (`api/src/askwell/clarify.py`'s own docstring on `raise_candidates` names the open tracker issue for this). This walkthrough only exercises a source scanned once, after ingestion is already complete, which is the path that actually runs today.
- **Date-format and unguessable-column triggers do not exist yet.** The ranking order in `docs/memory-and-clarification.md` §8 names five tiers; only three are implemented (`contradiction`, `document_identity` sits between them, `abbreviation`, `unreadable_scan`) — date-format ambiguity and unguessable columns arrive with M4's data sources and are not reachable to test here.
- **`unreadable_scan` is not exercised in this document.** `M3-RAISE-BE-068`'s own manual test already covers that trigger individually; re-deriving a poor scan here would not add anything to what this ticket changes (ranking and the cap), which is fully exercised by the abbreviation and contradiction triggers used above.
