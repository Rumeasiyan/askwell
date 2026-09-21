# Manual test — M7-SEC-BE-152, encrypting the corpus itself, not just credentials

**Ticket:** `M7-SEC-BE-152` — chunk content (`chunks.content`) is encrypted at rest with the
passphrase-derived key, alongside the connection credentials `M7-SEC-BE-151` already encrypted;
migration is resumable and per-row; the search index and embedding vectors stay derived from
plaintext, documented rather than hidden.
**Version under test:** `0.6.5`
**Time:** about 40 minutes, plus a first stack build. A native inference process
(`scripts/dev.sh inference`) is needed for Part C, where a question is actually asked.
**Who can run it:** anyone who can paste a line into a terminal, click through the app, and run
two `psql` queries to look at what is actually stored.

**What is being checked.** `docs/decisions.md`'s 2026-09-21 `M7-SEC-BE-152` entry and
`docs/ux/settings.md` §4: with a passphrase set, `chunks.content` — the extracted text of the
user's own documents — is unreadable in the database without the key. `chunks.content_tsv` and
`chunks.embedding` stay plaintext-derived on purpose; the documentation says so rather than
overclaiming "the corpus is encrypted." Setting a passphrase on an existing, already-indexed
corpus migrates it; removing it decrypts it back.

**Where this stops on purpose.** The vector index is never encrypted — the ticket's own Out of
Scope line, and `docs/architecture.md` §7 backs it. There is no interrupted-migration simulation
that corrupts data on purpose; Part D interrupts a real migration by killing the API process
mid-batch, which is the honest version of that test. Read "Known gaps" before reporting anything
here as a defect of this ticket.

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

Make one small test file to index:

```
mkdir -p ~/askwell-test/material
printf '%s\n' '%PDF-1.7' 'Either party may terminate on ninety days written notice.' \
  > ~/askwell-test/material/contract.pdf
```

In `.env`, set `ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/material` with your real home
directory filled in.

---

## Cold start

### 1. Bring the stack up

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error, including one for
`b7e91a4c3f65` — that is this ticket's own migration (`content_encrypted` column, `content_tsv`
turned from a generated column into an ordinary one).

### 2. Start native inference

In a separate terminal:

```
scripts/dev.sh inference
```

Leave it running for the rest of this walkthrough — Part C needs it to ask a real question.

### 3. Open Askwell and index a document

`http://127.0.0.1:8000`. Complete first-run if it appears. Drag `contract.pdf` onto the window,
answering the folder question with the absolute path to `~/askwell-test/material`.

**You should see:** the document reach **Ready** (watch the library view; this can take under a
minute on a light profile). Do not move on until it says Ready — a still-Queued document has no
chunks yet and Part B has nothing to migrate.

### 4. Ask a question before any passphrase exists

Click through to the ask screen (the app's own navigation, not a typed URL) and ask:

> When can either party terminate this agreement?

**You should see:** an answer citing `contract.pdf`, quoting or paraphrasing the ninety-day
notice term. This is the baseline — plaintext content, plaintext everything, exactly as before
this ticket existed. Keep this answer in mind; Part C repeats the same question after
encryption and it must still work.

---

## Part A — what the database actually holds, before a passphrase exists

### 5. Look at the row directly

```
scripts/dev.sh psql
```

```sql
SELECT id, content, content_encrypted FROM chunks;
```

**You should see:** `content_encrypted = f`, and `content` is the readable sentence about the
ninety-day notice — plain text, no passphrase set yet.

Leave `psql` open in this terminal; Part B and D come back to it.

---

## Part B — setting a passphrase migrates the existing corpus

### 6. Open Settings

Navigate to **Settings** through the app's own left-strip navigation, then the **Privacy and
security** section.

**You should see:** a **Passphrase** control, currently "Off. A stolen laptop is readable as-is.
Setting a passphrase encrypts your library and stored credentials."

### 7. Set a passphrase

Click **Set a passphrase**. You should see the no-recovery warning
("There is no recovery. Losing this passphrase means losing the library…") displayed next to the
fields, not behind a dialog you could dismiss unread. Type a passphrase in both fields —
`correct horse battery staple` works — and watch the strength meter update as you type. Tick
**I understand there is no recovery**, then click **Set passphrase**.

**You should see:** the button read "Setting…" while the request is in flight, then the control
switch to "On. The library and stored credentials are encrypted with it," with **Change
passphrase** / **Remove passphrase** buttons.

**Record how long "Setting…" was shown for**, and whether any progress figure appeared during
it. For this one-chunk corpus it will be near-instant either way — this is what "Known gaps"
flags, not a defect to report here.

### 8. Confirm in the database, in the terminal already open

```sql
SELECT id, content, content_encrypted FROM chunks;
```

**You should see:** `content_encrypted = t`, and `content` is no longer the readable sentence —
it is an opaque base64-looking token (a Fernet token). This is the check that matters: the
extracted contract text a stolen, imaged disk would otherwise expose is no longer readable by
looking at the row.

### 9. Confirm what is deliberately still readable

```sql
SELECT content_tsv FROM chunks;
```

**You should see:** real lexemes from the original sentence (`'either'`, `'terminate'`,
`'ninety'`, `'day'`, `'notice'` and similar, stemmed) — not garbage, not empty. This is
`docs/decisions.md`'s stated trade: `content_tsv` is computed from plaintext at write time and
never re-derived from ciphertext, so it stays a real, readable index of the words in the
document even while `content` itself is encrypted. That is the leak `docs/architecture.md` §7
and `docs/ux/settings.md` §4 both name plainly — not a bug you are finding here.

### 10. Confirm stored credentials moved with it

If you have not already, add any live database connection through **Add a source** — even one
pointed at a throwaway local Postgres is enough, since this step only checks the encryption
state of the stored config, not that the connection itself works. Then:

```sql
SELECT id, config_encrypted IS NOT NULL AS has_config FROM sources WHERE config_encrypted IS NOT NULL;
```

**You should see:** at least one row — credentials continue to be encrypted with the same
migrated key, per `M7-SEC-BE-151`'s existing behaviour, which this ticket extends rather than
replaces.

---

## Part C — encrypted content still answers questions, at acceptable speed

### 11. Ask the same question again

Back on the ask screen, ask the exact same question from step 4:

> When can either party terminate this agreement?

**You should see:** the same answer as step 4, citing `contract.pdf`, the ninety-day term.
**Time it roughly** (a stopwatch on your phone is fine) — it should feel indistinguishable from
step 4's response time on this one-document corpus. This is the "queries still work with
acceptable latency" acceptance line: content is decrypted once per candidate row on the read
path (`askwell.retrieve._decrypt`), not once per token generated, so the added cost is one
decrypt call per retrieved passage, not a per-word tax on the answer.

---

## Part D — an interrupted migration resumes rather than leaving a half-encrypted corpus

This part needs a corpus large enough that migration does not finish in one HTTP request before
you can kill the process. Add several more copies of different text to get enough chunks:

### 12. Add more material

```
for n in 1 2 3 4 5; do
  printf '%s\n' '%PDF-1.7' "Clause number $n: the parties agree to distinct terms for section $n." \
    > ~/askwell-test/material/doc-$n.pdf
done
```

Drag all five onto the app the same way as step 3, and wait for every one to reach Ready.

### 13. Remove the passphrase first, to have a plaintext corpus to re-migrate

In Settings, click **Remove passphrase**, enter the passphrase from step 7, and confirm.
**You should see:** the confirmation message about the library being decrypted with the
machine's own key again, and the control back to "Off."

### 14. Start setting a passphrase again, and kill the API mid-migration

Click **Set a passphrase**, fill in the fields the same way as step 7, tick the acknowledgement,
and click **Set passphrase** — then, as fast as you can after clicking, in a terminal run:

```
podman compose restart api
```

**What you are testing:** `migrate_chunk_content` commits after every batch of up to 500 rows;
with only a handful of chunks in this corpus the whole migration may complete inside a single
batch before the restart lands, in which case this step will not actually catch it mid-flight —
if that happens, note it and treat step 15 as confirming a clean, uninterrupted migration
instead. That is an honest limitation of testing this by hand on a small corpus, not a failure
of the migration itself.

### 15. Check what state was left behind

```
curl -s http://127.0.0.1:8000/settings/passphrase/migration | jq
```

**You should see:** either `"migrating": false` with `migrated == total` (it finished before the
restart caught it), or `"migrating": true` with `migrated < total` (you caught it mid-flight).
Either is a valid outcome of this step.

```sql
SELECT content_encrypted, count(*) FROM chunks GROUP BY content_encrypted;
```

**You should see:** a mix of `t` and `f` if you caught it mid-flight — some rows migrated,
others not yet — and every migrated row's `content` still a readable ciphertext when decrypted
with the same passphrase (not corrupted, not double-encrypted).

### 16. Resume by retrying the same call

In the app, check the passphrase status — if it still shows **Off** or a stuck "Setting…"
state, reload the page. Reopen **Set a passphrase**, enter the same passphrase and tick the
acknowledgement again, and submit.

**You should see:** it completes and the control reaches "On." Confirm every row finished:

```sql
SELECT content_encrypted, count(*) FROM chunks GROUP BY content_encrypted;
```

**You should see:** every row `content_encrypted = t`. No row was left unreadable in both
directions — the resume picked up exactly where the interrupted run left off, per
`content_encryption.migrate_chunk_content`'s own `WHERE content_encrypted != target` batch
selection.

### 17. Confirm a second migration cannot start while one is running

This is hard to catch by hand on a fast local corpus (the same timing problem as step 14), so
check it the direct way instead:

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/set \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "a different one", "acknowledged_no_recovery": true}' | jq
```

Run this once while you know a migration to be genuinely in progress (immediately after
restarting the API in step 14, before it has had time to finish) if you can catch the timing;
otherwise confirm from the code instead (`content_encryption.assert_not_migrating`, called at
the top of `set_passphrase`/`change_passphrase`/`remove_passphrase`) that the guard exists, and
note in your results which of the two you actually exercised.

---

## Known gaps

- **No progress bar renders in the UI.** `docs/ux/settings.md` §4 describes "a progress figure
  (`GET /settings/passphrase/migration`), not an instant flip." The backend endpoint exists and
  works (steps 15, 17), and the migration logic genuinely is resumable and batched — but
  `web/components/settings/passphrase.tsx` never polls it; the button shows only "Setting…" /
  "Changing…" / "Removing…" for the whole duration of the (synchronous) HTTP request. On a large
  corpus this is a long, silent spinner rather than the progress figure the UX doc promises. Not
  a defect of this ticket's own backend work, but a real gap between what is documented and what
  renders — worth its own follow-up ticket against the frontend.
- **`set`/`change`/`remove` block the whole HTTP request until migration finishes.** There is no
  background job; the request that calls `/settings/passphrase/set` does not return until every
  chunk has been re-encrypted. For a corpus large enough to take minutes, the browser holds one
  open request that long. This is why Part D above resorts to killing the API process to observe
  an interrupted migration — there is no smaller unit of interruption to test against.
- **Setting a passphrase silently stalls ingestion of every document added afterward.** Filed as
  issue #508: `chunk.run` and `embed.run` run in the `worker` process, which never unlocks (the
  same architectural gap `M7-SEC-BE-151` filed as #504 for two background connection jobs) —
  once a passphrase is set, new documents queue and never reach Ready, indefinitely, even across
  a worker restart. This walkthrough avoids the issue by indexing everything in step 3/12
  *before* setting a passphrase in step 7/14; do not add a document after step 7 and expect it to
  index — that is the known, filed gap, not something to re-report.
- **A locked worker or a locked API mid-`/ask`** was not exercised end-to-end here — asking a
  question while the API process is locked (after a restart, before `/settings/passphrase/unlock`
  is called) surfaces as the generic `unhandled_exception` 500 handler in `app.py`, not a graceful
  abstention message, since nothing in `askwell.ask` or `askwell.retrieve` catches
  `CredentialsLocked` specially. Out of this ticket's stated scope; noted here so it is not
  mistaken for new information if seen while testing.
- **The vector index and full-text index are never encrypted, by design.** Step 9 confirms this
  directly. `docs/architecture.md` §7 and `docs/ux/settings.md` §4 both state it; it is this
  ticket's own Out of Scope line, not a partial implementation.
