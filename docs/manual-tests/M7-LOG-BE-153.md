# Manual test — M7-LOG-BE-153, log storage budget with staged degradation

**Ticket:** `M7-LOG-BE-153` — a budget measured across the interaction store and trace
buffer, a notice at 80%, ingestion refused (not asking) at the hard limit, and only a
decisions-store write failure ever fails an action.
**Version under test:** `0.6.2`.
**Time:** about 20 minutes.
**Who can run it:** anyone who can open a browser and a terminal. Changing the budget and
simulating a decisions-store failure need `scripts/dev.sh psql`/`curl` — see "Known gaps" for
why those two steps cannot be done by clicking.

**What is being checked.** `api/src/askwell/log_budget.py` (`GET`/`POST /log-budget`,
`enforce_ingestion_allowed`) and its three call sites in `api/src/askwell/sources.py`
(`POST /sources`, `/sources/dump`, `/sources/connection`). This ticket is backend-only: there
is no settings-screen notice yet (that is `M7-SET-FE-148`, confirmed not started by
`docs/BRAIN.md`), so the 80%-notice acceptance criterion is checked at the API only, and the
hard-limit refusal is checked through the real "Add a source" screen, which already renders
whatever error text the API returns.

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

Confirm the budget is at its shipped default before starting, so the steps below are
reproducible:

```
curl -s localhost:8000/log-budget | python3 -m json.tool
```

**Expect:** `"budget_bytes"` at or under `2147483648` (2 GB — smaller if 5% of this machine's
free disk is smaller), `"stage": "ok"`, and `"used_bytes"` far below `"budget_bytes"`.

---

## Part A — cold start, ordinary use is unaffected

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads normally — nothing about it names log storage, because at
the `ok` stage nothing should.

### 2. Add a source normally

Click **Library** in the left rail, then **Add a source**. Under **Files**, click **Choose
files** and pick any small text or PDF file from this machine, then answer the folder prompt
if asked.

**Expect:** the file is accepted and queued — a card appears naming it queued for background
ingestion. This is the baseline: ingestion works when nowhere near the budget.

### 3. Ask a question

Click **Ask** in the left rail, type any question, and send it.

**Expect:** Askwell answers or abstains as it normally would (the corpus is small, so
abstention is likely) — nothing about the response mentions log storage.

---

## Part B — the notice stage (backend only)

`M7-SET-FE-148`, the settings screen this notice belongs on, has not been built. This part
checks the API directly returns what that screen will one day render — it is the only way to
observe this stage today.

### 4. Set a very small budget

```
curl -s -X POST localhost:8000/log-budget -H 'content-type: application/json' \
  -d '{"budget_bytes": 1000000}'
```

**Expect:** a JSON body back with `"budget_bytes": 1000000` (or smaller, if 5% of free disk
on this machine is under a million bytes) and a `"stage"` of either `"notice"` or
`"hard_limit"` — the interaction store and trace buffer created in Parts A already use a
meaningful fraction of a megabyte, so lowering the budget this far should show the notice
immediately without needing to add anything further. This is the ticket's own "budget lowered
below current use" edge case.

### 5. Confirm the change was recorded as a decision

```
scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind = 'log_budget_changed' ORDER BY occurred_at DESC LIMIT 1;"
```

**Expect:** one row, `payload` containing `"previous_bytes"` and `"new_bytes": "1000000"`.

---

## Part C — the hard limit: ingestion refused, asking unaffected

### 6. Push past the hard limit

```
curl -s -X POST localhost:8000/log-budget -H 'content-type: application/json' \
  -d '{"budget_bytes": 1}'
curl -s localhost:8000/log-budget | python3 -m json.tool
```

**Expect:** `"stage": "hard_limit"`.

### 7. Try to add a source through the real screen

Go to **Library → Add a source** (click through the rail — do not type the URL). Under
**Files**, click **Choose files** and pick a different small file than the one used in step 2.

**Expect:** the file is detected as supported and a folder prompt may appear as before, but
after it is answered the batch card shows a note headed **"Askwell is not answering"**
containing text naming the limit — something like *"Log storage is at its limit ... New
ingestion is refused until space is freed — export, archive or prune the log, or free disk
space. Asking questions still works."* No new document is queued for this batch.

### 8. Confirm nothing was written for the refused batch

```
scripts/dev.sh psql -c "SELECT count(*) FROM documents WHERE created_at > now() - interval '2 minutes';"
```

**Expect:** the count matches only the file successfully added in step 2 — the batch refused
in step 7 added nothing, confirming the refusal happens before the transaction commits.

### 9. Confirm asking still works at the hard limit

Click **Ask**, type a question, and send it.

**Expect:** Askwell answers or abstains exactly as in step 3 — no refusal, no error, no
mention of log storage. This is the ticket's headline behaviour: ingestion is the first thing
refused, asking is not touched at all.

---

## Part D — only a decisions-store write failure fails an action

### 10. Revoke the app role's ability to write decisions

```
scripts/dev.sh psql -c "REVOKE INSERT ON audit_decisions FROM askwell_app;"
```

### 11. Try to change a setting through the real screen

Go to **Settings** (click the rail). Under **Retrieval threshold**, change the number and
click **Change threshold**. (This setting, not the log budget itself, is used here because it
is the one settings control this ticket's own scope has a working UI for today — see "Known
gaps" — and it goes through the exact same decisions-record write path `set_budget` uses.)

**Expect:** the control shows an error rather than a confirmation — in this development
environment, the message includes `IngestionRefused` is *not* the error; instead expect
wording naming an unexpected error, and (because `scripts/dev.sh` runs in development) the
underlying exception naming `audit_decisions` or a permission failure. The threshold value
shown does not change.

### 12. Restore the privilege

```
scripts/dev.sh psql -c "GRANT INSERT ON audit_decisions TO askwell_app;"
```

**Expect:** repeating step 11 with a different value now succeeds with a confirmation
message.

---

## Cleanup — restore the real budget

```
curl -s -X POST localhost:8000/log-budget -H 'content-type: application/json' \
  -d '{"budget_bytes": 2147483648}'
```

**Expect:** `"stage": "ok"` again, so the stack is left in its normal state for whoever uses
it next.

---

## What was checked against the ticket's acceptance criteria

- Budget measured across the interaction store and trace buffer, recomputed on every call —
  Part B, step 4 (no restart needed for the lowered budget to take effect).
- 80% notice — Part B, checked at the API only (no settings screen exists yet).
- Hard limit refuses new ingestion with a clear reason, through the real add-source screen —
  Part C, steps 7–8.
- Asking is unaffected at the hard limit — Part C, step 9.
- Budget lowered below current use shows the new stage immediately — Part B, step 4.
- A budget change is a decisions record — Part B, step 5.
- Only a decisions-store write failure fails an action — Part D.
- Decisions and memory are never pruned at any budget — not separately exercised; `measure()`
  never reads or touches `audit_decisions` at all (confirmed by reading
  `api/src/askwell/log_budget.py`), so there is no code path that could prune it.

## Known gaps

Do not report these as defects — they are out of scope for this ticket or not practical to
exercise live:

- **The 80%-notice UI does not exist.** `docs/states-and-edge-cases.md` §1 calls for "a
  persistent dismissible notice offering export, archive or prune"; that is `M7-SET-FE-148`,
  confirmed not started in `docs/BRAIN.md`. Part B checks only that the API returns the
  `notice` stage correctly — there is nothing on screen to click through yet.
- **Changing the log budget itself has no UI.** Every budget change in this document goes
  through `curl` against `POST /log-budget` directly, because no settings control exists to
  do it by clicking. Part D uses the retrieval-threshold control instead, since it is the one
  settings surface today that shares the same decisions-write path.
- **The "disk fills from outside Askwell" edge case is not separately exercised.** Filling a
  real filesystem is destructive and not practical on a shared development machine. Reading
  `measure()` shows this is the same code path as Part B's lowered-budget test —
  `effective_budget = min(configured, free_disk * 5%)` is recomputed fresh every call
  regardless of which side shrank — so no separate behaviour exists to test differently, but
  a genuinely full disk was not tried.
- **Export, archive and prune themselves are not built** — explicitly out of scope for this
  ticket (`M7-LOG-BE-155` and `M7-LOG-BE-154`), so the notice's own offered actions have
  nothing to click even once the notice UI exists.
- **The exact wording shown in Part D, step 11 was not asserted character-for-character**
  against the running dev-mode error response, since the generic exception handler
  (`api/src/askwell/app.py`) is exercised by many other tickets already and its shape is not
  new here.
