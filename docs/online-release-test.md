# Online-mode release test — only the authorised destination

`M8-ONLINE-TEST-176`. Run this once per release, after `docs/offline-release-test.md` and before
`docs/release-procedure.md` step 4 (checksums). **A failed run blocks the release**, and so does
a run that could not be completed. It is gate G13 in `docs/release-checklist.md`.

**What it proves.** Online AI is the first thing in Askwell that sends anything anywhere. C1
(`AGENTS.md` §3) allows it only for the one conversation the user switched online, and only to
the provider their key belongs to. The proxy's grant design (`M8-ONLINE-SEC-169`,
`docs/decisions.md` 2026-09-24) says that is so. This gate is where it is watched from outside:

- with online AI on for one conversation, the only traffic leaving the machine is to the
  authorised destination;
- a second conversation in the same session, left local, sends nothing;
- switching online AI off stops it at once;
- the sandbox sends nothing, whatever else is on;
- a dependency asking for the authorised destination is refused, because the authorisation is
  for one conversation's requests, not for the internet.

**It adds to the cable-unplugged gate (G4). It does not replace it.** G4 proves the product
works with no network. This gate proves that with the network *up*, the one exception stays
one exception. Both run for every release.

Two independent checks run throughout, as in G4: the proxy's own counters (`GET /network`),
which the system under test reports about itself, and a **packet capture**, which does not
depend on Askwell being honest about itself. A counter on its own is not sufficient evidence.

---

## 0. Before you start

**Needs:** `M8-ONLINE-SEC-169` (the conversation grant), `M8-ONLINE-BE-170` (the provider
client), `M8-KEY-BE-173`/`M8-KEY-FE-174` (the stored key), and a decided disclosure (#737).
**While #737 is open, every online send is refused**, and this gate's positive half (§4.3)
cannot run. Record the gate as `BLOCKED`, not `PASS`. Everything else here still runs and
still has to pass.

**A provider key of the maintainer's own**, for an OpenAI-compatible provider, with a small
spending limit set at the provider. It is used for two or three questions. Write down its
destination (`host:port`) exactly as Settings shows it. That string is *the authorised
destination* for the rest of this document.

**The same machine state as G4**: a model placed, the fixture corpus
(`eval/fixtures/corpus/`) added and indexed, and a SQL dump source imported (§4.6 needs one).

**Update checks off** (Settings → About). The update check is the one other destination
Askwell can reach (`M7-UPDATE-BE-161`). With it off, anything in the capture that is not the
authorised destination is a failure, with no need to argue about which one it was. If a
release needs it on for the walkthrough, turn it off for this gate and back on after.

**Web search not used.** A web search is a separate, per-question egress path (C10) and its
own gate (`web_escalation.v1`). Do not accept a web search offer during this run.

---

## 1. Resolve the authorised destination

On the host, before starting the capture:

```
getent ahosts <host>
```

Write down every address it returns. The capture filter below allows exactly those, and DNS.
Providers sit behind CDNs, so the answer can change between runs and between this step and the
question. That is why §6 matches the destination by name in the TLS handshake as well as by
address.

---

## 2. Start the capture

Start it **before** the stack comes up, and leave it running to the end. In order of
preference, as in `docs/offline-release-test.md` §0:

1. `tcpdump` on a second machine that sees this machine's traffic (a span port, or a hub).
   It cannot be fooled by anything on the machine under test.
2. On the machine under test, on the interface that reaches the internet:

   ```
   sudo tcpdump -i <interface> -n -w online-<version>.pcap
   ```

   Capture everything. Do not filter at capture time. A filter written here decides in advance
   what counts as evidence, and §6 is where that is judged.

Save the capture. It is part of the record.

---

## 3. What the script does, and what it cannot

`scripts/verify-online-egress.sh` runs §4.1 to §4.7 against the running stack over HTTP, reads
`GET /network` before and after, and exits `0` (pass), `1` (fail) or `2` (blocked: nothing
failed, but the online send could not run). It is necessary and not sufficient.

It **cannot**:

- **present a conversation's credential itself.** The credential lives only in the API
  process's memory. That is what keeps any other caller out, so a script that could present
  it would be proving the wrong thing. The two edge cases that need it are pinned by tests
  that run in every `scripts/dev.sh check`, and are re-checked in the capture (§6):
  - *a name that resolves to the authorised address but is a different service*:
    `api/tests/test_egress.py::test_another_name_for_the_authorised_address_is_not_the_authorised_destination`.
    The grant names a host, compared as written. The address it resolves to, the same name in
    another case, and the fully qualified form are each refused, even with the owning
    conversation's credential.
  - *a retry storm against an unreachable destination*: the bound is **one connection attempt
    per question**. The answer's generation makes one provider request, over one tunnel, and
    on any failure answers locally instead of retrying
    (`test_ask_online.py::test_a_failure_before_the_answer_falls_back_to_local_and_says_so`
    asserts exactly one request). Each tunnel is one `CONNECT`
    (`test_inference_provider.py::test_through_the_proxy_with_the_conversations_credential_one_tunnel_per_call`),
    and the proxy makes one upstream attempt per `CONNECT`, answering `502` and counting
    nothing as permitted
    (`test_egress.py::test_an_unreachable_destination_costs_one_connection_attempt_per_connect`).
    One upstream attempt can still be a TCP connect to each address the name resolves to,
    inside the proxy's 10-second connect limit.
- **read the capture.** That is §6, and it is a person's judgement.

---

## 4. The walkthrough

Keep a note of the time at the start of each step. §6 reads the capture against these times.

### 4.1 Store the key

Settings → Online AI → add the key, the provider address and the model. **Expect:** the section
shows the provider and never the key. Nothing leaves: storing a key sends nothing.

### 4.2 Run the script

```
scripts/verify-online-egress.sh
```

It creates two conversations, switches one online (confirming the disclosure for it, once #737
has recorded one), and checks that the proxy holds exactly that one authorisation. The rest of §4 is what it then does. Read every line it prints.

### 4.3 The online conversation asks (the script's step 4)

One question in the online conversation. **Expect:** one permitted connection in `GET /network`,
attributed to that conversation and the authorised destination. In the capture: one DNS lookup
for the authorised name (the proxy resolves it; no other container can resolve an outside name)
and one TLS session to one of its addresses, whose SNI is the authorised name.

While #737 is open this step prints `BLOCKED` and the script exits `2`. The gate is then
`BLOCKED`.

### 4.4 A dependency asks for the same destination (step 2)

From inside the `api` and the `worker` containers, a `CONNECT` to the authorised destination
with no credential, which is what a dependency honouring `HTTPS_PROXY` sends. **Expect:** `403`
from the proxy for both, each counted as a refusal. From `api`, a direct connection to the name
and to its address, ignoring the proxy. **Expect:** the name does not resolve and the address is
unreachable. In the capture: nothing at those times.

### 4.5 The local conversation asks, in the same session (step 5)

**Expect:** the answer arrives, and neither the global permitted count nor any per-conversation
count moves. In the capture: nothing.

### 4.6 The sandbox (step 3)

While the online conversation's authorisation stands, from inside the `sandbox` container: no
route to the egress proxy, to the authorised name, or to its address, and the name does not
resolve. **Expect:** all four fail. Then, by hand, ask a question that routes to the dump source
(`docs/offline-release-test.md` §3.7) in the **online** conversation, before §4.7 switches it off.
The query runs in the sandbox, and a database-routed turn stays local even in an online
conversation: only the answer to a document question goes online (`M8-ONLINE-BE-170`).
**Expect:** the turn is labelled *Answered locally*, and the capture shows nothing at that time.
The sandbox is on a network with no route out (`compose.yaml`;
`api/tests/test_dump_containment.py`).

### 4.7 Switch it off (step 6)

**Expect:** the conversation reads local as soon as the request returns, `GET /network` lists no
authorisation, and the next question in that conversation is answered with nothing permitted. By
hand, repeat it with a long answer in flight: start a question in the online conversation, and
switch online AI off in the interface while the answer is still streaming. **Expect:** the
answer is withdrawn and finished locally, and the capture shows the TLS session to the provider
ending within about one second of the click (`CONVERSATION_RECHECK_SECONDS`). This is the
"stops immediately" criterion. One second is the stated bound, and a request already sent in
that second has left.

### 4.8 A while with nothing on

Leave Askwell running for ten minutes after §4.7 with no online conversation. **Expect:** nothing
in the capture for those ten minutes.

---

## 5. Investigate every refusal

As `docs/offline-release-test.md` §4. The script accounts for its own two probes. Every other
refusal counted during the run is named: which service, which destination, why. A refusal is
never noise. The ticket's own example is this one: a dependency's request slipping through
while online was enabled. Here it would show as a refusal (the proxy held), or worse, as
traffic in the capture that no counter explains.

---

## 6. Read the capture

Using the times noted in §4, confirm all of these:

- **Only the authorised destination.** Every packet leaving the machine, other than DNS, goes to
  an address from §1 on the authorised port. Every TLS ClientHello's SNI is the authorised name.
  In Wireshark, `tls.handshake.extensions_server_name` lists exactly one value. A TLS session
  to an allowed address with any other SNI is a **different service on the same address**, and
  fails the run.
- **Only DNS for that name.** Every DNS query is for the authorised name. A query for anything
  else shows that something tried to reach it, even with no reply.
- **Only while authorised.** Traffic to the provider appears only inside §4.3's question and
  §4.7's in-flight answer. Nothing after §4.7's click plus one second. Nothing in
  §4.5, §4.8, or while the script's probes ran.
- **Bounded.** The number of TLS sessions to the provider is at most the number of questions
  asked in the online conversation while it was online.

A capture on the machine under test also holds the machine's own traffic (browser, OS, VPN), and
this section does not yet say how to separate it from Askwell's (#745). Until it does, take a
five-minute baseline capture with Askwell stopped, as `docs/manual-tests/M8-ONLINE-TEST-176.md`
does, and explain every destination the run has that the baseline does not.

Anything the counters do not explain fails the run, even if every counter reads right. The gate
is two checks because either one can be wrong.

---

## 7. Record the result

Append one entry to `docs/online-test-log.md`, newest first, in its format, and remove the key
from Settings if it should not stay on the release machine.

**Any of these fails the run:**

- the script exits `1`;
- a refusal in §5 is unexplained and has no fix or issue;
- the capture shows traffic to any address, name or SNI other than the authorised destination,
  or DNS for any other name;
- the capture shows provider traffic outside the authorised windows, or more than one second
  after switching off;
- more TLS sessions to the provider than online questions asked.

**The script exiting `2`, or a capture that was not taken, is `BLOCKED`.** Neither is a pass,
and like a `FAIL` it blocks the release. This gate cannot be `ACCEPTED`
(`docs/release-checklist.md`), because it protects C1.
