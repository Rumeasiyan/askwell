# Manual test — M7-UPDATE-BE-161, the update check agreed to at installation

**Ticket:** `M7-UPDATE-BE-161` — a stored answer (`not_asked`/`yes`/`no`), a weekly scheduled
check when the answer is `yes`, a manual "check now" that works regardless of the stored answer,
and exactly one egress-proxy destination opened only while the answer is `yes` or a manual check
is in flight.
**Version under test:** `0.6.9`
**Time:** about 20 minutes, no native inference process required (nothing here touches
retrieval or generation).

**What is being checked.** `api/src/askwell/update_check.py`'s `/settings/update-check*` routes —
`GET /settings/update-check` (status), `POST /settings/update-check` (record the answer),
`POST /settings/update-check/run` (manual check) — registered in `app.py` via
`register_update_check`. The weekly half, `maybe_run_scheduled_check`, runs inside
`api/src/askwell/worker.py`'s cron job (`run_update_check`), polled every
`update_check_poll_seconds` (default 3600s) and only actually firing once
`update_check_interval_seconds` (default 604800s, one week) has elapsed since the last check.
This is a **backend-only ticket**: read "Known gaps" before reporting anything about a missing
install prompt or update-notification screen as a defect.

**Where this stops on purpose.** The installer's own prompt wording and presentation
(`M7-PACK-DEPLOY-139`/`140`/`141`) and how a found update is shown to the user
(`M7-UPDATE-FE-162`) are both out of scope — this ticket only learns a newer version exists and
records the answer. Everything below is exercised through the API directly because that is the
only surface this ticket built; there is no settings-screen control yet
(`docs/ux/settings.md` §7's "About" section describes one, but `web/components/settings/` has no
`about.tsx` or `update-check.tsx`).

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

### 3. Open Askwell in a browser

```
http://127.0.0.1:8000
```

**You should see:** the app loads normally — first-run or the composer, depending on whether a
source has been added before. Click through the app's own left-strip navigation into
**Settings** (not by typing a URL).

**You should see:** no update-check control anywhere in Settings — no "About" section, no
version display, no "check for updates" button. This is the expected, checked-for state (see
"Known gaps"), not something to report.

### 4. Confirm a fresh install has never been asked

```
curl -s http://127.0.0.1:8000/settings/update-check | jq
```

**You should see:**

```json
{
  "answer": "not_asked",
  "last_checked_at": null,
  "latest_known_version": null,
  "update_available": false,
  "last_result": null
}
```

The third state, distinct from `no` — nobody has answered yet.

### 5. Confirm the egress proxy shows nothing for this destination

```
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq
```

**You should see:** no entry for `raw.githubusercontent.com` under either `permitted` or
`refused` — the door was never touched.

---

## Part A — answering "no" never opens the destination

### 6. Answer no

```
curl -s -X POST http://127.0.0.1:8000/settings/update-check \
  -H 'Content-Type: application/json' \
  -d '{"answer": "no"}' | jq
```

**You should see:** `"answer": "no"` in the response, other fields unchanged from step 4.

### 7. Confirm the egress proxy still shows nothing

```
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq
```

**You should see:** still no entry for `raw.githubusercontent.com`.

### 8. Wait and confirm the scheduled check never fires

The worker's cron polls every `update_check_poll_seconds` (default one hour), but only runs a
check once `update_check_interval_seconds` (default one week) has passed — and only when the
answer is `yes`. With the answer `no`, no wait is needed to prove this; re-check status:

```
curl -s http://127.0.0.1:8000/settings/update-check | jq '.last_checked_at'
```

**You should see:** `null` — no check has ever run.

---

## Part B — answering "yes" opens exactly one destination and records a decision

### 9. Answer yes

```
curl -s -X POST http://127.0.0.1:8000/settings/update-check \
  -H 'Content-Type: application/json' \
  -d '{"answer": "yes"}' | jq
```

**You should see:** `"answer": "yes"`.

### 10. Confirm the egress proxy now permits exactly the feed host

```
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq
```

**You should see:** `raw.githubusercontent.com:443` (or equivalent) listed under permitted
destinations — the one host `_feed_destination` names, nothing else added.

### 11. Confirm the decision was recorded

```
curl -s http://127.0.0.1:8000/settings/update-check | jq '.answer'
```

Then check the decisions store recorded it (via the audit-verify tool, since there is no HTTP
listing of individual decisions):

```
podman compose exec api askwell-verify
```

**You should see:** the verify command reports the decisions chain intact (no tamper warnings).
If you have direct `psql` access:

```
scripts/dev.sh psql -c "SELECT kind FROM audit_decisions WHERE kind = 'update_check_enabled' ORDER BY id DESC LIMIT 1;"
```

**You should see:** one row, `update_check_enabled`.

### 12. Re-answer yes again (idempotency)

```
curl -s -X POST http://127.0.0.1:8000/settings/update-check \
  -H 'Content-Type: application/json' \
  -d '{"answer": "yes"}' | jq
```

**You should see:** `"answer": "yes"`, same as before — re-asserting an unchanged answer must
not add a second decision record. Confirm:

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_decisions WHERE kind = 'update_check_enabled';"
```

**You should see:** `1`, not `2`.

---

## Part C — a manual check works, sends exactly the stated payload, and reports what it found

### 13. Run a manual check while the answer is yes

```
curl -s -X POST http://127.0.0.1:8000/settings/update-check/run | jq
```

**You should see:** `last_result` is `"ok"` or `"unreachable"` depending on whether
`raw.githubusercontent.com` is reachable from this machine, `last_checked_at` is now a recent
timestamp. If `"ok"`, `latest_known_version` holds the value from the published `VERSION` file
on the `main` branch, and `update_available` reflects whether that is newer than this install's
own version (`0.6.9`).

### 14. Confirm what the request actually carried

The request sends only a `User-Agent: Askwell/<version>` header and a `GET` against
`settings.update_feed_url` — no request body, no query parameters, no other headers. This
matches the "current version, nothing else" claim `docs/ux/settings.md` §7 states before the
question is answered. Confirm by reading the code path exercised:

```
grep -n "headers=" api/src/askwell/update_check.py
```

**You should see:** the single `User-Agent` header, with the comment stating it is the whole
payload. (A live packet capture is the stronger proof if you have `tcpdump`/`mitmproxy`
available; this repository has no automated capture harness for this ticket.)

### 15. Turn the answer off after yes, confirm the destination closes

```
curl -s -X POST http://127.0.0.1:8000/settings/update-check \
  -H 'Content-Type: application/json' \
  -d '{"answer": "no"}' | jq
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq
```

**You should see:** `raw.githubusercontent.com` no longer listed under permitted destinations —
the door closed in the same moment the answer changed.

### 16. Run a manual check while the answer is no

```
curl -s -X POST http://127.0.0.1:8000/settings/update-check/run | jq
```

**You should see:** the check still runs (`last_checked_at` advances, `last_result` updates) —
a manual check is a deliberate act regardless of the standing answer. Immediately after, confirm
the destination is closed again:

```
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq
```

**You should see:** no permitted entry for `raw.githubusercontent.com` — the manual check opened
the door only for its own request and closed it again, since the standing answer is `no`.

### 17. Confirm only `yes` or `no` may be recorded as an answer

```
curl -s -i -X POST http://127.0.0.1:8000/settings/update-check \
  -H 'Content-Type: application/json' \
  -d '{"answer": "not_asked"}' | head -5
```

**You should see:** HTTP 422 (Pydantic rejects `"not_asked"` — the request body only accepts the
literal `"yes"`/`"no"`) — there is no route by which `not_asked` can be written back once it has
been left.

---

## Part D — an upgrade never answers on the user's behalf

### 18. Restart the API and worker

```
podman compose restart api worker
```

Wait about ten seconds.

**You should see:** nothing about the stored answer changes — restarting/upgrading the process
does not touch the `settings` table. Confirm:

```
curl -s http://127.0.0.1:8000/settings/update-check | jq '.answer'
```

**You should see:** `"no"` — whatever was last recorded in step 15, unchanged by the restart.
There is no install-time-only code path here that could re-ask or silently flip the answer; an
install that was truly never asked (see step 4, before this walkthrough answered anything) stays
`not_asked` through any number of restarts for the same reason.

---

## Part E — an unreachable feed is silent, not an error the user has to dismiss

### 19. Point the feed at an address that will not respond

This requires overriding `UPDATE_FEED_URL`/`UPDATE_FEED_HOST` for one run — check
`.env.example` for the variable names, set them to an unreachable address (for example
`https://127.0.0.1:1/version`) in `.env`, then:

```
podman compose up -d --force-recreate api worker
curl -s -X POST http://127.0.0.1:8000/settings/update-check \
  -H 'Content-Type: application/json' \
  -d '{"answer": "yes"}' | jq
curl -s -X POST http://127.0.0.1:8000/settings/update-check/run | jq
```

**You should see:** HTTP 200 back from `/settings/update-check/run` (the endpoint itself never
errors), `"last_result": "unreachable"`, `"latest_known_version"` unchanged from whatever it
already was (`null` on a fresh answer), and no exception surfaced to the caller — the failure is
logged (`update_check_unreachable`) and swallowed, not raised as a user-facing error. Revert
`.env` and `--force-recreate` again afterwards to restore the real feed URL.

---

## Known gaps

- **No settings UI for this feature.** `docs/ux/settings.md` §7 describes an "About" section
  with an update-check opt-in and a "check now" control, but no frontend component exists yet —
  `web/components/settings/` has neither an `about.tsx` nor an `update-check.tsx`. Everything
  above is tested at the API level because that is genuinely all that has been built. Building
  that screen, and presenting a found update once the check has run, is `M7-UPDATE-FE-162`.
- **No installer prompt to test.** The actual first-run question — "may Askwell check for new
  versions?" — is presented by the installers (`M7-PACK-DEPLOY-139`/`140`/`141`), not this
  ticket. This ticket only provides the mechanism the installer's answer writes into
  (`POST /settings/update-check`). An install reached through `podman compose up` (as this
  walkthrough does) starts with `not_asked` because nothing asked it, which is correct for this
  environment but is not the installer flow itself.
- **No packet capture was run.** Step 14 confirms the payload by reading the code path
  (`_fetch`'s single `User-Agent` header, no body, no other headers) rather than a live network
  capture — this repository has no automated capture harness for this ticket, and the sandbox
  environment does not have `tcpdump`/`mitmproxy` set up. A manual capture with either tool on a
  real machine is the stronger proof if this needs re-verifying.
- **The scheduled weekly check was not observed running live.** Waiting a full week (or
  reducing `update_check_interval_seconds` to something short via `.env` and restarting the
  worker) was not done here; the unit/integration coverage in `api/tests/test_update_check.py`
  (`test_the_scheduled_check_runs_once_when_due`,
  `test_the_scheduled_check_does_not_run_again_inside_the_week`,
  `test_a_month_offline_produces_one_check_not_a_backlog`) exercises this logic directly against
  a real database and is the stronger proof for the weekly-gate behaviour; this walkthrough
  proves only that the manual and answer-driven paths work end to end against a running stack.
