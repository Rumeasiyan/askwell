# Manual test — M6-TTS-BE-131, fall back to text when synthesis is unavailable

**Ticket:** `M6-TTS-BE-131` — a synthesis failure delivers the answer as text with a note instead of failing the turn
**Version under test:** `0.5.6`
**Time:** about 30 minutes
**Who can run it:** anyone who can paste lines into a terminal, rename a file, and read a Postgres query result. No microphone needed — the walkthrough drives the voice WebSocket directly with pre-recorded audio, the same way `M6-TTS-BE-130`'s did. Real Whisper `small` **and** Kokoro `v1.0` weights must already be in place — see step 2. You will deliberately hide the Kokoro file partway through, so keep a note of where it lives.

**What is being checked.** Before this ticket, `askwell.voice_tts._speak_answer` let a `/synthesize` failure propagate out of its poll loop, and `askwell.voice_channel._run_driver`'s broad exception handler turned that into the whole turn failing — an answer that had already generated correctly was thrown away over an unrelated model not being loaded. From this ticket, that failure is caught per sentence: the turn keeps generating and streaming text exactly as before, a `voice` WebSocket event tells the screen synthesis is unavailable, and no further sentence for *that* turn is sent to `/synthesize`. Availability is tracked across turns, not just within one — the very next turn's own first synthesis attempt is independent, so a recovered service is spoken again with no restart.

**Where this stops on purpose.** There is still no microphone button and no Ask-screen voice mode — `web/` has no voice UI at all (`M6-VUI-FE-135` has not landed). This walkthrough drives the channel directly from a terminal, listening for the new `voice` event this ticket adds. There is also no automatic repair of synthesis (the ticket's own stated gap) and no screen-level "voice mode disabled" state for the case where transcription itself is also down — see Known gaps.

---

## Before you start

You need a terminal, Podman, at least one document already added to your library that you can ask a real question about (with a fact you know the answer to), a way to record a few seconds of your own voice, and `ffmpeg` on your own machine to convert the recording.

### 1. Confirm the stack builds and comes up

```
scripts/dev.sh build-api
podman compose up -d
podman compose ps
```

**Expect:** `api` and `voice` rows, state `Up`.

### 2. Confirm real Whisper and Kokoro weights are both loaded

```
curl -s http://127.0.0.1:8090/health
```

**Expect:** both the `transcription` and `synthesis` objects show `"state": "loaded"`, with no `reason`. If either shows `"state": "missing"`, place the real weights under `ASKWELL_MODELS_DIR` per `M6-AUDIO-DEPLOY-125`'s walkthrough (Kokoro `v1.0` alongside the existing Whisper `small`), then `podman compose restart voice` and recheck. Note the exact path Kokoro's model file is loaded from (`ASKWELL_VOICE_KOKORO_MODEL_PATH`, `/models/kokoro-v1.0.onnx` inside the container — find the host-side file under your `ASKWELL_MODELS_DIR`) — you will move it aside in step 5.

### 3. Confirm the document you will ask about is indexed

Open `http://127.0.0.1:8000` in a browser and confirm at least one document is listed as ready in your library, and that it contains an answerable fact (a notice period, a renewal term, anything with a specific value). Note the fact and its answer for comparison later.

### 4. Record and convert two real spoken questions

Record yourself asking, out loud, two different questions your indexed document can answer — for example *"What is the notice period?"* and *"What is the renewal term?"* — and convert each the same way `M6-STT-BE-127`'s walkthrough did:

```
ffmpeg -i question1.wav -f s16le -acodec pcm_s16le -ar 16000 -ac 1 question1.pcm
ffmpeg -i question2.wav -f s16le -acodec pcm_s16le -ar 16000 -ac 1 question2.pcm
podman cp question1.pcm $(podman compose ps -q api):/tmp/question1.pcm
podman cp question2.pcm $(podman compose ps -q api):/tmp/question2.pcm
```

### 5. Hide the Kokoro model file to make synthesis unavailable, but leave Whisper in place

On the host, move the Kokoro model file (found in step 2) aside — do not delete it, you will restore it in step 9:

```
mv ~/.local/share/askwell/models/kokoro-v1.0.onnx ~/.local/share/askwell/models/kokoro-v1.0.onnx.bak
podman compose restart voice
```

```
curl -s http://127.0.0.1:8090/health
```

**Expect:** `transcription` still shows `"state": "loaded"`; `synthesis` now shows `"state": "missing"` with a `"reason"` naming the hidden path. This is the ticket's own scenario — "cold start with the synthesis model removed" — with transcription and synthesis failing independently, per the ticket's own Assumption.

### 6. Have a way to speak a real turn and watch text, the voice note, and (the lack of) audio arrive

Save this as `/tmp/voice_client.py`, then copy it into the `api` container. It streams a `.pcm` file in, sends `end`, and prints every event and the size of every binary audio frame as it arrives:

```python
import asyncio
import json
import sys

import websockets

PCM_PATH = sys.argv[1]
CHUNK = 3200  # 100ms at 16kHz/mono/16-bit

async def main() -> None:
    async with websockets.connect("ws://127.0.0.1:8000/voice/ws") as ws:
        print("turn:", json.loads(await ws.recv()))

        with open(PCM_PATH, "rb") as f:
            data = f.read()
        for i in range(0, len(data), CHUNK):
            await ws.send(data[i : i + CHUNK])
        await ws.send(json.dumps({"type": "end"}))

        while True:
            message = await ws.recv()
            if isinstance(message, bytes):
                print(f"audio bytes: {len(message)}")
            else:
                event = json.loads(message)
                print("event:", event)
                if event.get("type") == "status":
                    return

asyncio.run(main())
```

```
podman cp /tmp/voice_client.py $(podman compose ps -q api):/tmp/voice_client.py
```

---

## The walkthrough

### 7. Speak a real question with synthesis unavailable and confirm it is transcribed and answered as text, with a note

```
podman compose exec api python3 /tmp/voice_client.py /tmp/question1.pcm
```

**Expect, in order:**
- `turn:` line.
- One or more `transcript` events whose text reads back close to what you actually asked — transcription is unaffected by synthesis being down.
- A `confidence` event.
- `text` events building up the full answer, word by word.
- **No `audio bytes:` line anywhere in the output** — nothing was queued for playback.
- Exactly one `event: {'type': 'voice', 'available': False, 'reason': ...}` — the note this ticket adds. The `reason` should mention the failure the `voice` container returned (a 503 naming the missing Kokoro file), not a generic string.
- `event: {'type': 'status', 'status': 'completed'}` — the turn completes normally, not `failed`.

Compare the joined `text` events against the fact you noted in step 3 — the answer should actually address your question. This is the acceptance criterion itself: a voice question, transcribed, answered as text, with a note that voice is unavailable.

### 8. Confirm the turn's transcript and text answer are both logged like any other

Using the `turn_id` printed in step 7:

```
scripts/dev.sh psql -c "select role, content from messages m join audit_interactions a on a.payload->>'turn_id' = '<turn_id-from-step-7>' order by m.id;"
```

**Expect:** an `assistant` row whose `content` is the full answer text from step 7 — stored exactly as a synthesized answer would be. A voice failure changing nothing about how the answer itself is recorded is the point: only the spoken half is missing.

### 9. Confirm the availability transition was logged

```
podman compose logs api | grep voice_synthesis_unavailable | tail -1
```

**Expect:** one line naming the `turn_id` from step 7 and a `reason` — the audit requirement ("availability transitions are logged") and the local-counter requirement (C1: nothing left this machine) are the same log line.

### 10. Restore the Kokoro model and confirm the very next turn is spoken again, with no restart of `api`

Put the model file back and restart only `voice` — **do not** restart or rebuild `api`:

```
mv ~/.local/share/askwell/models/kokoro-v1.0.onnx.bak ~/.local/share/askwell/models/kokoro-v1.0.onnx
podman compose restart voice
curl -s http://127.0.0.1:8090/health
```

**Expect:** `synthesis` now shows `"state": "loaded"` again.

```
podman compose exec api python3 /tmp/voice_client.py /tmp/question2.pcm
```

**Expect:** `transcript`, `confidence` and `text` events as before, **at least one `audio bytes: <n>` line** (synthesis working again), and **no `voice` event at all** — recovery has nothing to announce, per this ticket's own design (only the failure is a one-shot event; recovery is simply the next turn behaving normally). `status: completed`.

```
podman compose logs api | grep voice_synthesis_recovered | tail -1
```

**Expect:** one line naming this turn's `turn_id` — the recovery half of the same audit trail.

### 11. Confirm a synthesis failure partway through a longer answer still delivers the rest as text, with one note

Hide the Kokoro file again (step 5's `mv`, then `podman compose restart voice`), then ask a question you expect a multi-sentence answer to:

```
podman compose exec api python3 /tmp/voice_client.py /tmp/question1.pcm
```

**Expect:** the full multi-sentence `text` answer arrives regardless of sentence count, exactly **one** `voice` event (not one per sentence after the failure), no `audio bytes:` lines, and `status: completed`. This is the ticket's own mid-answer edge case: synthesis failing partway through does not fail the turn, and does not spam a note per remaining sentence.

### 12. Confirm a stopped turn with synthesis already unavailable still stops promptly

With Kokoro still hidden, run the client interactively (or add a short `asyncio.sleep` plus a `stop` control message, the same pattern `M6-TTS-BE-130`'s walkthrough step 10 used) partway through a longer answer:

```python
await asyncio.sleep(1.0)
await ws.send(json.dumps({"type": "stop"}))
```

**Expect:** `text` events stop arriving promptly after the `stop` message, `status` arrives without a further pause, and — as in every other step here — no `audio bytes:` line at any point.

### 13. Confirm text asking still works, untouched

Restore the Kokoro model (step 10) so the stack is left in a working state, then open `http://127.0.0.1:8000` in a browser and ask a typed question against the same document.

**Expect:** the Ask screen behaves exactly as before — this fallback path only changes what happens on the voice channel when synthesis specifically fails; typed asking never touches `askwell.voice_tts` at all.

---

## Known gaps

- **No microphone button, no Ask-screen voice mode.** `web/` has no voice UI at all (`M6-VUI-FE-135`), so this walkthrough drives the WebSocket directly with pre-recorded audio, the same way `M6-TTS-BE-130`'s and `M6-STT-BE-127`'s did. The `voice` event this ticket adds has nothing to render yet — a future screen-level ticket is what turns it into the on-screen note `docs/ux/voice.md` §5 describes.
- **No automatic repair of synthesis.** A model that failed to load stays unavailable for the rest of that turn regardless of how long the answer runs; the walkthrough's only way to make it available again is to actually fix the file and restart `voice` (steps 5 and 10), exactly as the ticket's Out of Scope states.
- **Both transcription and synthesis unavailable is not exercised here as a distinct case.** If Whisper is also missing, transcription fails first (`askwell.voice_stt.TranscriptionUnavailable`) and the whole turn ends with `status: failed` before this ticket's fallback code is ever reached — the same behaviour every earlier voice ticket's walkthrough has already exercised. The ticket's own edge case ("voice mode disabled with the reason, typing unaffected") is a screen-level state that has no surface to show it on yet; typed asking being unaffected is covered by step 13 regardless of which model is down.
- **The 3.5s/8s time-to-first-audio budget is not re-measured here** — not applicable to a turn where no audio is produced at all; unaffected turns are still covered by `M6-TTS-BE-130`'s own walkthrough.
- **Non-English speech and no-speech turns are not re-tested here.** Those paths are unchanged by this ticket and were exercised in `M6-STT-BE-127`'s walkthrough.
