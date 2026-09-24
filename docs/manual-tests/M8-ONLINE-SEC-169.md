# Manual test — M8-ONLINE-SEC-169, per-conversation egress authorisation for exactly one destination

**Ticket:** `M8-ONLINE-SEC-169` — switching one conversation to online AI authorises exactly one
destination, for that conversation only, time-bound, revoked on disable and on restart, with
permitted requests counted per conversation.
**Version under test:** `0.7.39` (check `cat VERSION` — update this line if it has moved on).
**Time:** about 40 minutes.
**Who can run it:** Part A by anyone with a browser. Parts B–F also need a terminal and
`podman compose exec`, for the reason below.

**What is being checked.** `api/src/askwell/online.py` (`GET`/`POST`/`DELETE
/conversations/{id}/online`, restart revocation), the conversation grant in
`api/src/askwell/egress.py` (credential check, per-conversation counter, the one-second recheck
that cuts an open tunnel), `api/src/askwell/network.py` (`authorised`,
`permitted_by_conversation`), `api/src/askwell/reset.py` (reset revokes everything), and the
per-conversation list in `web/components/settings/network-activity.tsx`.

---

## Read this first — what can and cannot be clicked today

This ticket builds the **authorisation**, not the switch a user presses. The switch in a
conversation (`M8-ONLINE-FE-171`) and in Settings (`M8-KEY-FE-174`) do not exist yet, and there
is no online provider (`M8-ONLINE-BE-170`), so nothing in the app makes an outbound request. The
**Online AI** section in Settings is still the inert placeholder from `M7-SET-FE-150`.

So the walkthrough has two kinds of steps:

- **Clicking steps** walk the real path: cold start, ask questions, open Settings from the rail,
  and read the Network activity statement this ticket extends. Do these every time — they are
  how a broken rail or a Settings page that no longer loads gets caught.
- **Terminal steps** stand in for the switch that has not been built. Each is labelled
  **Stand-in**. They call the same endpoints the switch will call, and speak to the proxy the
  way the provider will. Where this document says "turn online AI on for conversation A", the
  stand-in is the only way to do that today.

**Nothing leaves this machine during this test.** The destination is set to `redis:6379`,
Askwell's own internal Redis, which is the same trick the implementer used. A permitted
request goes from the `api` container, through the egress proxy, to another container on the
same internal network. Do **not** set a real internet host here: that would be a real outbound
request, and C1 permits one only for a real user decision.

---

## Before you start

1. In the repository's `.env` (copy `.env.example` if there is none), set:

   ```
   ASKWELL_ONLINE_AI_DESTINATION=redis:6379
   ASKWELL_ONLINE_AI_AUTHORISATION_TTL_SECONDS=14400
   ```

2. Bring the stack up with the built frontend. The API serves `web/out`, not live source:

   ```
   podman compose up -d
   scripts/dev.sh db upgrade head
   scripts/dev.sh web-build
   podman compose up -d --force-recreate api
   ```

   **Expect:** `podman compose exec api env | grep ONLINE_AI_DESTINATION` prints
   `ASKWELL_ONLINE_AI_DESTINATION=redis:6379`.

3. Save the helper script below on the host as `/tmp/askwell-tunnel.py`. It opens one connection
   through the egress proxy to `redis:6379` the way a provider call would. It presents a
   conversation's credential if you give it one, then sends `PING` if the proxy lets it through.

   ```python
   import base64, os, socket, time

   conv = os.environ.get("CONV", "")
   token = os.environ.get("TOKEN", "")
   hold = int(os.environ.get("HOLD", "0"))

   s = socket.create_connection(("egress-proxy", 3128), timeout=10)
   request = "CONNECT redis:6379 HTTP/1.1\r\nHost: redis:6379\r\n"
   if conv:
       credential = base64.b64encode(f"conversation-{conv}:{token}".encode()).decode()
       request += f"Proxy-Authorization: Basic {credential}\r\n"
   s.sendall((request + "\r\n").encode())
   status = s.recv(1024).decode(errors="replace").splitlines()[0]
   print("proxy said:", status)
   if " 200 " in status:
       s.sendall(b"PING\r\n")
       print("destination said:", s.recv(64).decode().strip())
       if hold:
           print(f"tunnel held open for {hold} seconds - turn online AI off now")
           time.sleep(hold)
           try:
               s.sendall(b"PING\r\n")
               data = s.recv(64)
               print("after turning off:", data.decode().strip() or "connection closed by the proxy")
           except OSError as error:
               print("after turning off: connection cut -", type(error).__name__)
   ```

   You run it as `podman compose exec -T api python3 - < /tmp/askwell-tunnel.py`, adding
   `-e CONV=… -e TOKEN=…` when a step says to.

4. Take a session for the terminal steps, the same way the interface does. Re-run this if a
   later `curl` answers `No session.`:

   ```
   curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null
   ```

---

## Part A — cold start, by clicking

### 1. Open Askwell

In a browser (a private window if this browser has used Askwell before), open
`http://127.0.0.1:8000/`. If first-run setup appears, complete it as prompted.

**Expect:** the Ask screen loads. The left rail shows **Ask**, **Library**, **Clarifications**,
**Memory** and **Settings**.

### 2. Read the resting state in Settings before anything else

Click **Settings** in the left rail and scroll to **Privacy and security** → **Network
activity**.

**Expect:** a sentence of the form "**N** outbound requests permitted · **M** refused, measured
by the egress proxy itself. Not a setting — this is what actually happened." Write down **N**
and **M**. On a machine that has never run this test there is **no** line reading "Permitted,
by the conversation that made them:". If there is one from an earlier run, write down its rows
so you can tell new rows from old.

### 3. Confirm the Online AI control is still inert

Scroll to the **Online AI** section on the same page.

**Expect:** a **Use online AI** switch with "Off. Not available yet." beside it. Click it.
**Expect:** it stays off and a message appears: "Online AI is not available yet, so it cannot
be turned on. …". This ticket must **not** have wired that switch to anything. If it turns on,
that is a defect.

### 4. Make conversation A

Click **Ask** in the left rail. Type any question, for example `What is in my library?`, and
send it.

**Expect:** an answer or an abstention appears. Either is fine. This creates conversation A.

### 5. Make conversation B

Reload the page (the browser's reload button). Ask a different question, for example
`Summarise my most recent document.`

**Expect:** an answer or an abstention appears. A reload starts a new conversation, because a
conversation does not yet survive a refresh (issue #156). This creates conversation B.

### 6. Find the two conversations' ids

**Stand-in** — the app does not show a conversation's id.

```
scripts/dev.sh psql -c "SELECT id, ai_backend, created_at FROM conversations ORDER BY created_at DESC LIMIT 2;"
```

**Expect:** two rows, both with `ai_backend` = `local`. The newer is **B**, the older is **A**.
Copy both ids. The steps below write them as `$A` and `$B`, so set them in your terminal:

```
A=<older id>; B=<newer id>
```

---

## Part B — turn online AI on for A only

### 7. Both conversations start local

**Stand-in.**

```
curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/conversations/$A/online | jq
curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/conversations/$B/online | jq
```

**Expect:** both show `"ai_backend": "local"`, `"destination": null`, `"available": true`.
(`available: false` with a reason about no provider means step 1 of *Before you start* did not
take. Recreate the `api` container.)

### 8. Turn online AI on for A

**Stand-in** for the switch `M8-ONLINE-FE-171` will add.

```
curl -s -b /tmp/askwell.cookies -X POST http://127.0.0.1:8000/conversations/$A/online | jq
```

**Expect:** `"ai_backend": "online"`, `"destination": "redis:6379"`, and `"expires_in_seconds":
14400`.

### 9. Turning it on twice is not two decisions

Run step 8's command again.

**Expect:** the same answer. `expires_in_seconds` is now a little under 14400, not reset to
14400. Nothing is renewed.

### 10. Exactly one destination, for exactly one conversation

```
curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq '.authorised'
curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/conversations/$B/online | jq '.ai_backend'
podman compose exec redis redis-cli --scan --pattern 'askwell:egress:conversation:*'
```

**Expect:** `authorised` holds **one** entry, A's id with `redis:6379`. B still reads `"local"`.
Redis holds exactly one key, `askwell:egress:conversation:<A's id>`.

### 11. The decision was recorded

```
scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind LIKE 'online_ai_%' ORDER BY occurred_at;"
```

**Expect:** exactly one `online_ai_enabled` row for this run (step 9 added none), whose payload
names A's `conversation_id`, `"destination": "redis:6379"` and `"ttl_seconds": 14400`.

### 12. Settings still reads the same

Back in the browser, click **Settings** in the left rail and scroll to **Network activity**.

**Expect:** permitted is still **N** from step 2. Turning online AI on sends nothing by itself.
No new row has appeared under "Permitted, by the conversation that made them:".

---

## Part C — only A's own requests get out

### 13. Nothing without a credential

**Stand-in** for "a dependency, or anything else on the machine, tries the same destination".

```
podman compose exec -T api python3 - < /tmp/askwell-tunnel.py
```

**Expect:** `proxy said: HTTP/1.1 403 Forbidden`. The destination is authorised, but not for
anonymous traffic.

### 14. The local conversation has no route out

**Stand-in** for "conversation B tries to reach the same destination".

```
podman compose exec -T -e CONV=$B -e TOKEN=anything api python3 - < /tmp/askwell-tunnel.py
```

**Expect:** `proxy said: HTTP/1.1 403 Forbidden`. This is the ticket's first edge case: two
conversations, one online and one local, and the local one cannot get out.

### 15. A's id with the wrong credential is refused

```
podman compose exec -T -e CONV=$A -e TOKEN=guessed api python3 - < /tmp/askwell-tunnel.py
```

**Expect:** `proxy said: HTTP/1.1 403 Forbidden`. Knowing a conversation's id is not enough.

### 16. Refusals are counted as refusals

Reload Settings and read **Network activity**.

**Expect:** refused is **M + 3** (or more, if something else was refused meanwhile). Permitted is
still **N**. The "Most recent refusals" list includes entries naming `redis:6379`.

### 17. A's own credential gets through, three times

A's real credential exists only inside the running API process, by design, and there is no
provider yet to use it. **Stand-in:** replace A's grant with one under a credential you know.
This is the same call `enable` makes.

```
podman compose exec -T api python3 -c "
import asyncio
from askwell import egress
from askwell.config import load_settings
asyncio.run(egress.open_conversation_grant(load_settings(), conversation_id='$A',
    destination='redis:6379', token='manual-test-token', ttl_seconds=600))
"
for i in 1 2 3; do
  podman compose exec -T -e CONV=$A -e TOKEN=manual-test-token api python3 - < /tmp/askwell-tunnel.py
done
```

**Expect:** three times, `proxy said: HTTP/1.1 200 Connection Established` followed by
`destination said: +PONG`.

### 18. The three permitted requests are attributed to A

Reload Settings and read **Network activity**.

**Expect:** permitted is **N + 3**. A line reads "Permitted, by the conversation that made
them:", followed by a row `Conversation <first 8 characters of A's id> → redis:6379: 3 · online
now`. No row names B. This is the ticket's real-world scenario: three permitted requests,
attributable to one conversation.

### 19. A grant Askwell did not open is not adopted

Step 17 replaced A's grant behind the API's back. Ask the API about A:

```
curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/conversations/$A/online | jq '.ai_backend'
podman compose exec redis redis-cli --scan --pattern 'askwell:egress:conversation:*'
```

**Expect:** `"local"`, and Redis holds no conversation key. The API found a grant whose
credential it did not mint, closed it, and put A back to local. It did not keep the door open.
Re-run step 11's query. **Expect:** a new `online_ai_revoked` row for A, reason `lapsed`,
destination `redis:6379`.

---

## Part D — turning it off, and a request in flight

### 20. Turn A on again, then open a tunnel and hold it

**Stand-in.** Run step 8 again (**Expect:** `"online"`). Then repeat step 17's first command
only, to put a known credential on A's grant. Now open a tunnel and hold it for 15 seconds:

```
podman compose exec -T -e CONV=$A -e TOKEN=manual-test-token -e HOLD=15 api python3 - < /tmp/askwell-tunnel.py
```

**Expect:** `200 Connection Established`, `+PONG`, then "tunnel held open for 15 seconds - turn
online AI off now".

### 21. Turn A off while that tunnel is open

In a **second** terminal, within the 15 seconds:

```
curl -s -b /tmp/askwell.cookies -X DELETE http://127.0.0.1:8000/conversations/$A/online | jq '.ai_backend'
```

**Expect:** `"local"` at once. When the first terminal's 15 seconds are up it prints either
`after turning off: connection closed by the proxy` or `after turning off: connection cut - …`.
It does **not** print a second `+PONG`. This is the decided in-flight behaviour: **cancelled,
not completed**. The proxy re-reads the grant every second and cuts the open tunnel when the
grant is gone.

### 22. And nothing new gets out

```
podman compose exec -T -e CONV=$A -e TOKEN=manual-test-token api python3 - < /tmp/askwell-tunnel.py
curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq '.authorised'
```

**Expect:** `403 Forbidden`, and `authorised` is `[]`.

### 23. The revocation was recorded, and the settings row stays honest

Re-run step 11's query. **Expect:** a new `online_ai_revoked` row for A with `"reason":
"disabled"` and `"destination": "redis:6379"`.

Reload Settings. **Expect:** the row for A still shows its permitted count (4 now, counting step
20's tunnel), but **without** "· online now". The count is what happened; the marker is what is
open.

---

## Part E — restart and crash do not bring it back

### 24. A clean restart

**Stand-in** for turning online AI on: run step 8 for A. Then confirm Redis holds A's key (the
`--scan` command from step 10). Restart Askwell:

```
podman compose restart api egress-proxy
```

**Expect,** once the API is back (the browser reloads the Ask screen normally):

- `podman compose exec redis redis-cli --scan --pattern 'askwell:egress:conversation:*'` prints
  nothing.
- `curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/conversations/$A/online | jq
  '.ai_backend'` prints `"local"`. Re-take the session (step 4 of *Before you start*) if it says
  `No session.`
- Step 11's query shows a new `online_ai_revoked` row for A with `"reason": "restart"` and
  `"destination": "redis:6379"`.

### 25. A crash mid-conversation

Run step 8 for A again and confirm the Redis key is there. This time kill the stack's API and
proxy outright instead of stopping them:

```
podman compose kill api egress-proxy
podman compose up -d
```

**Expect:** the same three results as step 24. Redis is `appendonly`, so the grant key survives
the kill. It is gone after startup because both the proxy and the API close every grant when
they start, and the API writes a `restart` record for A. A surviving authorisation nobody asked
for would be a failure here.

### 26. Settings after the restart

Click **Ask** in the rail, then **Settings**, and read **Network activity**.

**Expect:** the statement loads (not "Unavailable"). A's row is still listed with its count, and
no row says "· online now".

---

## Part F — reset, and the log still verifies

### 27. The chains are intact

On the Settings page, find **Verify the log** and click it.

**Expect:** "Checking…", then a report in which **Decisions** is intact. Every enable and revoke
above went through the same hash-chained store.

### 28. Optional: a reset revokes everything

**Only on a disposable install** — a reset deletes the library. Turn A on (step 8). Then, in
Settings, use the reset control under **Your data** and confirm it.

**Expect:** after the reset, `redis-cli --scan --pattern 'askwell:egress:conversation:*'`
prints nothing. There is no revocation record, because the reset emptied the audit tables with
the conversations. The per-conversation permitted counts in Network activity **survive** the
reset, as the refused count already does.

### 29. Put the configuration back

Clear `ASKWELL_ONLINE_AI_DESTINATION` in `.env` (leave it empty) and run `podman compose up -d
--force-recreate api`. Then re-run step 7 for either conversation.

**Expect:** `"available": false` and an `unavailable_reason` beginning "Online AI is not
available: no online provider is configured". Running step 8 now answers with an `error` and
HTTP `409`, and nothing is opened.

---

## Known gaps

Do not report these as defects. They are deliberately not built yet, or not practical to
exercise here.

- **There is no switch to turn online AI on.** The in-conversation control and marker are
  `M8-ONLINE-FE-171`. The Settings key and provider setup are `M8-KEY-FE-174` and
  `M8-KEY-BE-173`. Until then every enable and disable in this document is a terminal stand-in,
  and the Settings **Online AI** switch stays "Off. Not available yet."
- **Nothing is actually sent.** There is no provider (`M8-ONLINE-BE-170`). The permitted
  requests in Part C were made by the helper script with a credential planted in step 17, not
  by Askwell answering a question. When the provider lands it must present
  `askwell.online.proxy_credentials(conversation_id)`. Without it the proxy refuses it, which is
  intended.
- **The destination comes from `ASKWELL_ONLINE_AI_DESTINATION`**, empty by default, so a fresh
  install cannot turn online AI on at all (`409`). `M8-KEY-BE-173` replaces this with the
  provider the user's own key belongs to.
- **"The conversation ends" has no button.** Askwell has no close, archive or delete for a
  conversation. The authorisation ends when it is turned off, when its 4-hour bound lapses,
  on a restart of the API or the proxy, or on a reset. The 4-hour lapse is not walked here. A
  lapse is recorded as `lapsed` when it is next noticed, not at the moment of expiry. Step 19
  exercises the same reconciliation path.
- **"Immediately" means within one second for an open connection.** A new request is refused
  at once, but a tunnel already open is cut on the proxy's one-second recheck. A request fully
  sent inside that second has already left. `docs/decisions.md`, 2026-09-24.
- **The Settings row shows only the first 8 characters of a conversation id**, and no title.
  Linking a row to its conversation needs a conversation list, which does not exist yet.
- **Redis has no authentication on the internal network.** Anything already able to write to
  Redis can plant a grant, as step 17 does on purpose. The credential guards against accidental
  use, not a compromised container. Tracked as issue #730.
- **The conversation id is not shown anywhere in the app**, which is why step 6 reads it from
  the database.
