# Manual test — M8-ONLINE-TEST-176, the online-mode release test

**Ticket:** `M8-ONLINE-TEST-176`. The release gate G13 in `docs/release-checklist.md`: with online
AI switched on for one conversation, only the authorised destination may be reached, and only by
that conversation. It is proven two independent ways. One is the egress proxy's own counters
(**Settings → Privacy and security → Network activity**), and `scripts/verify-online-egress.sh`
reads them. The other is a packet capture taken by the operating system, which does not depend on
Askwell reporting honestly about itself. The procedure is `docs/online-release-test.md`, and the
record is `docs/online-test-log.md`.

This document walks that procedure as a person would: from a cold start, by clicking, with a
capture running the whole time. It is the check that the gate can actually be run on the
product as it is built today.

**Version under test:** `0.7.45`. This ticket changes no version, because it adds docs, tests and
a release script. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 75 minutes. Most of it is waiting: indexing, three local answers on CPU (two of
them asked by the script), and the ten quiet minutes in Part G.

**Who can run it:** anyone with a browser, a terminal and `sudo` on the machine. Every Askwell
screen is reached by clicking, starting from Askwell's front page. The terminal starts Askwell,
runs the capture, runs the release script and reads the capture. Those steps are labelled
**Stand-in**, because none of them is something a user of Askwell does.

**What is being checked.**

- `docs/online-release-test.md`: that every step can be followed on today's screens.
- `scripts/verify-online-egress.sh`: its checks and exit codes, against a running stack.
- The screens it relies on: **Settings → Online AI → Your key**
  (`web/components/settings/online-key.tsx`), the **Local** / **Online AI: on** switch and the
  disclosure box beside **Ask** (`web/components/ask/online-conversation.tsx`), and **Network
  activity** (`web/components/settings/network-activity.tsx`).
- On the server: the proxy's conversation grant (`api/src/askwell/egress.py`) and `GET /network`.
- The edge cases the procedure hands to tests (Part I).

---

## Read this first

**The expected result today is `BLOCKED`, not `PASS`.** Every online question is refused until the
owner decides what online AI may send (#737, which is waiting on #730). So nothing can go to a
provider, and the half of the gate that watches a real send cannot run. Everything else here can
run and must pass: the switch opens exactly one authorisation, a dependency is refused, the
sandbox is sealed, the local conversation sends nothing, and switching off closes it. The script
reports this by exiting `2`. **Do not report `BLOCKED` as a defect. Do not record it as a pass.**

**No real key is needed, and none should be used.** The provider below is real:
`api.openai.com:443`. That way the capture has a real name and real addresses to look for. The key
is a made-up value, the **placeholder**:

```
sk-release-test-placeholder-176
```

It is never sent anywhere, because every online question is refused before anything leaves. If
the capture shows any TLS connection to `api.openai.com`, that is a defect, whatever the key.

**The capture sees the whole machine, not only Askwell.** Your browser, the operating system and
anything like Tailscale make their own traffic, and the procedure does not yet say how to tell
theirs from Askwell's (#745). Until it does, this test takes a five-minute **baseline** capture
with Askwell stopped. After that, a destination that also appears in the baseline counts as the
machine's own. It is a stand-in, and Part H says exactly how to use it.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key. Your
> original files are not touched. On the shared development machine, check that nobody needs what
> the stack holds now. If you are unsure, open **Settings → Your data → Export everything** first.

### 1. One document and one dump

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -n "ONLINE_AI_DESTINATION\|ONLINE_AI_MODEL" .env
```

If the first line is empty or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. If the
second `grep` prints anything, delete those lines. Nothing reads them since `M8-KEY-BE-173`, and
the destination now comes from the key you store in Part B.

```
rm -rf /tmp/askwell-test-176
mkdir -p /tmp/askwell-test-176/files /tmp/askwell-test-176/dumps /tmp/askwell-test-176/capture
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-176/files/
cat > /tmp/askwell-test-176/dumps/orders.sql <<'EOF'
--
-- PostgreSQL database dump
--
CREATE TABLE orders (id integer primary key, total numeric);
INSERT INTO orders VALUES (1, 100), (2, 250);
EOF
ls -R /tmp/askwell-test-176
```

**You should see:** `handbook_a.pdf` under `files` and `orders.sql` under `dumps`. Page 2 of the
handbook reads "The standard notice period for resignation at Meridian Loom is sixty-three days."

### 2. Build first, while the capture is not yet running (Stand-in)

The builds fetch packages from the internet. That is the build machine, not Askwell, so do it
before the capture starts:

```
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman images --format '{{.Repository}}:{{.Tag}}' | grep -E 'redis|postgres|askwell'
```

**You should see:** the volumes removed, both builds finish with no red error text, and the image
list includes `redis`, `postgres` and `localhost/askwell-api:dev`. If `redis` or `postgres` is
missing, run `podman compose pull` now, so the pull does not land in the capture.

### 3. Which interface reaches the internet, and where the authorised name points (Stand-in)

```
ip route get 1.1.1.1
getent ahosts api.openai.com | awk '{print $1}' | sort -u | tee /tmp/askwell-test-176/capture/authorised-addresses.txt
```

**You should see:** a line with `dev <name>`. Write the name down. It is `wlp41s0` on the build
host. If it says `tailscale0`, an exit node is routing your traffic. Turn the exit node off and run
it again, because a capture on the tunnel cannot see names. The second command prints one or more
addresses, and they are now saved in `authorised-addresses.txt`. This is procedure §1.

### 4. The baseline: five minutes with Askwell stopped (Stand-in)

Close every browser window. Then open one **private** browser window on a blank page and leave it
open. It will be the window you test with, and its own background traffic belongs in the baseline.

```
sudo timeout 300 tcpdump -i <interface> -n -w /tmp/askwell-test-176/capture/baseline.pcap
```

**You should see:** `listening on <interface>`, and after five minutes a line such as
`1234 packets captured`. Do nothing else on the machine for those five minutes.

### 5. Start the capture for the run, then start Askwell (Stand-in)

In a terminal you will leave open until Part H:

```
sudo tcpdump -i <interface> -n -w /tmp/askwell-test-176/capture/online-0.7.45.pcap
```

**You should see:** `listening on <interface>`. Capture everything. Do not add a filter: §6 of
the procedure decides what counts as evidence, not the capture command.

In a second terminal:

```
cd ~/external/quantum-plus/askwell
podman compose up -d
scripts/dev.sh db upgrade head
date +%T
```

In a third terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the containers start, the migration finish without an error, and the
supervisor report the model and the embedding model ready.

**Keep a time log.** At the start of every Part below, run `date +%T` in the second terminal and
write the time down beside the Part's letter. Part H reads the capture against these times.

---

## Part A — cold start, and a local session

1. In the private window, open `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button. If
   you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you start*,
   step 2.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step headed **Add a source**, with a **Files** box (**Choose files**,
   **Choose a folder**) and, below it, a **Database dump** box. The dump box says *This file
   contains commands, not just data.* and that Askwell runs it in a sealed database that cannot
   reach the internet.

3. In the **Files** box click **Choose files**, open `/tmp/askwell-test-176/files`, select
   `handbook_a.pdf` and confirm. When asked **"Which folder are these files in?"**, type
   `/tmp/askwell-test-176/files` and click **Add them**. If a note offers to nominate the folder,
   or a parent of it, click that and then **Add them** again. ☐

   **You should see:** the file accepted, with no red "Not added" note.

4. **While you are still on this step**, in the **Database dump** box click **Choose a dump
   file**, open `/tmp/askwell-test-176/dumps` and select `orders.sql`. When asked
   **"Which folder is "orders.sql" in?"**, type `/tmp/askwell-test-176/dumps` and click
   **Import**. Nominate the folder if offered, as in step 3. ☐

   **You should see:** the button read **Importing…**, then a note headed **Queued** or
   **Imported**. The latter says the dump *loaded into its own sealed database*.

   Add the dump here, during first run. Once anything has been added, no click reaches **Add a
   source** again (#712).

5. Finish the welcome steps. Skipping an optional step is fine. Click **Library** in the rail on
   the left. Wait until both sources say **ready**. ☐

   **You should see:** `handbook_a.pdf` and `orders.sql`, both ready. If the dump says it did not
   finish, stop and report it with its message. Part D needs it.

6. Click **Ask** in the rail. Type `What is the notice period for resigning at Meridian Loom?`
   and press **Enter**. Wait for the answer. On CPU this can take a minute or two. ☐

   **You should see:**
   - the small line at the top reads `Askwell 0.7.45 · nothing leaves this machine`;
   - to the left of **Ask**, a button reading **Local**;
   - an answer saying sixty-three days, with a source card naming `handbook_a.pdf`, page 2.

7. Click **Settings** in the rail. Scroll to **Privacy and security**, then **Network
   activity**. ☐

   **You should see:** *0 outbound requests permitted · 0 refused, measured by the egress proxy
   itself.* There is no list under it. If either number is not `0`, note the destinations it
   lists and keep going. Part H explains each one.

8. In the same Settings page, scroll to **About**. ☐

   **You should see:** **Check for updates once a week**, **not** ticked. Leave it unticked, and
   do not click **Check now**. The update check is the one other place Askwell can reach. With it
   off, anything in the capture that is not the authorised destination is a failure.

## Part B — store the key

9. Scroll up to **Online AI**, then to **Your key**. ☐

   **You should see:** *"No key is set. Online AI cannot be switched on in any conversation."* and
   a button **Add a key**.

10. Click **Add a key**. Fill in **Provider address** `api.openai.com:443`, **Model**
    `release-test-model` and **Key** `sk-release-test-placeholder-176`. Click **Save the key**. If you are
    asked for your passphrase, enter the one from step 2. ☐

    **You should see:** the form close, and *"A key is set for api.openai.com:443, asking for
    release-test-model."* The placeholder is not shown anywhere on the page. Askwell does not check a key
    when you save it, so storing one sends nothing.

11. Click **Ask** in the rail, then click **Settings** again, and read **Network activity**. ☐

    **You should see:** the same two numbers as step 7. Saving a key opened nothing.

## Part C — two conversations in one session: one online, one local

Each browser tab on the **Ask** screen is its own conversation. Both tabs share the same session.

12. Click **Ask** in the rail. This tab is **Tab 1**. Right-click **Ask** in the rail, choose
    **Open link in new tab**, and switch to that new tab. It is **Tab 2**. ☐

    **You should see:** in Tab 2, an empty **Ask** screen with **Local** beside **Ask**, and the
    top line ending `nothing leaves this machine`.

13. Go back to **Tab 1** and click **Local**. ☐

    **You should see:**
    - the button now reads **Online AI: on**, in heavier type with a dark border;
    - the top line reads `Askwell 0.7.45 · online AI is on for this conversation`;
    - above the question box, a marker in bold: *Online AI is on for this conversation until
      HH:MM. Questions go to api.openai.com:443.* HH:MM is some hours from now;
    - below it, a box headed **Before anything is sent: what will leave this machine**, reading
      *Askwell has not yet defined exactly what online AI would send, so it will not send
      anything. …* It has one button, **Switch back to local**, and no confirm button;
    - beside the switch: *Not sent. Online AI is on for this conversation, and what it sends has
      not been confirmed.*

14. In **Tab 1**, type `What is the notice period for resigning at Meridian Loom?` and click
    **Ask**. ☐

    **You should see:** nothing is sent. **Ask** stays greyed out, and no answer and no progress
    line appear. This refusal is #737, and it is why the gate is `BLOCKED` today. If an answer
    does appear in Tab 1 labelled **Answered online**, stop. #737's safeguard has failed, which is
    a C1 defect. Report it with the time.

15. Switch to **Tab 2**. It is still **Local**. Type the same question and press **Enter**. Wait
    for the answer. ☐

    **You should see:** sixty-three days, citing `handbook_a.pdf`, page 2. The top line still ends
    `nothing leaves this machine`. There is no marker, and no "Answered locally" label: this
    conversation has never been online. Switching Tab 1 online did not touch Tab 2.

## Part D — the sandbox, while a conversation is online

Tab 1 is still online. Its authorisation stands while this Part runs.

16. In **Tab 2**, type `What is the total of order 2?` and press **Enter**. Wait for the answer. ☐

    **You should see:** an answer of 250, with the SQL that produced it shown beside the answer.
    That query ran inside the sealed sandbox holding `orders.sql`. If Askwell says instead that it
    cannot answer from your material, note that as a separate finding. This Part is about the
    network, and Part H still checks that nothing left.

17. Click **Settings** in the rail and read **Network activity**. ☐

    **You should see:** still the same two numbers as step 7, and no **Permitted, by the
    conversation that made them** list. Tab 1 is authorised, but nothing has gone through that
    authorisation.

## Part E — switch it off

18. Switch to **Tab 1**. In the disclosure box, click **Switch back to local**. ☐

    **You should see:**
    - the box and the "Not sent" line disappear;
    - the button beside **Ask** reads **Local** again;
    - the top line reads `… · nothing leaves this machine` again;
    - the marker stays, now in plain grey: *Online AI was on in this conversation earlier. It is
      local now: nothing you ask here leaves this machine.*

19. In **Tab 1**, click **Ask**. Your question from step 14 is still in the box. Wait for the
    answer. ☐

    **You should see:** sixty-three days, citing `handbook_a.pdf`, page 2, and labelled **Answered
    locally**.

## Part F — the release script (Stand-in)

The script needs no conversation to be online when it starts, and after Part E none is. It makes
its own two conversations, switches one online, probes the proxy and the sandbox, asks questions,
and switches off again.

20. In the second terminal:

    ```
    date +%T
    scripts/verify-online-egress.sh; echo "exit $?"
    date +%T
    ```

    It asks two questions of the local model, so it can take several minutes. ☐

    **You should see**, in this order:
    - `pass  session established` and `pass  key held for api.openai.com:443`;
    - a baseline line, `permitted=0 refused=<n>`, where `<n>` is the refused number from step 17;
    - `pass  the proxy holds exactly one authorisation: that conversation, that destination`;
    - `pass  api: refused (HTTP/1.1 403 Forbidden)` and the same for `worker`. These are the
      ticket's "dependency making an unexpected request while online is enabled", and both are
      refused;
    - two `pass  api → …:443: no route: …` lines, one for the name and one for an address;
    - four `pass  sandbox: …` lines: no route to the proxy, to the name or to the address, and
      the name does not resolve;
    - `BLOCKED  online sends are refused: … has not been decided yet … (#737)`;
    - `pass  nothing permitted for the local conversation`;
    - `pass  the authorisation is gone as soon as the request returns` and `pass  the next
      question in that conversation is answered with nothing permitted`;
    - `pass  permitted moved by exactly the online sends (0)` and `pass  refused moved by exactly
      this script's own probes (2)`;
    - finally `Nothing failed, but the online send could not run: BLOCKED, not a pass.` and
      `exit 2`.

    Any `FAIL` line, or `exit 1`, fails the run. Copy the whole output into your notes.

21. Click **Settings** in the rail (in either tab) and read **Network activity**. ☐

    **You should see:** *0 outbound requests permitted*, and the refused number 2 higher than in
    step 17. Under **Most recent refusals**, the two newest are `askwell-api-1 → api.openai.com:443` and
    `askwell-worker-1 → api.openai.com:443`, the script's own probes. Any other entry that was not there in
    step 7 must be explained in Part H.

## Part G — ten quiet minutes

22. Leave Askwell running, with both tabs open and neither online, for ten minutes. Do nothing on
    the machine. Note the start and end times. ☐

    **You should see:** nothing on screen. Part H checks the capture for this window.

## Part H — read the capture (Stand-in)

23. In the capture terminal, press **Ctrl+C**. Then:

    ```
    cd /tmp/askwell-test-176/capture
    sudo chown "$USER" *.pcap
    ls -l
    ```

    **You should see:** `baseline.pcap` and `online-0.7.45.pcap`, both larger than zero bytes, and
    a packet count printed when tcpdump stopped. ☐

24. **DNS for the authorised name.** ☐

    ```
    tcpdump -r online-0.7.45.pcap -n -tttt 'port 53' 2>/dev/null | grep -i 'api\.openai\.com'
    ```

    **You should see:** queries for `api.openai.com` **only** at times inside Part F, from the
    script's step *a dependency ignoring the proxy*. There, the script asks the egress proxy
    container to resolve the name so that it can try the address directly. That lookup is the
    script's own, not Askwell's. A query at any other time, and in particular during Parts A–E or
    G, is a defect: something tried to find the provider. If this prints nothing at all and no
    `port 53` traffic exists in the file, the machine resolves names over encrypted DNS. Write that
    down, because this check then cannot be made.

25. **Any connection to the authorised destination.** ☐

    ```
    for a in $(cat authorised-addresses.txt); do
      tcpdump -r online-0.7.45.pcap -n -tttt "host $a and tcp[tcpflags] & tcp-syn != 0" 2>/dev/null
    done
    tcpdump -r online-0.7.45.pcap -n -A 'tcp dst port 443' 2>/dev/null | grep -a -c 'api\.openai\.com'
    ```

    **You should see:** the loop prints nothing, and the count prints `0`. No connection was opened
    to any of the provider's addresses, and no TLS greeting named it. This is the gate's "only
    while authorised" and "bounded" check. Today nothing can be sent at all, so the bound is zero.
    A connection here is a defect, whatever else passed. If the provider's addresses changed
    between step 3 and now, the second command still catches it by name.

26. **Everything else that left the machine, against the baseline.** ☐

    ```
    new_flows() {
      tcpdump -r "$1" -n "(tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0) or (udp and not port 53 and not port 5353)" 2>/dev/null \
        | awk '{print $5}' | sed -E 's/\.[0-9]+:?$//' | sort -u
    }
    new_flows baseline.pcap > baseline-destinations.txt
    new_flows online-0.7.45.pcap > run-destinations.txt
    comm -13 baseline-destinations.txt run-destinations.txt
    ```

    **You should see:** nothing, or only destinations you can name as the machine's own (for
    example, the browser reaching its vendor while the private window was open). For each one,
    run `tcpdump -r online-0.7.45.pcap -n -tttt host <address> | head` to see when it happened,
    and write down what it was. A destination you cannot name, at a time inside your Parts, is a
    finding: report it with its address and time. The baseline is a stand-in (#745). It cannot
    tell a new destination of the machine's from a new one of Askwell's, so read this list
    suspiciously rather than generously.

27. **Every refusal is named.** Compare the **Most recent refusals** list from step 21 with step 7.
    ☐

    **You should see:** the only new refusals are the script's two probes. Procedure §5 applies to
    any other refusal: name the service, the destination and why. A refusal is never noise.

## Part I — the edge cases the capture cannot drive (Stand-in)

Two of the ticket's edge cases need a conversation's credential, which lives only in the API
process's memory. A script that could present it would prove the protection has a hole. They are
pinned by tests instead, and the procedure names those tests (§3):

28. ```
    scripts/dev.sh test tests/test_egress.py tests/test_inference_provider.py -p no:warnings -rA \
      -k "another_name_for_the_authorised or plain_http_request_to_the_authorised or unreachable_destination_costs or one_tunnel_per_call" \
      | grep -E "PASSED|FAILED|ERROR|passed|failed"
    scripts/dev.sh test-db tests/test_ask_online.py -p no:warnings -rA \
      -k "failure_before_the_answer_falls_back" | grep -E "PASSED|FAILED|ERROR|passed|failed"
    ```
    ☐

    **You should see:** `8 passed` from the first command, including four `PASSED` lines for
    *another name for the authorised address*: the address it resolves to, the same name in
    another case, the fully qualified name, and the address mapped to IPv6. A different service at
    the authorised address is refused even with the right credential. Then `3 passed` from the
    second. Each provider failure costs exactly one request and then answers locally. It never
    retries, so there is no retry storm to bound beyond one attempt per question.

## Part J — record it

29. For a **release run**, append an entry at the top of `docs/online-test-log.md` in its format.
    Result `blocked` while #737 is open. Include the script's exit code and every line that was
    not `pass`, the counters from steps 7 and 21, where the two capture files are, the results of
    steps 24 to 27, and "not measurable: nothing was sent" for the stop-on-switch-off time. When
    checking this ticket, compare with the existing `0.7.45` entry instead of adding a second one
    for the same version. ☐

30. In **Settings → Online AI → Your key**, remove the placeholder key. ☐

    **You should see:** *"No key is set. Online AI cannot be switched on in any conversation."*

**Any of these fails the run:** a `FAIL` line or `exit 1` from the script; an answer labelled
**Answered online** in step 14; a DNS query for the authorised name outside Part F; any
connection to, or TLS greeting naming, the authorised destination; an unexplained new destination
in step 26; an unexplained refusal in step 27; a `FAILED` test in Part I. **`exit 2` with nothing
else wrong is `BLOCKED`,** and a run with no capture is `BLOCKED` too. Neither is a pass, and both
hold the release (`docs/release-checklist.md`, G13).

---

## Known gaps

These are deliberate, or already tracked. Do not report them as defects.

- **The positive half cannot run (#737, after #730).** Until the owner decides what online AI may
  send, every online question is refused. So none of these can be walked today: one question
  reaching the provider and counted once against its conversation (procedure §4.3); the capture
  showing exactly one TLS session with the authorised name in it; the "answer in flight when
  switched off" check, where the provider traffic must end within about one second of the click
  (§4.7, `CONVERSATION_RECHECK_SECONDS`); and a dump question asked in the *online* conversation
  staying local (§4.6). Here that question is asked in the local tab. The gate is `BLOCKED`, and
  `docs/release-checklist.md` lists #737 against G13.
- **The capture cannot yet separate the machine's traffic from Askwell's (#745).** The baseline
  comparison in Part H is a stand-in until the procedure captures Askwell's egress on its own.
- **No click reaches Add a source after the first add (#712).** That is why the dump is added
  during first run in step 4.
- **The "different service at the same address" and "retry storm" edge cases are tests, not
  walkthrough steps.** This is by design: the credential that would drive them exists only inside
  the API process (`docs/decisions.md`, 2026-09-25, `M8-ONLINE-TEST-176`). Part I runs them.
- **Network activity does not list a standing authorisation on its own.** It shows **online now**
  only beside a conversation that has already been permitted a connection. With nothing sent,
  Tab 1's authorisation is visible to the script (`GET /network`'s `authorised` list) but not on
  the screen.
- **The billing payload is not tested.** It is out of scope for this ticket, and blocked on its
  own decision.
- **No second machine.** Procedure §2 prefers a capture from a second machine that sees this one's
  traffic. The build host has none (#590, #592, #598), so this walkthrough captures on the machine
  under test, which is the procedure's second option.
