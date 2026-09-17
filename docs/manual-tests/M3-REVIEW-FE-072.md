# Manual test — M3-REVIEW-FE-072, the clarifications screen as a single reviewable list

**Ticket:** `M3-REVIEW-FE-072` — `/clarifications` shows every pending question as one list, grouped by source, newest source first, with a count per group and a total at the top. Not a wizard, not a modal queue. Two entry points: the count badge in the left rail, and a one-line prompt after ingestion finishes. Answering and skipping are out of scope (`-073`, `-074`) — this ticket is the list and its two doors in.
**Version under test:** `0.3.5`
**Time:** about 60–75 minutes, plus a first stack build and native inference startup.
**Who can run it:** a browser, a terminal, and `psql` access via `scripts/dev.sh psql` (used only to confirm what the screen is reading, never to drive the UI itself).

**What is being checked.** `web/app/clarifications/page.tsx` renders `ClarificationsScreen` (`web/components/clarifications/clarifications-screen.tsx`), which calls `GET /clarifications` (`M3-REVIEW-BE-072a`, unchanged by this ticket) and folds the response into grouped cards with a per-group count and a total line. `web/components/shell/rail.tsx` polls the same endpoint every 10 seconds (`useClarificationsTotal`) and shows a plain count badge next to **Clarifications**, hidden entirely at zero. `web/components/shell/clarifications-prompt.tsx` watches `subscribeIngest` for the queue going from active to idle while mounted, and shows a dismissible one-line banner naming the pending total, once per idle transition.

**Where this stops on purpose.** No item is answerable yet — no **Save**, no **Skip**, no inline text field. `docs/ux/clarifications.md` §3's full item anatomy (evidence formatting, inference marker, answer field) is `M3-REVIEW-FE-073`; the actions are `-074`. This walkthrough confirms the list, its counts, its two entry points, and that it never blocks anything — not what a click on an item does, because nothing here reacts to one yet.

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

**You should see:** lint, format, typecheck and test stages finish without red error text.

```
scripts/dev.sh web-check
```

**You should see:** lint, typecheck, the test suite (including `clarifications.test.ts`), build, contrast and offline checks all finish without red error text.

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

### 6. Open the app

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell load with no sign-in prompt. The left rail shows **Ask**, **Library**, **Clarifications**, **Memory**, **Settings**, with no badge next to **Clarifications** — nothing is pending yet.

### 7. Nominate the test folder

Click **Settings** in the left rail, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — nothing pending: the teaching empty state

### 8. Click Clarifications before anything has been added

Click **Clarifications** in the left rail.

**You should see:** the address bar end in `/clarifications/`, a heading **Clarifications** with no count line beneath it (there is nothing to count), and a single block of text reading:

> Nothing to clarify. Askwell asks when it finds something it can't work out — an unlabelled column, a date format, two documents that disagree.

This is `docs/ux/clarifications.md` §5's "None pending" state — it must not say something bare like "no items", and it must teach what the feature does to someone who has never seen it fire. Confirm there is no modal, no spinner stuck mid-load, and the rest of the app (the **Ask** composer, the rail) is fully usable while this is on screen.

---

## Part B — one source, one question: grouping, counts, the two entry points

### 9. Write a file that raises exactly one clarification

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/contracts", exist_ok=True)
with open("/app/askwell-test-material/contracts/agreement.txt", "w") as f:
    f.write("The SLA applies to all vendors. The SLA renews annually. The SLA covers uptime.\n")
print("done")
PY
```

**You should see:** the script print `done`. `SLA` is an all-caps token appearing three times, not in Askwell's common-abbreviation stoplist (`PDF`, `USA`, and similar) and not already in memory — the abbreviation trigger fires for it.

### 10. Add the folder as a source, by clicking through the app

Click **Ask** in the left rail.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**, point it at `.../askwell-test-material/contracts`, and click **Add it**. Wait for it to settle (no red error text; the card stops showing progress).

### 11. Watch the badge appear in the rail without reloading the page

Stay on whatever screen you land on after step 10, and watch the left rail for up to ten seconds (`useClarificationsTotal` polls every 10s).

**You should see:** a plain number badge appear next to **Clarifications** — `1`. It sits in the same ink as the rest of the rail text, not red, not a dot — `docs/ux/clarifications.md` §6's "never an alarm" rule.

### 12. Watch the ingestion-finished prompt appear

If you are not still on the page you were on right after adding the source, add a second, throwaway source now (any small `.txt` file in a new folder) so ingestion transitions from active to idle while you are watching — the prompt only fires on that transition while mounted, not on a page load onto an already-idle queue.

**You should see:** a one-line dismissible banner appear below the top status bar, reading something like:

> 1 question came up while adding sources.

with a **Review** link and a **Dismiss** button. Confirm it is not a modal — the rest of the page is still visible and clickable behind it, and you did not have to act on it to keep using the app.

### 13. Dismiss the prompt and confirm it stays gone

Click **Dismiss**.

**You should see:** the banner disappear immediately. Reload the page.

**You should see:** the banner does not reappear — `docs/ux/clarifications.md` §6's "never nag": a page load onto an already-idle queue with old pending questions does not re-trigger it. (The rail badge, checked next, is the durable signal — that is what it is for.)

### 14. Open the clarifications screen from the rail badge

Click **Clarifications** in the left rail.

**You should see:** the address bar end in `/clarifications/`, the heading **Clarifications**, and directly beneath it a total line reading `1 question pending`. Below that, one group:

- A heading with the source name (the `contracts` folder's source name, however the source list names it).
- A count next to it reading `1 question`.
- One card for the `SLA` item: a mono subject line reading `SLA`, a serif question sentence (`'SLA' appears throughout. What does it mean?`), and a line of evidence text beneath it (currently raw JSON, e.g. `{"occurrences":3}` — see **Known gaps**).

Confirm there is no **Save**, no **Skip**, no text field on the card — none is built yet — and confirm you reached the item without navigating anywhere past this one screen.

---

## Part C — several sources: newest first, correct counts, a real total

### 15. Write and add two more sources, each with its own clarification

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/invoices", exist_ok=True)
os.makedirs("/app/askwell-test-material/memo", exist_ok=True)
with open("/app/askwell-test-material/invoices/statement.txt", "w") as f:
    f.write("The PO covers Q1 spend. The PO was approved. The PO number is on file.\n")
with open("/app/askwell-test-material/memo/note.txt", "w") as f:
    f.write("The MOU applies here. The MOU was signed. The MOU expires next year.\n")
print("done")
PY
```

**You should see:** the script print `done`.

Click **Add a source** and add `.../askwell-test-material/invoices`, wait for it to settle, then click **Add a source** again and add `.../askwell-test-material/memo`, and wait for that to settle too.

### 16. Confirm the total and the order on the clarifications screen

Click **Clarifications** in the left rail.

**You should see:** the total line now reads `3 questions pending`, and the rail badge (visible in the background) reads `3`. Three groups appear, **newest source first**: `memo` at the top (added last), then `invoices`, then `contracts` at the bottom. Each group heading shows its own count (`1 question` for each), and each shows its own item — `MOU`, `PO`, `SLA` respectively.

### 17. Confirm nothing is lost navigating away and back

Click **Ask** in the left rail, then click **Clarifications** again.

**You should see:** the same three groups, same order, same counts — nothing reset, nothing re-ordered, and no loading flicker that drops a group. This is the list re-fetching from the server each time you arrive, not client state that could go stale or be lost.

### 18. Confirm asking a question is never blocked by any of this

Click **Ask** in the left rail and ask any question about the material you have added (for example, "What does the agreement cover?").

**You should see:** a normal answer stream back, citations in the provenance margin, and no prompt, redirect, or interruption referencing the clarifications queue at any point. `docs/ux/clarifications.md` §6: never block on asking a question.

---

## Part D — a very long list stays navigable

### 19. Write a file with ten abbreviations, so one source produces many candidates

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

**You should see:** the script print `done`. Ten fresh five-letter tokens (`AAAAA` … `JJJJJ`), each occurring at least twice.

### 20. Add it, then reopen the clarifications screen

Add `.../askwell-test-material/many` the same way as step 10, wait for it to settle, then click **Clarifications**.

**You should see:** the `many` group at the top, its own count reading `5 questions` — `M3-RAISE-BE-069`'s cap of five per source, applied before this screen ever sees the rest — not ten. The total line now reads `8 questions pending` (5 from `many` + one each from `memo`, `invoices`, `contracts`). The group is a plain list under one heading, not paginated, not collapsed — confirm you can see all five of its items by scrolling the page normally, with no separate control needed to reveal them.

---

## Part E — what the screen is actually reading (confirms grouping is server-side, not reordered by the browser)

### 21. Compare the API response to what rendered

```bash
scripts/dev.sh psql
```

```sql
SELECT s.name, s.added_at, c.subject FROM clarifications c
JOIN sources s ON s.id = c.source_id
WHERE c.status = 'pending'
ORDER BY s.added_at DESC, c.rank ASC NULLS LAST, c.asked_at ASC;
```

**You should see:** rows in the same source order the screen showed in step 20 (`many`, `memo`, `invoices`, `contracts`), confirming the screen trusts the server's order rather than re-sorting anything itself.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No item is answerable.** No **Save**, **Skip**, answer field, or the confirmation-after-saving copy (`docs/ux/clarifications.md` §4) exist yet — `M3-REVIEW-FE-073` (item anatomy) and `-074` (the actions) are out of scope for this ticket. Do not report a missing **Save** button as a defect of this ticket.
- **Evidence renders as raw JSON**, e.g. `{"occurrences":3}`, instead of the value-distribution/passage formatting `docs/ux/clarifications.md` §3 describes. This is deliberate — `-073`'s own "item anatomy" scope — and the code comment in `clarifications-screen.tsx` names it explicitly so it is not mistaken for an oversight.
- **The "capped" copy is not shown.** `docs/ux/clarifications.md` §5's capped-state sentence ("Asking about the 5 that matter most...") is not rendered anywhere on this screen — Part D's ten-candidate source shows only the five that were actually asked, with no note that five more were inferred. Confirm this gap exists rather than reporting it fresh; it is not tracked separately as of this version and may be worth its own issue if it is still missing when `-073`/`-074` land.
- **The inline-blocking entry point is not exercised.** `docs/ux/clarifications.md`'s third entry point — a question blocking an answer, rendered inline in the conversation (`ask.md` §5) — is separate scoped work (`M3-INLINE-FE-085`) and not reachable through this screen.
- **"Ingestion still running" mid-open is not exercised.** `docs/ux/clarifications.md` §5 describes new questions appearing on this screen while ingestion for another source is still in progress, without disrupting an in-progress answer. Since nothing here is answerable yet, there is no in-progress answer to disrupt, and the walkthrough does not attempt to add a source while `/clarifications/` is already open and watch a group appear live — the screen has no live-update mechanism (it fetches once per mount), so a group added mid-visit will not appear until the page is revisited. Worth re-checking once `-073`/`-074` make "mid-answer" a real state.
- **Skip-all-for-a-source and undo are not exercised**, by design — both are `-074`'s own actions.
