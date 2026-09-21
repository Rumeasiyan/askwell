# Manual test — M7-LOG-FE-156, Verification surface reporting where the chain breaks

**Ticket:** `M7-LOG-FE-156` — the settings screen's "Verify the log" action: runs the hash-chain
check across both audit stores, reports intact or names the first break with its date, and never
calls the log immutable.
**Version under test:** `0.6.8` (check `cat VERSION` — bump this line if it has moved on).
**Time:** about 20 minutes.
**Who can run it:** anyone who can open a browser and a terminal (tampering steps need
`scripts/dev.sh psql`).

**What is being checked.** `web/components/settings/verify-log.tsx`, `web/lib/log-verify.ts`
against `POST /log-verify`, `GET /log-verify/{id}`, `POST /log-verify/{id}/cancel`
(`api/src/askwell/log_verify.py`), which drives `askwell.audit.verify`.

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

Use Askwell for a short session first — ask at least one question — so both audit stores hold
at least one real record rather than being empty.

---

## Part A — cold start, reaching the action by clicking

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads. The left rail shows **Ask**, **Library**, and **Settings**.

### 2. Open Settings

Click **Settings** in the left rail.

**Expect:** the Settings page loads. Scroll down past **Hardware profile**, **Retrieval
threshold**, and **Storage** to a heading **Your data**.

**Expect:** under **Your data**, a subsection **Verify the log** with explanatory text:
"Checks both stores' hash chains and reports where, if anywhere, one breaks. Askwell never
rewrites history — it has no permission to. A break means something outside Askwell changed the
file." and a **Verify the log** button. Read this text closely: the word **immutable** does not
appear anywhere on the page.

---

## Part B — chain intact

### 3. Run verify on an untampered log

Click **Verify the log**.

**Expect:** the button becomes disabled and reads "Verifying…". A **Stop** button appears next
to it. A status line appears reading "Checked `<n>` of `<total>` records…", with the numbers
increasing (or completing immediately if the log is small).

### 4. Read the result

Wait for it to finish.

**Expect:** the button returns to its normal "Verify the log" label and the **Stop** button
disappears. Two report lines appear, one per store, e.g. "Decisions: `<n>` records, chain
intact." and "Interactions: `<n>` records, chain intact." — in the provenance colour, not the
alarm colour. Neither line uses the word immutable.

### 5. Confirm the run itself was logged

```
scripts/dev.sh psql
select kind, payload->>'job_id' from audit_decisions where kind = 'log_verify_completed' order by occurred_at desc limit 1;
\q
```

**Expect:** one row, `kind` = `log_verify_completed`, with a `job_id` matching nothing visible in
the UI but confirming the run recorded its own outcome (the ticket's Audit Requirement).

---

## Part C — chain broken, named with its date

### 6. Tamper with a decisions record directly in the database

```
scripts/dev.sh psql
select id, occurred_at from audit_decisions order by occurred_at asc limit 1 offset 1;
```

Note the `id` and `occurred_at` of a record that is **not** the first (genesis) row — altering
the genesis row itself is a different, rarer case. Then:

```
update audit_decisions set payload = '{"tampered": true}'::jsonb where id = '<id from above>';
\q
```

### 7. Run verify again

Back in the browser, reload Settings (or just click **Verify the log** again).

**Expect:** the same progress behaviour as step 3, then on completion the **Decisions** report
renders as an alarm-coloured box (not the plain intact line), reading "Decisions: chain breaks".

**Expect:** the body names the record: "At the record written `<date>` (`<the id from step
6>`)." followed by a detail phrase ending in "...hash to..." (the stored hash no longer matches
the record's contents). Below that, a second line reads "Askwell never rewrites history — it has
no permission to. This means something outside Askwell changed the file after it was written."

**Expect:** the **Interactions** report still shows the plain intact line — only the store you
tampered with reports broken.

**Expect:** the word immutable does not appear anywhere in this broken-chain report.

### 8. Confirm the break was logged too

```
scripts/dev.sh psql
select payload from audit_decisions where kind = 'log_verify_completed' order by occurred_at desc limit 1;
\q
```

**Expect:** the JSON payload's `decisions.intact` is `false`, `decisions.break_id` matches the
tampered record's id, and `decisions.break_reason` is `"altered"`.

### 9. Restore, or note the log is now permanently marked

There is no repair path — do not attempt one; it is explicitly out of scope. If you want a clean
log for further testing, this database will need to be reset (`scripts/dev.sh db downgrade
base && scripts/dev.sh db upgrade head`), which discards all audit history. Do this only if you
do not need the tampered state for anything else.

---

## Part D — interruptible on a large log

### 10. Start a verify and stop it mid-run

If your log is large enough that verification takes a few seconds (otherwise this step will
complete before you can click Stop — note that rather than treat it as a failure), click
**Verify the log**, then quickly click **Stop**.

**Expect:** the **Stop** button reads "Stopping…" briefly. The run ends with neither an intact
nor a broken report shown — instead a muted line reads "Stopped before finishing. Nothing was
found broken or confirmed intact — run it again to get a result."

### 11. Run it again to completion

Click **Verify the log** once more and let it finish.

**Expect:** a normal intact or broken report per Part B or C, confirming a fresh run after a
cancelled one behaves normally.

---

## Known gaps

Do not report these as defects — they are deliberately not built yet or not practical to
exercise on every run:

- **Prune-boundary breaks are not distinguishable from tampering.** `M7-LOG-BE-154` (prune) does
  not exist yet, so there is no legitimate boundary to test — every break `verify()` can
  currently produce is real tampering. `docs/states-and-edge-cases.md` §6 and issue #516 track
  this as deferred to whoever builds prune.
- **Both stores broken at once was not exercised in this walkthrough.** The code path (each
  store reports independently) is the same one covered in Part C for a single store; tampering
  with `audit_interactions` the same way step 6 tampers with `audit_decisions` would exercise it
  but was not run here to avoid destroying both stores' history in one pass.
- **`forked` and `missing_genesis` break reasons were not reproduced.** `forked` is described in
  `api/src/askwell/audit.py` as "not something a user can do by hand" — a concurrency bug
  signature — and `missing_genesis` requires deleting the very first record, which is a more
  destructive tamper than step 6's. Both are exercised by `api/tests/test_log_verify.py`, not by
  this manual walkthrough.
- **No repair path exists, and none was attempted** — this is the ticket's own stated Out of
  Scope, not a gap to fix.
- **A very large log's actual multi-minute runtime was not measured.** The ticket's own
  Assumption is that a year of interactions completes in tolerable time; this walkthrough
  confirms progress and interruptibility exist, not the number of minutes a real year-sized log
  takes.
