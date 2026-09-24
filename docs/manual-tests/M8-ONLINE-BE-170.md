# Manual test — M8-ONLINE-BE-170, the online backend behind the inference client

**Ticket:** `M8-ONLINE-BE-170`. When a conversation is switched to online AI, a provider writes
the answer. Everything else is unchanged: retrieval, source cards, abstention and the trace all
work exactly as for a local answer. If the provider cannot answer (network gone, refused,
rate-limited, cut off partway), the local model answers instead and the answer says so. It is
never an error. Every turn records which backend and model wrote it.

**Version under test:** `0.7.40`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 50 minutes. Most of it is waiting for files to index and for local answers on CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal does four things: start Askwell, run
the test provider, **stand in for the online switch that does not exist yet**, and read two
records the interface does not show.

**What is being checked.**

- `api/src/askwell/inference/provider.py`: the online client, and its six failure reasons.
- In `api/src/askwell/ask.py`: `_online_client`, `_backend_record`, and the fallback loop in
  the compose step.
- `askwell.online.configured`: both a destination and a model are needed.

---

## Read this first — what can and cannot be clicked today

This ticket builds the **backend**, not the switch a user presses. The switch in a conversation
is `M8-ONLINE-FE-171`, and it does not exist yet. The **Online AI** section in Settings is still
the inert placeholder from `M7-SET-FE-150`, and pressing it must still do nothing.

So there are two kinds of steps:

- **Clicking steps** walk the real path: cold start, first run, adding files, asking, opening
  **How did you get this?**, and opening Settings. Do them every time. They are how a broken
  rail, a lost conversation or a trace that no longer opens gets caught.
- **Terminal steps** are labelled **Stand-in**. They do what the missing switch will do, or read
  a record the interface does not show yet. Where this document says "turn online AI on", the
  stand-in is the only way to do that today.

**Nothing leaves this machine during this test.** The "online provider" is a small test server
in a container on Askwell's own `internal` network, which has no route off the machine. Askwell
reaches it through its egress proxy in exactly the way it would reach a real provider. **Do not**
point `ASKWELL_ONLINE_AI_DESTINATION` at a real provider. That would be a real outbound request,
and C1 permits one only for a real user decision. It would also fail: Askwell holds no key yet
(see Known gaps).

**The test server can be told how to behave.** It reads one word from `/tmp/fakeprov/mode`
before each answer:

| Mode | What the server does | What it stands for |
| ---- | -------------------- | ------------------ |
| `answer` | Streams a cited answer: *ONLINE-ANSWER: The standard notice period for resignation at Meridian Loom is sixty-three days [1].* | A provider that works |
| `uncited` | Streams the same sentence **without** the `[1]` | A provider that breaks the citation rule |
| `429` | Answers `429 Too Many Requests` | Rate-limited |
| `401` | Answers `401 Unauthorized` | Refused |
| `cut` | Streams the first half of the sentence, then hangs up | Fails partway through an answer |

Every answer starts with `ONLINE-ANSWER:`, so you can always tell an online answer from a local
one at a glance. The server also writes one line per request to `/tmp/fakeprov/requests.jsonl`,
so you can count what was sent.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not touched.
> On the shared development machine, check that nobody needs what the stack holds now. If you are
> unsure, use **Settings → Your data → Export everything** first.

### 1. Test files

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then copy the fixture
corpus:

```
rm -rf /tmp/askwell-test-170
mkdir -p /tmp/askwell-test-170
cp -r eval/fixtures/corpus /tmp/askwell-test-170/corpus
ls /tmp/askwell-test-170/corpus
```

**You should see:** nine files, including `handbook_a.pdf`. Page 2 of `handbook_a.pdf` reads
"The standard notice period for resignation at Meridian Loom is sixty-three days." That is the
sentence this test asks about.

### 2. The test provider

Make a certificate for the name `fakeprovider`, which is the name the server will have on the
internal network:

```
rm -rf /tmp/fakeprov && mkdir -p /tmp/fakeprov && cd /tmp/fakeprov
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=fakeprovider \
  -addext subjectAltName=DNS:fakeprovider -keyout key.pem -out cert.pem
echo answer > mode
: > requests.jsonl
chmod a+rw mode requests.jsonl
```

Save this as `/tmp/fakeprov/server.py`:

```python
import http.server, json, os, ssl, time

LOG, MODE = "/data/requests.jsonl", "/data/mode"
CITED = ["ONLINE-ANSWER: The standard notice period for resignation ",
         "at Meridian Loom is sixty-three days [1]."]
UNCITED = ["ONLINE-ANSWER: The standard notice period for resignation ",
           "at Meridian Loom is sixty-three days."]


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        mode = open(MODE).read().strip() if os.path.exists(MODE) else "answer"
        with open(LOG, "a") as f:
            f.write(json.dumps({
                "mode": mode,
                "model": body.get("model"),
                "roles": [m["role"] for m in body["messages"]],
                "has_retrieved": "<retrieved-content" in body["messages"][1]["content"],
                "auth": "Authorization" in self.headers,
            }) + "\n")
        if mode in ("401", "429"):
            self.send_response(int(mode))
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        pieces = UNCITED if mode == "uncited" else CITED
        for piece in pieces[:1] if mode == "cut" else pieces:
            ev = {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.3)
        if mode == "cut":
            return  # hang up with no finish: the answer was cut off partway
        ev = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(f"data: {json.dumps(ev)}\n\ndata: [DONE]\n\n".encode())


srv = http.server.HTTPServer(("0.0.0.0", 8443), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("/data/cert.pem", "/data/key.pem")
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
```

Save this as `/tmp/fakeprov/override.yaml`. It makes the `api` container trust the test
certificate, and nothing else:

```yaml
services:
  api:
    environment:
      SSL_CERT_FILE: /run/askwell/fakeprovider.pem
```

### 3. Start Askwell from nothing

```
cd ~/external/quantum-plus/askwell
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
mkdir -p .run && cp /tmp/fakeprov/cert.pem .run/fakeprovider.pem
ASKWELL_ONLINE_AI_DESTINATION=fakeprovider:8443 \
ASKWELL_ONLINE_AI_MODEL=test-destination-model \
  podman compose -f compose.yaml -f /tmp/fakeprov/override.yaml up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, Compose
report the containers started, and the migration end without an error. Then check the two
settings took:

```
podman compose exec api env | grep ONLINE_AI
```

**You should see:** `ASKWELL_ONLINE_AI_DESTINATION=fakeprovider:8443` and
`ASKWELL_ONLINE_AI_MODEL=test-destination-model`, among others.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

### 4. Start the test provider

In a **third** terminal:

```
podman run -d --rm --name askwell-fakeprovider --network askwell_internal \
  --network-alias fakeprovider -v /tmp/fakeprov:/data:Z --entrypoint python \
  localhost/askwell-api:dev /data/server.py
podman logs askwell-fakeprovider
```

**You should see:** a container id, then no output from `podman logs` (no Python traceback). To
watch requests arrive during the test, leave this running in that terminal:

```
tail -f /tmp/fakeprov/requests.jsonl
```

---

## Part A — cold start, and a local answer to compare against

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open
   `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to *Start Askwell
   from nothing*.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step with **Choose files** and **Choose a folder**.

3. Click **Choose files**. In the file picker, open `/tmp/askwell-test-170/corpus`, select all
   nine files (`Ctrl+A`) and confirm. When asked **"Which folder are these files in?"**, type
   `/tmp/askwell-test-170/corpus` and click **Add them**. If a note offers to nominate the folder
   (or a parent), click it and then click **Add them** again. Finish the welcome steps. Skipping
   an optional step is fine. ☐

   **You should see:** the PDFs and `spec.docx` accepted, with no red "Not added" note.

4. Click **Library** in the rail on the left. Wait until every file is **ready**.
   `notice_scan.pdf` may say it needs attention because it is a scan. That is fine. ☐

   **You should see:** `handbook_a.pdf` ready.

5. Click **Ask** in the rail. Type `What is the notice period for resigning at Meridian Loom?`
   and send it. Wait for the answer; on CPU this can take a minute or two. ☐

   **You should see:** named steps while it works, then an answer saying sixty-three days. It does
   **not** start with `ONLINE-ANSWER:`. A source card in the right-hand margin names
   `handbook_a.pdf`, page 2. The test server's log (third terminal) has **no** new line.

6. Under the answer, click **How did you get this?** ☐

   **You should see:** a panel titled **How did you get this?** listing the steps. Near the top
   is one line of the form **local · *name of the local model*** (for example
   `local · Qwen3.5-4B-Q4_K_M`). **It must not read `local · model`.** That was an old defect
   this ticket fixed: every turn was recorded against the placeholder name `model`. Write the
   name down; Part D compares against it. Click **Close**.

## Part B — turn online on for this conversation

The page you are on is one conversation. Every question you ask on it, without reloading, lands
in the same conversation. **Do not reload the page until Part D says to.** A reload starts a new
conversation.

7. **Stand-in** — the app does not show a conversation's id. Find it: ☐

   ```
   scripts/dev.sh psql -c "SELECT id, ai_backend FROM conversations ORDER BY created_at DESC LIMIT 1;"
   ```

   **You should see:** one row with `ai_backend` = `local`. Copy the id and set it in your
   terminal: `C=<the id>`.

8. **Stand-in** for the switch `M8-ONLINE-FE-171` will add. Take a session the way the interface
   does, then turn online on: ☐

   ```
   curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null
   curl -s -b /tmp/askwell.cookies -X POST http://127.0.0.1:8000/conversations/$C/online | jq
   ```

   **You should see:** `"ai_backend": "online"` and `"destination": "fakeprovider:8443"`.
   If you see `"available": false` or a `409` about no provider, the two settings in step 3 of
   *Before you start* did not reach the `api` container. Both are needed: a destination with no
   model is not a provider.

   The Ask screen shows **no** marker that the conversation is now online. That is expected
   today (Known gaps).

## Part C — an online answer is the same answer

9. Back in the browser, on the **same page**, ask the same question again:
   `What is the notice period for resigning at Meridian Loom?` ☐

   **You should see:**
   - the same named steps as in step 5, including the search of your files;
   - an answer that starts **ONLINE-ANSWER: The standard notice period for resignation at
     Meridian Loom is sixty-three days**, with a citation marker. It arrives in two pieces, a
     moment apart;
   - a source card in the margin naming `handbook_a.pdf`, **page 2**, looking exactly like the
     card in step 5. (The test server always cites passage `[1]`, the one Askwell ranked first.
     If the card names a different page of `handbook_a.pdf`, write it down. That is the ranking,
     not this ticket);
   - clicking the card opens `handbook_a.pdf` at the sentence about sixty-three days, as it would
     for a local answer;
   - exactly **one** new line in the server's log. It shows `"mode": "answer"`,
     `"model": "test-destination-model"`, `"roles": ["system", "user"]`,
     `"has_retrieved": true` and **`"auth": false`**. The last means Askwell sent no API key,
     because it holds none yet.

10. Click **How did you get this?** under the online answer. ☐

    **You should see:** the backend line reads **online · test-destination-model**. The steps
    include the search of your files and **Wrote the answer — 1 claim, 1 cited**. Click
    **Copy trace**, paste it anywhere, and find the line
    `Backend: online · test-destination-model`. Click **Close**.

11. **Stand-in** — the stored records, which no screen shows in full: ☐

    ```
    scripts/dev.sh psql -c "SELECT trace->'backend' AS backend, model_identity FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;"
    scripts/dev.sh psql -c "SELECT payload->>'backend' AS backend, payload->>'model' AS model, payload->>'online_fallback' AS fallback FROM audit_interactions WHERE kind='ask_asked' ORDER BY occurred_at DESC LIMIT 1;"
    ```

    **You should see:** `backend` is
    `{"mode": "online", "model": "test-destination-model", "destination": "fakeprovider:8443"}`
    and `model_identity` is `{"source": "online", "display_name": "test-destination-model"}`.
    The audit row reads `online`, `test-destination-model`, and an empty fallback.

## Part D — the rules are not relaxed for the online path

12. On the same page, ask `What colour is the moon on Tuesdays?` ☐

    **You should see:** the ordinary abstention, beginning "Nothing in your files answers this."
    The margin reads **No sources — nothing in your files matched.** The server's log has **no**
    new line: nothing was sent, because Askwell decided to abstain before generation. In
    **How did you get this?** the backend line reads **local ·** and the model name from step 6.
    That is correct: no model wrote this answer, and the provider was never asked.

    Under the abstention, the options include **Ask a larger model**, greyed out, reading
    *your own API key · not set up yet*. Click it. **You should see:** nothing happens, and still
    no new server log line. It is disabled until `M8-ONLINE-FE-171`, and it must not have been
    wired to this ticket's backend.

13. In the third terminal, run `echo uncited > /tmp/fakeprov/mode`. In the browser, on the same
    page, ask `What is the notice period for resigning at Meridian Loom?` ☐

    **You should see:** an answer starting `ONLINE-ANSWER:` that ends **without** a citation
    marker. The margin reads **Nothing in this answer was cited.** In **How did you get this?**,
    the compose step reads **Wrote the answer — 1 claim, 0 cited**. This is exactly how a local
    answer with no citation is shown. The online path gets no special treatment in either
    direction. One new server log line, `"mode": "uncited"`.

## Part E — every provider failure answers locally, and says so

The live list of steps is only visible while the answer is being written, so watch the screen
as each answer arrives.

14. Run `echo 429 > /tmp/fakeprov/mode`. On the same page, ask the notice-period question again. ☐

    **You should see:** while it works, a step reading **The online provider is limiting requests
    right now (429). Answering with the local model instead.** The answer is the local model's:
    it does **not** start with `ONLINE-ANSWER:`, it has the `handbook_a.pdf` source card, and it
    ends with a line reading **Answered by the local model. The online provider is limiting
    requests right now (429).** No error, and the question box is usable straight away. One new
    server log line, `"mode": "429"`. In **How did you get this?** the backend line reads
    **local ·** and the step-6 model name, and one step reads `online_fallback`. Expand it to see
    `rate_limited`.

15. Run `echo 401 > /tmp/fakeprov/mode`. Ask the question again. ☐

    **You should see:** the same as step 14, but the step and the closing line read **The online
    provider refused the request (401).** The expanded `online_fallback` step shows `refused`.

16. Run `echo cut > /tmp/fakeprov/mode`. Ask the question again. ☐

    **You should see:** the first half of the online answer appear ("ONLINE-ANSWER: The standard
    notice period for resignation"), then a step reading **The online provider stopped answering
    partway through. Answering with the local model instead.**, then the local model's full
    answer, closing with **Answered by the local model. The online provider stopped answering
    partway through.**

    **Known, not a defect of this ticket:** the half online answer stays on screen above the
    local one. The server withdraws it (an `answer_reset` event), but the Ask screen does not act
    on that event yet (#733). What was stored is correct; check it:

    ```
    scripts/dev.sh psql -c "SELECT left(content, 60) AS starts, trace->'backend'->>'mode' AS mode FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;"
    ```

    **You should see:** the stored answer does **not** start with `ONLINE-ANSWER:`, and the mode
    is `local`.

17. Run `echo answer > /tmp/fakeprov/mode`, then take the provider off the network entirely:
    `podman stop askwell-fakeprovider`. Ask the question again. ☐

    **You should see:** a step reading **Online AI could not reach fakeprovider:8443: the network
    is unavailable. Answering with the local model instead.** A local answer with its
    `handbook_a.pdf` card, closing with **Answered by the local model. Online AI could not reach
    fakeprovider:8443: the network is unavailable.** This is one of the few places Askwell
    correctly says the network is unavailable, because you asked for something that needs it.

    Stopping the container stands in for unplugging the cable. The egress proxy tries the
    destination and cannot reach it, which is what happens offline. Pulling the real cable
    would prove nothing more here, because the test provider never leaves the machine.

18. **Stand-in** — the record of the fallback: ☐

    ```
    scripts/dev.sh psql -c "SELECT trace->'backend' AS backend FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;"
    scripts/dev.sh psql -c "SELECT payload->>'backend' AS backend, payload->>'online_fallback' AS fallback FROM audit_interactions WHERE kind='ask_asked' ORDER BY occurred_at DESC LIMIT 1;"
    ```

    **You should see:** `backend` has `"mode": "local"`, the step-6 model name,
    `"requested": "online"`, and a `fallback` whose `reason_code` is `network_unavailable`. The
    audit row reads `local` and `network_unavailable`.

## Part F — Settings: what went out, and no key field

19. Click **Settings** in the rail. Scroll to **Privacy and security** → **Network activity**. ☐

    **You should see:** a line **Permitted, by the conversation that made them:** with a row
    **Conversation *first 8 characters of `$C`* → fakeprovider:8443: 5**. Five is the online
    requests from steps 9, 13, 14, 15 and 16. Steps 12 and 17 add nothing: the first sent
    nothing, and a destination that could not be reached is not a permitted request. If the
    number is off by one or two, see #731 before reporting it.

20. Scroll to the **Online AI** section. Click the **Use online AI** switch. ☐

    **You should see:** it stays off, and a message says online AI is not available yet. This
    ticket must not have wired the switch to anything; if it turns on, that is a defect. The
    **Your key, your bill** paragraph *describes* a future key in words. Check that there is
    **no text box** anywhere in the section.

21. Look for anywhere the interface asks for a third-party API key. Walk every Settings section
    top to bottom, then click **Library** → **Add a source** and look at each way of adding a
    source. ☐

    **You should see:** no field asking for an API key, token or provider account. The only
    password-style fields are your Askwell passphrase and a database connection's own password.
    As a cross-check in the terminal:

    ```
    grep -rniE 'api[ _-]?key|bearer' web/components web/app web/lib | grep -v '^\S*:\s*\(\*\|//\)'
    ```

    **You should see:** exactly two lines, both words rather than fields: the disabled
    **Ask a larger model** option in `web/components/ask/ask-screen.tsx` ("your own API key · not
    set up yet") and the Settings paragraph in `web/lib/online-ai.ts`. A third line, or any
    line in an `<input>`, is a defect.

## Part G — a local conversation is untouched

22. Start the provider again (the `podman run` command from *Before you start*, step 4). Then
    **reload the browser page**. That starts a new conversation, which is local. Ask the
    notice-period question. ☐

    **You should see:** a local answer with the `handbook_a.pdf` card, **no** closing "Answered
    by the local model" line, and **no** new line in the server's log. In **How did you get
    this?** the backend line reads **local ·** and the step-6 model name, with no
    `online_fallback` step. A conversation nobody switched is never sent anywhere, even with a
    provider configured and reachable.

## Teardown

```
podman stop askwell-fakeprovider
rm -f .run/fakeprovider.pem
podman compose up -d --force-recreate api
podman compose exec api env | grep ONLINE_AI
podman compose exec api askwell-verify
```

**You should see:** `ASKWELL_ONLINE_AI_DESTINATION=` and `ASKWELL_ONLINE_AI_MODEL=` both empty
(unless your `.env` sets them), and both audit chains reported intact.

---

## Known gaps

These are deliberately not built yet. Do not report them as defects of this ticket.

- **No online switch in the interface.** Turning online on is a terminal stand-in, and the Ask
  screen shows no marker that a conversation is online, and nothing about what will be sent.
  That is `M8-ONLINE-FE-171`. The **Online AI** section in Settings stays inert until
  `M8-KEY-FE-174`.
- **No key.** Askwell sends no `Authorization` header, so a real provider would refuse every
  request and each turn would answer locally, saying the provider refused. That is the honest
  state of an install with no key. The ticket's line "Askwell never holds a key" was superseded
  when the credit service was dropped (#255, `docs/decisions.md` 2026-09-23): the user will bring
  their own key, stored by `M8-KEY-BE-173` and entered through `M8-KEY-FE-174`. This ticket adds
  no key field. Part F checks that is still true.
- **No credits, balance or limits.** Dropped with the credit service (#255), not merely blocked.
- **Only the document answer goes online.** Database questions, the tool loop, SQL generation
  and the answer after a web search still run on the local model in an online conversation
  (#734).
- **A half-finished online answer stays on screen** above the local one until the page is
  reloaded. The stored answer is correct (#733).
- **The per-conversation count** in Network activity counts connections, not requests. With one
  request per connection they match today, but the wording overstates it (#731).
- **If Askwell's own egress proxy is down**, an online conversation says "the network is
  unavailable", which is not quite true: the machine's network may be fine (#735).
- **The "not authorised" failure** (the authorisation lapsing between the start of a turn and
  the provider call) is not walked here. It is hard to trigger by hand, and the authorisation
  itself is walked in `M8-ONLINE-SEC-169.md`. It is covered by `api/tests/test_inference_provider.py`.
- **Redis has no authentication**, so another container on the internal network could write a
  grant (#730). It must be fixed before `M8-KEY-BE-173` makes online AI usable against a real
  provider.
