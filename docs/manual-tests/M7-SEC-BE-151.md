# Manual test — M7-SEC-BE-151, the optional passphrase: set, unlock, no recovery

**Ticket:** `M7-SEC-BE-151` — an optional passphrase that strengthens the existing
`M4-CONN-SEC-098` key derivation, with no recovery path anywhere, a wrong-passphrase refusal
that never reveals closeness, and credential-writing operations refusing rather than writing
unencrypted while the process is locked.
**Version under test:** `0.6.4`
**Time:** about 20 minutes, no native inference process required (nothing here touches
retrieval or generation).

**What is being checked.** `api/src/askwell/passphrase.py`'s `/settings/passphrase*` routes —
`GET /settings/passphrase` (status), `POST /settings/passphrase/strength`, `/set`, `/change`,
`/remove`, `/unlock` — registered in `app.py` via `register_passphrase`. This is a **backend-only
ticket**: read "Known gaps" before reporting anything about a missing screen as a defect.

**Where this stops on purpose.** Corpus encryption itself (the documents and chunks, not just
connection credentials) is `M7-SEC-BE-152`, out of scope here per the ticket's own line. There is
no settings screen for this feature yet — `docs/backlog/M7-someone-else-can-install-it.md`
`M7-SET-SEC-1xx` (the privacy-section ticket) says explicitly "the passphrase control is inert
until its own ticket lands," meaning this one. Everything below is exercised through the API
directly because that is the only surface this ticket built.

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

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait
about thirty seconds.

### 2. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 3. Open Askwell in a browser

```
http://127.0.0.1:8000
```

**You should see:** the app loads normally — first-run or the composer, depending on whether a
source has been added before. Open **Settings** by clicking through the app's own left-strip
navigation (not by typing a URL).

**You should see:** no passphrase control anywhere in Settings — no mention of it in the Privacy
section or elsewhere. This is the expected, checked-for state (see "Known gaps"), not something
to report.

### 4. Confirm the passphrase is off by default

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:**

```json
{ "enabled": false, "locked": false }
```

A fresh install with nobody having set one — matches the ticket's "off by default."

---

## Part A — strength feedback

### 5. Check a weak candidate

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/strength \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "short"}' | jq
```

**You should see:** `"meets_minimum": false`, `"strength": "weak"`, and feedback text telling you
to use at least 8 characters.

### 6. Check a strong candidate

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/strength \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "Correct-Horse-Battery-Staple-42!"}' | jq
```

**You should see:** `"meets_minimum": true`, `"strength": "strong"`, empty `feedback`.

---

## Part B — setting a passphrase requires the no-recovery acknowledgement

### 7. Try to set one without acknowledging

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/set \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "correct horse battery staple"}' | jq
```

**You should see:** HTTP 400 (add `-i` to the curl command to see the status line), body:

```json
{ "error": "Setting a passphrase requires acknowledging that there is no recovery." }
```

### 8. Confirm nothing was set

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:** still `{"enabled": false, "locked": false}`.

### 9. Set a passphrase, acknowledging no recovery

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/set \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "correct horse battery staple", "acknowledged_no_recovery": true}' | jq
```

**You should see:** `{"enabled": true}`.

### 10. Confirm status: enabled and unlocked

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:** `{"enabled": true, "locked": false}` — the process that just set it is
unlocked immediately, per the ticket's own note that there is nothing to prompt for right after
typing it.

### 11. Try setting a second passphrase over the first

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/set \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "a different one entirely", "acknowledged_no_recovery": true}' | jq
```

**You should see:** HTTP 400, `{"error": "A passphrase is already set. Use change instead."}`.

---

## Part C — the API process locks on restart, and a wrong passphrase refuses without hinting

### 12. Restart the API process

```
podman compose restart api
```

Wait about ten seconds for it to come back.

**You should see:** the unlock state was in-memory only for the process that just died —
confirm next.

### 13. Check status after restart

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:** `{"enabled": true, "locked": true}` — this is the "unlock prompt before
anything decrypts" requirement: the fact the API now reports is exactly what a restart-time
prompt would gate on.

### 14. Reload Askwell in the browser

Reload `http://127.0.0.1:8000`.

**You should see:** the app still loads and the composer/first-run screen still renders — there
is no unlock **prompt** in the UI yet (that is the paired frontend work, not built here); confirm
this is the case rather than assuming it, and note it under "Known gaps" rather than reporting it
as this ticket's defect.

### 15. Try unlocking with the wrong passphrase

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/unlock \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "not the right one"}' | jq
```

**You should see:** HTTP 401, `{"error": "Incorrect passphrase."}` — read this exact text; it must
not say anything like "close" or "almost" or give a hint. Confirm you are still locked:

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:** `{"enabled": true, "locked": true}`, unchanged.

### 16. Unlock with the correct passphrase

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/unlock \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "correct horse battery staple"}' | jq
```

**You should see:** `{"locked": false}`. Confirm status again:

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:** `{"enabled": true, "locked": false}`.

---

## Part D — a locked process refuses to write a new connection's credentials, it does not write them unencrypted

### 17. Restart the API again to re-lock it

```
podman compose restart api
```

Wait ten seconds, then confirm locked:

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:** `{"enabled": true, "locked": true}`.

### 18. Try adding a database connection while locked

Through the app's own **Settings → Connections → Add a connection** flow (click through, do not
call the endpoint from the browser's address bar), enter any host/port/database/username/password
— the values do not need to be real, since the refusal happens before any network attempt.

**You should see:** the request fails. If the web UI surfaces this cleanly you will see an error
message; either way, confirm what actually happened at the API level:

```
curl -s -i -X POST http://127.0.0.1:8000/sources/connection \
  -H 'Content-Type: application/json' \
  -d '{"engine": "postgresql", "host": "db.example", "port": 5432, "database": "x", "username": "u", "password": "p"}' \
  | head -5
```

**You should see:** HTTP 401, body `{"error": "Askwell is locked. Unlock with your passphrase
first."}` — this is the "pauses rather than writing unencrypted" acceptance criterion for the
one credential-writing path this ticket actually touches (`api/src/askwell/sources.py`'s
`/sources/connection` route). Confirm no `sources` row exists for it:

```
curl -s http://127.0.0.1:8000/sources | jq '.[] | select(.kind == "connection")'
```

**You should see:** no entry for `db.example` — the refusal happened before any row was written,
not a row written in a bad state.

### 19. Unlock and confirm the same request now succeeds in principle

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/unlock \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "correct horse battery staple"}' | jq
```

**You should see:** `{"locked": false}`. Re-run the same connection request from step 18 — it
will still fail (there is no real Postgres at `db.example`), but **you should see** a different
kind of failure this time: a connection/network error in the JSON body, not the `401`/"Askwell is
locked" message — confirming the lock, not the fake host, was what blocked step 18.

---

## Part E — changing the passphrase requires the current one and re-encrypts silently

### 20. Change with the wrong current passphrase

```
curl -s -i -X POST http://127.0.0.1:8000/settings/passphrase/change \
  -H 'Content-Type: application/json' \
  -d '{"current_passphrase": "wrong one", "new_passphrase": "a brand new passphrase!!"}' \
  | head -5
```

**You should see:** HTTP 401, `{"error": "Incorrect passphrase."}`.

### 21. Change with the correct current passphrase

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/change \
  -H 'Content-Type: application/json' \
  -d '{"current_passphrase": "correct horse battery staple", "new_passphrase": "a brand new passphrase!!"}' \
  | jq
```

**You should see:** `{"enabled": true}`.

### 22. Confirm the old passphrase no longer unlocks

```
podman compose restart api
```

Wait ten seconds, then:

```
curl -s -i -X POST http://127.0.0.1:8000/settings/passphrase/unlock \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "correct horse battery staple"}' \
  | head -5
```

**You should see:** HTTP 401 — the old passphrase is dead.

### 23. Confirm the new one works

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/unlock \
  -H 'Content-Type: application/json' \
  -d '{"passphrase": "a brand new passphrase!!"}' | jq
```

**You should see:** `{"locked": false}`.

---

## Part F — removing the passphrase states the consequence

### 24. Remove with the wrong passphrase

```
curl -s -i -X POST http://127.0.0.1:8000/settings/passphrase/remove \
  -H 'Content-Type: application/json' \
  -d '{"current_passphrase": "wrong"}' \
  | head -5
```

**You should see:** HTTP 401, `{"error": "Incorrect passphrase."}`.

### 25. Remove with the correct one

```
curl -s -X POST http://127.0.0.1:8000/settings/passphrase/remove \
  -H 'Content-Type: application/json' \
  -d '{"current_passphrase": "a brand new passphrase!!"}' | jq
```

**You should see:**

```json
{
  "enabled": false,
  "message": "The passphrase has been removed. Your library and stored credentials are decrypted with this machine's own key again — a stolen laptop is a data breach until a passphrase is set again."
}
```

Read the message text — it must state the consequence plainly, not just confirm success.

### 26. Confirm status is back to off

```
curl -s http://127.0.0.1:8000/settings/passphrase | jq
```

**You should see:** `{"enabled": false, "locked": false}`.

### 27. Confirm there is no reset/recovery route anywhere

```
curl -s http://127.0.0.1:8000/openapi.json | jq '.paths | keys[]' | grep -i passphrase
```

**You should see:** exactly six paths — `/settings/passphrase`, `/settings/passphrase/strength`,
`/settings/passphrase/set`, `/settings/passphrase/change`, `/settings/passphrase/remove`,
`/settings/passphrase/unlock`. No `reset`, no `recover`, no `forgot` — there is nothing to click
or call, which is the acceptance criterion "there is no recovery mechanism anywhere" made
concrete.

---

## Known gaps

- **No settings UI for this feature.** `docs/ux/settings.md` §4/§8 describe the passphrase
  control, strength meter, and no-recovery warning as UI, but no frontend component exists yet
  (`web/components/settings/` has no `passphrase.tsx`). `docs/backlog/M7-someone-else-can-install-it.md`
  records this explicitly as its own later ticket. Everything above is tested at the API level
  because that is genuinely all that has been built.
- **No unlock prompt on restart.** The acceptance criterion "restarting prompts for it before
  anything decrypts" is proven at the API level (`GET /settings/passphrase` reports
  `locked: true` after a restart, and every read/write path that needs the key raises `Locked`
  until unlocked) but there is no browser-side modal blocking the UI yet — the app renders
  normally with encrypted data simply inaccessible behind the scenes rather than visibly gating
  the screen. Do not report this as a defect in this ticket; it is the paired frontend work.
- **No export-while-unlocked UI to test.** The ticket's scope line "export offered while unlocked"
  and the edge case "export offered while still unlocked" describe UI framing around the existing
  export feature (`docs/ux/settings.md` §6 "Export everything"), not a new export mechanism this
  ticket builds. Nothing new to verify here beyond confirming the existing export endpoint is
  unaffected by lock state, which this walkthrough did not separately exercise.
- **Ingestion-pause is proven for connection credentials only.** The acceptance edge case "a
  passphrase set while ingestion is running — ingestion pauses and resumes after unlock" is
  implemented and tested here for the one credential-writing path this ticket actually touches:
  `POST /sources/connection` (`api/src/askwell/sources.py`, `crypto.CredentialsLocked` → 401).
  File/folder ingestion (`POST /sources`) and dump import (`POST /sources/dump`) do not encrypt
  document content under this key at all — that is `M7-SEC-BE-152`'s scope, not built yet — so
  there is no "pause" behaviour to test for those routes, and none was found in the diff.
- **Cross-process unlock gap, filed rather than fixed here.** `api` and `worker` are separate
  processes with independent in-memory unlock state (`passphrase.py`'s own module docstring).
  Steps above only exercise the `api` process. A live connection's background health check or
  introspection running in `worker` stays permanently `CredentialsLocked` once a passphrase is
  set, regardless of whether `api` is unlocked — this was not separately re-verified here since
  it is called out and filed as its own architectural gap in the module docstring.
- **Backup/restore interaction** (encrypted backup, restore on a machine without the passphrase)
  is explicitly out of scope per the ticket's own "Backup interaction is handled in the backup
  tickets" line — not exercised here.
