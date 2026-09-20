# Manual test — M6-AUDIO-DEPLOY-125, the voice container

**Ticket:** `M6-AUDIO-DEPLOY-125` — voice container with transcription and synthesis
**Version under test:** `0.5.1`
**Time:** about 20 minutes
**Who can run it:** anyone who can paste a line into a terminal and open a URL in a browser. No microphone, no speaker and no real model weights are needed for most of this — see step 3.

**What is being checked.** This ticket has no screen and no audio path yet — nothing can be spoken to or heard from Askwell today. What exists is a fourth container (`voice`) that loads three local model files at startup and reports, separately, whether transcription and synthesis are usable. The two things that matter: a missing model never crashes the service or the rest of the stack, and the container makes no outbound request of any kind, ever — not even a refused one, because it has no network route to attempt one on.

**Why "reported separately" matters.** A future release can have working transcription and broken synthesis, or the reverse. If the health surface only said "voice: down", the interface would have to disable voice mode entirely for a fault that only affects half of it. Two independent lines are what let a later ticket keep transcription usable while synthesis falls back to text.

**Where this stops on purpose.** There is no microphone button, no WebSocket, and nothing that sends or receives audio — that is `M6-AUDIO-API-126`. This walkthrough only reaches the health surface, directly, because there is nothing else built yet to route through.

---

## Before you start

You need a terminal and Podman. You do not need Python, Node, real Whisper/Kokoro/Silero weights, or a microphone.

### 1. Confirm the stack builds and comes up

```
scripts/dev.sh build-api
podman compose up -d
podman compose ps
```

**Expect:** a `voice` row alongside `api`, `worker`, `postgres`, `redis`, `sandbox`, `egress-proxy`, state `Up` (it may briefly show `starting` — the healthcheck has a 15-second grace period).

### 2. Check `.env` has the models directory set

Open `.env` and confirm this line is present (added by `.env.example`, copied when the stack was first set up):

```
ASKWELL_MODELS_DIR=~/.local/share/askwell/models
```

You do not need anything in that directory yet — that is exactly what the next step tests.

---

## The walkthrough

### 3. Start cold, with no model files at all

Make sure the directory named by `ASKWELL_MODELS_DIR` is empty or does not exist, then restart just the voice container fresh:

```
podman compose stop voice
podman compose rm -f voice
podman compose up -d voice
```

In a browser, open:

```
http://127.0.0.1:8090/health
```

**Expect:** the page loads (not a connection error, not a 5xx) and shows JSON with two top-level model entries, `transcription` and `synthesis`, each with `"state": "missing"` and a `"reason"` that names the exact file path Askwell looked for and was not able to find — for example, a path ending in `whisper-small/model.bin`. Nothing here should say "loading" or hang; it answers immediately.

**Record:** read the two reasons. Each must name a specific path on disk, not a generic "not configured". A vague reason here is the defect this ticket exists to prevent — the acceptance criterion is explicitly "a clear refusal naming the path".

### 4. Confirm the container logged what happened

```
podman compose logs voice | grep voice_startup
```

**Expect:** one `voice_startup` line from this restart, naming the version and both model states as `missing`, each with its path — the same information `/health` gave you, now in the durable log rather than only on the page.

### 5. Confirm the service made no outbound request

```
podman compose exec voice python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
try:
    s.connect(('1.1.1.1', 443))
    print('REACHED THE INTERNET — FAIL')
except OSError as e:
    print('blocked:', e)
"
```

**Expect:** `blocked: [Errno 101] Network is unreachable` (or equivalent) — not a timeout, not a refusal from the egress proxy. The `voice` container sits on the `internal` network only, with no `egress` membership at all, so there is no route out to attempt, let alone a refusal to log.

Then confirm the egress proxy agrees nothing passed through it:

```
curl -s http://127.0.0.1:8000/network
```

**Expect:** whatever refusal count was already there before this walkthrough, unchanged. If this number went up during steps 3–5, something in `voice` reached the proxy, which should not be possible given its network membership — stop and report it.

### 6. Confirm text asking still works with voice unavailable

Open `http://127.0.0.1:8000` in a browser and ask any question against material you have already added (or add one first, per `M1-ADD-BE-023`'s walkthrough, if the library is empty).

**Expect:** the Ask screen behaves exactly as before — question submits, answer streams, citations appear. Nothing about the voice container's state is visible here, because nothing wires them together yet (that wiring is a later ticket). This step exists only to confirm the missing/failed voice container did not take anything else down with it.

### 7. Stop the voice container entirely and recheck text asking

```
podman compose stop voice
curl -s http://127.0.0.1:8000/health
```

**Expect:** `api`'s own `/health` still returns `200` and does not mention `voice` failing anything — ask a question again in the browser exactly as in step 6, and it still works. Voice being absent must not degrade the product the rest of the way; that is the ticket's own out-of-scope boundary.

Bring it back for later use:

```
podman compose up -d voice
```

### 8. Load one real model and confirm the two lines move independently

If you have (or are willing to fetch on another machine and copy over, never onto this one at runtime) real weights, this step shows the two health lines actually diverging — skip it if you don't have the files, and note that in your results instead of guessing at the outcome.

Place only the Kokoro synthesis files (`kokoro-v1.0.onnx` and `voices-v1.0.bin`, from `thewh1teagle/kokoro-onnx`'s `model-files-v1.0` release) under `~/.local/share/askwell/models/`, leaving the Whisper and Silero VAD paths empty, then:

```
podman compose restart voice
curl -s http://127.0.0.1:8090/health
```

**Expect:** `synthesis.state` is `"loaded"` with no `reason`, while `transcription.state` is still `"missing"` with its path. This is the acceptance criterion "transcription available but synthesis not — reported separately" in its mirror image, and it is the whole reason the two lines are independent properties rather than one aggregate flag.

---

## Known gaps

- **Nothing can be spoken to or heard from Askwell yet.** No microphone, no WebSocket, no audio in or out — this ticket is model loading and health reporting only. `M6-AUDIO-API-126` is the transport.
- **Whisper `small` on CPU is untested against any latency budget.** The ticket's own assumption is unverified; do not report slow transcription as a defect of this ticket, since nothing here transcribes anything yet.
- **Load failure (a present-but-corrupt file, `state: "load_failed"`) is not exercised in this walkthrough.** It would need a deliberately truncated model file; the code path exists (`api/src/askwell/voice/models.py`) but was not walked step by step here.
- **Insufficient-memory degradation on the `light` profile** (`docs/architecture.md` §"deployment profiles") is not exercised — this walkthrough does not constrain container memory.
- **`egress-proxy` crash-looping is a real, pre-existing bug unrelated to this ticket**, tracked as issue #439. If `podman compose ps` shows `egress-proxy` restarting repeatedly, that is the known issue, not something this walkthrough introduced.
