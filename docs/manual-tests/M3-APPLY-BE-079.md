# Manual test — M3-APPLY-BE-079, citing a memory fact and recording fact usage

**Ticket:** `M3-APPLY-BE-079` — a claim that rests on a memory fact or schema note cites it by index, the same `[N]` marker convention a document passage uses, continuing straight on from the document candidates' own `1..N`. Citing it writes a row to `fact_usage` (not `citations`), attributed to the user and the date the fact was supplied. A fact that only helped interpret a document still leaves the claim citing the document. The uncited-claim check accepts a fact-backed answer as compliant.
**Version under test:** `0.3.17`
**Time:** about 45 minutes, plus a first stack build and native inference startup.
**Who can run it:** a browser, and `psql` access via `scripts/dev.sh psql` for the parts nothing on screen renders yet — see "Where this stops on purpose".

**What is being checked.** `api/src/askwell/agent/conflict._delimit_memory_facts`/`_delimit_schema_notes`, which number every retrieved fact and note continuing on from the document candidates' `1..N`; `api/src/askwell/ask._cite_claim`, which resolves an index in that continued range against `fact_usage` instead of `citations` and emits a `fact_citation` SSE event carrying the fact's subject, text, origin, confidence and `created_at`; and `api/src/askwell/agent/citation_check.check_citations`, whose exclusion of any message with a `fact_usage` row was dead code until this ticket populated the table for real.

**Where this stops on purpose — read this before reporting anything below as a defect.**

- **No screen renders a memory chip or a fact citation.** `docs/ux/ask.md` §3/§4 specify a chip reading something like `st_cd = student status code` in the provenance margin, and a "How did you get this?" trace panel. Neither is built — the correction chip is `M3-CORRECT-FE-081` and the memory screen's usage count is `M3-MEM-FE-083`, both still not started (`docs/BRAIN.md`). This document confirms the `fact_citation` SSE event and the `fact_usage` row by reading the browser's network stream and the database directly, not by clicking a chip — there is nothing yet to click.
- **`schema_notes` retrieval has no natural way to reach through the running app.** As `M3-STORE-BE-076`'s and `M3-APPLY-RET-078`'s own manual tests already found, nothing in the app writes a schema note. §3 below seeds one directly.
- **The local model's exact wording is not deterministic.** Getting the model to emit a citation marker on the *fact* index rather than the document index depends on how it reads the prompt. §1 below asks a question shaped so the fact is the only thing that can answer it, which is what makes the model's citation choice predictable in practice; if your run's model cites the document instead, that is a prompt-following gap in the model, not this ticket's data path — the record-keeping is what §1 exists to check, not the model's word choice.

---

## Before you start

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

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank. Find `ASKWELL_EMBEDDING_MODEL_PATH` and confirm it points at a model that actually exists on this machine.

Create the file this walkthrough asks Askwell to read:

```
cat > askwell-test-material/procurement.txt <<'TXT'
The RFQ process starts on page 4 of the supplier handbook.
Every RFQ must be logged in the tracking sheet before it is sent.
TXT
```

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

**You should see:** lint, format, typecheck and unmarked tests finish without red error text.

### 3. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started, then migration lines finishing with no error.

### 4. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready`.

### 5. Open the app and nominate the test folder

Open a browser at `http://127.0.0.1:8000`. **You should see:** the Askwell shell load with no sign-in prompt.

Click **Settings**, scroll to **Folders Askwell may read**, and nominate:

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

Click **Add a source** in the sidebar, choose that folder, and wait for the **Library** screen to show `procurement.txt` as **Ready**.

---

## 1. The ticket's own walkthrough: a taught abbreviation is cited as a fact, not invented from the document

### 6. Wait for the abbreviation to be raised as a clarification

Click **Clarifications** in the sidebar. This can take a few seconds after the file shows **Ready**; refresh the screen if nothing shows yet.

**You should see:** one card whose subject is `RFQ`, with a question like "What does RFQ mean?" and evidence quoting the passage from `procurement.txt`.

### 7. Teach Askwell the abbreviation

Open the `RFQ` card, type into its text field:

```
Request for Quotation
```

Click **Save**.

**You should see:** the card disappears from the pending list (or the count above it decreases by one).

### 8. Open your browser's network panel before asking

Open your browser's developer tools, switch to the **Network** tab, and clear it. This is where the `fact_citation` event this ticket adds will show up — there is no chip yet, so the network stream is the only place in the running app to see it.

### 9. Ask the question the fact answers

Go to the **Ask** screen (route `/`) and ask:

```
What does RFQ mean?
```

**You should see:** an answer that states RFQ stands for Request for Quotation.

### 10. Read the fact citation off the network stream

In the Network panel, find the request to `/ask` (or `/ask/{id}/stream` if the panel split it), open it, and look at the event stream body.

**You should see:** an `event: fact_citation` block whose `data` names `"fact_kind": "memory"`, `"subject": "RFQ"`, `"fact": "Request for Quotation"`, and a non-null `"supplied_at"` — the date you saved the clarification in step 7. This is the "attributed to the user and the date it was supplied" the ticket's acceptance criteria ask for, streamed live rather than only written to a table afterward.

### 11. Confirm it on the record, not just on the wire

```
scripts/dev.sh psql <<'SQL'
SELECT m.id,
       (SELECT count(*) FROM fact_usage f WHERE f.message_id = m.id) AS fact_usage_rows,
       (SELECT count(*) FROM citations c WHERE c.message_id = m.id) AS citation_rows
FROM messages m
WHERE m.role = 'assistant'
ORDER BY m.created_at DESC
LIMIT 1;
SQL
```

**You should see:** `fact_usage_rows` is `1` and `citation_rows` is `0` — the claim cited the fact, and wrote to `fact_usage`, not `citations`. (If your run's model happened to also make a claim about something in `procurement.txt` in the same answer, `citation_rows` may be greater than `0` for that separate claim — the check that matters here is that a `fact_usage` row exists at all.)

```
scripts/dev.sh psql <<'SQL'
SELECT fact_kind, fact_id, m.created_at AS supplied_when
FROM fact_usage fu
JOIN memory m ON m.id = fu.fact_id
WHERE fu.message_id = (SELECT id FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1);
SQL
```

**You should see:** one row, `fact_kind = 'memory'`, `fact_id` pointing at the row your clarification answer created, and `supplied_when` matching what you saw in the `fact_citation` event.

---

## 2. Edge case: a fact used to interpret a document still cites the document

### 12. Ask a question the document itself answers, using the taught term

```
Where does the RFQ process start?
```

**You should see:** an answer naming page 4 of the supplier handbook, citing `procurement.txt` — the fact you taught (RFQ = Request for Quotation) may have helped the model recognise the term in the question, but the claim about *where the process starts* comes from the document, not from memory.

### 13. Confirm the citation landed on the document, not the fact

```
scripts/dev.sh psql <<'SQL'
SELECT (SELECT count(*) FROM citations c
        WHERE c.message_id = m.id) AS citation_rows
FROM messages m
WHERE m.role = 'assistant'
ORDER BY m.created_at DESC
LIMIT 1;
SQL
```

**You should see:** `citation_rows` is at least `1` — the claim about page 4 traces to `procurement.txt`'s own chunk. This is the ticket's own edge case: memory explaining what a term means does not license inventing what is in the document.

---

## 3. Edge case: a schema note is cited the same way a memory fact is

Nothing in the running app writes a schema note yet, so this is seeded directly — the same way `M3-STORE-BE-076`'s and `M3-APPLY-RET-078`'s own manual tests do.

### 14. Seed a schema note

```
scripts/dev.sh psql <<'SQL'
INSERT INTO schema_notes (id, table_name, column_name, description, origin, confidence)
VALUES (gen_random_uuid(), 'students', 'st_cd', 'student status code: A = active, W = withdrawn', 'manual', 1.0);
SQL
```

### 15. Ask a question that can only be answered from the note

```
What does st_cd mean in the students table?
```

**You should see:** an answer describing the status code meaning.

### 16. Confirm it wrote to fact_usage as a schema note, not a memory fact

```
scripts/dev.sh psql <<'SQL'
SELECT fact_kind, fact_id
FROM fact_usage
WHERE message_id = (SELECT id FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1);
SQL
```

**You should see:** `fact_kind = 'schema_note'`, with `fact_id` pointing at the row seeded in step 14.

---

## 4. Edge case: the uncited-claim check accepts a fact-backed answer

### 17. Run the check the ticket names in its own Testing Notes

```
scripts/dev.sh run python -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.agent.citation_check import check_citations

async def main():
    settings = Settings()
    factory = session_factory(build_engine(settings))
    async with session_scope(factory) as db:
        result = await check_citations(db)
        print(result)

asyncio.run(main())
"
```

**You should see:** a `CitationCheckResult` whose `excluded_fact_usage` is at least `2` (the two answers from §1 and §3 above that wrote a `fact_usage` row) and whose `violations` does not include either of those two messages — they are excluded from the check entirely, not counted as violations, matching the module's own reasoning for why a whole fact-backed message is excluded rather than checked claim-by-claim.

---

## 5. Edge case: a deleted fact's usage history survives

### 18. Delete the fact you taught in step 7

```
scripts/dev.sh psql <<'SQL'
DELETE FROM memory WHERE subject = 'RFQ';
SQL
```

### 19. Confirm the old usage row is untouched

```
scripts/dev.sh psql <<'SQL'
SELECT count(*) FROM fact_usage
WHERE message_id = (
  SELECT id FROM messages WHERE content LIKE '%Request for Quotation%'
  ORDER BY created_at ASC LIMIT 1
);
SQL
```

**You should see:** `1` — the row from step 11 is still there. History is not rewritten by a later deletion, per the ticket's own edge case; the row now references a `fact_id` that no longer exists in `memory`, which is expected and is why `fact_usage` has no foreign key enforcing otherwise.

---

## Known gaps

- **No chip renders a fact citation, and nothing is clickable.** `docs/ux/ask.md` §3/§4's memory chip and "How did you get this?" trace panel are both specified but not built — every check above that confirms a `fact_citation` reads the network stream or the database directly. The correction interaction (`M3-CORRECT-FE-081`) and the memory screen's "used in N answers" count (`M3-MEM-FE-083`) both remain not started.
- **`fact_usage` has no `claim_ordinal`.** A message with two claims, one fact-backed and one not, is excluded from the uncited-claim check *as a whole message* rather than having only its fact-backed claim excluded — `docs/decisions.md`, 2026-09-18, has the reasoning for accepting this rather than a second migration.
- **Schema note retrieval is exercised only by seeding rows.** Nothing in the app writes a schema note yet (`M3-STORE-BE-076`'s own gap, unchanged here) — §3 above seeds one because there is no other way to get one into the database through the running app.
- **The model's choice of which index to cite is not deterministic.** §1 asks a question shaped so the fact is the only source, but a different local model, or a different run, may cite the document candidate instead of the fact, or both. That is a prompt-following property of the model, not a defect in the citation or `fact_usage` plumbing this ticket adds.
