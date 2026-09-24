# Manual test — M8-KEY-FE-175, the provider refusing falls back to local and keeps working

**Ticket:** `M8-KEY-FE-175`. Sometimes the provider says no: your account has run out of quota,
or it rejects your key. When that happens, the question is still answered, by the local model,
and the answer says so. The conversation also goes back to local straight away, so later
questions are not sent to a provider that has already said no. The marker above the question
box says why online AI ended and what you can do about it. It never blames Askwell. Nothing
switches online AI back on by itself. When the quota or key is fixed, you switch it on again
yourself. The marker now also names the reason when online AI ended because you removed your
key or replaced it with one for a different provider.

**Version under test:** `0.7.45`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 40 minutes. Most of it is waiting for one file to index, three local answers on
CPU, and a few one-minute waits for the marker to reread.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal only starts Askwell, stands in for the
provider refusing, and reads records that no screen shows yet. Those steps are labelled
**Stand-in**.

**What is being checked.**

- `web/lib/online-conversation.ts`: `markerView` names why online AI ended (`ENDED_BECAUSE`).
- `api/src/askwell/online.py`: `end_after_provider_refusal`, and `ended_reason` on the
  conversation's online state, read from its latest `online_ai_revoked` record.
- `api/src/askwell/ask.py`: when the provider rejects the key or the quota has run out, the
  local answer ends the conversation's online authorisation and adds *"This conversation is
  local now."* to its closing line.
- `api/src/askwell/inference/provider.py`: a rejected key (`401`/`403`) and an exhausted quota
  (`402`, or a `429` saying `insufficient_quota`) are told apart from a plain rate limit.

---

## Read this first

**No online question can be sent yet, by anyone.** Every online send is refused until the owner
decides the wording of what the provider receives (#737). That means the provider cannot really
refuse anything during this test, because nothing reaches it. So the refusal is simulated in
two ways:

- **On screen (Parts B–D):** a terminal stand-in does exactly what Askwell does when the
  provider refuses: it ends the conversation's online authorisation and records the reason. You
  then watch the conversation on screen: the marker changes, the question box works again, and
  the next answer is local.
- **The answer's closing line, and the two online answers before the refusal (Part F):** these
  need a provider that answers. They are checked by an automated test that plays the ticket's
  full walkthrough through the same routes the interface uses. It has two online answers, then
  a quota refusal, then a third question answered locally that says so, then a fourth that goes
  nowhere.

**Nothing leaves this machine during this test.** The provider below, `api.provider.example:443`,
is a made-up name that does not exist. **Do not** enter a real key for a real provider. The key
used throughout is a made-up value called the **sentinel**:

```
ASKWELL-SENTINEL-KEY-175-a91e
```

**If you see the sentinel, or any part of it, anywhere on screen after saving it, that is a
defect.**

**This ticket carries a copy review.** Every sentence in *italics* below is wording a user reads.
When one is unclear, or could make someone think Askwell broke, write down the step number, the
sentence and why. The reviewer needs that note.

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
rm -rf /tmp/askwell-test-175
mkdir -p /tmp/askwell-test-175/files
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-175/files/
ls /tmp/askwell-test-175/files
```

**You should see:** `handbook_a.pdf`.

### 2. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, and the migration finish without an error. Do not skip either build. The marker wording
under test is built into `web/out` and served from the API image. Without both builds, you will
see the old marker.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

### 3. The stand-in for the provider refusing

Parts B and C use this command. Keep a third terminal open in the repository for it. It finds the
**one** conversation that has online AI on and ends it exactly as Askwell does after a refusal. It
changes nothing if there is not exactly one.

```
podman compose exec -T -e REASON=provider_quota_exhausted api python - <<'EOF'
import asyncio, os
from sqlalchemy import text
from askwell import online
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory, session_scope

async def main() -> None:
    settings = Settings()
    engine = build_engine(settings)
    async with session_scope(session_factory(engine)) as db:
        rows = (await db.execute(text(
            "SELECT id FROM conversations WHERE ai_backend = 'online' ORDER BY created_at DESC"
        ))).scalars().all()
        if len(rows) != 1:
            print(f"Expected exactly one online conversation, found {len(rows)}. Nothing changed.")
        else:
            ended = await online.end_after_provider_refusal(db, settings, rows[0], os.environ["REASON"])
            print("Ended: the conversation is local now." if ended else "It was not online. Nothing changed.")
    await engine.dispose()

asyncio.run(main())
EOF
```

Part C runs the same command with `REASON=provider_rejected_key`. Nothing else changes.

---

## Part A — cold start, a key, and a local answer

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open
   `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button. If
   you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you start*,
   step 2.

2. Click **Get started** and follow the steps until one offers to add material. **Do not set a
   passphrase.** ☐

   **You should see:** a step with **Choose files** and **Choose a folder**.

3. Click **Choose files**. Open `/tmp/askwell-test-175/files`, select `handbook_a.pdf` and
   confirm. When asked **"Which folder are these files in?"**, type `/tmp/askwell-test-175/files`
   and click **Add them**. If a note offers to nominate the folder (or a parent), click it and
   then click **Add them** again. Finish the welcome steps. Skipping an optional step is fine. ☐

   **You should see:** the file accepted, with no red "Not added" note.

4. Click **Library** in the rail on the left. Wait until `handbook_a.pdf` says **ready**. ☐

5. Click **Settings** in the rail. Scroll to **Online AI** and click **Add a key**. Fill in
   **Provider address** `api.provider.example:443`, **Model** `walkthrough-model`, and **Key**
   `ASKWELL-SENTINEL-KEY-175-a91e`. Click **Save the key**. ☐

   **You should see:** *"A key is set for api.provider.example:443, asking for
   walkthrough-model."* and *"Saved. The key will not be shown again."*

6. Click **Ask** in the rail. Type `What is the notice period for resigning at Meridian Loom?` and
   press **Enter**. Wait for the answer. On CPU this can take a minute or two. ☐

   **You should see:** an answer saying sixty-three days, with a source card naming
   `handbook_a.pdf`, page 2. The top line reads `Askwell 0.7.45 · nothing leaves this machine`.
   There is no marker above the question box and no *"Answered locally"* label on the answer,
   because this conversation has never been online.

## Part B — the account runs out of quota

7. Click the **Local** button to the left of **Ask**. ☐

   **You should see:**
   - the button reads **Online AI: on**;
   - above the question box, a bold marker: **"Online AI is on for this conversation until
     *(a time about four hours from now)*. Questions go to api.provider.example:443."**;
   - the top line reads `online AI is on for this conversation`;
   - a box headed **"Before anything is sent: what will leave this machine"**, saying *"Askwell has
     not yet defined exactly what online AI would send, so it will not send anything…"*, with a
     **Switch back to local** button;
   - beside **Ask**: *"Not sent. Online AI is on for this conversation, and what it sends has not
     been confirmed."* The **Ask** button is greyed out.

   The first answer now carries a small *"Answered locally"* label. That is correct: the
   conversation has now been online, so every answer says which model wrote it.

8. Type `How much annual leave do staff get?` into the question box. Do **not** press Enter. ☐

   **You should see:** **Ask** stays greyed out. This is #737's refusal, not this ticket's, and is
   the reason the refusal below is simulated.

9. **Stand-in** — the provider says the account is out of quota. In the third terminal, run the
   command from *Before you start*, step 3, exactly as written (`REASON=provider_quota_exhausted`).
   ☐

   **You should see:** `Ended: the conversation is local now.` If it says it found 0 or 2
   conversations, stop and check that only this one tab has online AI on.

10. Go back to the browser. **Do not reload.** A reload starts a new conversation. Wait up to one
    minute without touching anything. The screen rereads an online conversation once a minute. ☐

    **You should see**, without clicking anything:
    - the button goes back to **Local**;
    - the bold marker turns into a plain grey one that reads:
      *"Online AI was on in this conversation earlier, until your provider account ran out of
      quota. It is local now: nothing you ask here leaves this machine. Add more with your
      provider, then switch online AI back on if you want it."*
    - the top line reads `nothing leaves this machine` again;
    - the *"Before anything is sent"* box and the *"Not sent…"* line are gone, and **Ask** is no
      longer greyed out.

    **Judge the sentence as the person in the ticket would.** It should say that the quota ran out
    with the provider, not with Askwell, and what to do about it. It should not suggest Askwell
    failed or will switch back on by itself. The text you typed in step 8 should still be in the
    box. **Nothing was lost.**

11. **Now take the machine offline.** Turn off Wi-Fi or unplug the network cable. The ticket's
    edge case is running out of quota while offline, and the local model should still answer. ☐

12. Press **Enter** to ask `How much annual leave do staff get?`. Wait for the answer. ☐

    **You should see:** an answer drawn from `handbook_a.pdf`, with a source card naming it and a
    page. **No error, no refusal, no mention of the network.** The answer carries *"Answered
    locally"*. The marker is unchanged.

13. On that answer, click **How did you get this?** ☐

    **You should see:** a panel with, near the top, a line reading `local · ` and the local model's
    name. There is **no** **show what was sent** line, because nothing was sent for this turn.
    Close the panel with **Escape**. Open the panel on the first answer from step 6 too. It also
    reads `local · …`. Each turn names the backend that answered it.

14. Reconnect the network. ☐

15. **Credit restored later: nothing switches back on by itself.** Wait two full minutes without
    touching anything. ☐

    **You should see:** the button still reads **Local**, and the grey marker from step 10 is still
    there. Open a **second tab** on `http://127.0.0.1:8000`, click **Settings** in the rail and
    scroll to **Online AI**. **You should see:** the key still set for `api.provider.example:443`.
    Running out of quota did not remove your key, and did not change anything in Settings. Close
    the second tab and return to the first. It still shows both answers.

16. Click **Local** once. ☐

    **You should see:** **Online AI: on** and the bold marker from step 7, in one click. The
    *"Before anything is sent"* box comes back too. That is still #737, not a second question from
    this ticket. Coming back online was your choice. Click **Switch back to local** in that box.

    **You should see:** **Local**, with the plain marker *"Online AI was on in this conversation
    earlier. It is local now…"*. This time you switched it off yourself, so no reason is named.

## Part C — the provider rejects the key

17. **Reload the page** (F5). ☐

    **You should see:** an empty Ask screen. The reload started a new, local conversation. There is
    no marker. This is also how you start a fresh conversation today.

18. Click **Local**. ☐

    **You should see:** **Online AI: on**, and the bold marker naming `api.provider.example:443`, as
    in step 7.

19. **Stand-in** — the provider rejects the key. Run the step 3 command again, with
    `REASON=provider_rejected_key` in place of `REASON=provider_quota_exhausted`. ☐

    **You should see:** `Ended: the conversation is local now.`

20. Back in the browser, wait up to one minute without touching anything. ☐

    **You should see:** **Local**, and the grey marker:
    *"Online AI was on in this conversation earlier, until your provider rejected your key. It is
    local now: nothing you ask here leaves this machine. Check the key with your provider or
    replace it in Settings, then switch online AI back on if you want it."*

    It does **not** mention quota. The two refusals have different fixes, and the marker has to
    tell them apart. Nothing in it names the key itself.

21. Type `What is the notice period for resigning at Meridian Loom?` and press **Enter**. ☐

    **You should see:** the sixty-three-day answer with its source card for `handbook_a.pdf`, page
    2, labelled *"Answered locally"*. The user is never blocked from asking.

## Part D — the key replaced, then removed

These two reasons were left generic by `M8-KEY-FE-174`. That ticket's walkthrough, steps 24 and
27, now reads differently.

22. Click **Local** to switch this conversation online again. ☐

    **You should see:** **Online AI: on** in one click.

23. Open a **second tab** on `http://127.0.0.1:8000`. Click **Settings**, scroll to **Online AI**
    and click **Replace the key**. Change **Provider address** to `api.other-provider.example:443`
    and **Model** to `other-model`, and put the sentinel in **New key**. Click **Replace the
    key**. ☐

    **You should see:** *"A key is set for api.other-provider.example:443, asking for
    other-model."*

24. Switch to the first tab and wait up to one minute. ☐

    **You should see:** **Local**, and the grey marker:
    *"Online AI was on in this conversation earlier, until you replaced your provider key with one
    for a different provider. It is local now: nothing you ask here leaves this machine."*
    There is no advice sentence after it, because you did this yourself.

25. Click **Local** again. ☐

    **You should see:** **Online AI: on**, with the marker naming `api.other-provider.example:443`.

26. In the Settings tab, click **Remove the key**. ☐

    **You should see:** *"No key is set. Online AI cannot be switched on in any conversation."* and
    *"Removed. The key is no longer on this machine."*

27. Switch to the Ask tab and wait up to one minute. ☐

    **You should see:** **Local**, and the grey marker:
    *"Online AI was on in this conversation earlier, until you removed your provider key. It is
    local now: nothing you ask here leaves this machine."*

    Click **Local** once more. **You should see:** it stays **Local**, and beside it: *"Online AI
    is not available: no provider key is stored, so there is no provider to send to. Add one in
    Settings. Nothing has left this machine."*

## Part E — what was recorded, and that nothing left

28. **Stand-in** — the revocation records of Parts B–D: ☐

    ```
    scripts/dev.sh psql -c "SELECT kind, payload->>'reason' AS reason, payload->>'conversation_id' AS conversation FROM audit_decisions WHERE kind = 'online_ai_revoked' ORDER BY occurred_at;"
    ```

    **You should see,** in this order:
    - `provider_quota_exhausted` (step 9);
    - `disabled` (step 16), with the **same** conversation id as the row above;
    - `provider_rejected_key` (step 19), with a **different** conversation id;
    - `key_replaced` (step 23) and `key_removed` (step 26), with the same id as step 19's row.

29. **Stand-in** — each turn names its backend: ☐

    ```
    scripts/dev.sh psql -c "SELECT conversation_id, trace->'backend'->>'mode' AS backend, left(content, 40) AS answer FROM messages WHERE role = 'assistant' ORDER BY created_at;"
    ```

    **You should see:** three rows, each `local`. The first two share a conversation id (steps 6
    and 12), and the third has step 19's id (step 21). A mixed conversation that had online answers
    would show `online` on those rows. Part F checks that.

30. Click **Settings → Privacy and security → Network activity**. ☐

    **You should see:** `0 outbound requests permitted`. Running out of quota, a rejected key, and
    everything after them sent nothing anywhere.

31. **Stand-in** — the sentinel appears nowhere: ☐

    ```
    podman compose logs 2>&1 | grep -c "ASKWELL-SENTINEL"
    ```

    **You should see:** `0`.

## Part F — the parts that need a provider that answers

32. **Stand-in** — the ticket's full walkthrough, with a simulated provider: ☐

    ```
    scripts/dev.sh test-db tests/test_ask_online.py tests/test_online.py tests/test_inference_provider.py
    ```

    **You should see:** all passed, with no skips. These named tests carry the parts no screen can
    show yet:
    - `test_an_empty_account_answers_locally_ends_online_and_loses_nothing`: two questions answered
      online, then the provider answers `429 insufficient_quota`. The third question is answered
      locally, and its answer ends with *"Answered by the local model. Your account with the
      online provider has run out of quota (429). Add more with your provider, then switch online
      AI back on. This conversation is local now."* The conversation is then local. The fourth
      question is answered without any request to the provider. All four answers are stored, each
      with the backend that wrote it.
    - `test_a_rate_limit_answers_locally_and_leaves_the_conversation_online`: a plain `429` answers
      that one question locally and **leaves the conversation online**, because the next question
      is worth trying.
    - `test_a_failure_mid_answer_starts_again_locally_and_keeps_nothing_online`: the provider stops
      partway through. What had arrived is withdrawn, and the local model answers from the start
      with the *"Answered by the local model."* line. This is the ticket's "exhaustion
      mid-answer" edge case, answered by "restarts locally with that stated".
    - `test_a_429_that_says_the_quota_ran_out_is_told_apart_from_a_rate_limit`: quota and rate
      limit are told apart from the provider's error code, and the provider's error body is never
      repeated.

33. **Stand-in** — the marker wording: ☐

    ```
    scripts/dev.sh web-check
    ```

    **You should see:** no failures. `web/lib/online-conversation.test.ts` pins each marker sentence
    from steps 10, 20, 24 and 27. It also checks that an unknown reason falls back to the plain
    marker rather than showing `undefined`.

---

## Teardown

```
podman compose exec api askwell-verify
podman compose down -v
rm -rf /tmp/askwell-test-175
```

**You should see:** both audit chains reported intact before the wipe.

---

## Known gaps

These are deliberately not built yet. Do not report them as defects of this ticket.

- **No online question can be sent (#737).** A real refusal from a real provider cannot happen
  until something can be sent. On screen, the refusal is a stand-in, and the answer's closing line
  (*"… This conversation is local now."*) is seen only in the automated test in step 32.
- **Real quota exhaustion cannot be tested.** The credit service and its balance, limits and
  purchase are blocked. Exhaustion is simulated, as the ticket allows.
- **The marker takes up to a minute to change** after the provider refuses, while the screen is
  idle. After a real refusal, the screen rereads the conversation as soon as the answer finishes,
  so the marker is already right by then. The one-minute wait in steps 10 and 20 exists only
  because the stand-in acts outside a turn.
- **A plain rate limit, a network outage or a provider error keeps the conversation online.**
  That one question is answered locally, and the next one is tried online again. Only a rejected
  key or an empty account ends it (`docs/decisions.md`, 2026-09-25).
- **The provider refusing can only happen before the answer starts.** A refusal arrives as the
  response's status, before any text. A provider that stops partway through is the separate
  *interrupted* case, restarted locally and stated (step 32).
- **Ending by the switch, the four-hour limit or a restart keeps the plain marker**, with no
  reason named. The switch is something you just did. The limit and a restart end up in a single
  record that cannot say which of the two it was.
- **A conversation cannot be reopened after a reload (#199).** A reload starts a new local one.
  The server keeps the reason, so reopening will show the marker once that exists.
- **No screen shows the revocation records or the per-turn backend in a list.** Steps 28 and 29
  read them from the database. The trace panel shows the backend one turn at a time (step 13).
