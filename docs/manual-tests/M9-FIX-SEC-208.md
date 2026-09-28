# Manual test — M9-FIX-SEC-208, log pruning works on a real install, and a restore keeps one chain

**Ticket:** `M9-FIX-SEC-208`, issues #682 and #697. Askwell keeps a log of every question you ask
(the *interactions* log) and of every setting or decision you make (the *decisions* log). Each
record is chained to the one before it, so a record removed or altered by hand shows up as a
break when you click **Verify the log**.

Two things were wrong:

- **Pruning never worked on a real install** (#682). You set a retention window, say one month,
  and Askwell is meant to remove interactions older than that, once you have exported them. The
  prune deleted rows as Askwell's own database user, which is not allowed to delete from the
  log. So the database refused every prune, and the log kept growing. The development database
  had a stray permission that no migration ever granted, and that permission hid the bug.
- **A restore onto a fresh machine could fork the decisions chain** (#697). Starting Askwell for
  the first time used to write a "version first started" record. A backup restored after that
  brought its own first record, so the chain had two beginnings, and verification reported it
  as broken.

Now a prune deletes through one narrow database function. That function deletes only what the
prune's own decisions record describes, and it refuses every other caller. The same migration
removes the stray permission, so a development machine and a real install have the same
permissions. The #697 fix landed earlier, in `M7-UPDATE-FE-162` (`0.7.34`). This ticket
re-checks it with Askwell's real, restricted database user.

**Version under test:** `0.7.56`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 40 minutes.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from the address in step 5. The terminal starts Askwell, makes the machine
clean, and does the three things that have no screen yet: prune, back up and restore. Those steps
are labelled **Stand-in**, and each one says why no screen can do it yet.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| `askwell_prune_interactions()`, the only way to delete an interaction, owned by the `askwell_audit_prune` role. The same migration removes the development database's stray `DELETE` permission | `api/src/askwell/db/migrations/versions/20260928_f4b8d2c6a915_audit_prune_function.py` |
| The prune writes its `interactions_pruned` record first, then calls the function in the same transaction | `run_job` in `api/src/askwell/log_prune.py` |
| A first start writes only the version file, so a restore that follows keeps one chain (#697, unchanged here) | `record_running_version` in `api/src/askwell/update_check.py` |
| **Verify the log** accepts a chain that starts where a recorded prune ended | `verify`, `prune_boundaries` in `api/src/askwell/audit.py`, reached through `web/components/settings/verify-log.tsx` |

The automated proof is in `api/tests/test_log_prune.py` and
`api/tests/test_restore.py::test_a_restore_onto_a_machine_that_has_started_keeps_one_chain`.
Both now connect as `askwell_app`, with the same restrictions it has at runtime. This document
repeats the behaviour on a cold-started stack, the way a person meets it.

**The one rule of this test.** Never type an address into the browser bar except the one in
step 5. Reach every screen by clicking.

### Where this stops on purpose. Read this before reporting anything as a defect.

- **No screen can prune yet** (#487). On **Settings → Storage**, the **Export and prune** button
  is greyed out and says "Not built yet". Step 9 confirms that is still true. Part D then starts
  the prune from the terminal, through the same route a future button will call.
- **No screen can back up or restore yet.** Parts F and G use the terminal for those two steps
  only. Checking the chain after each of them is done by clicking.
- **A fresh install has nothing a month old to prune.** Part B adds six correctly chained
  interaction records dated between 400 days and 1 day ago. Askwell itself always stamps "now",
  and the date is part of each record's hash, so a real record cannot be back-dated afterwards.
  The script refuses to run unless the interactions log is empty, so it cannot splice records
  into a real history.
- **Do not open the browser between the second wipe and the restore (Part G).** On a fresh
  machine two things write a decisions record before any restore can happen. The first is the
  welcome screen's first load, which records the hardware check (#795, not fixed here). The
  second is **Verify the log** itself, which records that it ran. Either one gives the fresh
  machine its own first record, and then the restored history forks from it. That is a real
  defect, but it is #795's defect, not this ticket's. Part G shows the #697 path holds.

> **Warning: this test deletes every Askwell record on the machine it runs on.** Part A and
> Part G empty Askwell's database: sources, memory, conversations and both logs. Your files on
> disk are not touched. Run it on a development machine whose Askwell data you do not need, or
> take a backup first (`docs/restore-release-test.md` §1.3) and restore it once you have
> finished.

> **Known defects you may see on the way. Do not report them against this ticket.**
>
> - **The first click on an item in the left column after a fresh load sometimes does nothing**
>   (#665). Click it again.
> - **The retention window's confirmation line still says "Askwell does not yet prune
>   interactions past this window".** That is still accurate from the screen's point of view: no
>   button prunes, and nothing prunes on a schedule (#487).

---

## Before you start

Bring the stack up, apply migrations, and build the interface. The API serves the built files in
`web/out`, not the live source, so the build is needed.

```
cd ~/external/quantum-plus/askwell
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

### 1. Confirm the migration this ticket adds is applied

```
scripts/dev.sh psql -Atc "SELECT version_num FROM alembic_version;"
```

**Expect:** `f4b8d2c6a915`, or a later revision if other migrations have landed since. If you see
`e1c5a8f3b207`, the upgrade above did not run. Everything below would then test the old code.

---

## Part A — make this machine a clean one

### 2. **Stand-in.** Empty Askwell's database and forget the last version it ran as

No screen can do this. **Settings → Your data → Reset Askwell** empties the data, but it leaves a
`reset_performed` record as the first record of a new decisions chain. That is its job, and it
means the machine is no longer clean.

This is the same simulation `docs/restore-release-test.md` §3 uses, plus the version file that
#697 is about:

```
scripts/dev.sh psql <<'SQL'
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename <> 'alembic_version' LOOP
    EXECUTE format('TRUNCATE %I CASCADE', t);
  END LOOP;
END $$;
SQL
podman compose exec api rm -f /var/lib/askwell/running_version
podman compose exec api sh -c 'rm -f $(python3 -c "from askwell.config import Settings; print(Settings().install_secret_path)")'
podman compose restart api worker
```

**Expect:** `DO`, then the two containers restarting with no error.

### 3. **Stand-in.** Confirm the first start left the log empty

```
scripts/dev.sh psql -Atc "SELECT (SELECT count(*) FROM audit_decisions), (SELECT count(*) FROM audit_interactions);"
podman compose exec api cat /var/lib/askwell/running_version
```

**Expect:** `0|0`, and then the version from `cat VERSION` (`0.7.56`). Starting Askwell wrote the
version to a file and nothing to the log. This is the #697 fix. If the first number is `1`, the
first start wrote a decisions record, and #697 has come back.

---

## Part B — give the machine a history older than a month

### 4. **Stand-in.** Add six dated interaction records

Paste the whole block into the terminal. It runs inside the API container as `askwell_app`,
which is allowed to add log records but not to change or delete them.

```
podman compose exec -T api python - <<'PY'
import asyncio, uuid
from datetime import UTC, datetime, timedelta
from sqlalchemy import text
from askwell.audit import GENESIS, canonical_payload, compute_hash
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory

AGES_DAYS = [400, 200, 90, 45, 5, 1]

async def main() -> None:
    engine = build_engine(load_settings())
    try:
        async with session_factory(engine)() as session:
            existing = (await session.execute(text("SELECT count(*) FROM audit_interactions"))).scalar_one()
            if existing:
                print(f"REFUSED: audit_interactions already holds {existing} rows. Wipe first (Part A).")
                return
            prev_hash, now = GENESIS, datetime.now(UTC)
            for days in AGES_DAYS:
                record_id, occurred_at = uuid.uuid4(), now - timedelta(days=days)
                payload = {"manual_test": "M9-FIX-SEC-208", "age_days": str(days)}
                digest = compute_hash(record_id=record_id, kind="question_asked", payload=payload,
                                      occurred_at=occurred_at, prev_hash=prev_hash)
                await session.execute(
                    text("INSERT INTO audit_interactions (id, kind, payload, prev_hash, hash, occurred_at) "
                         "VALUES (:id, 'question_asked', CAST(:payload AS jsonb), :prev, :hash, :at)"),
                    {"id": record_id, "payload": canonical_payload(payload), "prev": prev_hash,
                     "hash": digest, "at": occurred_at})
                prev_hash = digest
            await session.commit()
            print(f"SEEDED: {len(AGES_DAYS)} interactions, aged {AGES_DAYS} days")
    finally:
        await engine.dispose()

asyncio.run(main())
PY
```

**Expect:** `SEEDED: 6 interactions, aged [400, 200, 90, 45, 5, 1] days`. If it prints `REFUSED`,
step 2 did not empty the log. Do not continue.

With a one-month window, the 400, 200, 90 and 45-day records are past it and the 5 and 1-day
records are inside it.

---

## Part C — cold start, by clicking

### 5. Open Askwell

In a browser, go to `http://localhost:8000/`. This is the only address you type.

**Expect:** the **Welcome to Askwell** screen, with "A personal AI over your own files, on this
machine." under the heading and a **Skip setup** button at the top right. The machine has never
indexed a source, so Askwell starts first-run.

### 6. Skip setup

Click **Skip setup**.

**Expect:** the **Ask** screen, with the left column listing **Ask**, **Library**,
**Clarifications**, **Memory** and **Settings**.

### 7. Ask one question

Type `What notice period does my contract give?` into the question box and send it.

**Expect:** after a wait (it can take minutes on a machine without a graphics card), Askwell says
nothing in your material answers this. You have added no sources, so it must abstain rather than
answer from general knowledge. The question is now in the interactions log, after the six
records from step 4.

### 8. Verify the log before pruning

Click **Settings** in the left column. Scroll to **Your data** and find **Verify the log**. Click
the **Verify the log** button.

**Expect:** the button reads **Checking…** with a seconds counter, then two green-edged panels:

- **Decisions — chain intact**, some number of records checked.
- **Interactions — chain intact**, at least `7 records checked` (the six from step 4 plus your
  question; asking can write more than one record). **Write this number down** as *N-before*.

There is no grey note under **Interactions** yet. The chain still starts at its first record.

### 9. Set the retention window to one month

Scroll up to **Storage** and find **Interaction retention window**.

**Expect:** "Current window: 12 months", the shipped default.

Clear the box, type `1`, and click **Change retention window**.

**Expect:** the button reads **Changing…** briefly. Then this line appears: "Retention window
changed from 12 to 1 months. Recorded in the decisions log. Askwell does not yet prune
interactions past this window — that arrives with a later ticket." The line above it now reads
"Current window: 1 months". Nothing is deleted yet.

Below that, under **Export and prune**, the **Export and prune** button is greyed out and does
nothing when clicked. This is the gap Part D works around (#487).

### 10. Export the log

Scroll down to **Your data** and find **Export the log**. Click the **Export the log** button.

**Expect:** the button reads **Exporting…** and a progress line appears, ending "This runs in the
background; you can keep using Askwell." Within a few seconds it becomes "Ready, …" followed by a
size and a **Download the export** link. You do not need to download it. Askwell refuses to prune
records you have never been given a copy of, and this export is the copy.

If a red panel asks you to export without protection, a passphrase is set. Step 2 should have
removed it. Click **Cancel** and repeat Part A.

---

## Part D — prune

### 11. **Stand-in.** Start a prune

No screen can do this yet (step 9, #487). The terminal needs a session first, the way the
browser got one in step 5:

```
curl -s -c /tmp/askwell-208.cookies -H 'Accept: text/html' localhost:8000/ -o /dev/null
curl -s -b /tmp/askwell-208.cookies -X POST localhost:8000/log-prune \
  -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** a job with an `"id"`, a `"status"` of `"queued"` or `"running"`, and a `"cutoff"`
one calendar month before today. **Copy the `"id"`.**

If you see `"export_required": true` instead, step 10 did not finish. Go back and wait for
**Ready**. If you see `"confirmation_required": true`, far more records are past the window than
this test adds. Stop and repeat from Part A.

### 12. **Stand-in.** Read the result

```
curl -s -b /tmp/askwell-208.cookies localhost:8000/log-prune/<the id> | python3 -m json.tool
```

Repeat until `"status"` is no longer `"queued"` or `"running"`.

**Expect:** `"status": "done"`, `"pruned_count": 4`, a `"boundary_hash"` of 64 letters and
digits, and `"error": null`.

**This is the #682 fix.** Before this ticket the same call ended `"status": "failed"` with
`"error"` naming `permission denied for table audit_interactions`, on every real install.

### 13. Verify the log after pruning

Back in the browser, go to **Settings → Your data** and click **Verify the log** again.

**Expect:**

- **Decisions — chain intact**, with more records than in step 8. Step 8's own check, the
  retention change, the export, the prune request and the prune itself are all recorded here. The
  decisions log is never pruned.
- **Interactions — chain intact**, *N-before* minus 4 records checked. **Write this number down**
  as *N-after*. A grey note sits under it:
  "Chain starts after a prune (pruned through …), not at genesis — expected, recorded in the
  decisions store." The date after "pruned through" is the cutoff from step 11.

A red **Interactions — chain broken** panel here is a failure of this ticket.

---

## Part E — nothing else can delete from the log

### 14. **Stand-in.** Try to delete as Askwell's own database user

No screen offers a delete, so this is checked in the database. Each statement runs inside a
transaction that is rolled back, so nothing changes even if one wrongly succeeds.

```
scripts/dev.sh psql <<'SQL'
BEGIN; SET LOCAL ROLE askwell_app; DELETE FROM audit_interactions; ROLLBACK;
BEGIN; SET LOCAL ROLE askwell_app; DELETE FROM audit_decisions; ROLLBACK;
BEGIN; SET LOCAL ROLE askwell_app; SELECT askwell_prune_interactions(); ROLLBACK;
BEGIN; SET LOCAL ROLE askwell_readonly; SELECT askwell_prune_interactions(); ROLLBACK;
SELECT table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type)
  FROM information_schema.role_table_grants
 WHERE grantee = 'askwell_app' AND table_name LIKE 'audit_%' GROUP BY 1 ORDER BY 1;
SELECT table_name, string_agg(privilege_type, ', ' ORDER BY privilege_type)
  FROM information_schema.role_table_grants
 WHERE grantee = 'askwell_audit_prune' GROUP BY 1 ORDER BY 1;
SQL
```

**Expect,** in this order:

1. `ERROR:  permission denied for table audit_interactions`. Askwell's own user cannot delete an
   interaction directly. That is also true on a development machine now: the stray permission
   is gone.
2. `ERROR:  permission denied for table audit_decisions`.
3. `ERROR:  interactions can only be deleted by a prune recorded in this transaction`. Askwell's
   user can call the function, but it refuses unless a prune record was written in the same
   transaction.
4. `ERROR:  permission denied for function askwell_prune_interactions`. `askwell_readonly` is the
   user that model-written database queries run as, and it cannot call the function at all.
5. `audit_decisions | INSERT, SELECT` and `audit_interactions | INSERT, SELECT`. There is no
   `DELETE`, `UPDATE` or `TRUNCATE` on either line.
6. `audit_decisions | SELECT` and `audit_interactions | DELETE, SELECT`. The function's owner can
   delete interactions and nothing else.

Any `DELETE 0` or `DELETE <n>` line in place of 1 or 2 is a failure of this ticket, even though
the rollback undid it.

---

## Part F — back up

### 15. **Stand-in.** Take a backup

No screen can do this yet.

```
curl -s -b /tmp/askwell-208.cookies -X POST localhost:8000/backup \
  -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** a job with an `"id"` and `"status"` of `"queued"` or `"running"`. Copy the id, then
repeat this until `"status": "done"`:

```
curl -s -b /tmp/askwell-208.cookies localhost:8000/backup/<the id> | python3 -m json.tool
```

**Expect:** `"status": "done"`, `"tables_done"` equal to `"tables_total"`, and `"error": null`.

Find where the file was written:

```
scripts/dev.sh psql -Atc "SELECT file_path FROM backup_jobs WHERE status = 'done' ORDER BY created_at DESC LIMIT 1;"
```

**Expect:** a path under `/var/lib/askwell/backups/`, ending `.zip`. **Write it down.** Both the
API and the worker can read that folder, so a restore on this machine can use it where it is.

---

## Part G — restore onto a fresh machine

### 16. **Stand-in.** Make the machine clean again

Repeat **step 2** exactly: the wipe, both `rm` commands, and the restart. The backup file is not
in the database, so the wipe does not remove it.

**Do not touch the browser tab from here until step 20.** Close it if you are unsure. See "Where
this stops on purpose".

### 17. **Stand-in.** Confirm the first start left the log empty

Repeat **step 3**.

**Expect:** `0|0`, and the version file holding `0.7.56` again. This is the clean machine #697
is about: Askwell has started once and has written nothing to either log.

### 18. **Stand-in.** Restore

The wipe replaced the signing secret, so the terminal needs a new session. The `curl` call below
fetches the page but does not run it, so it does not trigger the welcome screen's hardware
record.

```
curl -s -c /tmp/askwell-208.cookies -H 'Accept: text/html' localhost:8000/ -o /dev/null
curl -s -b /tmp/askwell-208.cookies -X POST localhost:8000/restore \
  -H 'content-type: application/json' \
  -d '{"path": "<the path from step 15>", "replace_existing": true}' | python3 -m json.tool
```

`"replace_existing": true` is needed on a clean machine today because of #597, not because there
is anything to replace. Getting a session writes one settings row, and restore counts that as
existing data.

**Expect:** a job with an `"id"`. Copy it, then repeat this until `"status"` is no longer
`"queued"` or `"running"`:

```
curl -s -b /tmp/askwell-208.cookies localhost:8000/restore/<the id> | python3 -m json.tool
```

The restore replaces the settings table, which includes the session secret. If a call answers
`No session.`, run the first `curl` line of this step again and retry.

**Expect:** `"status": "done"`, `"tables_done"` equal to `"tables_total"`, `"error": null`, and
**`"chain_verified": true`**.

### 19. **Stand-in.** Verify from the terminal, which records nothing

```
podman compose exec api askwell-verify; echo "exit $?"
```

**Expect:**

```
audit_decisions: <n> records, chain intact.
audit_interactions: <m> records, chain intact. Chain starts after a prune (pruned through …), not at genesis — expected, recorded in the decisions store.
exit 0
```

`<m>` is *N-after* from step 13. `<n>` is whatever the backup carried; it only has to be intact.
The interactions log still starts where the prune ended. The restore brought back both the gap
and the record that explains it.

`exit 1` with `(forked)` is the #697 failure. If it happens, check that you did not open the
browser after step 16. If you did, it is #795. Repeat Part G.

### 20. Verify by clicking

Go back to the browser (reopen `http://localhost:8000/` if you closed it) and reload the page.

**Expect:** the **Ask** screen. The restored settings include the skip from step 6, so the
welcome screen does not come back. If it does come back, click **Skip setup**.

Click **Settings**, scroll to **Your data**, and click **Verify the log**.

**Expect:** **Decisions — chain intact**, with the same count as step 19. This click's own record
is written after the check, so it shows up next time. **Interactions — chain intact** with
*N-after* records, and the same grey "Chain starts after a prune" note.

### 21. Restart and verify once more

```
podman compose restart api
```

Wait a few seconds, reload the browser tab, and click **Settings → Your data → Verify the log**.

**Expect:** both chains intact, the decisions count one higher than in step 20 (step 20's click),
and interactions still *N-after*. The restart is the same version as before, so it records no upgrade and does not start a
second chain.

---

## Cleanup

This machine now holds only the test history. To get your earlier Askwell data back, restore the
backup you took before starting (`docs/restore-release-test.md` §3.2, with `replace_existing`).
Otherwise set the retention window back to `12` on **Settings → Storage**. The six seeded
records, or the two that survived the prune, stay in the log. They cannot be deleted, and that is
the point.

---

## What was checked against the ticket's acceptance criteria

- **Prune removes interactions past the window on a real install.** Steps 11–13: four records
  pruned as `askwell_app`, on a machine whose permissions match a real install (step 14, line 5).
- **`askwell-verify` reports an intact chain after a restore.** Steps 18–21, with the startup
  version record having run first (step 17).
- **An ordinary path still cannot DELETE from an audit table.** Step 14, lines 1–4.
- **The development database's stray grant is corrected by migration.** Steps 1 and 14, line 5.
  The same check on the development database before migration `f4b8d2c6a915` listed `DELETE` for
  `askwell_app` on `audit_interactions` (#682's closing comment).
- **C6: only the named, recorded prune may delete.** Step 14, line 3 shows the function refuses
  without a record. The automated tests cover the cases that cannot be set up by hand: a record
  from an earlier transaction, a record followed by another, and a record whose count or boundary
  does not match what the cutoff would delete (`api/tests/test_log_prune.py`).

## Known gaps

Do not report these as defects in this ticket.

- **No screen can prune, back up or restore** (#487 for prune). Those steps use the terminal.
  Every check of their result goes through **Verify the log**.
- **A real clean-machine restore can still fork the decisions chain** (#795). The welcome
  screen's first load records the hardware check, and every installer runs that check, so
  opening Askwell before restoring gives the fresh machine its own first record. That is why
  Part G keeps the browser closed until the restore is done. It is #697's bug from a second
  writer, found during this ticket and not fixed here.
- **Clicking Verify the log also writes a decisions record.** On a fresh machine that, too,
  forks a restore that follows it. It belongs with #795.
- **A restore onto a clean machine needs `replace_existing`** (#597).
- **A restore onto a machine that already has its own log reports the chain as broken** (#574).
  This test restores only onto a machine that was emptied first.
- **Any code running as `askwell_app` that writes a truthful `interactions_pruned` record can call
  the function in the same transaction.** The record must describe exactly what is deleted, and
  it lands in the decisions log, which is never pruned. Reset's function has the same limit
  (#684). That is a limit of the design, and this document does not attempt it by hand.
- **The seeded records in step 4 are a stand-in for a month of real use.** They are hashed the
  way Askwell hashes its own records, which is why **Verify the log** accepts them. But they were
  not written by the ask path.
- **The upgrade record after a restore** (a later version starting on a restored machine) is not
  walked by hand, because it needs two builds. `test_restore.py` runs it as `askwell_app`.
