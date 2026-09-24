# Manual test — M7-DATA-BE-159a, reset clears the audit tables, and nothing else can

**Ticket:** `M7-DATA-BE-159a` — reset empties every table in Askwell's own database, the two audit stores included, in one transaction, while the app's ordinary database role still cannot change or delete an audit record (#523).
**Version under test:** `0.7.28`. Run `cat VERSION` and update this line if the version has moved on.
**Time:** about 40 minutes. Most of it is waiting for a document to index and a question to be answered.
**Who can run it:** anyone with a browser and a terminal who can copy and paste commands. No database knowledge is needed; every database command is given in full, with what it should print.

**What is being checked.**

- `askwell.reset.perform` and `POST /reset` (`api/src/askwell/reset.py`). The ordinary tables are emptied with `DELETE`. The audit tables are emptied by `askwell_reset_audit()`.
- Migration `b5d09e3c71a8` (`api/src/askwell/db/migrations/versions/20260924_b5d09e3c71a8_audit_reset_function.py`). It adds `askwell_reset_audit()`, a `SECURITY DEFINER` function owned by a new role, `askwell_audit_reset`. That role cannot log in and holds only `SELECT, TRUNCATE` on the two audit tables. The function refuses to run unless the newest decisions record is a `reset_requested` record written in the same transaction.
- What survives a reset: exactly one decisions record, `reset_performed`. It holds the counts of what was removed and starts a fresh, intact chain.

**Where this stops on purpose.** Nothing in the interface can start a reset yet. **Settings → Your data** has only **Verify the log**. The confirmation screen is `M7-DATA-FE-160`. So Parts A, B and E are done by clicking, as a user would. Part C starts the reset with one `curl` command, using the session cookie the browser would carry. Parts D and F read the database with `psql`, which is how the ticket's own walkthrough says to check it. When `M7-DATA-FE-160` lands, Part C becomes a button and the rest of this document still applies.

> **This test deletes everything in Askwell's database on the machine you run it on**: sources, conversations, memory, settings, and the whole audit log. Your original files on disk are not touched. Run it on a test install. On the shared development machine, do not run it if anyone needs what that stack currently holds.

---

## Before you start

In a terminal:

```
cd ~/external/quantum-plus/askwell
cp -n .env.example .env
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the API image build finishes without an error. The web build finishes with a route list and no red error text. Compose reports its containers as started, including `postgres`, `redis`, `egress-proxy`, `sandbox`, `api` and `worker`. The migration step finishes without an error.

Do not skip `build-api`. The API's code is built into its image rather than mounted. Without a rebuild, the running API has no `/reset` route and Part C returns `404`.

Confirm the new migration is the one in place:

```
scripts/dev.sh psql -c "SELECT version_num FROM alembic_version"
```

**You should see:** one row, `b5d09e3c71a8`. If a later migration has landed since, a later id is fine. Confirm the function exists either way:

```
scripts/dev.sh psql -c "SELECT proname, pg_get_userbyid(proowner) AS owner, prosecdef FROM pg_proc WHERE proname = 'askwell_reset_audit'"
```

**You should see:** one row: `askwell_reset_audit | askwell_audit_reset | t`. The `t` means it is `SECURITY DEFINER`.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor logs that the embedding and generation models are ready.

Keep one small document ready that states a fact you can ask about, for example a `.txt` or PDF with a date or an amount in it.

---

## Part A — cold start, and using Askwell so there is something to reset

### 1. Open Askwell

Open a **private or fresh-profile** browser window, so no earlier session carries over. Go to `http://127.0.0.1:8000`.

**You should see one of two screens:**

- **A fresh install, with nothing added yet:** the welcome screen, headed "Welcome to Askwell".
- **Sources already added:** the **Ask** screen, with a line at the top reading "Askwell 0.7.28 · nothing leaves this machine" and a rail on the left with **Ask**, **Library**, **Clarifications**, **Memory** and **Settings**.

### 2. Add a document

- **On the welcome screen:** click **Get started** and follow the steps. On *Add something and ask*, add your document.
- **On the Ask screen:** click **Library** in the rail, then click the **Add a source** button below the list, and add your document.

Wait until **Library** shows the document as indexed, not indexing.

**You should see:** each step leads to the next with no dead end. The document appears in **Library** with its name, and its status changes to indexed.

### 3. Ask a question about it

Click **Ask** in the rail. Type a question that your document answers, for example "What is the notice period?", and send it.

**You should see:** an answer that names your document and a page, such as "your-document.pdf, p. 1". An abstention is also fine here, for example "Nothing in your material answers this". Either way, the question has now been written to the interaction log.

### 4. Look at the log before the reset

Click **Settings** in the rail. Scroll down to **Your data**, then click **Verify the log**.

**You should see:** the button reads "Checking…" and then two results:

- "Decisions — chain intact", with "N records checked." N is at least 1, because adding the source was recorded.
- "Interactions — chain intact", with "N records checked." N is at least 1, because the question was recorded.

Write both numbers down.

On the shared development machine, **Decisions** may instead read "chain broken" because of #565, an earlier break in that stack's own history. That is not a defect in this ticket. Note it and continue: the reset should clear it (step 12).

---

## Part B — the other tables hold something too

### 5. Count what is there

In the terminal:

```
scripts/dev.sh psql -c "SELECT (SELECT count(*) FROM documents) AS documents, (SELECT count(*) FROM conversations) AS conversations, (SELECT count(*) FROM messages) AS messages, (SELECT count(*) FROM roots) AS folders, (SELECT count(*) FROM audit_decisions) AS decisions, (SELECT count(*) FROM audit_interactions) AS interactions"
```

**You should see:** one row with every number at least 1. `decisions` and `interactions` match the two numbers from step 4.

---

## Part C — reset

### 6. A reset without a session is refused

```
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/reset
```

**You should see:** `401`. Nothing was removed. Run step 5 again and the counts are unchanged.

### 7. Get the session the browser would carry

```
curl -s -c /tmp/ck.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
```

**You should see:** no output. The file `/tmp/ck.txt` now holds an `askwell_session` cookie. This is the same cookie a browser receives when it opens Askwell.

### 8. Reset

```
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/reset | python3 -m json.tool
```

**You should see:** a response with `"counts"` listing every table by name, including `"audit_decisions"` and `"audit_interactions"`, and a `"total"`. The counts for `documents`, `conversations`, `messages`, `roots`, `audit_decisions` and `audit_interactions` match step 5. The `"total"` equals the sum of all the counts.

If you see `{"detail": ...}` with a `500` error, or a message containing `permission denied`, that is the bug this ticket fixes. Stop and report it with the full output.

---

## Part D — everything is gone except the record of the reset

### 9. Count again

Run the step 5 command again.

**You should see:** `documents`, `conversations`, `messages`, `folders` and `interactions` are all `0`. `decisions` is `1`.

### 10. Every table, not just those six

```
scripts/dev.sh psql -c "SELECT table_name, (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I', table_name), false, true, '')))[1]::text::int AS n FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name <> 'alembic_version' ORDER BY 1"
```

**You should see:** one row per table. Every `n` is `0`, except `audit_decisions`, which is `1`. Nothing else has a row.

### 11. The one surviving record says what happened

```
scripts/dev.sh psql -c "SELECT kind, prev_hash = repeat('0', 64) AS starts_new_chain, payload->'counts'->>'audit_interactions' AS interactions_removed, payload->'counts'->>'documents' AS documents_removed FROM audit_decisions"
```

**You should see:** one row: `reset_performed | t | <step 5's interactions> | <step 5's documents>`. The reset is the one thing the reset did not erase, and it starts a new chain rather than hanging off a deleted one.

`reset_requested`, written before anything was removed, is **not** there. That is expected: it was deleted along with the rest of the audit table. `reset_performed` carries the same counts.

### 12. The interface sees a fresh install

Go back to the browser window from Part A and reload the page.

**You should see:** the welcome screen, "Welcome to Askwell". Askwell now holds no indexed document and no record that welcome was skipped, so it starts over as a first run. Your document is still in its folder on disk. Reset never touches original files.

Click **Skip setup**. You land on **Ask**. Click **Library** in the rail.

**You should see:** the empty Library, with no sources listed.

Click **Settings** in the rail, scroll to **Your data**, and click **Verify the log**.

**You should see:**

- "Decisions — chain intact", "1 records checked."
- "Interactions — chain intact", "0 records checked."

If Decisions read "chain broken" in step 4 because of #565, it now reads intact. That history is gone, and the new chain starts at the reset.

The terminal gives the same result:

```
podman compose exec api askwell-verify
```

**You should see:** `decisions: 1 records, chain intact.` and `interactions: 0 records, chain intact.`

---

## Part E — Askwell works normally after a reset

### 13. Add and ask again

Use **Library → Add a source** to add the same document again. You may need to nominate its folder again under **Settings → Folders**, because the reset removed the list of nominated folders. Wait until it is indexed, then ask the question from step 3 again.

**You should see:** the same kind of answer as in step 3, citing the document and page. Back in **Settings → Your data → Verify the log**, both chains are intact, and Interactions now has at least 1 record. The log carries on from the reset record rather than breaking.

---

## Part F — the app's own role still cannot rewrite the log

These commands connect as the database owner and then switch to `askwell_app`, the role Askwell runs as. Each command switches in its own session, so they can run in any order.

### 14. The ordinary role cannot delete, change or truncate an audit record

First, read the grants. This changes nothing:

```
scripts/dev.sh psql -c "SELECT t AS audit_table, has_table_privilege('askwell_app', t, 'UPDATE') AS can_update, has_table_privilege('askwell_app', t, 'DELETE') AS can_delete, has_table_privilege('askwell_app', t, 'TRUNCATE') AS can_truncate FROM unnest(ARRAY['audit_decisions', 'audit_interactions']) AS t"
```

**You should see:** two rows, with `f` in all three privilege columns on both.

Then try each change. Each command runs inside a transaction that is rolled back. If a privilege has drifted on this database, the change is still undone:

```
scripts/dev.sh psql -c "BEGIN" -c "SET LOCAL ROLE askwell_app" -c "DELETE FROM audit_interactions" -c "ROLLBACK"
scripts/dev.sh psql -c "BEGIN" -c "SET LOCAL ROLE askwell_app" -c "UPDATE audit_decisions SET kind = 'x'" -c "ROLLBACK"
scripts/dev.sh psql -c "BEGIN" -c "SET LOCAL ROLE askwell_app" -c "TRUNCATE audit_decisions" -c "ROLLBACK"
scripts/dev.sh psql -c "BEGIN" -c "SET LOCAL ROLE askwell_app" -c "TRUNCATE audit_interactions" -c "ROLLBACK"
```

**You should see:** each prints `BEGIN` and `SET`, then an error, then `ROLLBACK`:

- `ERROR:  permission denied for table audit_interactions`
- `ERROR:  permission denied for table audit_decisions`
- `ERROR:  permission denied for table audit_decisions`
- `ERROR:  permission denied for table audit_interactions`

**Report it** if the first command prints `DELETE <number>` instead of an error, or if any row in the grants check shows `t`. That means the database's grants differ from what the migrations create. The rollback has already undone the delete. This happened on the shared development stack on 2026-09-24: `askwell_app` held `DELETE` on `audit_interactions` there, although no migration grants it (#682).

Then check that nothing moved: **Settings → Your data → Verify the log** shows the same record counts as at the end of step 13.

### 15. The reset function, called on its own, is refused

```
scripts/dev.sh psql -c "SET ROLE askwell_app" -c "SELECT askwell_reset_audit()"
```

**You should see:** `ERROR:  the audit tables can only be cleared by a reset recorded in this transaction`. Verify the log again: the counts are unchanged.

### 16. A reset request from an earlier transaction does not unlock it

This writes a record that looks like a reset request, commits it, and then tries the function in a new transaction.

```
scripts/dev.sh psql -c "SET ROLE askwell_app" -c "INSERT INTO audit_decisions (kind, payload, prev_hash, hash) SELECT 'reset_requested', '{}'::jsonb, repeat('0',64), repeat('f',64)" -c "SELECT askwell_reset_audit()"
```

**You should see:** `INSERT 0 1`, followed by the same `ERROR:  the audit tables can only be cleared by a reset recorded in this transaction`. `psql -c` commits each command separately, so the request belongs to an earlier transaction.

If the `INSERT` itself fails because a column name differs, run `scripts/dev.sh psql -c "\d audit_decisions"` and adjust. What matters is the refusal on the second command.

This step leaves a hand-written record with a false hash in the decisions chain. **Verify the log** now shows Decisions as "chain broken". That is correct behaviour: the chain has caught a record written outside Askwell. Part G's reset clears it.

### 17. Other roles cannot call it at all

```
scripts/dev.sh psql -c "SET ROLE askwell_readonly" -c "SELECT askwell_reset_audit()"
```

**You should see:** `ERROR:  permission denied for function askwell_reset_audit`. `askwell_readonly` is the role that runs model-generated SQL (C2), and it cannot reach the function.

### 18. The function's owner can touch nothing else

```
scripts/dev.sh psql -c "SELECT has_table_privilege('askwell_audit_reset', 'documents', 'DELETE') AS documents_delete, has_table_privilege('askwell_audit_reset', 'audit_decisions', 'INSERT') AS audit_insert, has_table_privilege('askwell_audit_reset', 'audit_decisions', 'TRUNCATE') AS audit_truncate, rolcanlogin FROM pg_roles WHERE rolname = 'askwell_audit_reset'"
```

**You should see:** `f | f | t | f`. The role can truncate the audit tables and do nothing else, and it cannot log in.

---

## Part G — a reset that fails partway removes nothing

### 19. The automated coverage, run by hand

A partial failure cannot be caused safely from the interface, so this step runs the tests that cause one. They run as `askwell_app`, the way Askwell connects at runtime, not as the database owner. Testing as the owner is the gap that let #523 ship.

```
scripts/dev.sh test-db -- api/tests/test_reset.py -v
```

**You should see:** every test passes, including:

- `test_reset_as_the_app_role_empties_every_table_audit_included`
- `test_a_reset_that_fails_partway_removes_nothing`
- `test_a_row_a_concurrent_writer_commits_mid_reset_does_not_survive_it`
- `test_an_ordinary_app_path_still_cannot_rewrite_an_audit_table` (six cases)
- `test_the_reset_function_called_directly_is_refused`
- `test_a_reset_request_from_an_earlier_transaction_does_not_authorise_it`
- `test_a_reset_request_followed_by_another_record_does_not_authorise_it`
- `test_only_the_app_role_may_call_it_and_its_owner_can_touch_nothing_else`
- `test_every_table_in_the_schema_is_one_reset_clears`
- `test_performing_a_reset_requires_a_session`
- `test_post_reset_succeeds_as_the_app_role`

A skipped test counts as a failure here. This suite fails, rather than skips, when the database is not reachable.

### 20. Reset once more, to leave a clean install

Repeat steps 7 and 8, then step 12's **Verify the log**.

**You should see:** the reset succeeds, and the record hand-written in step 16 is gone with everything else. Decisions shows "chain intact", "1 records checked"; Interactions shows "0 records checked".

---

## Cleanup

```
rm -f /tmp/ck.txt
```

Stop the inference terminal with `Ctrl+C` if you no longer need it.

---

## What was checked against the ticket's acceptance criteria

- Reset completes against a real deployment and every named table is empty afterwards, audit tables included: Parts C and D, steps 8 to 12.
- An ordinary code path running as `askwell_app` cannot `UPDATE`, `DELETE` or `TRUNCATE` an audit table: step 14, and automatically in step 19.
- The reset is recorded before the tables go: `reset_requested` is required by the function (steps 15 and 16 show the function refusing without one). `reset_performed` is what survives: step 11.
- The elevated path invoked from anywhere but reset is refused: steps 15, 16 and 17.
- A reset that fails partway leaves nothing half-cleared: step 19. It is not reproducible by hand.
- Reset attempted while an ingestion is running: see Known gaps. The behaviour differs from what the ticket assumed.

## Known gaps

Do not report these as defects in this ticket.

- **No reset button.** Nothing in the interface starts a reset. **Settings → Your data** has only **Verify the log**. The confirmation dialog, the preview of what will be deleted, and the statement that original files are never touched belong to `M7-DATA-FE-160`. Until then, Part C uses `curl`.
- **No "refused while ingesting".** The ticket assumed an existing refusal while ingestion holds a lock. None existed anywhere in the code. Reset instead locks every ordinary table and waits for any in-flight ingestion write to finish, then removes it too (`docs/decisions.md`, 2026-09-24). Timing a reset against a running ingestion by hand is unreliable at this corpus size. `test_a_row_a_concurrent_writer_commits_mid_reset_does_not_survive_it` covers it instead.
- **`reset_requested` does not survive.** It is written first and then deleted with the audit table it lives in. `reset_performed`, with the same counts, is the record that remains. This is by design (`docs/audit-log.md` §4).
- **Only Askwell's own database is reset.** These are left alone, and are `M7-DATA-FE-160`'s to handle:
  - sandbox databases created by dump imports;
  - trace files on disk (the third audit store, `docs/audit-log.md` §2);
  - backup and export files already written;
  - a passphrase still unlocked in the running API's memory.
  
  Trace files are not named in `reset.py`'s list of what `M7-DATA-FE-160` must handle, so they are tracked in #683.
- **The function's guard checks that a reset was recorded, not which code called it.** Any code running as `askwell_app` that writes a `reset_requested` record and calls the function in the same transaction can empty the log. Today only `askwell.reset` writes that kind of record. Model-generated SQL runs as `askwell_readonly` and cannot call the function (step 17). Step 16 shows a request from an earlier transaction is refused, but this document does not attempt the same-transaction case by hand. That is a limit of the design, not a test failure, and it is tracked in #684.
- **Folders must be nominated again after a reset.** The list of nominated folders is Askwell data, so reset removes it (step 13). This is intended.
- **Interaction pruning has the same bug #523 had** (#682). Prune deletes interaction records as `askwell_app`, which has no `DELETE` grant, and its tests connect as the owner. Prune is not part of this ticket. This matters here only because a database that has been hand-patched so prune works will fail step 14.
- **#565** (the development stack's own broken decisions chain) is cleared on any machine where this test runs, because the reset removes that history. The issue stays open for its root cause.
