# Manual test — M8-ONLINE-OBS-172, the local record of what was sent to an online provider

**Ticket:** `M8-ONLINE-OBS-172`. Each request Askwell makes to an online provider is now recorded
on this machine in two places. The first is the turn's trace, which you open with **How did you
get this?** and then **show what was sent**. The second is a new `online_ai_request` record in the
interaction log. The record says where the request went, which model, when, its exact size in
bytes, what it was made of (by reference, never by text), and how it ended. **Nothing is sent to
Askwell itself.** The ticket's "transmitted billing record" went with the credit tier (#255), so
that record is not built. See `docs/decisions.md`, 2026-09-24, `M8-ONLINE-OBS-172`.

**Version under test:** `0.7.42`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 30 minutes. Most of it is waiting for one file to index and for two local answers
on CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal does four things: start Askwell, give it
a stand-in online destination, read the interaction log directly (the interface does not list it),
and run the automated tests that cover what cannot be clicked yet. Those steps are labelled
**Stand-in**.

> **Read this first: the online half of this ticket cannot be clicked through yet.** Every online
> question is refused until the owner decides what the provider receives (issue #737), and there
> is no way to enter a provider key until `M8-KEY-BE-173`. So no turn can reach a provider, and
> **show what was sent** cannot appear on any answer you can produce by clicking. This walkthrough
> proves the half that *can* be reached:
>
> - a local answer carries no transmission record, in the trace or in the log;
> - switching a conversation online and being refused sends nothing and records no request;
> - the turn's own `ask_asked` log record keeps exactly the shape it had before this ticket;
> - the audit chains stay intact.
>
> Part E then runs the automated tests that cover the online half against a mock provider. The
> **Known gaps** section lists everything else. When #737 and `M8-KEY-BE-173` land, this document
> needs a Part covering a real online turn and an independent network capture (the capture
> belongs to `M8-ONLINE-TEST-176`).

**What is being checked.**

- `api/src/askwell/inference/provider.py`: `Transmission`, and how `OnlineClient` fills it in on
  every call.
- `api/src/askwell/ask.py`: `_sent_contents`, `_transmission_record`, the `transmission` key on
  the trace's backend, and the `online_ai_request` interaction record.
- `web/lib/trace.ts` (`transmissionLines`) and `web/components/ask/trace-panel.tsx`
  (`BackendLine`): the **show what was sent** disclosure.

**Nothing leaves this machine during this test.** The online destination below is a made-up name
that does not exist. **Do not** set a real provider.

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
rm -rf /tmp/askwell-test-172
mkdir -p /tmp/askwell-test-172
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-172/
ls /tmp/askwell-test-172
```

**You should see:** `handbook_a.pdf`. Page 2 reads "The standard notice period for resignation at
Meridian Loom is sixty-three days."

### 2. Start Askwell from nothing, with a stand-in destination (Stand-in)

Without a destination, online AI cannot be switched on at all, and Part C could not be reached.
Start Askwell with a made-up one:

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
start, the migration finish without an error, and then
`ASKWELL_ONLINE_AI_DESTINATION=api.provider.example:443` and
`ASKWELL_ONLINE_AI_MODEL=walkthrough-model` among the lines printed.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

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

3. Click **Choose files**. In the file picker, open `/tmp/askwell-test-172`, select
   `handbook_a.pdf` and confirm. When asked **"Which folder are these files in?"**, type
   `/tmp/askwell-test-172` and click **Add them**. If a note offers to nominate the folder (or a
   parent), click it and then click **Add them** again. Finish the welcome steps. Skipping an
   optional step is fine. ☐

   **You should see:** the file accepted, with no red "Not added" note.

4. Click **Library** in the rail on the left. Wait until `handbook_a.pdf` says **ready**. ☐

5. Click **Ask** in the rail. ☐

   **You should see:** the small line at the top reads
   `Askwell 0.7.42 · nothing leaves this machine`. To the left of the **Ask** button there is a
   button reading **Local**.

6. Type `What is the notice period for resigning at Meridian Loom?` and press **Enter**. Wait for
   the answer. On CPU this can take a minute or two. ☐

   **You should see:** an answer saying sixty-three days, with a source card naming
   `handbook_a.pdf`, page 2.

## Part B — a local answer's trace has nothing to show as sent

7. Under the answer, click **How did you get this?** ☐

   **You should see:** a panel slide in from the right, headed **How did you get this?**, with
   **Copy trace** and **Close** at the top. The first line in the panel reads `local ·` followed by
   the local model's name. Below that is the list of steps, starting with the search of your files.

8. Look directly under the `local · …` line. ☐

   **You should see:** **no** "show what was sent" line. That line appears only when this turn made
   a request to an online provider, and this one made none. If it is there, that is a defect.
   Report it.

9. Click **Copy trace**, then paste into any text editor. ☐

   **You should see:** the button briefly reads **Copied**. The pasted text starts with
   `Question: What is the notice period…`, then `Backend: local · <model name>`. The next line is
   **not** one starting `Sent to` or `Nothing left this machine`.

10. Click **Close**. ☐

    **You should see:** the panel closes and the answer is still on screen.

## Part C — switching online, and being refused, sends nothing

11. Click **Local**. ☐

    **You should see:** the button now reads **Online AI: on**. Above the question box is a bold
    marker naming `api.provider.example:443`. Below it is a box headed **Before anything is sent:
    what will leave this machine**, which says nothing will be sent until that is defined. It has
    one button, **Switch back to local**. (This is `M8-ONLINE-FE-171`'s screen, unchanged by this
    ticket.)

12. Type `What is the probation period?` into the question box and try to send it: press
    **Enter**, then click **Ask**. ☐

    **You should see:** nothing is sent. **Ask** stays greyed out. No new turn appears, and your
    question stays in the box. Because no turn exists, there is no trace to open and no request to
    record.

13. Click **Settings** in the rail and scroll to **Privacy and security → Network activity**. ☐

    **You should see:** `0 outbound requests permitted`. If there is a row for your conversation
    under **Permitted, by the conversation that made them**, its count is `0`.

14. Click **Ask** in the rail. In the disclosure box, click **Switch back to local**. ☐

    **You should see:** the box disappears, the button reads **Local** again, and the marker turns
    to plain grey text saying online AI was on in this conversation earlier.

15. Click **Ask** (the probation question is still in the box). Wait for the answer. ☐

    **You should see:** either an answer from `handbook_a.pdf` or an honest "not in your material"
    abstention. Either is fine. Once the answer finishes, it is labelled **Answered locally**.

16. Under that answer, click **How did you get this?** ☐

    **You should see:** the first line reads `local ·` and the model name. There is **no** "show
    what was sent" line. This conversation was online earlier, but this turn was asked locally, so
    nothing was sent for it. Click **Close**.

## Part D — the interaction log agrees (Stand-in)

The interface does not list interaction records. Read them directly.

17. Count the records of each kind in the interaction log:

    ```
    echo "select kind, count(*) from audit_interactions group by kind order by kind;" | scripts/dev.sh psql
    ```
    ☐

    **You should see:** an `ask_asked` row with a count of `2` (steps 6 and 15). There is **no**
    `online_ai_request` row. No request was ever made to a provider, so none is recorded. Other
    kinds may appear. Only these two matter here.

18. Check that the `ask_asked` record kept its shape:

    ```
    echo "select distinct jsonb_object_keys(payload) as key from audit_interactions where kind = 'ask_asked' order by 1;" | scripts/dev.sh psql
    ```
    ☐

    **You should see:** these keys, and no others: `abstained`, `answer`, `backend`,
    `citation_count`, `conflict_detected`, `conflict_topic`, `conversation_id`, `duration_ms`,
    `memory_fact_ids`, `message_id`, `model`, `online_fallback`, `partial`, `question`,
    `retrieved_chunks`, `schema_note_ids`, `source_id`, `status`, `threshold`,
    `uncovered_aspects`. (`online_fallback` is from `M8-ONLINE-BE-170` and is empty on a local
    turn.) In particular, there is **no** `transmission` or `sent` key. Online mode adds its own
    record and never reshapes this one.

    If the list differs, check `git log -p -- api/src/askwell/ask.py` for a later ticket that
    changed `ask_asked` on purpose before you report it.

19. Check that neither trace carries a transmission:

    ```
    echo "select id, trace->'backend' as backend from messages where role = 'assistant' order by created_at;" | scripts/dev.sh psql
    ```
    ☐

    **You should see:** two rows. Each backend reads `{"mode": "local", "model": "…"}`, possibly
    with other keys. Neither contains `transmission`.

    If `psql` reports that a column does not exist, run `\d messages` in `scripts/dev.sh psql` and
    use that table's names. The check is the same: no `transmission` in either backend.

20. Verify the audit chains:

    ```
    podman compose exec api askwell-verify
    ```
    ☐

    **You should see:** every chain reported intact.

## Part E — the online half, against a mock provider (Stand-in)

No click can reach a provider yet (see the note at the top). These tests do: they run a turn
against a mock provider, read the request off the mock, and compare it with what was recorded.

21. Run the provider and ask-online tests (the stack must still be up):

    ```
    scripts/dev.sh test tests/test_inference_provider.py
    scripts/dev.sh test-db tests/test_ask_online.py
    ```
    ☐

    **You should see:** both runs end with `passed` and no `failed`, `error` or `skipped`. Between
    them, they prove the following:
    - the recorded `request_bytes` equals the size of the body the mock provider received;
    - the `online_ai_request` record matches the trace's `transmission` entry exactly, and contains
      none of the question, passage or answer text;
    - a provider refusal (401) or rate limit (429) is recorded as sent, and is shown on the local
      fallback answer;
    - a connection that was never made is recorded as not sent;
    - an abstention records no request;
    - `ask_asked` has the same keys online as locally;
    - the request body carries only `model`, `messages`, `max_tokens`, `temperature` and `stream`.

22. Run the frontend tests:

    ```
    scripts/dev.sh web-run pnpm test
    ```
    ☐

    **You should see:** a run that ends with no failures. Among the tests are the
    `transmissionLines` cases, which fix the exact wording **show what was sent** will display.
    For an answered request, the text is:
    *Sent to api.provider.example:443 · provider-model · 2026-09-24 10:31:05 UTC*, then
    *4210 bytes: Askwell's instructions (…), your question, 3 passages from your files, 1 fact you
    taught Askwell.*, then *The provider answered.* When the connection was never made, the only
    text is *Nothing left this machine. The connection to … was not made (network_unavailable).*

---

## Known gaps

These are deliberate, not defects. Do not report them.

- **No online turn can be walked (#737, `M8-KEY-BE-173`).** Every online question is refused
  until the owner decides what the provider receives, and there is no way to enter a provider key
  yet. So **show what was sent** cannot be seen on a real answer, and no `online_ai_request` record
  can be produced by clicking. Part E covers it with a mock provider. When both land, add a Part
  that asks an online question and opens **show what was sent**, and a Part in which the provider
  refuses and the local model answers.
- **The independent network capture.** The ticket's "a network capture confirms nothing beyond it
  left the machine" belongs to `M8-ONLINE-TEST-176`, and it needs a request that is actually sent.
  Until then, the body's fields are fixed by a test that reads the request off the wire (Part E).
- **No transmitted billing record, and no Settings view of one.** Askwell sends nothing to itself.
  The credit service it was designed for was dropped (#255), and #45's billing fields no longer
  apply. This is the ticket's "transmitted record", answered with *none*, and recorded in
  `docs/decisions.md`. Settings gets no new view. The per-turn view is the trace.
- **No token counts.** They were a billing field. Adding them would change the request payload,
  which #737 is still deciding. The provider's own dashboard is the authority on usage.
- **The text that was sent is never shown.** The record names the parts (instructions, question,
  how many passages, facts and notes) by identifier. It never copies their text, because a
  plaintext copy would sit outside the passphrase encryption and inside the log export. This is by
  design.
- **Tool-loop, SQL and web answers still run locally with online on (#734).** They never reach a
  provider, so they never carry a transmission.
- **"A failed billing transmission must never fail the answer."** Nothing is transmitted to
  Askwell, so this edge case has nothing to apply to. A failure to write the *local*
  `online_ai_request` record fails the turn's write as a whole, the same as `ask_asked` (C6).
