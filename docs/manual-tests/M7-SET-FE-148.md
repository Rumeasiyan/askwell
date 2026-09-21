# Manual test — M7-SET-FE-148, Settings: storage

**Ticket:** `M7-SET-FE-148` — the storage section of Settings: per-source index size, the log
budget with current use and adjustment, the interaction retention window, an export-and-prune
entry point, and the at-the-limit statement.
**Version under test:** `0.6.3`.
**Time:** about 20 minutes.
**Who can run it:** anyone who can open a browser and a terminal (one step needs
`scripts/dev.sh psql` to change how much is on disk to look at — see "Known gaps").

**What is being checked.** `web/components/settings/storage.tsx` and `web/lib/storage.ts`
against `GET /sources/storage`, `GET`/`POST /log-budget`, and `GET`/`POST /log-budget/retention`
(`api/src/askwell/sources.py`, `api/src/askwell/log_budget.py`). Export and prune themselves are
out of scope for this ticket (`M7-LOG-BE-155`, `M7-LOG-BE-154`) — this only checks that a stated
entry point exists.

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

---

## Part A — cold start, reaching the storage section by clicking

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads. The left rail shows **Ask**, **Library**, and **Settings**
among its entries.

### 2. Add a source, so there is something to show a size for

Click **Library** in the left rail, then **Add a source**. Under **Files**, click **Choose
files**, pick a small text or PDF file from this machine, and answer the folder prompt if
asked.

**Expect:** the file is accepted and a card appears naming it queued for background ingestion.
Wait roughly 30 seconds, then click **Library** again — the source should now show a status
other than "queued" (e.g. "ready").

### 3. Ask a question, so the interaction log has something in it

Click **Ask** in the left rail, type any question, and send it.

**Expect:** Askwell answers or abstains as normal. This is what the log-budget "current use"
figure in the next part will reflect.

### 4. Open Settings

Click **Settings** in the left rail.

**Expect:** the Settings page loads with headings including **Hardware profile**,
**Retrieval threshold**, and — scrolled further down — **Storage**. Scroll to **Storage**.

---

## Part B — the five displays

### 5. Index size per source

Under **Storage**, read the **Index size per source** table.

**Expect:** a row for the source added in step 2, showing its name, kind (`file`), and a size
in bytes/KB/MB (not "Unknown", not "0 B" — the file has content). A note below the table
explains the figure is approximate for the vector index and that a connection, dump, or a
still-indexing source shows "Unknown" rather than zero.

### 6. Log storage budget: current use

Read the **Log storage budget** block.

**Expect:** a line reading "Current use: `<some size>` of `<some size>`" — the used figure
should be small but nonzero (the interaction from step 3 has been written). No "approaching the
limit" or "at the limit" wording, since a fresh install is far under 80%.

### 7. Adjust the log budget

In the **GB** input next to **Log storage budget**, clear it and type `0.001`, then click
**Change budget**.

**Expect:** a confirmation line appears: "Budget changed to `<figure>`." followed by either
nothing more, or — since 1 MB is almost certainly below 5% of this machine's free disk — no
free-disk-cap sentence (that only shows when the 5% ceiling is what actually won). Because
current use from steps 2–3 is very likely already over 1 MB, the confirmation should also state
the immediate consequence: "Current use is already at or over that — export or prune to bring
it back under budget." The **Current use** line above updates to show the same small budget,
and the stage wording changes to "— at the limit."

**This is the ticket's own edge case: reducing the budget below current use.** Confirm both the
consequence sentence and the stage change appeared — that is the whole check.

### 8. Interaction retention window

Read the **Interaction retention window** block.

**Expect:** "Current window: 12 months" (the shipped default, unless a previous test run on
this machine changed it). Type `6` in the months field and click **Change retention window**.

**Expect:** a confirmation: "Retention window changed from 12 to 6 months. Recorded in the
decisions log. Askwell does not yet prune interactions past this window — that arrives with a
later ticket." The **Current window** line updates to 6.

### 9. Export and prune

Read the **Export and prune** block.

**Expect:** a disabled button labelled **Export and prune**, with text above it stating this
archives the interaction log then prunes what was archived, and that it is "Not built yet —
this is where it will be reached from once it is." Clicking the button does nothing (it is
`disabled`).

### 10. What happens at the limit

Read the box below **Export and prune**, headed **At the limit**.

**Expect:** it is always visible (not conditional on actually being at the limit) and states:
"Ingestion stops first — new material is refused until space is freed. Asking questions keeps
working." This matches step 7's stage change: ingestion, not asking, is what the limit affects.

---

## Part C — the free-disk-cap explanation (issue 484 case)

### 11. Force the 5%-of-free-disk ceiling to be the binding one

Reload Settings, scroll to **Storage**, and in the **Log storage budget** input type a large
number — `999999` (999 TB) — and click **Change budget**.

**Expect:** the confirmation and the line below **Current use** both now show a sentence
starting "You set 999.0 TB, but the effective budget is capped at `<some much smaller figure>`
— 5% of current free disk (`<some figure>`)." — the 5%-of-free-disk clause explained, not just a
number that silently refuses to match what was typed.

### 12. Restore a sane budget

Type `2` in the GB field and click **Change budget** again.

**Expect:** confirmation shows "Budget changed to 2.0 GB." with no free-disk-cap sentence
(2 GB is comfortably under 5% of free disk on any reasonable machine), and **Current use**
returns to showing "ok" stage wording rather than "at the limit".

---

## Part D — a source whose size cannot be computed

### 13. Add a database connection or dump, if one is available

If a Postgres dump file or a reachable database is at hand, add it via **Library → Add a
source → Connect a database** (or **Import a dump**). If none is at hand, skip to step 14 and
note this in the report — it is an acceptable gap for this run, not a defect.

**Expect:** back in **Settings → Storage**, the new row's index size reads **Unknown**, not
`0 B` — the ticket's own edge case for a source whose size cannot be computed.

### 14. Confirm the case is at least true by reading the response directly

```
curl -s localhost:8000/sources/storage | python3 -m json.tool
```

**Expect:** any row with `"kind": "connection"` or `"kind": "dump"`, or `"status": "queued"` /
`"status": "indexing"`, shows `"index_bytes": null` — confirms `Unknown` in the table (step 13)
comes from the same `null` this endpoint returns, not from the frontend inventing the word for
a zero.

---

## Cleanup

```
curl -s -X POST localhost:8000/log-budget -H 'content-type: application/json' \
  -d '{"budget_bytes": 2147483648}'
curl -s -X POST localhost:8000/log-budget/retention -H 'content-type: application/json' \
  -d '{"months": 12}'
```

**Expect:** both return `200` with the shipped defaults, leaving the stack in its normal state
for whoever uses it next.

---

## What was checked against the ticket's acceptance criteria

- Index size shown per source — Part B, step 5; unknown-for-connection/dump/queued —
  Part D.
- Log budget shown with current use, adjustable — Part B, steps 6–7.
- Retention window can be changed — Part B, step 8.
- Export and prune reachable — Part B, step 9 (as a stated, disabled entry point; the backend
  does not exist yet).
- At-the-limit statement, said before it happens — Part B, step 10 (always visible, not gated
  on actually being at the limit).
- Free disk changing moves the effective budget, recalculated and explained — Part C.
- Reducing the budget below current use: accepted, consequence stated, prune offered — Part B,
  step 7 (prune is "offered" only in the sense of being named in the consequence sentence and
  pointed at the disabled Export and prune button — there is no working prune to actually
  click, per Known gaps).
- A source whose size cannot be computed reads "Unknown", never zero — Part D.
- Decisions and memory are never pruned at any budget — not separately exercised here; reading
  `api/src/askwell/log_budget.py::measure` confirms it only ever reads the interactions table
  and the trace ring buffer, never `audit_decisions` or `memory`.

## Known gaps

Do not report these as defects — they are out of scope for this ticket or not practical to
exercise on every run:

- **Export and prune do nothing when clicked** — the button is `disabled` by design.
  `M7-LOG-BE-155` (export) and `M7-LOG-BE-154` (prune) are not built yet, and this ticket's own
  Out of Scope line says so.
- **The retention window changing does not prune anything.** Setting it to 6 months in step 8
  does not delete any interaction older than 6 months — the confirmation text says this
  explicitly, and there is nothing further to check here until `M7-LOG-BE-154` exists.
- **Part D needs a real database connection or dump file to exercise fully.** Step 14's direct
  API check is a substitute when neither is at hand, but does not exercise the settings screen
  rendering an actual "Unknown" row end-to-end.
- **Filling a real disk to move the 5% ceiling from the free-disk side (rather than by setting
  a huge configured value) was not tried** — destructive on a shared development machine.
  Reading `measure()` shows both paths recompute the same
  `effective_budget = min(configured, free_disk * 5%)` fresh on every call, so no separate
  behaviour exists to test differently, but a genuinely full disk was not observed directly.
- **Exact byte figures were not asserted precisely** — `storage_by_source`'s own docstring
  states the figure omits index structures and row/page overhead and is a deliberate
  approximation, not a bug to chase down.
