# Offline release test — the cable-unplugged gate

`M7-OFFLINE-TEST-145`. Run this once per release, alongside `docs/restore-release-test.md`
(after `docs/release-procedure.md` step 1, before step 4). **A failed run blocks the
release** — `AGENTS.md` §3, C1: "disconnect the machine and it must work identically."

C1 is the reason the product can exist for its users at all (`docs/architecture.md` §5).
This gate is what turns that from an assertion into something checked before every release,
per `docs/success-metrics.md` and `AGENTS.md`'s own framing of this ticket: "the promise is
verified as part of every release, not asserted."

Two independent verifications run together throughout: the proxy's own counters (a fact the
system under test reports about itself) and an external network capture (evidence that does
not depend on the system under test being honest about itself — `AGENTS.md`'s own assumption
for this ticket: "a counter produced by the system under test is not sufficient evidence on
its own").

The automatable half of this lives in `scripts/verify-no-egress.sh` — see §2. The rest is a
manual walkthrough, §3 onward, and stays manual: a physical cable pull and a browser driving
voice input are not things this repository can script against itself.

---

## 0. Before you start

Depends on `M7-OFFLINE-DEPLOY-144` (manual model placement — needed so first run does not
itself require a network fetch), `M0-STACK-SEC-011` (the egress proxy, `api/src/askwell/egress.py`,
`docs/architecture.md` §5.1) and `M6-VUI-FE-135` (voice, so the walkthrough's voice step is
real rather than stubbed). Where M6.5 has landed before the release — it has, as of `0.7.0`
(`M6.5-WEB-OBS-193` closed the milestone) — also `M6.5-WEB-FE-192`, so §3.9 below applies.

**A clean machine, or the closest simulation available.** The real test is a fresh install on
hardware that has never run Askwell, per `docs/manual-tests/M7-PACK-DEPLOY-139/140/141.md`'s
own disclosed constraint: this build host has no second machine and no Windows/macOS hardware
(issues #590, #592, #598). Where a second machine is not available, simulate with a database
wipe the same way `docs/restore-release-test.md` §3 does, and name the substitution in the log
entry rather than let it pass silently.

**A model already placed manually**, per `M7-OFFLINE-DEPLOY-144` — the whole point of this
gate is that first run does not need a network fetch. Confirm `GET /setup` reports a model
ready before disconnecting.

**Independent network capture.** Run one of, in order of preference:

1. `tcpdump` on a second machine's interface, watching the traffic actually leaving this one
   (needs a hub/span port or the two machines on the same segment) — the strongest evidence,
   because it cannot be fooled by anything running on the machine under test.
2. `tcpdump -i any -n 'not (host 127.0.0.1 or host ::1)'` on the test machine itself, started
   *before* the stack comes up and left running for the whole walkthrough — weaker (a
   sufficiently broken kernel or capture tool could in principle miss traffic its own host
   generated) but still independent of Askwell's own code, which is the property that matters
   here (`AGENTS.md`'s assumption: "a counter produced by the system under test is not
   sufficient evidence on its own").

Either way, save the capture file — it is part of what `docs/offline-test-log.md` records.

---

## 1. Disconnect

**Physically.** Unplug the ethernet cable, or turn off Wi-Fi at the hardware switch/radio, not
just at the OS network-manager applet — the point is a machine that genuinely cannot reach
anything, not one that has been told not to try. Confirm:

```
ping -c 1 -W 2 1.1.1.1   # must fail
```

Bring the stack up with the network already disconnected, exactly as a user would on first
install:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

**Expect:** the stack comes up cleanly. Nothing in `podman compose logs` should show a
connection attempt failing with a DNS or routing error for anything other than the deliberate
refusals the egress proxy itself logs (`egress_refused`) — those are expected and are what
§4 investigates.

Record the proxy's baseline before doing anything else:

```
curl -s localhost:8000/network | python3 -m json.tool
```

**Expect:** `permitted: 0`. Note whatever `refused` already reads (a container's own startup
probes may have tried something once before the network came up — `docs/architecture.md`
§5.1's liveness-probe carve-out means a bare connect-and-close is not counted, so a nonzero
number here is a real attempt, not noise, and needs the same investigation as anything found
later).

---

## 2. Run the automatable half

```
scripts/verify-no-egress.sh
```

This exercises the parts of the walkthrough that are pure HTTP against a running stack — add a
document source, ask a grounded question, ask an abstaining question, correct a memory fact,
run a database query against the sandbox, take a backup, export the audit log — reusing
`eval/fixtures/corpus/` the same way `docs/restore-release-test.md` §0 does, so this gate
exercises a corpus already known to produce a checkable citation rather than one assembled by
hand each release. It polls `GET /network` before and after and fails if `permitted` moved at
all, or if a new `refused` entry names anything other than a container talking to another
container on the internal network (the script's own `note`/`ok`/`bad` output says which).

**What it does not cover, and why each is manual:**

- **Voice** (§3.8) — needs a real microphone and a browser driving `/voice/ws`; no headless
  audio input exists in this repository's toolchain.
- **A SQL dump import** (§3.2) — `eval/fixtures/corpus/` has no dump fixture; adding one is
  out of scope for this ticket, which tests the network claim, not dump ingestion coverage.
- **The physical disconnect itself** — a script cannot unplug a cable; §1 stays manual.
- **The independent capture** — reading and judging a `tcpdump` file is a human step, so §4
  stays manual even though the traffic it is checking was generated by an automated call.

A clean run of the script is necessary, not sufficient — continue to §3 for the parts it
cannot reach.

---

## 3. Manual walkthrough — the rest of the product

Work through every remaining feature. For each, after it completes, re-check
`curl -s localhost:8000/network | python3 -m json.tool` — catching a leak close to the action
that caused it is far more useful than one combined check at the end.

### 3.1 First run

If not already satisfied by §0/§1, confirm the welcome screen accepts the manually placed
model with no network attempt (`M7-OFFLINE-DEPLOY-144`), and that `docs/states-and-edge-cases.md`
§1's "Offline / no network, local mode" row holds: **no offline banner or indicator anywhere**,
on any screen touched in this walkthrough. Finding one is itself a release blocker, independent
of anything the proxy or capture shows.

### 3.2 Add every source kind

- A folder of files (mixed formats — reuse `eval/fixtures/corpus/`, already covered by §2).
- A CSV (`table_infer`) — pick one from `eval/fixtures/` if a table fixture exists, or a small
  ad-hoc one; confirm clarifications raise correctly with no network attempt.
- A SQL dump — load into the sandbox (`docs/data-sources.md` §3, C3). Confirm the sandbox
  container itself has no route out either — it is architecturally isolated from the egress
  proxy entirely (`docs/architecture.md` §5), so this is also a check that nothing has
  regressed that isolation.
- A live database connection — **excluded from the network-claim check** per this ticket's own
  edge case: a configured connection is a permitted destination *by the user's own action*
  (the sandbox Postgres, or a real external database), not an egress leak. If one is exercised
  in this walkthrough, count its traffic separately in the log entry rather than folding it
  into the "zero outbound" figure — conflating the two would make a legitimate, user-authorised
  connection look like the failure this gate exists to catch.

### 3.3 Ask, and get a real answer

Ask a grounded question against the added corpus (§2 already did this against the eval
fixture; do it again by hand against whatever was added in §3.2 for a citation you did not
script).

### 3.4 Abstain

Ask something the corpus cannot answer. Confirm the abstention copy (`docs/ux/ask.md` §6) and
**not** an offline-flavoured message — abstention and "no network" are different states and
must not be conflated in what is shown.

### 3.5 Clarify

Trigger a clarification (adding a source with an ambiguous column or a contradicting fact
usually does this — `docs/memory-and-clarification.md`). Answer it via `GET /clarifications`
/ `POST /clarifications/{id}/answer`.

### 3.6 Correct a fact

`POST /memory/facts/{fact_kind}/{fact_id}/correct` against a fact surfaced in §3.5 or already
in `memory`.

### 3.7 Query a database

Ask a question that routes to `askwell.sql_execute` against the sandbox or connection added in
§3.2 (`docs/architecture.md` §5.1, C2/C3). Confirm the generated query is disclosed
(`docs/ux/ask.md`) and that the sandbox's own isolation held (no external route attempted).

### 3.8 Use voice

Open the composer's mic control, speak a question, confirm transcription, turn detection,
generation and sentence-streamed speech all work (`M6-VUI-FE-135` and its dependencies) with
the network still disconnected. This is the one step with no HTTP equivalent to script.

### 3.9 Web search — the negative check, now that M6.5 has landed

Out of scope as a *working feature* per this ticket's own Out of Scope (web search is tested
for real separately, `M6.5-EVAL-TEST-194`, with the network up). What this gate does assert,
with the network down: trigger an abstention (§3.4), confirm the escalation offer still
renders (`docs/ux/web-search.md` §4's "Offered" state), accept it, and confirm the result is
*"I can't reach the web right now"* with the abstention still standing as the answer — not a
failed turn, not an offline banner, and no request actually leaves the machine attempting it
(`POST /ask/{message_id}/escalate/web` should show as a proxy refusal or, if the provider fails
before ever reaching the proxy, no attempt at all — either is acceptable; a silent success is
not). `docs/ux/web-search.md` §4's "Search unavailable" row is the exact copy to expect.

### 3.10 Take a backup

`POST /backup`, poll to `done`, download. No network attempt — a backup is a local file
operation only.

### 3.11 Export the audit log

`POST /log-export`, poll, download (`api/src/askwell/log_export.py`).

---

## 4. Investigate every refusal — required, not optional

Read the accumulated `GET /network` `refused` count and the proxy's own log
(`podman compose logs egress-proxy` or equivalent service name) for every entry recorded during
this run. Per this ticket's own Acceptance Criteria: **"Any refusal counted by the proxy is
investigated and named, not dismissed."**

For each refusal, name:

- **Which service tried** (`askwell.egress._resolve_service` already resolves this to a
  container name in the log line, not a raw IP).
- **What destination it attempted** (from the same log line).
- **Why** — a version check on import, a telemetry default in a dependency, a font/asset
  fallback, anything else. This is exactly the scenario named in this ticket's own
  Real-World Example: "a dependency upgrade adds a version check on import; the release test
  catches it before anyone installs it."

**A refusal is never accepted as noise.** If it traces to a genuinely benign dependency
default (an update-checker library's own telemetry ping, say), the fix is to configure or patch
that dependency to stop trying — not to note it and move on. File an issue immediately if the
fix cannot land in this same change (`AGENTS.md` §8): what tried, why, where it surfaced, and
the fix once found.

**A refusal for a benign check is investigated and fixed or documented, never treated as
noise** — this ticket's own edge case, verbatim.

---

## 5. Check the capture, independently

Read the `tcpdump` capture (or equivalent) from §0. Confirm:

- No packets to any address outside `127.0.0.1`/`::1` and the container-internal network
  ranges, for the whole duration of the walkthrough — **except** any address deliberately
  reached in §3.2's live-connection case, which must be named and match exactly the one
  destination the user configured.
- No DNS queries for any external hostname (a DNS query with no matching response still shows
  intent to reach something, and `docs/architecture.md` §5.1 already treats a failed DNS
  lookup — from a container that ignored the proxy entirely — as the network-level refusal
  the proxy variables cannot produce).

A capture that shows *anything* unaccounted for **fails the run**, even if the proxy's own
counter still reads zero — that divergence is precisely why this gate is built from two
independent checks rather than one (`AGENTS.md`'s stated assumption for this ticket).

---

## 6. Recording the result

Append one entry to `docs/offline-test-log.md`, newest first, following its own format.

**Any of the following fails the run:**

- `GET /network` `permitted` is nonzero for anything other than a §3.2 live connection, named
  and accounted for.
- Any refusal in §4 traced to something other than an expected internal-network call, and not
  fixed or filed.
- The capture in §5 shows anything the proxy's counters do not explain.
- An offline banner or warning appeared anywhere (`docs/states-and-edge-cases.md` §1).
- Any step in §3 failed for a reason that reads like a network failure (a timeout reaching
  something that should have been entirely local) rather than a genuine product bug.

**A `fail` entry blocks the release** — do not proceed to `docs/release-procedure.md` step 4
(checksums) until a passing entry for this `VERSION` exists.
