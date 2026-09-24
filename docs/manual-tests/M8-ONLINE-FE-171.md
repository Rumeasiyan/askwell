# Manual test — M8-ONLINE-FE-171, the conversation marker and the pre-send disclosure

**Ticket:** `M8-ONLINE-FE-171`. Online AI is now switched on per conversation, with a button
beside that conversation's **Ask** button. A switched-on conversation carries a marker that cannot
be scrolled away. Before its first online question, a box states what will leave the machine. The
wording of that statement is not decided yet (#737). Until it is, the box says so and **every
online question is refused**. Settings no longer has a switch for online AI at all.

**Version under test:** `0.7.41`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 30 minutes. Most of it is waiting for one file to index and for one local answer on
CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal does three things: start Askwell, give it
a stand-in online destination, and read one record the interface does not show (Part F). Those
steps are labelled **Stand-in**.

**What is being checked.**

- `web/components/ask/online-conversation.tsx`: the marker, the switch, the disclosure box, and the
  "Answered locally" label on each turn.
- `web/lib/online-conversation.ts`: the wording, and every decision about what is shown.
- `web/components/ask/ask-state.tsx`: the conversation is created before its first question, so it
  can be switched online before anything is sent.
- `web/components/settings/online-ai.tsx`: no switch.
- On the server, `api/src/askwell/online.py` (`DISCLOSURE`, `confirm_disclosure`, `send_permitted`)
  and `api/src/askwell/ask.py` (`POST /conversations`, and the refusal on `POST /ask`).

**Nothing leaves this machine during this test.** The online destination below is a made-up name
that does not exist. Askwell never tries to reach it, because every online question is refused
before anything is sent, and that is exactly what this test proves. **Do not** set a real provider.

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
rm -rf /tmp/askwell-test-171
mkdir -p /tmp/askwell-test-171
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-171/
ls /tmp/askwell-test-171
```

**You should see:** `handbook_a.pdf`. Page 2 reads "The standard notice period for resignation at
Meridian Loom is sixty-three days."

### 2. Start Askwell from nothing, with a stand-in destination (Stand-in)

A fresh install has no online destination, and then online AI cannot be switched on at all. Part E
checks that. For everything before it, start Askwell with a made-up destination:

```
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
ASKWELL_ONLINE_AI_DESTINATION=api.provider.example:443 \
ASKWELL_ONLINE_AI_MODEL=walkthrough-model \
  podman compose up -d
scripts/dev.sh db upgrade head
podman compose exec api env | grep ONLINE_AI
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, the migration end without an error, and then
`ASKWELL_ONLINE_AI_DESTINATION=api.provider.example:443` and
`ASKWELL_ONLINE_AI_MODEL=walkthrough-model` among the lines printed.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

---

## Part A — cold start, and one local answer

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open
   `http://127.0.0.1:8000`. This is where a user starts. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to step 2 of *Before
   you start*.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step with **Choose files** and **Choose a folder**.

3. Click **Choose files**. In the file picker, open `/tmp/askwell-test-171`, select
   `handbook_a.pdf` and confirm. When asked **"Which folder are these files in?"**, type
   `/tmp/askwell-test-171` and click **Add them**. If a note offers to nominate the folder (or a
   parent), click it and then click **Add them** again. Finish the welcome steps. Skipping an
   optional step is fine. ☐

   **You should see:** the file accepted, with no red "Not added" note.

4. Click **Library** in the rail on the left. Wait until `handbook_a.pdf` says **ready**. ☐

5. Click **Ask** in the rail. ☐

   **You should see:**
   - The small line at the top reads `Askwell 0.7.41 · nothing leaves this machine`.
   - Under the question box, to the left of the **Ask** button, a button reading **Local**.
   - No marker and no box above the question box. Nothing on the screen mentions online AI apart
     from the **Local** button.

6. Type `What is the notice period for resigning at Meridian Loom?` and press **Enter**. Wait for
   the answer; on CPU this can take a minute or two. ☐

   **You should see:** an answer saying sixty-three days, with a source card naming
   `handbook_a.pdf`, page 2. The finished answer has **no** "Answered locally" label. That label
   appears only in a conversation that has used online AI.

## Part B — switch this conversation online mid-thread

7. Click **Local**. ☐

   **You should see:**
   - The button now reads **Online AI: on**, in heavier type with a dark border.
   - The top line changes to `Askwell 0.7.41 · online AI is on for this conversation`.
   - Directly above the question box, a marker in bold with a heavy dark bar on its left:
     *Online AI is on for this conversation until HH:MM. Questions go to
     api.provider.example:443.* HH:MM is about four hours from now.
   - Below the marker, a box headed **Before anything is sent: what will leave this machine**. It
     reads: *Askwell has not yet defined exactly what online AI would send, so it will not send
     anything. Questions in this conversation are refused until that is defined. Switch back to
     local to keep asking. Nothing has left this machine.*
   - The box has exactly one button, **Switch back to local**. There is **no** button to confirm
     or accept. There is nothing to confirm yet.
   - Beside the switch: *Not sent. Online AI is on for this conversation, and what it sends has not
     been confirmed.*
   - Your earlier answer, from step 6, now carries the label **Answered locally**. This is how a
     turn from before the switch is marked.

8. Type `What is the probation period?` into the question box. Press **Enter**, then click
   **Ask**. ☐

   **You should see:** nothing is sent. **Ask** stays greyed out and pressing it does nothing. No
   new turn appears and no working steps start. Your question is still in the box, not cleared.

## Part C — the marker stays

9. Scroll the conversation as far up as it goes. ☐

   **You should see:** the marker, the box and the question box stay pinned at the bottom of the
   window the whole time. None of them scroll out of view.

10. Click **Library** in the rail, then click **Ask** in the rail again. ☐

    **You should see:** the same conversation, with the step 6 answer still labelled **Answered
    locally**, the marker still in bold above the question box, the disclosure box still there, and
    **Ask** still refused.

11. Click **Settings** in the rail and scroll to the **Online AI** section. ☐

    **You should see:** no switch and no button anywhere in the section. Its first line reads:
    *There is no switch here. Online AI is turned on for one conversation at a time, with the
    switch beside that conversation's Ask button, and every new conversation starts local.* Below
    it, under **What it is**, it says there is no setting that turns online AI on everywhere.

12. In the same Settings page, scroll to **Privacy and security → Network activity**. ☐

    **You should see:** `0 outbound requests permitted`. There may be a line under **Permitted, by
    the conversation that made them** naming your conversation and `api.provider.example:443`; if
    so, its count is `0`. The switch opened the door for this conversation; nothing went through
    it.

13. Click **Ask** in the rail. ☐

    **You should see:** the marker and disclosure box still there, as in step 10.

## Part D — back to local

14. In the disclosure box, click **Switch back to local**. ☐

    **You should see:**
    - The box disappears. The "Not sent" line disappears.
    - The button beside **Ask** reads **Local** again.
    - The top line reads `… · nothing leaves this machine` again.
    - The marker stays, but changes to plain grey text with a lighter bar: *Online AI was on in
      this conversation earlier. It is local now: nothing you ask here leaves this machine.* It does
      not go away, because this conversation did use online AI.

15. Click **Ask** (your step 8 question is still in the box). Wait for the answer. ☐

    **You should see:** an answer, from `handbook_a.pdf` or an honest "not in your material"
    abstention, depending on whether the handbook covers probation. Either is fine. Once finished,
    it carries **Answered locally**.

16. Click **Local** again. ☐

    **You should see:** the bold marker and the disclosure box come back, and **Ask** is refused
    again. The box is shown again because nothing was ever confirmed for this conversation.

17. Click **Switch back to local**. ☐

    **You should see:** as in step 14.

## Part E — a new conversation starts local, and an unconfigured install cannot switch

18. Reload the page (`F5`). ☐

    **You should see:** an empty conversation. The top line says `nothing leaves this machine`. The
    button reads **Local**. No marker. A reload starts a new conversation, and a new conversation is
    always local.

19. **(Stand-in)** In the terminal, restart the API with no online destination:

    ```
    podman compose up -d --force-recreate api
    podman compose exec api env | grep ONLINE_AI
    ```

    **You should see:** `ASKWELL_ONLINE_AI_DESTINATION=` and `ASKWELL_ONLINE_AI_MODEL=`, both empty.
    ☐

20. Back in the browser, reload the page, then click **Local**. ☐

    **You should see:** the button stays **Local**. Beside it: *Online AI is not available: no
    online provider is configured, so there is no destination to authorise. Nothing has left this
    machine.* No marker, no disclosure box, and **Ask** still works.

## Part F — the records say nothing was confirmed (Stand-in)

The interface does not list decisions records. Read them directly:

21. ```
    echo "select kind, payload->>'conversation_id' as conversation, payload->>'reason' as reason from audit_decisions where kind like 'online_ai_%' order by occurred_at;" | scripts/dev.sh psql
    ```
    ☐

    **You should see:** for one conversation, `online_ai_enabled` twice (steps 7 and 16) and
    `online_ai_revoked` twice with reason `disabled` (steps 14 and 17). No `restart` row: nothing
    was still switched on when step 19 restarted the API. There is **no** `online_ai_disclosure_confirmed` row. Nothing could be confirmed.

22. ```
    podman compose exec api askwell-verify
    ```
    ☐

    **You should see:** every chain reported intact.

---

## Known gaps

These are deliberate, not defects. Do not report them.

- **The payload wording (#737).** What online AI sends has not been decided. Until it is,
  `askwell.online.DISCLOSURE` is empty on purpose, the disclosure box says so, it has no confirm
  button, and every online question is refused. That is the ticket's safeguard: the product must
  never send something it cannot describe.
- **Confirming the disclosure cannot be walked through.** With nothing to confirm, the confirm
  button, the `online_ai_disclosure_confirmed` decisions record naming the conversation, and "not
  asked again after confirming" cannot be reached from the interface. They are covered by
  `api/tests/test_online.py` and `api/tests/test_ask_online.py`, which set a test statement.
- **A conversation resumed weeks later (#199).** A reload starts a new conversation, and there is
  no way yet to reopen a past one in the interface. The server keeps what the marker needs (the
  conversation was used online, and whether it confirmed), so a reopened conversation will show the
  marker once reopening is built.
- **An online question that abstains.** Online questions are refused, so none can reach the
  provider or abstain there. The trace's "requested online, nothing sent" record
  (`_local_backend`'s `sent_online: false`) is covered by `api/tests/test_ask_online.py`.
- **An online answer withdrawn partway (#733).** This needs a working provider and a confirmed
  disclosure. The replay test in `web/lib/online-conversation.test.ts` covers it.
- **Tool loop, SQL and web answers still run locally with online on (#734).** Unreachable here
  anyway, because online sends are refused.
- **Purchase and balance.** Out of scope, blocked.
