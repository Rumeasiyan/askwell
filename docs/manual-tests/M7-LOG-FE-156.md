# Manual test — M7-LOG-FE-156, verify the log

**Ticket:** `M7-LOG-FE-156` — a settings action that walks the hash chain in both audit stores
and reports plainly: intact, or broken at a named record with its date. Never describes the log
as immutable.
**Version under test:** `0.7.3`
**Time:** about 20 minutes. Includes one manual database edit to simulate tampering, so you need
a way to run `psql` against the stack (`scripts/dev.sh psql`).

**What is being checked.** `web/components/settings/verify-log.tsx` (the "Verify the log"
action, under Settings → **Your data**), `web/lib/verify.ts` (`GET /log-verify`), and
`api/src/askwell/log_verify.py` (`register_log_verify`, calling `askwell.audit.verify` across
both `audit_decisions` and `audit_interactions`).

**Where this stops on purpose.** Repairing a broken chain is out of scope — it cannot be
repaired, and this ticket does not offer to. The other five actions `docs/ux/settings.md` §6
lists for "Your data" (export everything, export the log alone, delete a source, delete all
memory, reset Askwell) have no backend yet and are not part of this surface — see "Known gaps".

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

---

## Cold start

### 1. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started.
Wait about thirty seconds.

### 2. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 3. Open Askwell and use it for a session

```
http://127.0.0.1:8000
```

**You should see:** the app loads normally — first-run or the composer, depending on whether a
source has been added before. Add a source if none exists yet (a small text file or PDF is
enough) and ask it one question, so both audit stores have at least one record in them: a
decision (the answer you got) and an interaction (the question itself).

### 4. Navigate to Settings by clicking

Use the app's own left-strip navigation to open **Settings**. Do not type `/settings` into the
address bar.

**You should see:** the Settings screen, ending in a **Your data** section with a single button
labelled **Verify the log**, and a paragraph of explanatory copy above it.

### 5. Read the explanatory copy

**You should see:** wording to the effect that Askwell never rewrites or deletes a record after
it is written, that a break means something outside Askwell changed the file, and that the
guarantee is that tampering can be *detected*, not *prevented*. Read the whole section
carefully and confirm the word **"immutable" appears nowhere** on the page — not in this
paragraph, not in a tooltip, not in the button label.

---

## Part A — a clean log verifies intact

### 6. Run verify

Click **Verify the log**.

**You should see:** the button changes to "Checking…" and becomes disabled, a status line reads
"Checking… _N_ s" counting up once per second, and a **Stop** button appears next to it.

### 7. Wait for the result

**You should see:** within a few seconds (this log is tiny), two report cards appear, one
labelled **Decisions** and one labelled **Interactions**. Each reads "chain intact" with a count
of records checked (e.g. "3 records checked."). The card's left border and label are in the
provenance colour, not the alarm colour. The "Checking…" row and Stop button disappear.

### 8. Confirm the run itself is logged

```
scripts/dev.sh psql
```

```sql
SELECT kind, payload->>'decisions_intact', payload->>'interactions_intact'
FROM audit_decisions WHERE kind = 'log_verification_run' ORDER BY occurred_at DESC LIMIT 1;
```

**You should see:** one row, `log_verification_run`, both values `True`. (`\q` to leave psql.)

---

## Part B — stopping mid-check

### 9. Run verify again and immediately press Stop

Click **Verify the log**, then click **Stop** before it finishes (or navigate to a different
settings section and back).

**You should see:** the checking state ends immediately — no report card appears, no error
message, and the button returns to its idle "Verify the log" label. Nothing was written by
starting the check, so stopping it leaves nothing to clean up.

---

## Part C — a broken chain names the record and its date

### 10. Alter a record directly in the database

```
scripts/dev.sh psql
```

```sql
SELECT id, occurred_at FROM audit_interactions ORDER BY occurred_at ASC LIMIT 1;
```

Note the `id` and `occurred_at` of the row returned, then:

```sql
UPDATE audit_interactions SET payload = payload || '{"tampered": true}'::jsonb
WHERE id = '<the id you noted>';
```

`\q` to leave psql.

### 11. Run verify again in the browser

Click **Verify the log**.

**You should see:** the **Interactions** card now reads "chain broken", in the alarm colour, and
names the record: "Breaks at record `<the id you noted>` (`<the date from step 10, formatted>`)."
followed by a detail sentence stating its contents no longer hash to what is stored. The
**Decisions** card still reads "chain intact" — only the store you altered is reported broken.

### 12. Confirm the explanation, not an accusation

**You should see:** the copy above the button (still visible) states that Askwell never
rewrites history and that a break means something *outside* Askwell changed the file — the
broken-chain report itself does not say "tampering" or accuse the user; it states a fact about
the hash and lets the fixed copy above carry the explanation. Confirm again that **"immutable"
still appears nowhere**, including in this broken state.

### 13. Confirm the broken run is also logged

```sql
SELECT payload->>'interactions_reason', payload->>'interactions_broken_record_id'
FROM audit_decisions WHERE kind = 'log_verification_run' ORDER BY occurred_at DESC LIMIT 1;
```

**You should see:** `altered` and the same id from step 10.

---

## Part D — a prune boundary is an explained boundary, not tampering

This part needs `docs/decisions.md`'s prune feature (`log_prune`) to have run at least once, so
a `interactions_pruned` decisions record exists with a real `boundary_hash`. If prune has not
run in your environment, note that this scenario was checked in `api/tests/test_log_verify.py`
(`test_a_prune_boundary_reports_as_an_explained_boundary_not_tampering`, verified passing) and
skip to Part E, recording that this step relied on the automated test rather than a manual
repeat.

If prune has run:

### 14. Verify after a prune

Click **Verify the log**.

**You should see:** the **Interactions** card reads "chain intact", not broken, and a second
line of muted text underneath the "records checked" line explains the chain starts after a
prune rather than at genesis, naming the prune's cutoff date. No alarm colour, no "broken"
language.

---

## Part E — both stores broken

### 15. Restore or re-seed, then break both

Using the same `UPDATE ... SET payload = payload || '{"tampered": true}'::jsonb` pattern from
step 10, alter one row in `audit_decisions` as well as one row in `audit_interactions` (pick two
different records so both stores have exactly one break).

### 16. Verify

Click **Verify the log**.

**You should see:** both the **Decisions** and **Interactions** cards report "chain broken", each
naming its own record and date independently. Neither card's failure suppresses or hides the
other's.

---

## Known gaps

- **No repair.** A broken chain cannot be fixed from this screen, or at all — this is
  deliberate, not missing. Do not report the absence of a "repair" or "acknowledge" action as a
  defect.
- **The other five "Your data" actions do not exist yet.** Export everything, export the log
  alone, delete a source, delete all memory, and reset Askwell have no backend and are not
  stubbed on this screen (`web/app/settings/page.tsx`'s own comment confirms this is deliberate,
  matching how `storage.tsx` already handles export and prune).
- **No large-log stress test performed here.** The acceptance criteria call for progress on a
  "very large" log; this walkthrough only exercises a log of a handful of records. The elapsed
  counter and interruptibility are structurally the same regardless of size (`verify-log.tsx`
  has no size-dependent branch), but a genuinely large chain walk's wall-clock time was not
  measured in this pass.
- **No automated test for the double-break case (Part E)** in `api/tests/test_log_verify.py` —
  only single-store breaks and the all-intact case are covered there. This manual pass is
  currently the only verification of that combination.
