# Manual test — M3-REVIEW-FE-075, clarification screen states: none pending, capped, re-processing

**Ticket:** `M3-REVIEW-FE-075` — the clarifications screen's remaining states beyond a plain pending list: none pending (teaches the feature), ingestion still running (questions appear as raised, source already queryable), all answered (a brief completion state naming what improved), answered-and-re-processing (per-item progress, with failure and retry), and capped (honest about what was not asked, routes to Memory). `docs/ux/clarifications.md` §5 in full.
**Version under test:** `0.3.15`
**Time:** about 60 minutes, plus a first stack build and native inference startup if not already running.
**Who can run it:** a browser, a terminal, and `psql` access via `scripts/dev.sh psql` (used to seed material quickly and to force a re-processing failure that is otherwise slow to hit by chance — never to fake anything the screen itself renders).

**What is being checked.** `web/components/clarifications/clarifications-screen.tsx` (the empty/capped/completion branches, `maybeShowCompletion`, `SourceGroup`'s "still indexing" note), `web/components/clarifications/reapply-progress.tsx` (per-item progress, failure, retry), the pure logic in `web/lib/clarifications.ts` (`completionSentence`, `cappedSentence`, `NONE_PENDING_COPY`), and the backend it reads: `api/src/askwell/review.py` (`_capped_counts`, `list_pending`'s `cap` and `capped` fields, `answer_clarification`'s `reapply_job_id`) and `api/src/askwell/reapply.py` (`get_job`, `retry_failed`).

**Where the previous tickets left off.** `M3-REVIEW-FE-072` built the plain list and its two entry points. `-073` built one question's anatomy. `-074` wired Save/Skip/Skip-all/Undo, and named two gaps this ticket closes: no completion state, and no capped banner once a source's queue empties (issue #297). This ticket also closes #299 (a re-processing failure with no visible reason) and #300 (a reprocessing count that only ever said "documents").

---

## Before you start

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

If you have never run Askwell before, copy the env file and point `ASKWELL_ROOTS_MOUNT` at the folder above (with your own absolute path), and set `POSTGRES_APP_PASSWORD` to any word if it is blank — same as every previous manual test in this directory. If the stack is already running from a prior session, skip straight to **Cold start**, step 6.

---

## Cold start

### 1. Bring the stack up

```bash
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started.

### 2. Migrate

```bash
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 3. Start native inference, on the host, in its own terminal

```bash
scripts/dev.sh inference
```

Wait for it to report the embedding role `ready`.

### 4. Open the app

Open `http://127.0.0.1:8000` in a browser.

**You should see:** the Askwell shell, no sign-in prompt. The left rail shows **Ask**, **Library**, **Clarifications**, **Memory**, **Settings**.

### 5. Nominate the test folder

Click **Settings**, scroll to **Folders Askwell may read**, type the absolute path to `askwell-test-material`, click **Nominate**.

**You should see:** the path appears, marked **Readable**.

### 6. Clear out any clarifications left over from earlier testing

```bash
scripts/dev.sh psql -c "DELETE FROM reapply_items; DELETE FROM reapply_jobs; DELETE FROM clarifications; DELETE FROM audit_decisions WHERE kind LIKE 'clarification%';"
```

**You should see:** `DELETE` lines with no error. (This does not touch `sources`, `documents` or `memory` — only the clarification/reapply state this walkthrough is about.)

### 7. Click Clarifications with nothing pending

Click **Clarifications** in the left rail.

**You should see:** the heading **Clarifications** with no count line beneath it, and one block of text:

> Nothing to clarify. Askwell asks when it finds something it can't work out — an unlabelled column, a date format, two documents that disagree.

This is `docs/ux/clarifications.md` §5's "None pending" state. It is not "no items" — it names what the feature is for, to someone who has never met it. No badge next to **Clarifications** in the rail.

---

## Part A — pending, capped, and "still indexing" together

### 8. Write a source with more candidates than the cap

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/many", exist_ok=True)
letters = "ABCDEFGHIJ"
lines = []
for index, letter in enumerate(letters):
    token = letter * 5
    occurrences = index + 2
    lines.append(" ".join(f"The {token} applies here." for _ in range(occurrences)))
with open("/app/askwell-test-material/many/abbrevs.txt", "w") as f:
    f.write("\n".join(lines) + "\n")
print("done")
PY
```

**You should see:** the script print `done`. Ten fresh five-letter tokens, each occurring at least twice — ten abbreviation candidates from one source, against a cap of 5.

### 9. Add it as a source

Click **Ask**, click **Add a source**, point it at `.../askwell-test-material/many`, click **Add it**. Wait for it to settle — no red error text, the card stops showing progress.

### 10. Open Clarifications

Click **Clarifications** in the left rail (or wait up to 10 seconds and watch the badge appear on its own, then click).

**You should see:** a **many** group with a count reading **5 questions** (the cap, `docs/ux/clarifications.md`'s own rule — five asked, not ten), and directly below the five item cards, a banner:

> Asking about the 5 that matter most. Askwell inferred the rest — you can review them in Memory.

with a **Review in Memory** link. Click it.

**You should see:** the browser navigates to `/memory/` and back is available with the browser's own back button — Clarifications is not a dead end.

### 11. Grow the same source while it still has pending items — "still indexing"

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/many/extra.txt", "w") as f:
    f.write("This file exists only to make the source ingest again.\n" * 50)
print("done")
PY
```

Go back to **Ask**, click **Add a source** again, point it at the same `.../askwell-test-material/many` folder, click **Add it** — this re-scans the folder and picks up `extra.txt`, so `many`'s outstanding ingestion count goes above zero again while its five earlier clarifications are still sitting there unanswered.

Immediately click **Clarifications** (within the few seconds it takes the new file to embed).

**You should see:** the **many** group, its five items still there, with a line above or beside them reading:

> Still indexing this source — already searchable.

If you miss the window (ingestion here is small and finishes in a few seconds), repeat step 11 with a larger `extra.txt` — the point is that the note appears at all while `many` has outstanding work, not that it stays up any particular length of time. Confirm you can still act on the five items while this note is showing — the note is informational only, `docs/ux/clarifications.md` §6, "never block".

---

## Part B — answering, the completion state, and re-processing progress

### 12. Answer everything in `many`

For each of the five items in the **many** group, either click **Save** (the field is pre-filled with Askwell's own guess) or click **Skip**, until the group is empty. Do this quickly enough that you do not wait out any individual item's 10-second undo window before moving to the next.

**You should see:** each item leaves the list ten seconds after a save (or about a second after a skip), same as `M3-REVIEW-FE-074`'s own behaviour — nothing new here.

### 13. The completion state, once the last item clears

**You should see:** the moment the last `many` item leaves the list, the empty-state area shows a one-line completion instead of the plain "Nothing to clarify" text — something like:

> 3 answered, 2 skipped. 5 documents re-read.

(the exact counts depend on how you split step 12 between Save and Skip; the wording always leads with a digit and never congratulates on an all-skipped batch — see step 15). Time it: about 6 seconds after it appears, it hands back on its own to the plain "Nothing to clarify…" text, with no click needed.

### 14. A question raised after the completion state does not reset it jarringly

Before the 6-second window in step 13 elapses, add one more small source (any one-line `.txt` file with a fresh all-caps token in a new folder under `askwell-test-material`) so a new clarification lands while the completion banner is still up.

**You should see:** the completion line is not abruptly replaced or reset — either it keeps showing until its own timer expires and then the new pending item appears, or the new item is folded in without a flash of the "Nothing to clarify" text in between. What must **not** happen: the completion banner vanishing early to show "Nothing to clarify" for a moment before the new item pops in.

### 15. An all-skipped batch is not congratulated

Repeat steps 8–10 with a fresh folder name (e.g. `many2`, same script contents) to get another 5-item group, then **Skip** all five without saving any.

**You should see:** the completion line reads honestly, e.g. **"5 skipped. Nothing re-read."** — never a congratulatory line implying something was accomplished, per this ticket's own named Edge Case.

---

## Part C — per-item re-processing progress, failure, and retry

`askwell.reapply` resolves real chunks to re-embed from an answer's evidence, which — on this small test material — mostly resolves to nothing to re-process (`reapply_job_id` is `null`, no progress card opens). To exercise the progress card, its failure state, and Retry without depending on exactly which evidence shapes happen to name real chunks, seed one job and one failed item directly, the same way `M3-REVIEW-FE-074`'s own manual test seeds clarification rows to have something concrete to act on.

### 16. Seed a running job with one item

```bash
scripts/dev.sh psql <<'SQL'
INSERT INTO sources (id, kind, name, status, added_at)
VALUES ('55555555-5555-5555-5555-555555555555', 'file', 'progress-demo', 'ready', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO reapply_jobs (id, subject, source_id, status, total_items, done_items, failed_items)
VALUES ('66666666-6666-6666-6666-666666666666', 'demo.subject',
        '55555555-5555-5555-5555-555555555555', 'running', 2, 0, 0);

INSERT INTO reapply_items (id, job_id, kind, target_id, label, status)
VALUES ('77777777-7777-7777-7777-777777777771', '66666666-6666-6666-6666-666666666666',
        'chunk', gen_random_uuid(), 'progress-demo.pdf, page 1', 'pending'),
       ('77777777-7777-7777-7777-777777777772', '66666666-6666-6666-6666-666666666666',
        'chunk', gen_random_uuid(), 'progress-demo.pdf, page 2', 'pending');
SQL
```

Answer any one still-pending clarification on screen (from an earlier part, or seed a fresh one) but — rather than relying on the answer to open this exact job — confirm the card renders by hitting the endpoint the component itself polls:

```bash
curl -s http://127.0.0.1:8000/reapply-jobs/66666666-6666-6666-6666-666666666666 | head -c 400
```

**You should see:** JSON with `"status":"running"`, `"total_items":2`, `"done_items":0`. This confirms what `ReapplyProgress` itself will render once it is given this job id — the component under test has no seam that lets a manual test mount it standing alone without a real answer opening it, so the next steps drive it the way the app does: through a real save.

### 17. Drive the progress card through a real save, then force its job to fail

Add one more small source (a fresh `.txt` file, fresh token), open **Clarifications**, and **Save** one item.

**You should see:** immediately below the item list (or wherever `reapplyJobs` renders — a small card, separate from the item that was just answered), a line:

> Re-reading `<subject>` — 0 of `<n>` done. The source stays searchable.

Note the job id shown in the network response for that save (`POST /clarifications/{id}/answer`'s `reapply_job_id` — open the browser's network tab, or watch `scripts/dev.sh psql -c "SELECT id, status FROM reapply_jobs ORDER BY created_at DESC LIMIT 1;"` for the newest row) and force it to fail:

```bash
scripts/dev.sh psql -c "
UPDATE reapply_items SET status = 'failed', error = 'embedding model unreachable', attempts = 1
WHERE job_id = (SELECT id FROM reapply_jobs ORDER BY created_at DESC LIMIT 1);
UPDATE reapply_jobs SET status = 'failed', failed_items = total_items, finished_at = now()
WHERE id = (SELECT id FROM reapply_jobs ORDER BY created_at DESC LIMIT 1);
"
```

Within 2 seconds (the poll interval), without reloading the page:

**You should see:** the progress card updates on its own to:

> Stopped, not stuck: embedding model unreachable.

with a **Retry** button — never a progress indicator stuck at "0 of N done" forever. This is issue #299's own named edge case.

### 18. Retry clears the failure and the card eventually disappears

Click **Retry**.

**You should see:** the button disables itself briefly, the failure line and Retry button go away, and the card returns to showing "Re-reading … — 0 of N done."

```bash
scripts/dev.sh psql -c "SELECT status, failed_items FROM reapply_items ji JOIN reapply_jobs j ON j.id = ji.job_id ORDER BY j.created_at DESC LIMIT 1;"
```

Now let the job actually finish (there is no real worker action to re-run here since the material seeded in step 16 does not correspond to real chunks; the app's own worker will pick up the retried job and, finding nothing real to do for a demo target id, will most likely fail it again on the next attempt — that is expected for this seeded scenario, not a defect). Confirm instead, directly:

```bash
scripts/dev.sh psql -c "
UPDATE reapply_items SET status = 'done', done_at = now()
WHERE job_id = (SELECT id FROM reapply_jobs ORDER BY created_at DESC LIMIT 1);
UPDATE reapply_jobs SET status = 'done', done_items = total_items, finished_at = now()
WHERE id = (SELECT id FROM reapply_jobs ORDER BY created_at DESC LIMIT 1);
"
```

**You should see:** within 2 seconds, the progress card disappears from the screen entirely — `ReapplyProgress`'s `onDone` callback fires once `status` reaches `"done"`, and `ClarificationsScreen` drops it from `reapplyJobs`. Confirm the source itself was queryable the whole time this card was up: switch to **Ask** and ask any question — nothing about the pending re-processing job blocks a normal answer.

---

## Known gaps

- **Genuine re-processing failures are not exercised end-to-end.** `askwell.reapply`'s worker resolves real dependencies (chunks, schema notes, conflicts) from an answer's own evidence; on the small material this walkthrough creates, most answers resolve to no real work (`reapply_job_id` is `null`) rather than a job with items that could fail naturally. Steps 16–18 force a failure directly in the database to exercise the UI, which is legitimate for what this ticket owns (the screen's reaction to a failed job) but does not prove the worker itself produces a realistic `error` string for a real embedding failure — that is `M3-APPLY-ING-080`'s own territory, already shipped, not re-verified here.
- **Ranking reasons are not shown**, named in the ticket's own Testing Notes as a known gap — the capped banner names a count, not which candidates were chosen over which.
- **The inline-in-conversation clarification state is out of scope here** (`M3-INLINE-FE-085`) and not reachable through this screen.
- **The "still indexing" window in step 11 is small and timing-dependent** on this test material — a production source with real documents gives a longer, easier-to-observe window; this is a property of the test material, not the feature.
