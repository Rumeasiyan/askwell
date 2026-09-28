# Manual test — M9-FIX-FE-212, the trace tells taught facts from inferred ones, and the first click works

**Ticket:** `M9-FIX-FE-212`, issues #760 and #665.

This walkthrough checks two things, both by clicking, from a cold start:

1. **The first click in the left column works (#665).** The report said that in a freshly opened
   window, the first click on **Library**, **Memory** or another item in the left column did
   nothing. Every later click worked. It did not reproduce on `0.7.59` or on the `0.7.26`
   interface where it was found, so **no code changed for it**. Part B is the check a person makes
   in a real browser window. The issue asked for exactly that.
2. **What the trace says was sent (#760).** After an online answer, **How did you get this?** →
   **show what was sent** used to call every memory fact "fact you taught Askwell". That included
   conclusions Askwell reached on its own, which contradicts the statement the user confirmed
   before sending. The two kinds are now counted apart, in that statement's own words: *"N facts
   you taught Askwell"* and *"N conclusions Askwell drew on its own"*. Notes on spreadsheets and
   databases read *"notes on your tables"*. A conclusion you confirmed **before** asking counts as
   taught (the ticket's edge case).

**Version under test:** `0.7.60`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 45 minutes. Most of it is waiting for a file to index and for one local answer on
CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal is used only to start Askwell and a
stand-in online provider, and to read one record the interface does not show. Those steps are
labelled **Stand-in**.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| What the request carried, with the inferred facts recorded as a separate list | `_sent_contents` in `api/src/askwell/ask.py` |
| The lines under **show what was sent** | `transmissionLines`, `memoryFactParts` in `web/lib/trace.ts` |
| The left column and its narrow-window menu | `web/components/shell/rail.tsx`, `rail-drawer.tsx` (unchanged) |

---

## Read this first

**Nothing leaves this machine during this test.** The "online provider" is a small test server in
a container on Askwell's own `internal` network, which has no route off the machine. Askwell
reaches it through its egress proxy exactly as it would reach a real provider. **Do not** enter a
real provider or a real key. That would send your test material to that provider.

**The test server always gives the same answer**, starting `ONLINE-ANSWER:`. It does not match
the question. That is expected: this test is about what the trace says was sent, not about what
came back.

**Where Askwell's own conclusions come from in this test.** Askwell asks about at most five
things per source. When a file raises more, Askwell does not ask about the rest. It writes each of
them to Memory as its own conclusion, labelled **I guessed**. The test file below has six
unexplained abbreviations. Five become questions on the **Clarifications** screen. The sixth,
`ZQV`, becomes a conclusion Askwell drew on its own. **Leave the five questions unanswered** until
the end of the test.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key. Your
> original files are not touched. On the shared development machine, check that nobody needs what
> the stack holds now. If you are unsure, use **Settings → Your data → Export everything** first.

### 1. The test file (Stand-in)

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it, and check that
Redis has its three passwords (Compose refuses to start without them):

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -c '^REDIS_\(API\|WORKER\|PROXY\)_PASSWORD=.' .env
```

**You should see:** a mount that contains `/tmp` (if it does not, set `ASKWELL_ROOTS_MOUNT=/tmp`),
then `3`.

Make the test file:

```
rm -rf /tmp/askwell-test-212 && mkdir -p /tmp/askwell-test-212
cat > /tmp/askwell-test-212/harbour-notes.txt <<'EOF'
Harbour Works staff notes

The BKV desk opens at eight. Send questions for the BKV desk by email. The BKV desk closes at four. Ask the BKV desk about parking.
The DRL team handles deliveries. The DRL team works late on Fridays. Call the DRL team before noon. The DRL team keeps the loading keys.
The HMT store holds spare uniforms. The HMT store is on the ground floor. Sign the HMT store book. The HMT store shuts at lunch.
The KPX room is for interviews. Book the KPX room a day ahead. The KPX room seats six. Leave the KPX room tidy.
The NWS board lists shift changes. Check the NWS board each morning. The NWS board is by the lifts. Pin notices on the NWS board.
The ZQV review is held on the first Monday of every March. Bring last year's figures to the ZQV review.
EOF
ls /tmp/askwell-test-212
```

**You should see:** `harbour-notes.txt`. Five abbreviations appear four times each; `ZQV` appears
twice, so it ranks last and is the one Askwell does not ask about. None is explained anywhere in
the file.

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

KEY = "Bearer sk-walkthrough-placeholder-212"
ANSWER = ["ONLINE-ANSWER: The ZQV review is held ", "on the first Monday of March [1]."]
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

The certificate goes in the run directory, `.run` unless `ASKWELL_RUN_DIR` in `.env` says
otherwise. If it does, copy the file there instead.

```
cd ~/external/quantum-plus/askwell
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
mkdir -p .run && cp /tmp/fakeprov/cert.pem .run/fakeprovider.pem
podman compose -f compose.yaml -f /tmp/fakeprov/override.yaml up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, and the migration end without an error.

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

**You should see:** a container id, no output from `podman logs`, and then `tail` waiting with
nothing printed. Leave this terminal visible. A new line in it means a request reached the
provider.

---

## Part A — cold start and first run

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button. If
   you see the **Ask** screen instead, the stack was not cleared: go back to *Before you start*,
   step 3.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step headed **Add a source**, with **Choose files** and **Choose a
   folder**.

3. Click **Choose files**. In the file picker, open `/tmp/askwell-test-212`, select
   `harbour-notes.txt`, and confirm. When asked **"Which folder are these files in?"**, type
   `/tmp/askwell-test-212` and click **Add them**. If a note offers to nominate the folder (or a
   parent), click it and then click **Add them** again. Finish the welcome steps. Skipping an
   optional step is fine. ☐

   **You should see:** the file accepted, with no red "Not added" note, and then the **Ask**
   screen.

4. Click **Library** in the left column. Wait until `harbour-notes.txt` says **ready**. ☐

   **You should see:** `harbour-notes.txt`, ready. Close this browser window completely.

## Part B — the first click after a fresh load (#665)

Each step starts from a **new** private window, so nothing from an earlier page load carries over.
Click **once** and wait three seconds before judging. Do not click a second time.

5. Open a new private window at `http://127.0.0.1:8000`. When the **Ask** screen shows, click
   **Library** in the left column once. ☐

   **You should see:** within a second or two, the **Library** heading and `harbour-notes.txt`,
   and the address bar ending `/library/`.

6. Close the window. Open a new private window the same way, and click **Memory** once. ☐

   **You should see:** the **Memory** heading, with the line *What Askwell believes about your
   material, and where each belief came from.*, and the address ending `/memory/`.

7. Close the window. Repeat with **Clarifications**, then again with **Settings**. ☐

   **You should see:** the **Clarifications** screen (it lists the five questions about `BKV`,
   `DRL`, `HMT`, `KPX` and `NWS`; do not answer them), then the **Settings** screen. Each on the
   first click.

8. Close the window. Open a new private window, and before anything else make the window narrow,
   about half the screen or less, until the left column disappears and a small button with three
   short lines appears at the top left. Click that button once, then click **Library** once in
   the menu that opens. ☐

   **You should see:** the menu opens on the first click, and **Library** navigates on the first
   click, as in step 5.

9. Close the window. Open a new private window, wait about ten seconds with the mouse outside the
   page, then move straight to **Memory** and click it once. ☐

   **You should see:** the Memory screen, first click.

   **If any first click in steps 5–9 does nothing**, reopen #665 with: the browser and its
   version, the window width, roughly how long after the page appeared you clicked, and which
   item. Then click the same item again and note whether the second click works.

Leave the last window open and widen it again for the rest of the test.

## Part C — Askwell's own conclusion, and a fact you teach it

10. Click **Memory** in the left column. ☐

    **You should see:** a row whose subject is `ZQV`, labelled **I guessed**, reading
    *'ZQV' appears throughout. What does it mean? Not asked — ranked 6 of 6 for this source,
    below the cap of 5.* (the two numbers can differ if Askwell found something else in the file
    to ask about). It has a **Confirm** button. This is a conclusion Askwell drew on its
    own. Do **not** click **Confirm** yet.

    If there is no `ZQV` row, check the **Clarifications** screen: if `ZQV` is one of the questions
    there, write that down as a finding and stop; this part cannot run.

11. Click **Add a fact**. In **Subject, e.g. RFQ** type `annual review`. In **What it means, e.g.
    Request for Quotation** type `The annual review is chaired by the finance lead.` Click
    **Add**. ☐

    **You should see:** the form close, and a row for `annual review` labelled **You told me**.

## Part D — store the provider key, and switch one conversation online

12. Click **Settings** in the left column. Scroll to **Online AI**, then to **Your key**. Click
    **Add a key**. Fill in **Provider address** `fakeprovider:8443`, **Model**
    `test-destination-model` and **Key** `sk-walkthrough-placeholder-212`. Click **Save the
    key**. If asked for your passphrase, enter the one from step 2. ☐

    **You should see:** *"A key is set for fakeprovider:8443, asking for test-destination-model."*
    The key itself is not shown. The third terminal prints nothing.

13. Click **Ask** in the left column. Click the **Local** button to the left of **Ask**. ☐

    **You should see:** the button now reads **Online AI: on**, and a box headed **Before anything
    is sent: what will leave this machine**. In it, the statement includes *"facts you have taught
    it, conclusions it has drawn about your files and databases on its own"*. Those two phrases
    are what the trace has to agree with.

14. Click **I understand. Send my questions online**. ☐

    **You should see:** the box disappears, and **Ask** is no longer greyed out.

## Part E — the trace tells the two kinds apart (#760)

15. Type `When is the ZQV review held?` and click **Ask**. Wait for the answer. ☐

    **You should see:** an answer starting **ONLINE-ANSWER:**, labelled **Answered online ·
    test-destination-model**, with a source card naming `harbour-notes.txt`. In the third
    terminal, one new line with `"request": 1` and `"key_arrived": true`.

    If Askwell instead says it cannot find this in your material, nothing was sent (the third
    terminal stays empty), and this part cannot be checked. Write that down, including the
    answer's wording, and try once more with `What happens at the ZQV review in March?`

16. Under the answer, click **How did you get this?**, then **show what was sent**. ☐

    **You should see:** a line *Sent to fakeprovider:8443 · test-destination-model · <date and
    time> UTC*, then a line starting with a number of bytes. That line lists *Askwell's
    instructions (…)*, *your question*, a number of *passages from your files*, and then:

    - ***1 fact you taught Askwell*** — the `annual review` fact from step 11;
    - ***1 conclusion Askwell drew on its own*** — the `ZQV` row from step 10.

    The words *"fact you taught Askwell"* must **not** cover the `ZQV` row. If the line reads
    *2 facts you taught Askwell*, that is the #760 defect: report it. If the line shows only one
    of the two, write down which. Memory is matched on words in the question (#292), so a fact can
    be left out, and that is not this ticket's defect; but the one that **is** listed must be
    under the right name.

    If a *notes on your tables* part appears, its wording must be exactly that, never *notes on a
    database*. This test file is not a table, so none is expected.

17. In the same panel, find the step that lists the memory Askwell used. ☐

    **You should see:** a chip for `ZQV` marked **I guessed**, and one for `annual review` marked
    **You told me**. Click **Close**.

## Part F — a conclusion confirmed before asking counts as taught

18. Click **Memory** in the left column. On the `ZQV` row, click **Confirm**. ☐

    **You should see:** the row now labelled **You told me**, and no **Confirm** button.

19. Click **Ask** in the left column. ☐

    **You should see:** the same conversation, still **Online AI: on**, with the answer from
    step 15. No disclosure box: this conversation already confirmed the statement.

20. Type `When is the ZQV review held?` again and click **Ask**. Wait for the answer. Under the
    **new** answer, click **How did you get this?**, then **show what was sent**. ☐

    **You should see:** a second line, `"request": 2`, in the third terminal, and in the panel
    ***2 facts you taught Askwell*** and **no** *conclusion Askwell drew on its own*. The `ZQV`
    fact was confirmed before this question was sent, so it was sent as something you taught.
    Click **Close**.

21. Scroll up to the **first** online answer (step 15). Click **How did you get this?**, then
    **show what was sent**. ☐

    **You should see:** it still reads *1 fact you taught Askwell, 1 conclusion Askwell drew on
    its own*. That is what the fact was when that request left the machine, and the record of a
    send does not change afterwards (`docs/decisions.md`, 2026-09-28).

    In the same panel, the memory chip for `ZQV` now reads **You told me**. That is expected: the
    chip shows the fact as it stands today, while **show what was sent** shows it as it was sent.
    Click **Close**.

22. **Stand-in.** The record of each send keeps the same split: ☐

    ```
    cd ~/external/quantum-plus/askwell
    scripts/dev.sh psql -c "SELECT jsonb_array_length(payload->'contents'->'memory_fact_ids') AS facts, \
      jsonb_array_length(payload->'contents'->'inferred_fact_ids') AS inferred \
      FROM audit_interactions WHERE kind = 'online_ai_request' ORDER BY occurred_at;"
    ```

    **You should see:** two rows. The first `2 | 1`, the second `2 | 0`. The numbers must match
    what steps 16 and 20 showed.

## Part G — what cannot be clicked (Stand-in)

A trace recorded before `0.7.60` has no record of which facts were inferred. On a cold start there
is no such trace to open, so tests pin that case, along with the rest of the change.

23. ```
    cd ~/external/quantum-plus/askwell
    scripts/dev.sh test tests/test_ask_sent_contents.py -p no:warnings -rA | grep -E "PASSED|FAILED|ERROR|passed|failed"
    scripts/dev.sh test-db tests/test_ask_online.py -p no:warnings -rA \
      -k "taught_fact_from_an_inferred_one" | grep -E "PASSED|FAILED|ERROR|passed|failed"
    scripts/dev.sh web-check 2>&1 | grep -E "transmissionLines|pass|fail"
    ```
    ☐

    **You should see:** no `FAILED`, `ERROR` or `skipped`, and passing results for:
    - `test_an_inferred_fact_is_recorded_as_inferred`;
    - `test_a_confirmed_inference_counts_as_taught`;
    - `test_nothing_from_memory_records_empty_lists`;
    - `test_what_was_sent_tells_a_taught_fact_from_an_inferred_one`;
    - the web tests *transmissionLines says an inferred fact was inferred, not taught*,
      *transmissionLines names only inferred facts when nothing sent was taught*, and
      *transmissionLines claims neither origin for a record that predates the split*. That last one
      is the older-trace case: it reads *"things Askwell knows about your material"* rather than
      guessing.

---

## Teardown

1. In **Settings → Online AI → Your key**, remove the key. **You should see:** *"No key is set.
   Online AI cannot be switched on in any conversation."*
2. In a terminal:

   ```
   cd ~/external/quantum-plus/askwell
   podman stop askwell-fakeprovider
   rm -f .run/fakeprovider.pem
   podman compose -f compose.yaml up -d --force-recreate api
   rm -rf /tmp/fakeprov /tmp/askwell-test-212
   ```

---

## Known gaps

These are deliberate or already tracked. Do not report them as defects of this ticket.

- **#665 was checked, not fixed.** No code changed for the first click. 64 of 64 scripted
  first clicks navigated (headless and a real headed Chrome window; 1024 and 700 wide; column and
  menu; 300 ms to 10 s after load; empty and populated library; the welcome redirect; the page's
  navigation data refused), including on the `0.7.26` interface where it was reported. Part B is
  the human check. If it fails for you, reopen #665 with the details asked for in step 9.
- **Traces from before `0.7.60`** have no record of which facts were inferred and say *"things
  Askwell knows about your material"*. They are not rewritten. Part G covers this by test,
  because a cold start has none.
- **The old trace's memory chips show today's origin** (step 21). The chip list reads each fact
  as it is now; **show what was sent** reads it as it was sent. Both are intended.
- **Which memory facts are sent depends on word matching (#292).** A fact that bears on the
  question can be left out, or the other way round. This ticket is about how the facts that are
  sent are named, not which ones are sent.
- **The wording is the approved statement's, and awaits the owner's review** (#760). A change to
  it should follow the statement, not drift from it.
- **No real provider here.** A real provider, seen from outside in a packet capture, is release
  gate G13 (`docs/online-release-test.md`).
- **The five pending clarifications** from the test file are expected. Answering or dismissing
  them is covered by the clarification tickets, not this one.
