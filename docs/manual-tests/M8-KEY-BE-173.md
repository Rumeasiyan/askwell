# Manual test — M8-KEY-BE-173, the user's provider key, held as a secret

**Ticket:** `M8-KEY-BE-173`. Askwell can now hold one key from an online provider the user
already pays. The key is stored with the provider it belongs to: that provider's address and
model. The key is encrypted on disk the same way as a database password, and under the passphrase
if one is set. It is decrypted only at the moment a question is sent. It never appears in a log
line, the trace, the audit log, an error message or an export. Removing the key turns online AI off
straight away, and says so. Replacing it with a key for a different provider turns off every
conversation that was online. The online provider's address and model are no longer set in `.env`.
They come from the stored key.

**Version under test:** `0.7.43`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 40 minutes. Most of it is waiting for one file to index, one local answer on CPU,
and three restarts.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal does what no screen can do yet:
start Askwell, **store and remove the key** (the screen for that is `M8-KEY-FE-174`), unlock a
passphrase (no unlock prompt exists yet), and read records and files for the key. Those steps are
labelled **Stand-in**.

**What is being checked.**

- `api/src/askwell/provider_key.py`: the stored key, its encryption, and its masked `repr`.
- In `api/src/askwell/online.py`: `store_key`, `remove_key`, `key_status`, `_availability`,
  `key_for_send`, and the `GET`/`PUT`/`DELETE /settings/online-key` routes.
- In `api/src/askwell/ask.py`: `_online_client`, which decrypts the key at send time and refuses a
  key whose provider is not the one the conversation was switched on for.
- In `api/src/askwell/inference/provider.py`: a `401`/`403` reads as the provider rejecting the
  key; a connection that could not be opened reads as Askwell's gateway not running (#735).
- In `api/src/askwell/passphrase.py`: setting, changing or removing a passphrase re-encrypts the key.

---

## Read this first — what can and cannot be walked today

**No online question can be sent yet, by anyone.** Every online send is refused until the owner
decides the wording of what the provider receives (#737). So the part of this ticket that happens
*at send time* cannot be clicked through: decrypting the key for a turn, putting it in the
provider's `Authorization` header, and reporting a key the provider rejects. Part H runs the
automated tests that cover it, including the sentinel test the ticket asks for. Everything that
happens *before* a send is walked by hand: storing, surviving a restart, switching a conversation
on, replacing, removing, the passphrase lock, and whether the key leaks anywhere.

**Nothing leaves this machine during this test.** The provider below, `api.provider.example:443`,
is a made-up name that does not exist. **Do not** store a real key for a real provider. The key
used throughout is a made-up value called the **sentinel**:

```
ASKWELL-SENTINEL-KEY-7f3c9e21d4
```

It is long and unusual so that a search for it cannot match anything by accident. Wherever this
document says "search for the sentinel", search for exactly that text. **Finding it anywhere
except where a step says it is allowed is a defect.** Report it with the file or output it was in.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not touched.
> On the shared development machine, check that nobody needs what the stack holds now. If you are
> unsure, use **Settings → Your data → Export everything** first.

### 1. One test file

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then copy one file from
the fixture corpus:

```
rm -rf /tmp/askwell-test-173
mkdir -p /tmp/askwell-test-173/files /tmp/askwell-test-173/exports
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-173/files/
ls /tmp/askwell-test-173/files
```

**You should see:** `handbook_a.pdf`. Page 2 reads "The standard notice period for resignation at
Meridian Loom is sixty-three days."

### 2. Check the old settings are gone and no key is in the example file

```
grep -n "ONLINE_AI" .env.example compose.yaml
grep -n "ONLINE_AI_DESTINATION\|ONLINE_AI_MODEL" .env
```

**You should see:** from the first command, lines for `ASKWELL_ONLINE_AI_AUTHORISATION_TTL_SECONDS`,
`ASKWELL_ONLINE_AI_API_PATH` and `ASKWELL_ONLINE_AI_TIMEOUT_SECONDS`, plus a comment saying the
destination, model and key are stored when the user adds a key in Settings. There is **no**
`ASKWELL_ONLINE_AI_DESTINATION`, **no** `ASKWELL_ONLINE_AI_MODEL`, and no line that holds a key
value. The second command prints nothing. If your `.env` still sets either of them from an earlier
test, delete those lines. Nothing reads them now, and leaving them in would make this test
misleading.

### 3. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, and the migration finish without an error. Do not skip `build-api`. The API's code is baked
into its image, so without a rebuild the running API is the old one and Part B fails.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

### 4. A terminal session for the stand-ins

The API answers only a browser that has opened Askwell. Take a session the same way the interface
does, in the first terminal:

```
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null
curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/settings/online-key | jq
```

**You should see:**

```json
{ "set": false, "provider": null, "available": false,
  "unavailable_reason": "Online AI is not available: no provider key is stored, so there is no provider to send to. Add one in Settings. Nothing has left this machine." }
```

If you see `{"error": "No session."}`, the first line did not run. Run both again.

---

## Part A — cold start, and online AI with no key

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open
   `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button. If
   you see the **Ask** screen instead, the stack was not cleared. Go back to step 3 of *Before you
   start*.

2. Click **Get started** and follow the steps until one offers to add material. **Do not set a
   passphrase here** if the welcome steps offer one. Part E sets one on purpose, after the key is
   stored. ☐

   **You should see:** a step with **Choose files** and **Choose a folder**.

3. Click **Choose files**. In the file picker, open `/tmp/askwell-test-173/files`, select
   `handbook_a.pdf` and confirm. When asked **"Which folder are these files in?"**, type
   `/tmp/askwell-test-173/files` and click **Add them**. If a note offers to nominate the folder
   (or a parent), click it and then click **Add them** again. Finish the welcome steps. Skipping an
   optional step is fine. ☐

   **You should see:** the file accepted, with no red "Not added" note.

4. Click **Library** in the rail on the left. Wait until `handbook_a.pdf` says **ready**. ☐

5. Click **Ask** in the rail. ☐

   **You should see:** the small line at the top reads
   `Askwell 0.7.43 · nothing leaves this machine`. To the left of the **Ask** button there is a
   button reading **Local**.

6. Type `What is the notice period for resigning at Meridian Loom?` and press **Enter**. Wait for
   the answer. On CPU this can take a minute or two. ☐

   **You should see:** an answer saying sixty-three days, with a source card naming
   `handbook_a.pdf`, page 2. This turn is local, and it stays the only answer in this test.

7. Click **Local**. ☐

   **You should see:** the button still reads **Local**. Beside it, a short line reads **"Online
   AI is not available: no provider key is stored, so there is no provider to send to. Add one in
   Settings. Nothing has left this machine."** No marker appears above the question box, and the
   top line still says `nothing leaves this machine`.

   Before this ticket the sentence said *"no online provider is configured"*. If you see that
   wording, the API image is the old one: go back to `build-api`.

8. Click **Settings** in the rail and scroll to **Online AI**. ☐

   **You should see:** paragraphs of text and **no** text box, button or switch. The key is not
   entered here until `M8-KEY-FE-174`. Scroll to **Privacy and security → Network activity**:
   `0 outbound requests permitted`.

## Part B — store a key (Stand-in)

This is what the screen in `M8-KEY-FE-174` will do when you paste a key and save it.

9. Try two things that must be refused, and read the refusals: ☐

   ```
   curl -s -b /tmp/askwell.cookies -X PUT http://127.0.0.1:8000/settings/online-key \
     -H 'Content-Type: application/json' \
     -d '{"destination":"api.provider.example:443","api_key":"ASKWELL-SENTINEL-KEY-7f3c9e21d4"}' | jq
   curl -s -b /tmp/askwell.cookies -X PUT http://127.0.0.1:8000/settings/online-key \
     -H 'Content-Type: application/json' \
     -d '{"destination":"api.provider.example:443","model":"walkthrough-model","api_key":"ASKWELL-SENTINEL KEY-7f3c9e21d4"}' | jq
   ```

   **You should see:** the first, with no model, answers
   `{"error": "A provider key needs a destination, a model and the key, each text."}`. The second,
   with a space in the key, answers
   `{"error": "The key must be 8 to 512 printable characters with no spaces or line breaks."}`.
   **Neither response contains the sentinel, or any part of it.** That is the point of this step:
   a refusal must never repeat what was pasted.

10. Store the key: ☐

    ```
    curl -s -b /tmp/askwell.cookies -X PUT http://127.0.0.1:8000/settings/online-key \
      -H 'Content-Type: application/json' \
      -d '{"destination":"api.provider.example:443","model":"walkthrough-model","api_key":"ASKWELL-SENTINEL-KEY-7f3c9e21d4"}' | jq
    ```

    **You should see:**

    ```json
    { "set": true,
      "provider": { "destination": "api.provider.example:443", "model": "walkthrough-model" },
      "available": true, "unavailable_reason": null }
    ```

    The response names the provider. It does **not** contain the key, not even masked as
    `••••` or with its last four characters. The ticket says the key is never echoed back after
    entry.

11. Read how it is stored: ☐

    ```
    scripts/dev.sh psql -c "SELECT key, value FROM settings WHERE key = 'online_provider_key';"
    ```

    **You should see:** one row. Its value is a small JSON object with `destination`
    `api.provider.example:443` and `model` `walkthrough-model` in plain text, and a
    `key_encrypted` value that is a long run of letters, digits, `-` and `_`. **The sentinel is not
    in it.** The provider is stored in the clear on purpose: it is not secret, and it lets
    Settings say which provider is set up even while Askwell is locked.

## Part C — the key survives a restart, and a conversation goes online to its provider

12. Restart the whole stack **without** `-v`. With `-v` it would delete everything: ☐

    ```
    podman compose down
    podman compose up -d
    ```

    Wait about twenty seconds, then take a new session and read the key's status:

    ```
    curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null
    curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/settings/online-key | jq
    ```

    **You should see:** `"set": true`, the same provider as step 10, `"available": true`.

13. In the browser, **reload the page**. It lands on the Ask screen. Reloading starts a new
    conversation, and a new conversation is always local. Click **Local**. ☐

    **You should see:**
    - the button now reads **Online AI: on**;
    - above the question box, a bold marker: **"Online AI is on for this conversation until
      *(a time about four hours from now)*. Questions go to api.provider.example:443."**
      That address came from the stored key. Nothing in `.env` names it any more, so seeing it is
      the proof that the key, and the provider stored with it, survived the restart;
    - below the marker, a box headed **Before anything is sent: what will leave this machine**,
      saying Askwell has not yet defined what online AI would send, with one button,
      **Switch back to local**;
    - the top line now reads `online AI is on for this conversation`.

14. Type `What is the probation period?` and press **Enter**, then click **Ask**. ☐

    **You should see:** nothing is sent. **Ask** stays greyed out and the question stays in the
    box. This is #737's refusal, not a defect of this ticket. It is why no online answer appears
    in this test.

## Part D — replace and remove, both taking effect at once

The conversation from step 13 is still online. Leave that browser tab open on the Ask screen.

15. **Stand-in** — replace the key with a new one **for the same provider**. This is what
    rotating a key at the provider and pasting the new one looks like: ☐

    ```
    curl -s -b /tmp/askwell.cookies -X PUT http://127.0.0.1:8000/settings/online-key \
      -H 'Content-Type: application/json' \
      -d '{"destination":"api.provider.example:443","model":"walkthrough-model","api_key":"ASKWELL-SENTINEL-KEY-ROTATED-5b8a"}' | jq .set
    ```

    **You should see:** `true`. In the browser, wait a minute (the Ask screen rereads the
    conversation's state every minute). **The marker still reads "Online AI is on for this
    conversation … Questions go to api.provider.example:443."** A new key for the same provider
    keeps conversations online: the door is the one you opened.

16. **Stand-in** — replace it with a key **for a different provider**: ☐

    ```
    curl -s -b /tmp/askwell.cookies -X PUT http://127.0.0.1:8000/settings/online-key \
      -H 'Content-Type: application/json' \
      -d '{"destination":"api.other-provider.example:443","model":"other-model","api_key":"ASKWELL-SENTINEL-KEY-7f3c9e21d4"}' | jq .provider
    ```

    **You should see:** `{"destination": "api.other-provider.example:443", "model": "other-model"}`.
    The sentinel is the key again, so Part F's search covers it.

    In the browser, wait up to a minute. **You should see:** the button changes back to
    **Local**, the disclosure box disappears, and the marker turns to plain grey text: **"Online AI
    was on in this conversation earlier. It is local now: nothing you ask here leaves this
    machine."** The conversation was switched on for the old provider. Your key is now for another
    one, so it ended.

17. Click **Local** again. ☐

    **You should see:** **Online AI: on**, and the marker now reads **"… Questions go to
    api.other-provider.example:443."** The destination follows the key.

18. **Stand-in** — remove the key: ☐

    ```
    curl -s -b /tmp/askwell.cookies -X DELETE http://127.0.0.1:8000/settings/online-key | jq
    ```

    **You should see:** `"set": false`, `"provider": null`, `"available": false`, and the same
    no-key sentence as in *Before you start*, step 4.

    In the browser, wait up to a minute. **You should see:** the button reads **Local**, and the
    marker reads *"Online AI was on in this conversation earlier. It is local now…"*. Click
    **Local** once more. **You should see:** it stays **Local**, and beside it is the no-key
    sentence from step 7. Online AI is unavailable, stated plainly, before any question is asked,
    not a failure when one is.

19. **Stand-in** — the decisions records of all this: ☐

    ```
    scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind LIKE 'online_%' ORDER BY occurred_at;"
    ```

    **You should see,** in this order among others:
    - `online_key_stored`, with `destination` and `model` only (step 10);
    - `online_ai_enabled` for the conversation (step 13);
    - `online_key_replaced`, naming the same provider and a `previous` with the same provider
      (step 15). No revocation follows it;
    - `online_key_replaced`, naming `api.other-provider.example:443` with `previous`
      `api.provider.example:443` (step 16), followed by `online_ai_revoked` with reason
      `key_replaced`;
    - another `online_ai_enabled` (step 17);
    - `online_key_removed`, naming `api.other-provider.example:443` (step 18), followed by
      `online_ai_revoked` with reason `key_removed`.

    **No payload contains a key**: not the sentinel, not the rotated key, not part of either. An
    `online_ai_revoked` with reason `restart` may also appear if a conversation was online when you
    restarted. That is `M8-ONLINE-SEC-169` behaving correctly.

    If a kind name differs, check `git log -p -- api/src/askwell/online.py` for a later rename
    before you report it.

## Part E — a passphrase-locked install cannot read the key

20. **Stand-in** — store the sentinel key again: ☐

    ```
    curl -s -b /tmp/askwell.cookies -X PUT http://127.0.0.1:8000/settings/online-key \
      -H 'Content-Type: application/json' \
      -d '{"destination":"api.provider.example:443","model":"walkthrough-model","api_key":"ASKWELL-SENTINEL-KEY-7f3c9e21d4"}' | jq .set
    ```

    **You should see:** `true`.

21. In the browser, click **Settings** in the rail and scroll to **Privacy and security →
    Passphrase**. Click **Set a passphrase**. Type `correct horse battery staple` twice, tick
    **I understand there is no recovery.**, and click **Set passphrase**. ☐

    **You should see:** the button reads **Setting…**, then the section shows the controls for an
    install with a passphrase on. Setting it re-encrypts your library, your connection passwords
    and, since this ticket, the provider key. Askwell does not ask for the key again.

22. Restart the API, which locks it: ☐

    ```
    podman compose restart api
    ```

    Wait about twenty seconds. In the browser, reload, click **Settings** and scroll to
    **Passphrase**. **You should see:** "A passphrase is set for this install but this session has
    not unlocked it yet."

23. Click **Ask** in the rail, then click **Local**. ☐

    **You should see:** it stays **Local**, and beside it: **"Online AI is not available until
    Askwell is unlocked: your provider key is encrypted under your passphrase. Nothing has left this
    machine."** This is a different sentence from the no-key one. The key is there, but it cannot be
    read. If this click shows an error about the conversation instead, try once more after
    unlocking (step 25) and note it: an unlock prompt before the Ask screen is not built yet
    (Known gaps).

24. **Stand-in** — a locked install still says *which* provider, and refuses to store a new key: ☐

    ```
    curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/settings/online-key | jq
    curl -s -b /tmp/askwell.cookies -o /dev/null -w '%{http_code}\n' -X PUT \
      http://127.0.0.1:8000/settings/online-key -H 'Content-Type: application/json' \
      -d '{"destination":"api.provider.example:443","model":"walkthrough-model","api_key":"ASKWELL-SENTINEL-KEY-LOCKED-00"}'
    ```

    **You should see:** the first says `"set": true`, names `api.provider.example:443`, and has
    `"available": false` with the unlock sentence from step 23. The second prints `423`. A locked
    install does not store a key under the wrong encryption.

25. **Stand-in** for the unlock prompt that does not exist yet: ☐

    ```
    curl -s -b /tmp/askwell.cookies -X POST http://127.0.0.1:8000/settings/passphrase/unlock \
      -H 'Content-Type: application/json' -d '{"passphrase": "correct horse battery staple"}' | jq
    ```

    **You should see:** `{"locked": false}`.

26. In the browser, reload the page and click **Local**. ☐

    **You should see:** **Online AI: on**, with the marker naming `api.provider.example:443`. The key
    re-encrypted in step 21 still decrypts after the unlock. Click **Switch back to local** in the
    disclosure box.

## Part F — the sentinel appears nowhere

The sentinel has now been stored twice, replaced, removed, re-encrypted under a passphrase, and
used to switch conversations online. Search every output for it.

27. **Export everything.** Click **Settings** in the rail, scroll to **Your data**, and click
    **Export everything**. When it says **Ready**, click **Download the export** and save the file
    into `/tmp/askwell-test-173/exports`. Then do the same with **Export the log**. If a warning
    about the passphrase appears first, read it and continue. ☐

    Unzip both and search them:

    ```
    cd /tmp/askwell-test-173/exports
    for z in *.zip; do mkdir -p "${z%.zip}" && unzip -oq "$z" -d "${z%.zip}"; done
    grep -rl "ASKWELL-SENTINEL" . ; echo "exit: $?"
    grep -i "settings" */README.txt
    cd ~/external/quantum-plus/askwell
    ```

    **You should see:** the first `grep` prints no file names and `exit: 1`. `exit: 1` means
    grep found nothing, which is the pass. The `README.txt` line for `settings` says it was left out
    and names **your online provider key**.

28. **The logs of every container:** ☐

    ```
    podman compose logs 2>&1 | grep -c "ASKWELL-SENTINEL"
    podman compose logs api 2>&1 | grep -E "online_key_(stored|replaced|removed)" | head
    ```

    **You should see:** `0` from the first. The second prints log lines for storing, replacing and
    removing that name the destination and model, and nothing else about the key.

29. **The trace files and everything else Askwell keeps on disk:** ☐

    ```
    podman compose exec api sh -c 'grep -rl "ASKWELL-SENTINEL" /var/lib/askwell; echo "exit: $?"'
    ```

    **You should see:** no file names and `exit: 1`.

30. **The database, all of it, including the audit log and every stored trace:** ☐

    ```
    podman compose exec postgres pg_dump -U askwell askwell | grep -c "ASKWELL-SENTINEL"
    ```

    **You should see:** `0`. The key is in the database only as ciphertext, which does not contain
    the sentinel's text. If `pg_dump` says the role does not exist, use the `POSTGRES_USER` and
    `POSTGRES_DB` from your `.env`.

31. **The trace of the one answer:** click **Ask** in the rail. The answer from step 6 is in an
    earlier conversation, so ask the notice-period question once more in this one and wait for the
    answer. Click **How did you get this?**, then **Copy trace**, and paste into any text editor. ☐

    **You should see:** a trace starting `Question: What is the notice period…` and
    `Backend: local · …`. Search it for `SENTINEL`. **You should see:** no match. Click **Close**.

32. Verify the audit chains: ☐

    ```
    podman compose exec api askwell-verify
    ```

    **You should see:** every chain reported intact.

## Part G — Settings is unchanged

33. Click **Settings** in the rail. Scroll to **Online AI**. ☐

    **You should see:** the same text as step 8 and no field, even though a key is now stored.
    Scroll to **Privacy and security → Network activity**. **You should see:**
    `0 outbound requests permitted`. Switching conversations online authorised a destination,
    but nothing was ever sent to it. If the count is above zero, report it with this document's
    step numbers.

## Part H — what happens at send time, against a mock provider (Stand-in)

No click can reach a provider yet (#737). These tests do. The stack must still be up.

34. Run the tests for this ticket: ☐

    ```
    scripts/dev.sh test tests/test_provider_key.py tests/test_inference_provider.py
    scripts/dev.sh test-db tests/test_provider_key.py tests/test_online.py tests/test_ask_online.py
    ```

    **You should see:** each run end with `passed` and no `failed`, `error` or `skipped`. Between
    them they prove the parts of the ticket no click can reach today:

    - **`test_a_stored_key_survives_a_restart_is_sent_and_appears_nowhere_else`** is the ticket's
      sentinel test. It stores a sentinel key, restarts the app, answers one question online
      against a mock provider, then has the provider reject the key on a second question while
      echoing it back, as real providers do. It then reads the logs, the audit records, the stored
      traces, the trace files, "Export everything" and every response for the sentinel. The
      sentinel is found only in the `Authorization` header the mock provider received;
    - a `401` or `403` from the provider reads **"The online provider rejected your key (401).
      Check it with your provider, or replace it in Settings."**, and the local model answers. It is
      never phrased as Askwell being broken, and never contains the key;
    - a connection that could not be opened at all reads **"Online AI could not start: Askwell's
      network gateway is not running."**, not "the network is unavailable" (#735);
    - a key replaced for another provider after a conversation was switched on is not sent under
      the old switch-on;
    - a locked install neither reads nor stores the key, and a passphrase set, changed or removed
      carries the key with it;
    - the key's `repr` is masked, so a log line or traceback that captures it shows `[redacted]`;
    - **`test_no_online_send_is_possible_until_redis_is_authenticated`** fails if online sends
      are ever turned on (#737) while Redis still has no authentication (#730). It keeps #730 from
      being skipped.

---

## Teardown

```
curl -s -b /tmp/askwell.cookies -X DELETE http://127.0.0.1:8000/settings/online-key | jq .set
podman compose exec api askwell-verify
rm -rf /tmp/askwell-test-173 /tmp/askwell.cookies
```

**You should see:** `false`, and both audit chains reported intact. The passphrase from step 21 is
still set. Remove it in **Settings → Privacy and security → Passphrase**, or run
`podman compose down -v` for a clean slate.

---

## Known gaps

These are deliberately not built yet. Do not report them as defects of this ticket.

- **No screen to enter, replace or remove the key.** Parts B, D and E use terminal stand-ins.
  That screen is `M8-KEY-FE-174`. Until it lands, the **Online AI** section in Settings is words
  only. Its sentence *"Nothing on this screen asks for a key today, because there is nothing yet
  that could use one"* is now half out of date: a key can be stored, it just cannot be entered
  here. `M8-KEY-FE-174` rewrites that section.
- **No online question can be sent (#737).** So "the key is used for an online turn" and "a key the
  provider rejects is reported as the provider rejecting it" are proved by the automated tests in
  Part H, not by clicking. When #737 lands, add a Part that asks an online question against a local
  test provider and checks the `Authorization` header and the rejected-key wording by hand.
- **Redis has no authentication (#730).** Another container on the internal network could write
  an egress grant. It is harmless while every send is refused, and a test now makes #737 fail
  until #730 is fixed.
- **The conversation's wording when its key is removed** is `M8-KEY-FE-175`'s. Today the Ask
  screen shows the generic *"Online AI was on in this conversation earlier…"* marker, and it can
  take up to a minute to appear (the screen rereads the state once a minute while online).
- **No unlock prompt.** A locked install is unlocked with a terminal stand-in (step 25). The
  prompt belongs to the passphrase's frontend work, not to this ticket.
- **One key, one provider.** Storing a second key replaces the first. Several keys at once are
  out of scope until somebody asks for two.
- **No check of the key with the provider when it is stored.** That would be a network request
  before the user has switched any conversation online (C1). A wrong key is found out at the first
  online question, as a provider rejection.
- **Database, tool-loop and web answers stay local in an online conversation (#734).** They never
  use the key.
