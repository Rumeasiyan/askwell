# Manual test — M6-STT-BE-128, turn detection and the silent timeout

**Ticket:** `M6-STT-BE-128` — a turn closes itself on a pause, via Silero VAD, without the client sending `end`
**Version under test:** `0.5.4`
**Time:** about 25 minutes
**Who can run it:** anyone who can paste lines into a terminal and run `ffmpeg` and a short Python script. Real Silero VAD weights (`silero_vad.onnx`) must already be in place — see step 2. Real Whisper `small` weights help interpret the transcript in step 6 but are not required for this ticket's own pass/fail.

**What is being checked.** Since `M6-AUDIO-API-126`, a voice turn closed only when the client sent `{"type": "end"}` or `{"type": "stop"}`. This ticket adds a second, automatic trigger: every audio frame the channel receives is also scored by the `voice` container's `/vad` (`api/src/askwell/voice_turn_detection.py`), and once enough trailing silence has piled up *after* speech has been heard, the channel closes the turn itself — same sentinel, same code path as an explicit `end`. A pause before any speech has started never closes anything on its own; only the client's own `end`/`stop` (or eventually just disconnecting) ends a turn that never had speech in it, and that is what "silent return to idle" means from the server's side — no event, no transcript, no stored turn.

**Where this stops on purpose.** There is still no microphone button and no Ask-screen voice mode (`M6-VUI-FE-135` has not landed) — push-to-talk, the hands-free toggle, the level meter, and the "no speech detected" silent-idle screen described in `docs/ux/voice.md` §3 and §5 are all frontend behaviour that does not exist in `web/` yet. What exists is the backend half: a WebSocket channel that closes a turn on its own once VAD detects a pause. This walkthrough drives that channel directly with real recorded audio, standing in for holding and releasing a control that is not built yet.

---

## Before you start

You need a terminal, Podman, a way to record a few seconds of your own voice, and `ffmpeg` to convert it.

### 1. Confirm the stack builds and comes up

```
scripts/dev.sh build-api
podman compose up -d
podman compose ps
```

**Expect:** `api` and `voice` rows, state `Up`.

### 2. Confirm real Silero VAD weights are loaded, not missing

```
curl -s http://127.0.0.1:8090/health
```

**Expect:** the response includes a `service_starts` count and no crash. This endpoint does not surface VAD's own load state as a top-level field the way `transcription`/`synthesis` do — confirm VAD specifically by watching the startup log instead:

```
podman compose logs voice | grep voice_startup | tail -1
```

If `silero_vad.onnx` is missing, place it at `${ASKWELL_MODELS_DIR:-~/.local/share/askwell/models}/silero_vad.onnx` (MIT-licensed, `snakers4/silero-vad`, `files/silero_vad.onnx` — verified against the registry per `AGENTS.md` §4), then `podman compose restart voice`. Confirm it loaded:

```
curl -s -X POST http://127.0.0.1:8090/vad --data-binary @/dev/null
```

**Expect:** `{"speech_probabilities":[]}` (empty input, but 200 — not the 503 `"reason"` body you would get with no model loaded). If you get a 503, stop and note it — nothing past this point can be exercised for real without a loaded VAD model.

### 3. Record two short test clips

- **`question.wav`** — you asking a short English question aloud, including a deliberate **thinking pause of about one second in the middle** (e.g. *"What is the... [pause] ...notice period?"*).
- **`silence.wav`** — nothing, just ambient room noise, about 3 seconds.

Convert both to raw PCM the voice channel expects — 16 kHz, mono, 16-bit signed little-endian, no header:

```
ffmpeg -i question.wav -f s16le -acodec pcm_s16le -ar 16000 -ac 1 question.pcm
ffmpeg -f lavfi -i anullsrc=r=16000:cl=mono -t 3 -f s16le -acodec pcm_s16le silence.pcm
```

Copy both into the `api` container:

```
podman cp question.pcm $(podman compose ps -q api):/tmp/question.pcm
podman cp silence.pcm  $(podman compose ps -q api):/tmp/silence.pcm
```

### 4. Have a way to stream real-time audio to the channel and watch turn closure

Unlike a plain playback script, this needs to stream chunks **paced in real time** — the pause detector accumulates silence in milliseconds, so sending a whole file instantly defeats the point. Save this as `/tmp/voice_vad_client.py`:

```python
import asyncio
import json
import sys
import time

import websockets

PCM_PATH = sys.argv[1]
SEND_END = len(sys.argv) > 2 and sys.argv[2] == "--end"
CHUNK = 3200  # 100ms at 16kHz/mono/16-bit

async def main() -> None:
    async with websockets.connect("ws://127.0.0.1:8000/voice/ws") as ws:
        print("turn:", json.loads(await ws.recv()))

        with open(PCM_PATH, "rb") as f:
            data = f.read()

        async def sender():
            for i in range(0, len(data), CHUNK):
                await ws.send(data[i : i + CHUNK])
                await asyncio.sleep(0.1)  # pace to real time, 100ms per chunk
            if SEND_END:
                await ws.send(json.dumps({"type": "end"}))

        async def receiver():
            start = time.monotonic()
            while True:
                message = await ws.recv()
                elapsed = time.monotonic() - start
                if isinstance(message, bytes):
                    print(f"{elapsed:.2f}s audio bytes:", len(message))
                else:
                    event = json.loads(message)
                    print(f"{elapsed:.2f}s event:", event)
                    if event.get("type") == "status":
                        return

        send_task = asyncio.create_task(sender())
        try:
            await receiver()
        finally:
            send_task.cancel()

asyncio.run(main())
```

```
podman cp /tmp/voice_vad_client.py $(podman compose ps -q api):/tmp/voice_vad_client.py
```

---

## The walkthrough

### 5. Confirm the pause threshold, then hold through a thinking pause without being cut off

```
grep -n "voice_vad_pause_ms" api/src/askwell/config.py
```

Note the default (`700` ms unless overridden in `.env`). Your `question.wav` pause from step 3 should be **shorter** than this — that is the point: a normal mid-sentence pause must not close the turn early.

```
podman compose exec api python3 /tmp/voice_vad_client.py /tmp/question.pcm
```

**Expect:**
- `turn: {'type': 'turn', 'turn_id': '<a uuid>'}`
- No `status` event anywhere near your one-second thinking pause — the stream keeps going through it.
- After the clip finishes streaming (no `--end` was sent), a `status: completed` event appears roughly `voice_vad_pause_ms` after the **last real speech** in the clip — the trailing silence after your question closes the turn on its own, with no `end` message ever sent by this script.
- If you scripted a pause *longer* than the threshold in the middle of `question.wav` by mistake, you will instead see the turn close mid-question — that means your test clip's pause was too long for this check; re-record with a shorter pause and repeat.

**Record** the `turn_id` and confirm the whole question was heard, not truncated at the pause:

```
scripts/dev.sh psql -c "select content from messages m join audit_interactions a on a.payload->>'turn_id' = '<turn_id-from-above>' order by m.id desc limit 1;"
```

**Expect:** the stored transcript includes words from **both before and after** your mid-question pause — proof the pause did not truncate the turn.

### 6. Speak, then stop, and confirm the turn closes itself on the trailing pause

This is the same behaviour as step 5, isolated: a clean utterance followed by silence, with no `end` ever sent.

```
podman compose exec api python3 /tmp/voice_vad_client.py /tmp/question.pcm
```

**Expect:** exactly as step 5 — a `status: completed` event appears on its own, timed to roughly `voice_vad_pause_ms` after your speech ends in the clip, never because the script sent `end` (it did not — no `--end` flag was passed).

### 7. Confirm a turn with no speech at all does not close on VAD, and produces no record

```
podman compose exec api python3 /tmp/voice_vad_client.py /tmp/silence.pcm
```

**Expect:** the clip finishes streaming (all 3 seconds of silence sent), but **no `status` event appears** — the turn stays open. This is the "releasing push-to-talk before speaking" edge case: a pause before any speech was ever heard is not a pause worth closing on, so VAD never fires. Interrupt the script (Ctrl-C) once you have confirmed no `status` event arrives within a few seconds of the clip ending.

Confirm nothing was stored, since the turn never closed and nothing was asked:

```
podman compose logs api | grep voice_turn_started | tail -1
```

**Expect:** a `voice_turn_started` line for this turn, but no matching `voice_turn_finished` line yet — the turn is still open server-side, exactly as `docs/ux/voice.md` §5's "No speech detected → silent return to idle" implies: nothing happens, nothing is logged, because nothing was asked. (The actual silent-idle *screen* behaviour — no error sound, no dialogue — is `M6-VUI-FE-135`'s job once a frontend exists; this step only confirms the server never manufactures a turn from silence.)

### 8. Confirm the manual stop control still ends a turn instantly, VAD or not

```
podman compose exec api python3 /tmp/voice_vad_client.py /tmp/silence.pcm --end
```

**Expect:** `status: completed` appears almost immediately after the clip finishes streaming — because `--end` sends the client's own `end` message, which still closes the turn instantly regardless of VAD. This confirms VAD is an addition to the transport, not a replacement: the manual stop control (`docs/ux/voice.md` §3 point 6) keeps working exactly as before this ticket.

### 9. Confirm VAD unavailability degrades to "wait for explicit close", not a stuck or broken turn

```
podman compose stop voice
podman compose exec api python3 /tmp/voice_vad_client.py /tmp/question.pcm --end
```

**Expect:** the turn still completes normally (VAD failures are logged and swallowed, `voice_turn_detection.py`'s `_VadTurnDetector.feed` catching `httpx.HTTPError`) — but since VAD cannot be reached, it is the `--end` message that closes the turn, not a pause. Confirm:

```
podman compose logs api | grep voice_vad_unavailable | tail -3
```

**Expect:** one or more `voice_vad_unavailable` warning lines. Bring `voice` back before continuing:

```
podman compose up -d voice
```

### 10. Confirm text asking still works, untouched

Open `http://127.0.0.1:8000` in a browser and ask a typed question against material you have already added.

**Expect:** the Ask screen behaves exactly as before — turn detection is additive to the voice channel only.

---

## Known gaps

- **No microphone button, no push-to-talk control, no hands-free toggle, no level meter.** `web/` has no voice UI at all (`M6-VUI-FE-135`), so this walkthrough drives the WebSocket directly, real-time-paced, standing in for holding and releasing a control that does not exist yet. Do not report the absence of any of this as a defect of this ticket.
- **No silent-idle screen.** `docs/ux/voice.md` §5's "no error sound, no dialogue" is a frontend behaviour. Step 7 only confirms the server never manufactures a turn, an event, or a stored record from silence — it says nothing about what a user would see, because nothing renders that yet.
- **Hands-free noisy-room tuning is untuned and out of scope**, per the ticket's own text. This walkthrough does not attempt to characterise VAD behaviour in continuous background noise — that needs a frontend elapsed-time display (also not built) to be meaningful, and is explicitly an open question the ticket defers.
- **The pause threshold (`voice_vad_pause_ms`, default 700ms) is a single global config value**, not tuned per-environment or exposed to the user. Step 5 only confirms it does not cut off a short thinking pause with the default; whether 700ms is right for every voice is not verified here.
- **Answering the transcribed question is unaffected and untested here.** `M6-TTS-BE-130`'s dependency chain is what turns a closed turn into a spoken answer; this ticket only closes the turn.
