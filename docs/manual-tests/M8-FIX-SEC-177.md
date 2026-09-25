# Manual test — M8-FIX-SEC-177, Redis authentication, one user per service

**Ticket:** `M8-FIX-SEC-177`. Askwell keeps a small internal message store, Redis. It is also
where Askwell records what may leave your machine: a web search you asked for, an update check
you agreed to, a conversation you switched to online AI. The egress proxy is the part of Askwell
that lets a connection out, and it trusts whatever Redis says. Until this ticket, any part of
Askwell could write to Redis without a password. That included the worker, which reads your
documents. Now:

- a connection with no password is refused outright;
- each part of Askwell logs in as its own Redis user, and each user can reach only the keys it
  uses;
- only the API can write a permission to leave the machine. The proxy can only read one, and
  the worker cannot touch one at all;
- a missing password stops Askwell from starting. It never falls back to running with no
  password.

**Version under test:** `0.7.46`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 45 minutes. Most of it is the two builds, one file indexing, and one answer on
CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal starts Askwell and does the parts no
screen can do: it logs in to Redis as one of Askwell's users to show what that user is refused.
Those steps are labelled **Stand-in**.

**What is being checked.**

- `deploy/redis/users.acl`: the five Redis users and what each one may do.
- `deploy/redis/start.sh`: Redis's new entrypoint. It refuses to start without all three
  passwords and fills the ACL from `.env`.
- `api/src/askwell/redis_client.py`: every Redis connection logs in as its own service's user.
  The API, the worker and the proxy refuse to start without one.
- `compose.yaml`: each service is given its own user and password. Voice is given none.
- `deploy/{linux,macos}/lib.sh` `ensure_redis_passwords` and `deploy/windows/lib.ps1`
  `Set-AskwellRedisPasswords`: the installers generate the passwords, on upgrades too.

---

## Read this first

**There is nothing new to see on screen.** This ticket changes no screen. It adds a lock
underneath all of them. So the walkthrough does two things:

- **Clicking steps** walk Askwell's normal path from a cold start: add a file, ask, search the
  web, turn on online AI. Every one of those uses Redis, now through a password. If any of them
  breaks, this ticket broke it. That is the ticket's own acceptance criterion: *everything that
  worked before still works*.
- **Stand-in steps** log in to Redis from the terminal as each of Askwell's users in turn and try
  the things that user must not do. No screen shows a Redis refusal, so this is the only way to
  see one.

**Nothing leaves this machine during this test.** The web search uses Askwell's built-in
**fixture** provider, which answers from recorded results and makes no connection. The online AI
provider below, `api.provider.example:443`, is a made-up name that does not exist. **Do not**
enter a real key for a real provider.

> **Security note.** The Redis passwords in `.env` are credentials, like the database's. The
> stand-in helper below reads them from `.env` without printing them. Do not paste a password
> into an issue, a chat, or this document's results. If you record a result, record the refusal
> text, not the command line with a password in it.

**Record every refusal exactly as printed.** The expected texts below were copied from a live
run. Different wording is worth a note, even if the step still refused.

---

## Before you start

> **Warning: the cold start in Part B deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds now.
> If you are unsure, use **Settings → Your data → Export everything** first.

### 1. Back up your `.env`

```
cd ~/external/quantum-plus/askwell
cp .env /tmp/askwell-env-backup-177
```

If there is no `.env` yet, run `cp .env.example .env` and put any word after each blank
`POSTGRES_*` and `SANDBOX_*` password.

### 2. One test file

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then copy one file
from the fixture corpus:

```
rm -rf /tmp/askwell-test-177
mkdir -p /tmp/askwell-test-177/files
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-177/files/
ls /tmp/askwell-test-177/files
```

**You should see:** `handbook_a.pdf`.

### 3. Turn on the fixture web search

In `.env`, set:

```
ASKWELL_WEB_SEARCH_PROVIDER=fixture
```

The fixture provider never connects to anything. Askwell still opens and closes a real web
search permission in Redis around it, and that permission is the Redis write Part D checks.

### 4. The stand-in helper

Paste this into the terminal you will use for stand-ins. It logs in to Redis as one of
Askwell's users, taking that user's password from `.env`, and runs one Redis command:

```
askwell_redis() { user="$1"; shift; pass="$(grep "^REDIS_$(printf '%s' "$user" | tr a-z A-Z)_PASSWORD=" .env | cut -d= -f2)"; podman compose exec -T -e REDISCLI_AUTH="$pass" redis redis-cli --user "$user" "$@"; }
```

You use it as `askwell_redis worker PING`. The first word is the user: `api`, `worker` or
`proxy`. If you open a new terminal, paste it again. Ignore the line `>>>> Executing external
compose provider …` that `podman compose` prints before every answer.

---

## Part A — an install that predates this ticket gets its passwords

This is the upgrade edge case. An install from before `0.7.46` has a `.env` with no Redis
passwords, and `podman compose` refuses to start without them. The installer must add them
rather than leave Redis open or refuse. The full installer needs the desktop shell built, so
this runs the installer's own function on a **copy** of your `.env`. Your real `.env` is not
touched in this Part.

1. **Stand-in** — make a copy that looks like an old install, with no Redis lines: ☐

   ```
   grep -v '^REDIS_' .env > /tmp/askwell-old.env
   grep -c '^REDIS_' /tmp/askwell-old.env
   ```

   **You should see:** `0`.

2. **Stand-in** — run the Linux installer's password step on it, then look at the result without
   printing the passwords: ☐

   ```
   bash -c 'source deploy/linux/lib.sh && ensure_redis_passwords /tmp/askwell-old.env'
   grep '^REDIS_' /tmp/askwell-old.env | sed -E 's/=.*/=<hidden>/'
   grep '^REDIS_' /tmp/askwell-old.env | cut -d= -f2 | awk '{print length}'
   grep '^REDIS_' /tmp/askwell-old.env | cut -d= -f2 | sort -u | wc -l
   ```

   **You should see:** three lines, `REDIS_API_PASSWORD=<hidden>`,
   `REDIS_WORKER_PASSWORD=<hidden>` and `REDIS_PROXY_PASSWORD=<hidden>`. Then `64` three times.
   Then `3`, which means the three passwords are all different.

3. **Stand-in** — run it again. A second install must not change a password you already have: ☐

   ```
   cp /tmp/askwell-old.env /tmp/askwell-old.before
   bash -c 'source deploy/linux/lib.sh && ensure_redis_passwords /tmp/askwell-old.env'
   diff /tmp/askwell-old.before /tmp/askwell-old.env && echo unchanged
   ```

   **You should see:** `unchanged`.

4. **Stand-in** — a placeholder copied from `.env.example` is replaced too: ☐

   ```
   printf 'REDIS_API_PASSWORD=change-me-redis-api\nREDIS_WORKER_PASSWORD=\nREDIS_PROXY_PASSWORD=mine\n' > /tmp/askwell-placeholder.env
   bash -c 'source deploy/linux/lib.sh && ensure_redis_passwords /tmp/askwell-placeholder.env'
   grep -c change-me /tmp/askwell-placeholder.env; grep '^REDIS_PROXY_PASSWORD=' /tmp/askwell-placeholder.env
   ```

   **You should see:** `0`, meaning the placeholder is gone and the empty value was filled. Then
   `REDIS_PROXY_PASSWORD=mine`, because a real value is kept.

5. **Stand-in** — now make your real `.env` right the same way: ☐

   ```
   bash -c 'source deploy/linux/lib.sh && ensure_redis_passwords .env'
   grep -c '^REDIS_' .env; grep '^REDIS_' .env | grep -c change-me
   ```

   **You should see:** `3`, then `0`. If `.env` already had real values, nothing changed.

The macOS installer uses the same function. The Windows installer's `Set-AskwellRedisPasswords`
is not walked here. See *Known gaps*.

---

## Part B — cold start, by clicking

6. Start Askwell from nothing: ☐

   ```
   podman compose down -v
   scripts/dev.sh web-build
   scripts/dev.sh build-api
   podman compose up -d
   scripts/dev.sh db upgrade head
   ```

   **You should see:** the volumes removed, both builds finish with no red error text, every
   container start, and the migration finish without an error. `podman compose up -d` waits for
   Redis to report healthy before starting the rest. If it stops at Redis, go to *If something
   goes wrong* at the end.

   In a **second** terminal, start the model on the host and leave it running:

   ```
   scripts/dev.sh inference
   ```

   **You should see:** the supervisor report that the model and the embedding model are ready.

7. Open a **private or fresh-profile** browser window and open `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button.

8. Click **Get started** and follow the steps until one offers to add material. **Do not set a
   passphrase.** ☐

   **You should see:** a step with **Choose files** and **Choose a folder**.

9. Click **Choose files**. Open `/tmp/askwell-test-177/files`, select `handbook_a.pdf` and
   confirm. When asked **"Which folder are these files in?"**, type `/tmp/askwell-test-177/files`
   and click **Add them**. If a note offers to nominate the folder (or a parent), click it and
   then click **Add them** again. Finish the welcome steps. Skipping an optional step is fine. ☐

   **You should see:** the file accepted, with no red "Not added" note.

10. Click **Library** in the rail on the left. Wait until `handbook_a.pdf` says **ready**. ☐

    **You should see:** the row move to **ready**. **This is the ingestion check.** The API put the
    job on the queue as the `api` user, and the worker took it off and ran it as the `worker`
    user. If the row stays queued for more than a few minutes, the worker cannot reach its
    queue. That is a defect in this ticket.

11. Look at the top of the window, beside the word **Askwell**. Hover over the small dot. ☐

    **You should see:** the tooltip **Ready**, and no banner across the top. A banner reading
    **"Indexing is not available"**, **"Background work is not available"** or **"Network guard is
    not available"** means the worker, the queue or the egress proxy could not log in to Redis.

12. Click **Settings** in the rail. Scroll to **Privacy and security → Network activity**. ☐

    **You should see:** a sentence of the form "**N** outbound requests permitted · **M** refused,
    measured by the egress proxy itself." It must **not** say it is unavailable. The API reads
    those numbers from the proxy's own counters, which its Redis user may read but not change.
    Write down **N** and **M**.

---

## Part C — the locks

All stand-ins. Run them in the terminal where you pasted the helper, from the repository folder.

13. **No password at all.** ☐

    ```
    podman compose exec -T redis redis-cli PING
    ```

    **You should see:** `NOAUTH Authentication required.` Not `PONG`. An unauthenticated
    connection cannot do anything, not even `PING`.

14. **The worker tries to open a route off the machine.** This is the ticket's real-world
    scenario: a malicious spreadsheet exploits a parser bug in the worker and tries to set a
    permitted host. ☐

    ```
    askwell_redis worker PING
    askwell_redis worker SET askwell:egress:permitted_host x:443
    askwell_redis worker SET askwell:egress:grant:manual-test x:443
    askwell_redis worker GET askwell:egress:permitted_host
    askwell_redis worker DEL askwell:egress:conversation:manual-test
    ```

    **You should see:** `PONG` for the first line, which proves the worker's password works. Then
    `NOPERM No permissions to access a key` four times. The worker can neither write nor read
    anything under `askwell:egress:`.

15. **The same attack from inside the worker's own container**, the way a compromised dependency
    would try it, using the worker's real credentials: ☐

    ```
    podman compose exec -T worker python -c "
    import os, redis
    r = redis.Redis(host='redis', username=os.environ['ASKWELL_REDIS_USERNAME'], password=os.environ['ASKWELL_REDIS_PASSWORD'])
    try: r.set('askwell:egress:permitted_host', 'x:443'); print('WRITTEN - DEFECT')
    except Exception as e: print(type(e).__name__, e)"
    ```

    **You should see:** `NoPermissionError No permissions to access a key`. If it prints `WRITTEN
    - DEFECT`, stop. The ticket's core promise has failed.

16. **Voice has no Redis login at all.** Voice never uses Redis, so it is given no user and no
    password. ☐

    ```
    podman compose exec -T voice env | grep -i redis || echo "no Redis settings"
    podman compose exec -T voice python -c "
    import redis
    try: redis.Redis(host='redis', socket_connect_timeout=3).set('askwell:egress:permitted_host', 'x:443'); print('WRITTEN - DEFECT')
    except Exception as e: print(type(e).__name__, e)"
    ```

    **You should see:** `no Redis settings`, then `AuthenticationError Authentication required.`

17. **The proxy may read the permissions, and delete only a conversation's.** At startup the
    proxy clears every online AI permission left from before. That delete is the one write it
    has on a permission, and it must stretch no further. ☐

    ```
    askwell_redis proxy SET askwell:egress:conversation:manual-test x
    askwell_redis proxy SET askwell:egress:permitted_host x:443
    askwell_redis proxy DEL askwell:egress:grant:manual-test
    askwell_redis proxy DEL askwell:egress:permitted_host
    askwell_redis proxy DEL askwell:egress:conversation:manual-test
    askwell_redis proxy GET askwell:egress:permitted_host
    ```

    **You should see:** `NOPERM No permissions to access a key` for the first four lines. The
    proxy cannot create a permission, and cannot delete a web search's or the update check's.
    Then `0` for the fifth line: allowed, with nothing there to delete. Then an empty line for
    the sixth: allowed, with nothing set.

18. **The API may write permissions but not the proxy's counters.** Those counters are the
    numbers in Settings, and only the proxy may change them. ☐

    ```
    askwell_redis api DEL askwell:egress:grant:manual-test
    askwell_redis api SET askwell:egress:refused 0
    ```

    **You should see:** `0`, which is allowed with nothing to delete. Then `NOPERM No permissions
    to access a key`. (The API's *writing* of a permission is shown for real in Part D. Nothing
    here creates one, because a permission here would be a real open route.)

19. **A wrong password is refused, and not waved through.** ☐

    ```
    podman compose exec -T -e REDISCLI_AUTH=wrong redis redis-cli --user api PING
    ```

    **You should see:** `AUTH failed: WRONGPASS invalid username-password pair or user is
    disabled.`, followed by `NOAUTH Authentication required.`

---

## Part D — everything that worked before still works

Back to the browser.

20. Click **Ask** in the rail. Type `What is the notice period for resigning at Meridian Loom?` and
    press **Enter**. Wait for the answer. On CPU this can take a minute or two. ☐

    **You should see:** an answer saying sixty-three days, with a source card naming
    `handbook_a.pdf`, page 2.

21. **Web escalation.** Ask something the handbook cannot answer: `What year was the Antikythera
    mechanism recovered from the sea?` Press **Enter**. ☐

    **You should see:** Askwell says it found nothing in your material, and offers options below.
    **Search the web** is enabled, not greyed out and not marked *"not configured"*. If it says
    *"not configured"*, *Before you start* step 3 did not take effect. Run `podman compose up -d
    --force-recreate api` and ask again.

22. Click **Search the web**. ☐

    **You should see:** the caption change to *"sending your question now"* and then settle. Then:
    *"Nothing found on the web either."* That result is correct. The fixture provider has no
    recorded answer for this question, and it never connected to anything. You should **not**
    see an error, or the offer reporting the search unavailable.

23. **Stand-in** — confirm the API really wrote the web search permission into Redis, and closed
    it again: ☐

    ```
    scripts/dev.sh psql -c "SELECT kind, payload ->> 'destination' FROM audit_interactions WHERE kind IN ('web_search_grant_opened','web_search_grant_closed') ORDER BY occurred_at DESC LIMIT 2;"
    askwell_redis api --scan --pattern 'askwell:egress:grant:*'
    ```

    **You should see:** two rows, `web_search_grant_closed` then `web_search_grant_opened` (newest
    first), both naming `html.duckduckgo.com:443`. Then nothing from the scan, because the
    permission was closed when the search ended. The opened row is only written after Redis
    accepted the API's write, so it proves that write succeeded.

24. **Online AI.** Click **Settings** in the rail. Scroll to **Online AI** and click **Add a
    key**. Fill in **Provider address** `api.provider.example:443`, **Model** `walkthrough-model`
    and **Key** `ASKWELL-SENTINEL-KEY-177`. Click **Save the key**. ☐

    **You should see:** *"A key is set for api.provider.example:443, asking for
    walkthrough-model."* and *"Saved. The key will not be shown again."*

25. Click **Ask** in the rail and ask any question, for example `How much annual leave do staff
    get?`. Wait for the answer. Then click the **Local** button to the left of **Ask**. ☐

    **You should see:** the button now reads **Online AI: on**, and a bold marker above the
    question box says online AI is on for this conversation, with questions going to
    `api.provider.example:443`. A box headed **"Before anything is sent: what will leave this
    machine"** also appears, and **Ask** is greyed out. That box is issue #737, not this ticket.

26. **Stand-in** — the API wrote this conversation's permission, and the proxy can read it: ☐

    ```
    askwell_redis api --scan --pattern 'askwell:egress:conversation:*'
    ```

    **You should see:** exactly one key, `askwell:egress:conversation:<a long id>`. Copy the key,
    then:

    ```
    askwell_redis proxy EXISTS <paste the key>
    ```

    **You should see:** `1`. The proxy can see the permission it is meant to honour.

27. **Stand-in** — restart only the egress proxy. At startup it clears standing online AI
    permissions with the one delete it is allowed: ☐

    ```
    podman compose restart egress-proxy
    podman compose logs egress-proxy | grep egress_conversation_grants_cleared | tail -1
    askwell_redis api --scan --pattern 'askwell:egress:conversation:*'
    ```

    **You should see:** a log line containing `egress_conversation_grants_cleared` and `count`
    `1`. It must not contain `NOPERM` or `redis_write_refused`. The scan then prints nothing.

28. Go back to the browser. **Do not reload,** because a reload starts a new conversation. Wait
    up to one minute. ☐

    **You should see:** the button goes back to **Local** by itself, and the marker is no longer
    bold. Online AI ended when the proxy restarted, and the conversation says so rather than
    still showing on.

29. Click **Settings** in the rail and read **Network activity** again. ☐

    **You should see:** the sentence loads, and is not reported as unavailable. **Permitted** is
    still **N** from step 12, because nothing actually left the machine. **Refused** may be higher
    than **M**. That is fine.

30. **Voice.** Only if this machine has the voice models installed: on the Ask screen, press and
    hold the microphone button, say `How long is the notice period?`, release, and confirm the
    transcript. ☐

    **You should see:** the transcript appear, then an answer read aloud, the same as before this
    ticket. If the machine has no voice models, mark this **N/V** and instead check that the voice
    service is still up:

    ```
    podman compose ps voice
    ```

    **You should see:** `voice` with status `Up` (healthy). Voice holds no Redis connection, so this
    ticket cannot break its speech, but it could have broken its start.

31. Click **Settings** in the rail, find **Verify the log** and click it. ☐

    **You should see:** "Checking…", then a report in which every chain is intact.

---

## Part E — a missing password stops Askwell loudly

32. **Stand-in** — blank the proxy's password in `.env`, then try to start: ☐

    ```
    sed -i 's/^REDIS_PROXY_PASSWORD=.*/REDIS_PROXY_PASSWORD=/' .env
    podman compose up -d
    ```

    **You should see:** `podman compose` refuse before starting anything. Its error names
    `REDIS_PROXY_PASSWORD` and says `is not set. Set it in .env (C8); the installer generates it.`
    Nothing is restarted without a password.

33. **Stand-in** — put the password back from your backup, and confirm the stack is fine: ☐

    ```
    sed -i "s/^REDIS_PROXY_PASSWORD=.*/$(grep '^REDIS_PROXY_PASSWORD=' /tmp/askwell-env-backup-177)/" .env
    grep -c '^REDIS_PROXY_PASSWORD=.\+' .env
    podman compose up -d
    ```

    **You should see:** `1`, then `podman compose up -d` succeeding. If your backup from
    *Before you start* had no Redis lines, run Part A step 5 instead. Then run step 11 again:
    the dot's tooltip reads **Ready**.

34. **Stand-in** — start the proxy process itself without its password, to show the proxy
    refuses on its own and does not only rely on Compose: ☐

    ```
    podman compose run --rm --no-deps -e ASKWELL_REDIS_PASSWORD= egress-proxy
    ```

    **You should see:** exactly this line, and the container exiting:

    > The egress proxy connects to Redis as its own user and ASKWELL_REDIS_PASSWORD is not set.
    > Compose sets both from the REDIS_*_PASSWORD values in .env, which the installer generates
    > (C8).

    The running proxy is not affected. This was a separate, one-off container.

---

## Put things back

35. Restore your `.env` and the stack: ☐

    ```
    cp /tmp/askwell-env-backup-177 .env
    bash -c 'source deploy/linux/lib.sh && ensure_redis_passwords .env'
    podman compose up -d --force-recreate
    rm -f /tmp/askwell-old.env /tmp/askwell-old.before /tmp/askwell-placeholder.env
    ```

    If your backup had `ASKWELL_WEB_SEARCH_PROVIDER` set to something other than `fixture`, it is
    now back to that. Remove the test key in **Settings → Online AI** if you want it gone.

---

## If something goes wrong

- **Redis never becomes healthy and nothing else starts.** Run `podman compose logs redis`. A
  line ending `is not set. Set it in .env (C8); the installer generates it.` means a password is
  missing. Run Part A step 5. `users.acl names a password this script does not fill in` means
  `deploy/redis/users.acl` and `start.sh` disagree, which is a defect.
- **The worker, API or proxy keeps restarting.** Run `podman compose logs <service> | tail`. A
  `NOPERM` naming a Redis command means `users.acl` is missing a command that code now uses.
  That is a defect in this ticket. Record the command name.
- **Every `askwell_redis` line says `WRONGPASS`.** Redis was started with different passwords
  from the ones now in `.env`. Run `podman compose up -d --force-recreate redis`.

---

## Known gaps

Do not report these as defects. They are deliberate, or tracked.

- **No screen shows any of this.** Redis refusals are only visible from the terminal. That is by
  design: a user has nothing to do about them.
- **Voice has no Redis user.** The ticket asked for a voice user with the queue keys only. Voice
  never opens a Redis connection, so the narrowest permission it can have is none. It is refused
  as an unauthenticated connection (step 16). `inference-bridge` is the same. Recorded in
  `docs/decisions.md`, 2026-09-25.
- **A refused write from a compromised service is recorded by Redis, and nothing reads it.**
  Askwell's own code logs `redis_write_refused` when one of *its* grant writes is refused. Code
  that is not Askwell's, such as the attacker in step 15, is recorded only in Redis's internal
  `ACL LOG`, which no Askwell user may read. Issue #749.
- **The `change-me-redis-*` placeholders from `.env.example` are accepted as real passwords.**
  The installers replace them. A hand-copied `.env` that keeps them starts normally, and anyone
  who has read `.env.example` then knows the `api` password. Found while writing this test.
  Issue #750.
- **`SCAN` is not limited by key in Redis.** The `api` and `proxy` users can list key *names*
  outside their own patterns, but cannot read their values. The worker has no `SCAN`.
  `docs/decisions.md`, 2026-09-25.
- **A compromised API can still write a permission.** The API is the one part meant to write
  them, and it already holds the database and the provider key. This ticket separates the API
  from everything else. It does not protect the API from itself.
- **The Windows installer's password step was not run.** `deploy/windows/install.test.ps1` has
  the tests, but the development machine has no `pwsh` (#606). On a Windows machine, run the
  installer over an existing install and check that `.env` gains the three `REDIS_*_PASSWORD`
  lines.
- **The real installer was not run end to end** in Part A. It needs the desktop shell built.
  Part A runs the installer's own password function, which is what the installer calls on every
  run.
- **Nothing online is actually sent.** Online sends stay refused until #737 is decided, so Part D
  checks that the permission is written, read and cleared, not that a provider answered.
- **The web search used the fixture provider.** A real search (`ddgs`) connects to the internet,
  and C1 permits that only for a real user decision. The Redis path is identical for both
  providers. `M6.5-WEB-BE-195`'s manual test walks the real one.
- **Voice speech was not walked on the development machine**, which has no voice models
  (`M6-AUDIO-DEPLOY-125`'s long-standing gap).
