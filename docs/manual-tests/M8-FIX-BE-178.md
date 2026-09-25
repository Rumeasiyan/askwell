# Manual test — M8-FIX-BE-178, the approved statement of what online AI sends

**Ticket:** `M8-FIX-BE-178`. Until now every online question was refused, because Askwell had no
statement of what it would send (#737). This ticket sets that statement, as version `1`, to the
wording the product owner approved on 2026-09-25 (#753). The disclosure box shown before a
conversation's first online question now shows that statement, with a confirm button. Once
confirmed, the question goes to the provider.

This walkthrough checks two things by clicking:

1. The statement appears word for word, a question can be sent only after it is confirmed, and
   the question then reaches the provider.
2. **The statement is true.** A stand-in provider on this machine keeps a full copy of every
   request it receives. Part F compares that copy with the statement, one clause at a time. The
   ticket's own assumption is that "what is sent still matches the statement clause by clause". A
   statement that is not true of what leaves the machine is worse than refusing every send.

**Version under test:** `0.7.48`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 60 minutes. Most of it is waiting for two files to index and for local answers on
CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal starts Askwell and the stand-in
provider, reads what the provider received, reads one record the interface does not show, and
runs the tests for what cannot be clicked. Those steps are labelled **Stand-in**.

**What is being checked.**

- `api/src/askwell/online.py`: `DISCLOSURE`, which is now set, and the confirmation and refusal
  around it, which are unchanged.
- The disclosure box, the marker and the per-turn labels in
  `web/components/ask/online-conversation.tsx`, now showing a real statement rather than the
  "not yet defined" text.
- What `askwell.ask` actually sends: `askwell.agent.conflict.compose_conflict` and
  `askwell.agent.compose` (passages, memory facts, schema notes), plus the schema notes written by
  `askwell.table_infer.raise_table_inference`.
- The Redis-ordering guard, `test_no_online_send_is_possible_until_redis_is_authenticated`
  (Part K).

---

## Read this first

**Nothing leaves this machine during this test.** The "online provider" is a small test server in
a container on Askwell's own `internal` network, which has no route off the machine. Askwell
reaches it through its egress proxy exactly as it would reach a real provider. You enter it in
Settings as the provider, like any other. **Do not** enter a real provider or a real key. That
would send your test material to that provider. The real-provider check is release gate G13
(`docs/online-release-test.md`), and it is a separate procedure.

**The test server keeps everything it is sent.** For each request it writes:

- one line to `/tmp/fakeprov/requests.jsonl`: the request number, the model, and whether the key
  arrived;
- the full text Askwell sent as the question part of the request, to
  `/tmp/fakeprov/prompt-<number>.txt`.

It always gives the same answer: *ONLINE-ANSWER: The standard notice period for resignation at
Meridian Loom is sixty-three days [1].* When you see `ONLINE-ANSWER:`, the answer came from the
provider. Without it, the answer came from the local model. The fixed answer does not match
every question. That is expected: this test is about what was sent, not about what came back.

**The placeholder key** used below is `sk-walkthrough-placeholder-178`. It is made up.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key. Your
> original files are not touched. On the shared development machine, check that nobody needs what
> the stack holds now. If you are unsure, use **Settings → Your data → Export everything** first.

### 1. Two test files

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it, and check that
Redis has its three passwords (`M8-FIX-SEC-177`; Compose refuses to start without them):

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -c '^REDIS_\(API\|WORKER\|PROXY\)_PASSWORD=.' .env
grep -n "ONLINE_AI_DESTINATION\|ONLINE_AI_MODEL" .env
```

**You should see:** a mount that contains `/tmp` (if it does not, set `ASKWELL_ROOTS_MOUNT=/tmp`),
then `3`, then nothing from the last `grep`. If the last `grep` prints lines, delete them: nothing
has read them since `M8-KEY-BE-173`, because the destination now comes from the stored key.

Then make the test files. One is the handbook from the fixture corpus. The other is a small
spreadsheet, whose date column can only be read one way:

```
rm -rf /tmp/askwell-test-178
mkdir -p /tmp/askwell-test-178
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-178/
printf 'staff,period_start\nA. Perera,25/03/2026\nB. Silva,04/05/2026\nC. Fernando,11/06/2026\n' \
  > /tmp/askwell-test-178/rota.csv
ls /tmp/askwell-test-178
```

**You should see:** `handbook_a.pdf` and `rota.csv`. Page 2 of the handbook reads "The standard
notice period for resignation at Meridian Loom is sixty-three days." Page 5 reads "The Meridian
Loom probation period for new hires lasts one hundred and four days." In `rota.csv`, `25/03/2026`
can only be day-first, because there is no month 25. That cell is the "single value from one of
your tables" the statement mentions.

### 2. The test provider (Stand-in)

Make a certificate for the name `fakeprovider`, which is the server's name on the internal
network:

```
rm -rf /tmp/fakeprov && mkdir -p /tmp/fakeprov && cd /tmp/fakeprov
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=fakeprovider \
  -addext subjectAltName=DNS:fakeprovider -keyout key.pem -out cert.pem
: > requests.jsonl
chmod a+rw requests.jsonl && chmod a+rwx /tmp/fakeprov
```

Save this as `/tmp/fakeprov/server.py`:

```python
import http.server, json, ssl, time

KEY = "Bearer sk-walkthrough-placeholder-178"
ANSWER = ["ONLINE-ANSWER: The standard notice period for resignation ",
          "at Meridian Loom is sixty-three days [1]."]
count = 0


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        global count
        count += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with open(f"/data/prompt-{count}.txt", "w") as f:
            f.write(body["messages"][1]["content"])
        with open("/data/requests.jsonl", "a") as f:
            f.write(json.dumps({
                "request": count,
                "model": body.get("model"),
                "roles": [m["role"] for m in body["messages"]],
                "key_arrived": self.headers.get("Authorization") == KEY,
            }) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for piece in ANSWER:
            ev = {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.3)
        ev = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(f"data: {json.dumps(ev)}\n\ndata: [DONE]\n\n".encode())


srv = http.server.HTTPServer(("0.0.0.0", 8443), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("/data/cert.pem", "/data/key.pem")
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
```

Save this as `/tmp/fakeprov/override.yaml`. It makes the `api` container trust the test
certificate, and changes nothing else:

```yaml
services:
  api:
    environment:
      SSL_CERT_FILE: /run/askwell/fakeprovider.pem
```

### 3. Start Askwell from nothing (Stand-in)

The certificate goes in the run directory, which the `api` container sees as `/run/askwell`. It is
`.run` unless `ASKWELL_RUN_DIR` in `.env` says otherwise. If it does, copy the file there instead.

```
cd ~/external/quantum-plus/askwell
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
mkdir -p .run && cp /tmp/fakeprov/cert.pem .run/fakeprovider.pem
podman compose -f compose.yaml -f /tmp/fakeprov/override.yaml up -d
scripts/dev.sh db upgrade head
podman compose exec api env | grep SSL_CERT_FILE
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, the migration end without an error, and `SSL_CERT_FILE=/run/askwell/fakeprovider.pem`.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

### 4. Start the test provider (Stand-in)

In a **third** terminal:

```
podman run -d --rm --name askwell-fakeprovider --network askwell_internal \
  --network-alias fakeprovider -v /tmp/fakeprov:/data:Z --entrypoint python \
  localhost/askwell-api:dev /data/server.py
podman logs askwell-fakeprovider
tail -f /tmp/fakeprov/requests.jsonl
```

**You should see:** a container id, no output from `podman logs` (no Python traceback), and then
`tail` waiting with nothing printed. Leave this terminal visible. A new line in it means a request
reached the provider.

---

## Part A — cold start, and one local answer

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open
   `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you
   start*, step 3.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step headed **Add a source**, with **Choose files** and **Choose a
   folder**.

3. Click **Choose files**. In the file picker, open `/tmp/askwell-test-178`, select **both**
   `handbook_a.pdf` and `rota.csv`, and confirm. When asked **"Which folder are these files in?"**,
   type `/tmp/askwell-test-178` and click **Add them**. If a note offers to nominate the folder
   (or a parent), click it and then click **Add them** again. Finish the welcome steps. Skipping
   an optional step is fine. ☐

   **You should see:** both files accepted, with no red "Not added" note.

4. Click **Library** in the rail on the left. Wait until both files say **ready**. ☐

   **You should see:** `handbook_a.pdf` and `rota.csv`, both ready. If `rota.csv` asks a
   question about its dates, write that down as a finding: `25/03/2026` should have settled the
   format without asking.

5. Click **Ask** in the rail. ☐

   **You should see:** the small line at the top reads `Askwell 0.7.48 · nothing leaves this
   machine`, and to the left of the **Ask** button there is a button reading **Local**.

6. Type `What is the notice period for resigning at Meridian Loom?` and press **Enter**. Wait for
   the answer. On CPU this can take a minute or two. ☐

   **You should see:** an answer saying sixty-three days, **not** starting with `ONLINE-ANSWER:`,
   with a source card naming `handbook_a.pdf`, page 2. The third terminal prints **nothing**.

## Part B — teach Askwell a fact, outside any conversation

The statement says "something you taught it elsewhere can be included". The Memory screen is
"elsewhere": it belongs to no conversation.

7. Click **Memory** in the rail. ☐

   **You should see:** the heading line *What Askwell believes about your material, and where each
   belief came from.* Among the rows are some for `rota.csv`, labelled **I guessed**. Askwell
   wrote these on its own when it read the spreadsheet. One is for `period_start`, and its text
   includes `DD/MM/YYYY` and `'25/03/2026'`. That is the cell that settled the date format.

8. Click **Add a fact**. In **Subject, e.g. RFQ** type `Meridian Loom`. In **What it means, e.g.
   Request for Quotation** type `The client's trading name for Loom Holdings Ltd.` Click
   **Add**. ☐

   **You should see:** the form close, and a row for `Meridian Loom` labelled **You told me**.

## Part C — store the provider key

9. Click **Settings** in the rail. Scroll to **Online AI**, then to **Your key**. ☐

   **You should see:** *"No key is set. Online AI cannot be switched on in any conversation."* and
   a button **Add a key**.

10. Click **Add a key**. Fill in **Provider address** `fakeprovider:8443`, **Model**
    `test-destination-model` and **Key** `sk-walkthrough-placeholder-178`. Click **Save the key**.
    If you are asked for your passphrase, enter the one from step 2. ☐

    **You should see:** the form close, and *"A key is set for fakeprovider:8443, asking for
    test-destination-model."* The key itself is not shown anywhere. The third terminal prints
    nothing: storing a key sends nothing.

## Part D — switch the conversation online, and read the statement

11. Click **Ask** in the rail. ☐

    **You should see:** the conversation from step 6, with its answer. **Local** beside **Ask**.

12. Click **Local**. ☐

    **You should see:**
    - the button now reads **Online AI: on**;
    - the top line reads `Askwell 0.7.48 · online AI is on for this conversation`;
    - above the question box, a marker in bold: *Online AI is on for this conversation until
      HH:MM. Questions go to fakeprovider:8443.*;
    - the step 6 answer now labelled **Answered locally**;
    - below the marker, a box headed **Before anything is sent: what will leave this machine**,
      with two buttons: **I understand. Send my questions online** and **Switch back to local**;
    - beside the switch: *Not sent. Online AI is on for this conversation, and what it sends has
      not been confirmed.*

13. Read the statement in the box and compare it, word for word, with the approved text: ☐

    > When you ask in this conversation, Askwell sends your online AI provider your question, the
    > passages from your files that it found relevant to it, and what Askwell knows about your
    > material that bears on the question: facts you have taught it, conclusions it has drawn
    > about your files and databases on its own — including the names of your tables and
    > columns — and, occasionally, a single value from one of your tables that it used to work out
    > how the dates in a column are written. What Askwell knows is not tied to one conversation,
    > so something you taught it elsewhere can be included. It does not send whole files,
    > database query results, or the questions and answers from earlier turns. A question Askwell
    > cannot answer from your files sends nothing.

    **You should see:** exactly this text. Check every word and punctuation mark, including both
    long dashes. A missing, added or changed word is a defect: the ticket requires the text
    verbatim. The box must **not** say *"Askwell has not yet defined exactly what online AI would
    send…"*. That was the text before this ticket.

14. Type `What is the notice period for resigning at Meridian Loom?` into the question box. Press
    **Enter**, then click **Ask**. ☐

    **You should see:** nothing sent. **Ask** stays greyed out, no new turn appears, and your
    question stays in the box. The third terminal prints nothing. Being online does not permit a
    send until the statement is confirmed. This is the ticket's `NOT_CONFIRMED` edge case.

## Part E — confirm, ask, and the request reaches the provider

15. Click **I understand. Send my questions online**. ☐

    **You should see:**
    - the box disappears, and so does the *Not sent…* line;
    - the bold marker stays, still naming `fakeprovider:8443`;
    - **Ask** is no longer greyed out, and your question from step 14 is still in the box.

16. Click **Ask**. ☐

    **You should see:**
    - the same working steps as in step 6, including the search of your files;
    - an answer starting **ONLINE-ANSWER: The standard notice period for resignation at Meridian
      Loom is sixty-three days**, arriving in two pieces, with a source card naming
      `handbook_a.pdf`, page 2;
    - when it finishes, the label **Answered online · test-destination-model**;
    - in the third terminal, exactly **one** new line:
      `{"request": 1, "model": "test-destination-model", "roles": ["system", "user"], "key_arrived": true}`.

    This is the ticket's acceptance criterion: *a confirmation of version `1` is accepted, and the
    send then goes.* If no line appears, or the answer has no `ONLINE-ANSWER:`, the send did not
    go. Stop, and report it with the answer's **How did you get this?** panel.

17. Under the online answer, click **How did you get this?**, then **show what was sent**. ☐

    **You should see:** a line *Sent to fakeprovider:8443 · test-destination-model · <date and
    time> UTC*, then a line starting with a number of bytes. That line lists *Askwell's
    instructions (…)*, *your question*, a number of *passages from your files*, *1 fact you taught
    Askwell* and at least one *note on a database*. Write the byte count and the number of passages
    down. Click **Close**.

    The notes here come from `rota.csv`, which is a spreadsheet, not a database, and the trace
    calls every memory fact one "you taught". Both labels are issue #760. They are not a defect of
    this ticket.

## Part F — the statement is true of what was sent (Stand-in)

Read the request's full text:

```
cat /tmp/fakeprov/prompt-1.txt
```

It has `<retrieved-content …>` blocks (passages), then `<memory-facts>` and `<schema-notes>`
blocks, then `Question: …` at the end. Check each clause of the statement against it:

18. **"your question"**: the last line is `Question: What is the notice period for resigning at
    Meridian Loom?` ☐

19. **"the passages from your files that it found relevant to it"**: the number of
    `<retrieved-content` blocks equals the number of passages from step 17. One of them contains
    *"The standard notice period for resignation at Meridian Loom is sixty-three days."* ☐

20. **"It does not send whole files"**: text from `handbook_a.pdf` appears **only** inside
    `<retrieved-content>` blocks. There is no unlabelled stretch of the file. ☐

    To count:

    ```
    grep -c '<retrieved-content' /tmp/fakeprov/prompt-1.txt
    ```

21. **"facts you have taught it … something you taught it elsewhere can be included"**: inside
    `<memory-facts>`, a line containing `[user-confirmed] Meridian Loom: The client's trading name
    for Loom Holdings Ltd.` You taught this on the Memory screen in step 8, not in this
    conversation. ☐

22. **"conclusions it has drawn about your files and databases on its own — including the names
    of your tables and columns"**: inside `<schema-notes>`, a line marked `[inferred, confidence
    …]` naming the `rota.csv` table and the `period_start` column. ☐

23. **"occasionally, a single value from one of your tables that it used to work out how the
    dates in a column are written"**: the same line contains `Date format inferred: DD/MM/YYYY`
    and `'25/03/2026'`. ☐

    ```
    grep -n "25/03/2026" /tmp/fakeprov/prompt-1.txt
    grep -c "Perera\|Silva\|Fernando\|04/05/2026\|11/06/2026" /tmp/fakeprov/prompt-1.txt
    ```

    **You should see:** one line from the first command, and `0` from the second. One cell was
    sent, and no other cell of the table.

24. **Nothing outside the statement**: read the whole file once more. ☐

    **You should see:** only the blocks named above and the question. Anything else is a finding.
    Report the text and which clause it falls outside. Do not decide yourself whether it is
    harmless. The statement can only be changed by the owner, under a new version.

Steps 21 to 23 depend on Askwell's lexical memory search matching words in the question
(`askwell.memory.retrieve_relevant_facts`). The words that match are "Meridian Loom" for the fact
and "period" for the note. If step 17 listed no fact or no note, and the file has no such block,
write that down. It means nothing was sent that the clause would cover. It does not make the
statement untrue.

## Part G — earlier turns are not sent

25. In the same conversation, type `How long is the probation period for new hires at Meridian
    Loom?` and click **Ask**. ☐

    **You should see:** the fixed `ONLINE-ANSWER:` text again (the test server does not read the
    question), labelled **Answered online · test-destination-model**, and a second line in the
    third terminal, `"request": 2`.

26. **(Stand-in)** Check the second request for anything from the first turn: ☐

    ```
    tail -n 3 /tmp/fakeprov/prompt-2.txt
    grep -c "resigning\|ONLINE-ANSWER\|sixty-three days \[1\]" /tmp/fakeprov/prompt-2.txt
    ```

    **You should see:** the last line is `Question: How long is the probation period for new hires
    at Meridian Loom?`, and the count is `0`. The earlier question and the provider's earlier
    answer are not in it. This is the clause "It does not send … the questions and answers from
    earlier turns". A passage from the handbook's page 2 may still appear inside a
    `<retrieved-content>` block. That is a passage retrieved again for this question, not the
    earlier turn.

## Part H — a database question and an unanswerable question send nothing

27. In the same conversation, type `How many staff are on the rota?` and click **Ask**. Wait for
    the answer. ☐

    **You should see:** an answer of 3, with the query that produced it shown beside the answer,
    labelled **Answered locally**. **No** new line in the third terminal. Database answers stay
    local in an online conversation (#734), so query results are never sent. This is the clause
    "It does not send … database query results". If Askwell answers from the handbook instead of
    querying the table, write that down: it is routing, not this ticket. Still check that no line
    appeared.

28. Type `What is the capital of Mongolia?` and click **Ask**. ☐

    **You should see:** Askwell says it cannot find this in your material and names what would need
    adding. No `ONLINE-ANSWER:`, and **no** new line in the third terminal. This is the clause "A
    question Askwell cannot answer from your files sends nothing". It must never answer from
    general knowledge (C5).

## Part I — the confirmation holds for this conversation, and only this one

29. Click **Online AI: on** to switch back to local. Then click **Local** to switch online
    again. ☐

    **You should see:** after the first click, **Local**, and the marker in plain grey: *Online AI
    was on in this conversation earlier…*. After the second, **Online AI: on**, the bold marker,
    and **no** disclosure box. This conversation confirmed version `1` already, and the statement
    has not changed, so it is not asked again.

30. Reload the page (`F5`). ☐

    **You should see:** an empty, new conversation: **Local**, no marker, and the top line saying
    `nothing leaves this machine`.

31. Click **Local**. ☐

    **You should see:** **Online AI: on**, the bold marker, and the disclosure box with the same
    statement. **Ask** is refused until you confirm. A confirmation belongs to one conversation.
    Click **Switch back to local**.

## Part J — the records (Stand-in)

32. ```
    scripts/dev.sh psql -c "SELECT kind, payload->>'conversation_id' AS conversation, payload->>'version' AS version FROM audit_decisions WHERE kind LIKE 'online_ai_%' ORDER BY occurred_at;"
    ```
    ☐

    **You should see:** exactly **one** `online_ai_disclosure_confirmed` row, with version `1`,
    for the first conversation (step 15). No such row for the conversation from step 30. There are
    also `online_ai_enabled` and `online_ai_revoked` rows for both conversations. The audit
    requirement is that confirming the statement is a decisions record, and this row is it.

33. ```
    podman compose exec api askwell-verify
    ```
    ☐

    **You should see:** every chain reported intact.

34. Click **Settings** in the rail and scroll to **Privacy and security → Network activity**. ☐

    **You should see:** `2 outbound requests permitted`: steps 16 and 25. Under **Permitted, by the
    conversation that made them**, the first conversation and `fakeprovider:8443`, with a count of
    `2`. Steps 27 and 28 added nothing.

## Part K — what cannot be clicked (Stand-in)

Two parts of the ticket cannot be reached from the interface: setting `DISCLOSURE` back to `None`,
and the Redis-ordering guard. Tests pin both.

35. ```
    scripts/dev.sh test tests/test_provider_key.py -p no:warnings -rA \
      -k "until_redis_is_authenticated" | grep -E "PASSED|FAILED|ERROR|passed|failed"
    scripts/dev.sh test-db tests/test_online.py tests/test_ask_online.py -p no:warnings -rA \
      -k "approved_statement or payload_is_undefined or takes_no_question_until or changed_statement_is_confirmed_again" \
      | grep -E "PASSED|FAILED|ERROR|passed|failed"
    ```
    ☐

    **You should see:** no `FAILED`, `ERROR` or `skipped`, and a `PASSED` line for each of these:
    - `test_no_online_send_is_possible_until_redis_is_authenticated`. It passes because Redis is
      authenticated (`--aclfile` under `redis` in `compose.yaml`), not because the test was
      edited. Check that the assertion is still there, unchanged:
      `grep -n "assert online.DISCLOSURE is None or authenticated" api/tests/test_provider_key.py`
      prints one line;
    - `test_the_disclosure_is_the_approved_statement_verbatim_as_version_1`;
    - `test_the_approved_statement_is_shown_and_its_version_confirmed_before_a_send`;
    - `test_while_the_payload_is_undefined_nothing_can_be_confirmed_and_nothing_sent`. With
      `DISCLOSURE` set back to `None`, nothing can be confirmed and nothing is sent;
    - `test_an_online_conversation_takes_no_question_until_what_it_sends_is_confirmed`. The same
      check through `POST /ask`;
    - `test_a_changed_statement_is_confirmed_again`. A future version needs a fresh confirmation;
    - `test_the_approved_statement_is_shown_confirmed_and_the_question_then_sent`.

---

## Teardown

1. In **Settings → Online AI → Your key**, remove the key. **You should see:** *"No key is set.
   Online AI cannot be switched on in any conversation."*
2. In a terminal:

   ```
   podman stop askwell-fakeprovider
   rm -f .run/fakeprovider.pem
   podman compose -f compose.yaml up -d --force-recreate api
   rm -rf /tmp/fakeprov /tmp/askwell-test-178
   ```

   This removes the certificate, restarts the API without the override, and deletes the test
   files and the stand-in provider's copies of what it was sent.

---

## Known gaps

These are deliberate or already tracked. Do not report them as defects of this ticket.

- **No real provider here.** Every send in this walkthrough goes to a test server on the internal
  network. A real provider, seen from outside in a packet capture, is release gate G13
  (`docs/online-release-test.md`, `M8-ONLINE-TEST-176`). It needs the maintainer's own key and is
  run for a release. It still reads `BLOCKED` in `docs/online-test-log.md` until someone runs it.
- **The trace's wording of what was sent (#760).** **Show what was sent** calls every memory fact
  "fact you taught Askwell", including ones Askwell inferred itself, and calls every schema note a
  "note on a database", including notes on a spreadsheet. The statement itself is correct. The
  after-the-fact summary is less exact than the statement, and fixing that is copy owned
  elsewhere.
- **Inferred memory facts are not walked through.** Clarification inference can store a memory
  fact of Askwell's own (`origin = 'inferred'`). Producing one needs a clarification to go
  unanswered below the cap, so this walkthrough covers "conclusions it has drawn on its own"
  through the spreadsheet's schema notes instead.
- **A clarification answered in the same turn.** When a question is interrupted by a clarification
  and the user answers it, the answer is sent as a `<memory-fact>` block. The statement covers it
  as a fact you have taught Askwell. It is not walked here.
- **Tool-loop, database and web answers stay local in an online conversation (#734).** That is why
  step 27 sends nothing. It is also why "database query results" can never be sent today.
- **Whether memory is sent depends on lexical matching (#292).** Facts and notes are matched by
  words, not by meaning, so a fact can bear on a question and still not be sent, or the other way
  round. The statement promises nothing about which ones are sent, only what kinds.
- **Withdrawing the statement** means setting `DISCLOSURE` back to `None` in code and releasing.
  There is no switch for it in the interface, and there is not meant to be. Part K covers it.
- **Reopening a past conversation (#199).** A reload starts a new conversation, so "the
  confirmation outlives a lapse" is checked by switching off and on again in step 29, not by
  reopening the conversation days later.
- **Purchase and balance.** Blocked on their own decision.
