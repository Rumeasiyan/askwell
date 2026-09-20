# Manual test — M5-TRACE-FE-119, trace panel over Ask

**Ticket:** `M5-TRACE-FE-119` — the panel opened by "How did you get this?" under an answer
(`web/components/ask/trace-panel.tsx`, `web/lib/trace.ts`). It reads `GET /ask/{message_id}/trace`
(`askwell.ask.ask_trace`, `M5-TRACE-BE-125`) and renders a numbered, top-to-bottom sequence — one
row per step, each with a plain-language summary and a duration, raw detail expandable
underneath (`docs/ux/trace.md` §1–§2). While the turn is still `running`, the panel polls every
second (`POLL_MS` in `trace-panel.tsx`) and stops the moment the fetched trace itself reports
`status !== "running"`.

**Version under test:** check `cat VERSION` (`0.4.36` at the time this document was written;
treat the working tree, not a tag, as what is under test if the two disagree).
**Time:** about 30 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec`/`scripts/dev.sh psql` access,
native `llama.cpp` inference running on the host (`scripts/dev.sh inference`).

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Contents are minimal.** `stepSummary` in `web/lib/trace.ts` renders one line per step kind
  from whatever fields that step already carries (hit count and top score for `retrieve`, row
  count for `sql`, claim/citation counts for `compose`, and so on) — the deeper formatting inside
  a step (per-passage scores, full retrieved text, syntax-highlighted SQL) is `M5-TRACE-FE-120`'s
  scope, out of scope here. Raw detail expands as a plain `JSON.stringify` dump, not a formatted
  view.
- **No interactions beyond open/close/expand.** Clicking a passage to jump to the source viewer,
  clicking a memory fact, copying the trace as text, and adjusting the retrieval threshold from
  an abstention trace (`docs/ux/trace.md` §4) are `M5-TRACE-FE-121`'s scope.
- **No threshold control.** The threshold-in-force line from `docs/ux/trace.md` §3 is not
  rendered by this ticket.
- **A small local model's own choice of tool use and pacing cannot be forced.** Whether a turn
  produces the several distinct step kinds this document exercises (retrieve, sql, tool, compose)
  depends on the model actually calling those tools — the corpus and questions below are built to
  make that likely, with fallback guidance where they might not.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value.

### Make a document corpus with one distinct, quotable fact

```
mkdir -p ~/askwell-test/docs
cat > ~/askwell-test/docs/meridian-agreement.txt <<'EOF'
SUPPLIER AGREEMENT — MERIDIAN CORP — PAYMENT TERMS

Meridian Corp must be paid within 30 days of the invoice date. Contact for
disputes: meridian-ap@example.test. Standard order minimum: $2500.
EOF
```

**You should see:** one `.txt` file in `~/askwell-test/docs`.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note there was nothing to
remove.

### 2. Bring the stack up, migrate, and start native inference

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all reported
created and started; migration finishing with no error.

In a separate terminal, on the host:

```
scripts/dev.sh inference
```

**You should see:** the inference process logging that it is listening on its socket. Leave it
running for the rest of this document.

### 3. Open Askwell as a first-time user

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner, and the first-run empty state on the Ask screen.

### 4. Add the supplier agreement, by clicking

Click **Add a source**. In the **Files** section, click **Choose files** and select
`meridian-agreement.txt`. Answer any folder-nomination prompt by clicking its suggested folder.
**You should see:** the file appears in the batch list and moves to **Indexed** (or **Ready**)
within a few seconds.

### 5. Stand up a database to connect to

Plays the part of a database the user already runs, so a question can plausibly need both a
document and a database — several step kinds in one trace.

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE tracepanel_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d tracepanel_test <<'SQL'
CREATE TABLE payments (
    supplier text not null,
    invoice_date date not null,
    paid_date date not null
);
INSERT INTO payments VALUES
    ('Meridian Corp', '2026-06-01', '2026-07-16');
GRANT CONNECT ON DATABASE tracepanel_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON payments TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 1`, three `GRANT`s.

```
grep ^SANDBOX_READONLY_PASSWORD .env
```

Note the readonly password.

### 6. Connect to it, by clicking

Still on **Add a source**, in the **Connect a database** section: Engine `PostgreSQL`, Host
`sandbox`, Port `5432`, Database `tracepanel_test`, User `askwell_sandbox_readonly`, Password
(from step 5). Click **Connect**.

**You should see:** a queued/ready confirmation naming `tracepanel_test`; the library shows it as
**Ready** after a few seconds.

---

## 1. Cold-start walkthrough — open the trace, read it, expand a step, close it

### 7. Ask a multi-step question

Go to **Ask**. In the composer, type:

```
Using both the agreement and the database, is Meridian Corp actually being paid within the
required 30 days?
```

Click **Ask** (or press Enter).

**You should see:** the question appear above the streaming area, step labels appear under it
while the turn runs, and eventually an answer with citations.

### 8. Open the trace from the toggle under the answer

Once the answer has finished streaming, look directly under it for a button reading **How did
you get this?** (`TraceToggle` in `trace-panel.tsx`).

**You should see:** the button present under every finished turn — clicking it opens a panel
sliding in from the right edge of the window, titled **How did you get this?**, with a **Close**
button in its header and a dimmed overlay behind it covering the rest of the screen.

### 9. Read the numbered steps without technical knowledge

**You should see** a vertical, numbered list of steps, each on its own line, in the order they
happened — for this question, something like:

```
1  Searched your files — N passage(s), top score 0.NN          NNN ms
2  Queried your database — N row(s)                            NNN ms
3  Wrote the answer — N claim(s), N cited                       N.N s
```

Every line should be readable without knowing what an embedding or a `LIMIT` is — "Searched your
files", "Queried your database", "Wrote the answer" are plain descriptions of what happened, not
tool names or jargon. If the model also looked up schema, expect an additional `Looked up schema`
line between the search and query steps.

### 10. Confirm every step shows a duration, always visible

**You should see** a duration (e.g. `340 ms` or `8.2 s`) beside every step whose kind carries
one, positioned at the right edge of its row — never behind an expander, matching the ticket's
own Validation Rule that timings are always visible.

### 11. Expand one step and read the raw detail

Click **show detail** under the first step (`Searched your files`).

**You should see:** the summary line stays exactly where it was; a `<pre>` block of raw JSON
appears directly underneath it, in place, listing the actual step's fields (e.g. `hits`, an array
of passage objects with `score`) — not a separate mode or a new screen, matching the ticket's own
"expandable underneath, not two modes" rule. Clicking **show detail** again collapses it back.

### 12. Close the panel and confirm you are back at the same answer

Click **Close** (or press `Escape`, or click the dimmed overlay).

**You should see:** the panel and overlay disappear; the conversation is exactly as it was before
you opened the trace — same answer text, same citations, same scroll position, with keyboard
focus returned to the **How did you get this?** button you clicked in step 8.

---

## 2. Opening the trace mid-stream

### 13. Ask a broad question likely to run for a while

```
Walk through everything you can find about Meridian Corp — the agreement terms, the actual
payment history in the database, and whether they match — and explain any discrepancy.
```

Click **Ask**, and while the step labels are still changing under the composer (before the
answer starts streaming), click **How did you get this?**.

**You should see:** the toggle is present under a still-running turn too — the panel opens
immediately showing whatever steps have completed so far (possibly none yet, showing "Nothing was
recorded for this turn yet."), and every second or so a new step appears as the turn progresses,
with no need to close and reopen the panel to see it.

### 14. Confirm it stops polling once the turn finishes

Leave the panel open until the answer finishes streaming.

**You should see:** the final `Wrote the answer` step appear in the panel without you touching
anything, and — checking the browser's developer tools Network tab — no further requests to
`/ask/{message_id}/trace` firing once that row is showing (`trace-panel.tsx`'s poll loop stops
once the fetched trace itself reports `status !== "running"`).

---

## 3. Edge cases from the ticket itself

### 15. A step with nothing worth expanding shows no expander

Ask a question the assistant answers by search alone and abstains or answers with one document
step and no tool calls, e.g. immediately after step 14, ask:

```
What is Meridian Corp's order minimum?
```

Open its trace. **You should see:** a `Searched your files` step with no `show detail` control
under it if that step's only fields beyond `kind`, `ms`/`duration_ms`, and `outcome` are already
fully expressed in its summary line (`hasExpandableDetail` in `trace.ts`) — never an expander that
opens onto an empty block.

### 16. A turn with many steps scrolls and stays readable

Hard to force a specific count of 15 from the UI with a small local model choosing its own tool
use. Instead, confirm the scrolling mechanism directly:

- Resize the browser window to a short height (or use developer tools' device toolbar at a small
  height) and open the trace for any answered turn.
- **You should see:** the panel's header (title and Close) and, if you scroll, the step list
  scrolls independently inside the panel body — the header stays pinned and the panel itself
  never grows taller than the viewport (`TracePanel`'s body is `overflow-y-auto` inside a
  `fixed top-0 bottom-0` container in `trace-panel.tsx`).

### 17. Run the unit tests directly against the real summary logic

No model or stack access needed for the row-shaping logic itself.

```
scripts/dev.sh web-run npx vitest run web/lib/trace.test.ts
```

**You should see:** the suite pass, including cases covering `stepSummary` per step kind,
`formatDuration`'s ms/seconds split, and `hasExpandableDetail`'s "nothing left to show" case.

### 18. Confirm a rotated (dropped) trace reads as cleared, not broken

`docs/ux/trace.md` §5: traces are a capped ring buffer, and an old one can be gone while the
answer and its sources remain. Confirm the wording exists for that case:

```
grep -n "trace_rotated" web/components/ask/trace-panel.tsx
```

**You should see:** `TraceBody` returning "The detailed trace for this answer has been cleared.
The answer and its sources are still in your log." whenever `trace.trace_rotated` is true, checked
before the empty-step-list case — so a genuinely rotated trace never reads identically to a turn
that simply recorded nothing.

---

## 4. Clean up

```
podman compose down -v
rm -rf ~/askwell-test
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or a later ticket's scope:

- **Contents are minimal.** Per-passage scores, full retrieved text, syntax-highlighted SQL, the
  threshold in force, memory facts used, injection flags, and tool-ceiling detail
  (`docs/ux/trace.md` §3) are `M5-TRACE-FE-120`'s scope — this ticket's raw-detail expander is a
  plain `JSON.stringify` dump of whatever the step already carries, nothing formatted.
- **No interactions beyond open, close, and expand.** Clicking a passage to jump to the source
  viewer, clicking a memory fact for a correct/delete popover, copying the trace as plain text,
  and adjusting the retrieval threshold from an abstention trace are `M5-TRACE-FE-121`'s scope
  (`docs/ux/trace.md` §4).
- **Fifteen-plus steps in one real trace was not exercised against a live answer** — a small
  local model's own choice of tool use cannot be forced to that count on command. §16 confirms
  the scrolling mechanism directly instead of via a naturally long turn.
- **Whether a real model calls both the document and database tools in the same turn, or runs
  long enough to demonstrate mid-stream polling, is not guaranteed on command** — same caveat
  every prior ticket in this epic (`M5-LOOP-FE-118.md`, etc.) records.
