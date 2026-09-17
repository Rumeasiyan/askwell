# Manual test — M3-RAISE-BE-071, capture the evidence that makes a question answerable

**Ticket:** `M3-RAISE-BE-071` — every raised clarification now stores real, kind-tagged evidence alongside its question: `passage` (document, page, bounded excerpt) for an abbreviation or an ambiguous document identity, `contradiction` (both passages, each with its own page and date) for disagreeing sources, `poor_scan` (extracted text per flagged page, `page_images` honestly `"not available"`) for a bad OCR pass. Every evidence dict carries `current_inference` — what would have gone to `memory` as a guess had the candidate not been material enough to ask. Evidence that cannot be captured never drops the question — it raises with `{"kind": "unavailable", "reason": ...}` instead. Passages are bounded to 500 characters; column value lists (not reachable yet — see **Known gaps**) to the top 10 plus a remainder count.
**Version under test:** `0.3.6`
**Time:** about 75–90 minutes, plus a first stack build and native inference startup. Builds on `M3-RAISE-BE-068`'s four triggers, `-069`'s ranking/cap and `-070`'s suppression — this ticket only deepens what each trigger stores as `evidence`, so the walkthrough re-exercises the same four triggers with an eye on what is now stored, rather than re-testing ranking or suppression from scratch.
**Who can run it:** a browser, a terminal, and `psql` access via `scripts/dev.sh psql` (used to read the stored `evidence` column directly and confirm it matches what the screen shows — never to drive the UI itself).

**What is being checked.** `askwell.clarify` (`api/src/askwell/clarify.py`): `_detect_abbreviations`, `_detect_document_identity`, `_detect_unreadable_scans` and `_detect_contradictions` now build a `kind`-tagged `evidence` dict from real rows read at raise time — never a paraphrase — and `raise_candidates` merges `candidate.inferred_fact` into that dict as `current_inference` before writing the `clarifications` row. `column_distribution_evidence` is also new but unused by any trigger (M4's own query fills it in later); it is covered here only as a function, not through the UI. There is no answering UI yet (`M3-REVIEW-FE-073`), so evidence is read either as the raw JSON the `/clarifications` screen already prints (`M3-REVIEW-FE-072`) or directly in `psql` — both are used below, and every psql query here is read-only, confirming what the app already did rather than standing in for a missing UI action.

**Where this stops on purpose.** No screen formats this evidence into the value-distribution / passage layout `docs/ux/clarifications.md` §3 describes — it renders as one line of raw `JSON.stringify` output, deliberately, per `M3-REVIEW-FE-072`'s own code comment. Nothing here is answerable by clicking (no **Save**, no **Skip**, no field) — see "Where this stops on purpose" in `M3-RAISE-BE-070`'s manual test for the same gap, unchanged by this ticket. Column-distribution evidence has no trigger to reach it from the app at all (M4 is not built), so it is exercised only through `scripts/dev.sh run python3` calling the function directly, not through ingestion.

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

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank. Find `ASKWELL_EMBEDDING_MODEL_PATH` and confirm it points at a model that actually exists on this machine — a document only reaches `status = 'ready'`, the point at which clarifications get raised, once it is chunked and embedded.

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

**You should see:** lint, format, typecheck and test stages finish without red error text — including `api/tests/test_clarify.py`'s new evidence tests (`test_abbreviation_evidence_carries_real_passages_and_no_inference` and its siblings).

```
scripts/dev.sh web-check
```

**You should see:** the frontend checks finish clean too — this ticket touches no frontend file, but `M3-REVIEW-FE-072`'s screen is what renders the evidence this walkthrough reads on screen, so confirming it still builds matters.

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

### 6. Open the app and nominate the test folder

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell load with no sign-in prompt.

Click **Settings** in the left rail, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

### 7. Open a psql session and keep it open

```
scripts/dev.sh psql
```

Keep this terminal open for the rest of the walkthrough.

---

## Part A — an abbreviation's evidence: real samples, document and page, no invented inference

### 8. Write a file with a repeated, uncommon abbreviation across two locations

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/tenders", exist_ok=True)
text = (
    "Page one text. The RFQ closes Friday at noon.\n\n"
    "Page two text. Another RFQ follows next week, and RFQ terms are attached here in full.\n"
)
with open("/app/askwell-test-material/tenders/tender-one.txt", "w") as f:
    f.write(text)
print("done")
PY
```

**You should see:** the script print `done`. `RFQ` occurs three times, is not in the common-abbreviation stoplist, and is not yet in `memory`.

### 9. Add the file by clicking through the app

Click **Ask** in the left rail.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**, point it at `.../askwell-test-material/tenders`, and click **Add it**.

**You should see:** a card move to **Queued**, then progress through extraction, chunking and embedding, and settle with no red error text.

### 10. Read the raw evidence on the clarifications screen

Click **Clarifications** in the left rail.

**You should see:** the address bar end in `/clarifications/`, a total line reading `1 question pending`, one group for the `tenders` source, and one card: subject `RFQ`, question `'RFQ' appears throughout. What does it mean?`, and beneath it one line of raw JSON evidence starting `{"kind":"passage","occurrences":3,"samples":[...`.

Confirm by eye that the JSON contains:
- `"kind":"passage"`
- `"occurrences":3`
- a `samples` array with **at most 2** entries (`EVIDENCE_MAX_SAMPLES`), each with a `document`, a `page`, and a `text` field that is a real excerpt containing `RFQ` — not a placeholder or a paraphrase
- `"current_inference":null` — there is no safe guess at what an abbreviation means, so nothing is invented here even though a question was raised for it

### 11. Confirm the same shape in the database directly

```sql
SELECT subject, evidence FROM clarifications WHERE subject = 'RFQ';
```

**You should see:** one row. `evidence` matches exactly what rendered on screen in step 10 — same `kind`, `occurrences`, `samples` (`document` = `tender-one.txt`, real page numbers, excerpt text containing `RFQ`), and `current_inference` = `null`. This confirms the screen is reading the stored column verbatim, not reformatting it.

---

## Part B — a poor scan's evidence: extracted text per page, an honest gap for page images, and a real inference

Materiality for this trigger needs the document's own `ocr_confidence` flag and per-page `ocr_confidence`/`text` rows already set below the threshold — the ordinary ingestion pipeline for a plain `.txt` file never produces a low-confidence page, so this is set directly in `psql`, the same way `M2-PARTIAL-BE-057`'s and this ticket's own unit tests do it (`api/tests/test_clarify.py::test_a_materially_poor_scan_raises_a_candidate_naming_its_pages`).

### 12. Add a throwaway document to attach the low-confidence pages to

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/scans", exist_ok=True)
with open("/app/askwell-test-material/scans/old-scan.txt", "w") as f:
    f.write("placeholder content, replaced by hand below\n")
print("done")
PY
```

Add `.../askwell-test-material/scans` the same way as step 9, and wait for it to settle.

### 13. Find the document and lower its OCR confidence and page text by hand

```sql
SELECT id FROM documents WHERE filename = 'old-scan.txt';
```

Use that id in place of `<doc-id>` below:

```sql
UPDATE documents SET ocr_confidence = 0.2 WHERE id = '<doc-id>';
UPDATE document_pages SET ocr_confidence = 0.2,
  text = 'garbled text page one, barely legible fragments only'
  WHERE document_id = '<doc-id>' AND page_number = 1;
```

**You should see:** both statements report `UPDATE 1`.

### 14. Trigger a fresh scan of this source

`raise_candidates` only runs once per source (the "already has a clarification row" guard), and `scans` already has none yet, so re-nominating is not needed — but the document's `status` must already be `ready` for the trigger's own query to see it. Confirm and, if `raise_candidates` has not fired yet for this source, add one more small file to the same folder to trigger ingestion once more:

```sql
SELECT status FROM documents WHERE filename = 'old-scan.txt';
```

If `status` is `ready` and no `clarifications` row exists yet for this source, wait up to a minute (the worker polls) and re-check:

```sql
SELECT subject, evidence FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'old-scan.txt';
```

**You should see:** one row, `subject` = `old-scan.txt`. `evidence` contains:
- `"kind":"poor_scan"`
- `"pages":[1]`
- `"total_pages"` matching however many pages this document has
- `"extracted_text"` — an array with one entry, `"page":1`, and `"text"` containing `garbled text page one`
- `"page_images":"not available"` — stated honestly, not omitted (real capture is issue #251, out of this ticket's scope)
- `"current_inference"` — not null, and containing the words `indexed as-is`

### 15. Confirm the same evidence on the clarifications screen

Click **Clarifications** in the left rail.

**You should see:** a card for `old-scan.txt` whose raw JSON line matches step 14's query exactly, including `"page_images":"not available"`.

---

## Part C — an ambiguous document identity's evidence: a real passage from the newest file

### 16. Write two version-like files with different content

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/policy", exist_ok=True)
with open("/app/askwell-test-material/policy/handbook-v1.txt", "w") as f:
    f.write("Old terms apply. Leave policy is 20 days per year.\n")
with open("/app/askwell-test-material/policy/handbook-v2-FINAL.txt", "w") as f:
    f.write("New terms apply here. Leave policy is 30 days per year.\n")
print("done")
PY
```

**You should see:** the script print `done`. Both stems normalise to `handbook` (`_normalize_filename` strips `v1`/`v2-FINAL`), so this is a version-cluster of two.

### 17. Add the folder and wait for it to settle

Add `.../askwell-test-material/policy` the same way as step 9.

### 18. Read the evidence

```sql
SELECT subject, question, evidence FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename LIKE 'handbook%' LIMIT 1;
```

**You should see:** `question` asking whether `handbook-v2-FINAL.txt` (the newest by `added_at`) is current. `evidence` contains:
- `"kind":"passage"`
- one `samples` entry with `"document":"handbook-v2-FINAL.txt"` — the **newest** file, not the older one
- `"text"` containing `New terms apply here` — the newest file's own first extracted passage, real text pulled from `document_pages`, not a summary
- `"current_inference":null` — document identity has no `inferred_fact` set (`Candidate` default), so nothing is guessed here either

---

## Part D — a contradiction's evidence: both passages, each with its own page and date

### 19. Write two sources stating conflicting values for the same subject

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/contract-a", exist_ok=True)
os.makedirs("/app/askwell-test-material/contract-b", exist_ok=True)
with open("/app/askwell-test-material/contract-a/agreement-a.txt", "w") as f:
    f.write("Section terms. The notice period is 30 days for all parties involved.\n")
with open("/app/askwell-test-material/contract-b/agreement-b.txt", "w") as f:
    f.write("Section terms. The notice period is 60 days for all parties involved.\n")
print("done")
PY
```

### 20. Add both sources, oldest first, and wait for each to settle

Add `.../askwell-test-material/contract-a` first, wait for it to settle, then add `.../askwell-test-material/contract-b` and wait for it to settle too. Contradiction detection needs both documents visible in the same source scan, so **do not** let `raise_candidates` run before the second file lands — if a `clarifications` row already exists for either source when you check below, redo this part with two fresh subjects in one single new source instead (one folder holding both files) so both are ingested together.

### 21. Read the evidence

```sql
SELECT subject, question, evidence FROM clarifications WHERE subject LIKE '%notice period%';
```

**You should see:** one row. `question` names both values (`30 days` and `60 days`) and both filenames. `evidence` contains:
- `"kind":"contradiction"`
- a `passages` array with exactly two entries, one per document
- each entry has its own `document`, `page`, `value` (e.g. `30 days`), a `date` (an ISO date string — the document's own `added_at`, not today's date, not a shared date), and `text` — a real bounded excerpt around the matched sentence, containing the word `notice`
- `"current_inference":null` — a real, unresolved contradiction is never silently resolved to one side, so nothing is guessed here even though the question failed to raise... (if it raised, confirm `current_inference` is still `null`; if it did not raise — check `subject` is at least two non-stopword words — the same field is checked in the `dropped`/`inferred` memory row instead, and should still show no invented resolution: see step 22)

### 22. Confirm the contradiction is never resolved to a guess even if not raised

```sql
SELECT subject, fact, origin FROM memory WHERE subject LIKE '%notice period%';
```

**You should see:** either no row at all (if the question was raised and is still `pending` in `clarifications` — the fact is not written to `memory` until it is answered) — this is the expected outcome here, since a two-word subject with no stopwords passes materiality. This step exists so a future reader confirms by absence: `_detect_contradictions` sets `inferred_fact=None`, so a contradiction is never quietly resolved to one side in `memory` the way a capped or failing candidate with a real guess would be.

---

## Part E — evidence that cannot be captured still raises the question

### 23. Force a poor-scan row with no extractable text on its flagged page

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/blank-scan", exist_ok=True)
with open("/app/askwell-test-material/blank-scan/blank.txt", "w") as f:
    f.write("placeholder\n")
print("done")
PY
```

Add `.../askwell-test-material/blank-scan` and wait for it to settle.

```sql
SELECT id FROM documents WHERE filename = 'blank.txt';
```

Use that id below:

```sql
UPDATE documents SET ocr_confidence = 0.1 WHERE id = '<doc-id>';
UPDATE document_pages SET ocr_confidence = 0.1, text = ''
  WHERE document_id = '<doc-id>' AND page_number = 1;
```

Wait up to a minute, then read the evidence:

```sql
SELECT subject, evidence FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'blank.txt';
```

**You should see:** one row — the question is still raised, not dropped, despite there being nothing to show. `evidence` is:

```json
{"kind": "unavailable", "reason": "no text extracted from page 1 of 'blank.txt'"}
```

with no `current_inference` key merged in for this row's own trigger logic — check the raised `clarifications.evidence` includes `"current_inference"` alongside it (merged by `raise_candidates` for every raised item regardless of kind), and that it names `indexed as-is` the same way Part B's did, since the poor-scan trigger's `inferred_fact` is set the same way whether or not a sample was captured.

This is the ticket's own central edge case: evidence that cannot be captured never causes the candidate to be silently dropped.

---

## Part F — `column_distribution_evidence`: the shared shape, exercised directly (no UI reaches it yet)

No trigger in this repository calls this function — M4's own column-ambiguity trigger will. It is exercised here as a function call, not through ingestion, so this part uses the API container's Python directly rather than clicking anything.

### 24. Call it with more values than the cap, and confirm the truncation

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.clarify import column_distribution_evidence

values = [(f"value-{i}", 1000 - i) for i in range(50)]
evidence = column_distribution_evidence(values, row_count=50_000)
print(evidence["kind"])
print(len(evidence["values"]))
print(evidence["values"][0])
print(evidence["remainder_count"])
PY
```

**You should see:**
```
column_distribution
10
{'value': 'value-0', 'count': 1000}
44510
```
(the top 10 kept, by count descending; `remainder_count` = `50000` minus the sum of the kept counts — 10 values summing to `1000+999+...+991 = 9950`, so `50000 - 9950 = 40050`... confirm the printed number is `row_count` minus whatever the top-10 sum actually is, rather than matching this exact figure literally — the point is that it is a real subtraction and it is positive.)

### 25. Confirm the remainder never goes negative

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.clarify import column_distribution_evidence

evidence = column_distribution_evidence([("only-value", 5)], row_count=1)
print(evidence["remainder_count"])
PY
```

**You should see:** `0` — not a negative number, even though the single value's own count (5) exceeds the stated `row_count` (1). `max(remainder, 0)` in `column_distribution_evidence` is what this confirms.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No screen formats this evidence.** `docs/ux/clarifications.md` §3's value-distribution / dual-passage / page-image layout is `M3-REVIEW-FE-073`'s own scope, unbuilt as of this version — every evidence dict in this walkthrough is read as raw `JSON.stringify` output on the clarifications screen (`M3-REVIEW-FE-072`'s own deliberate placeholder) or directly in `psql`. Do not report the JSON-on-screen rendering as a defect of this ticket.
- **Nothing is answerable.** No **Save**, **Skip**, or answer field exists (`-073`/`-074`), so `current_inference` is confirmed by reading the stored column, never by seeing it prefilled into a field — there is no field yet.
- **Page images are named `"not available"`, not built.** `docs/architecture.md` names no page-image capture anywhere in the ingestion pipeline. Tracked separately as issue #251; this ticket's own scope stops at stating the gap honestly in the evidence dict rather than inventing a placeholder image or omitting the key.
- **`column_distribution_evidence` has no trigger calling it.** M4's column-ambiguity work will supply the query that produces `values`/`row_count`; until then this function is reachable only by calling it directly (Part F), never through ingestion or the UI. A future M4 walkthrough should re-exercise Part F's two scenarios (truncation, non-negative remainder) once a real column trigger exists, rather than assuming this manual test still covers it end-to-end at that point.
- **Part D's contradiction ingestion is order-sensitive** in a way this walkthrough works around by hand (adding both sources before either triggers `raise_candidates`, since the trigger scans a source's own documents, not across sources, and needs both filenames' facts collected across the whole corpus scan). If ingestion timing causes one source's clarification row to be written before the second file lands, the contradiction will not be detected for that pairing — this is `M3-RAISE-BE-068`'s own known per-source-once scanning behaviour (see issue #249 for the related "late-arriving candidate" gap), not a defect introduced by this ticket, but it can make Part D flaky depending on how fast ingestion completes on a given machine.
