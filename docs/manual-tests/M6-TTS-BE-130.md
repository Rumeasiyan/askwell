# Manual test — M6-TTS-BE-130, sentence-streamed speech synthesis

**Ticket:** `M6-TTS-BE-130` — synthesize the answer sentence by sentence as it streams, so audio starts before generation finishes
**Version under test:** `0.5.5`
**Time:** about 30 minutes
**Who can run it:** anyone who can paste lines into a terminal and read a Postgres query result. No microphone needed — the walkthrough drives the voice WebSocket directly with pre-recorded audio, exactly as `M6-STT-BE-127`'s did. Real Whisper `small` **and** Kokoro `v1.0` weights must already be in place — see step 2.

**What is being checked.** Since `M6-STT-BE-127`, a transcribed turn ended once its transcript was settled. From this ticket, a successful transcript now continues into a real answer: `askwell.ask`'s own generation engine runs, text streams onto the channel as `text` events exactly as typed asking shows it, and — the point of this ticket — audio for each completed sentence is queued and sent **before the rest of the answer has finished generating**, not after. A citation marker such as `[1]` stays in the on-screen text unchanged, but is never read aloud; the first sentence that cites a given document instead names it in passing ("...from the supplier agreement 2024"). Stopping mid-answer stops audio promptly, not after the sentence in flight finishes.

**Where this stops on purpose.** There is still no microphone button and no Ask-screen voice mode — `web/` has no voice UI at all (`M6-VUI-FE-135` has not landed). This walkthrough drives the channel directly from a terminal with real recorded speech, the same shape `M6-STT-BE-127`'s walkthrough used, listening for the new `citation`/`fact_citation` events and binary audio frames this ticket adds on top of it.

---

## Before you start

You need a terminal, Podman, at least one document already added to your library that you can ask a real question about, a way to record a few seconds of your own voice, and `ffmpeg` on your own machine to convert the recording.

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

**Expect:** both the `transcription` and `synthesis` objects show `"state": "loaded"`, with no `reason`. If either shows `"state": "missing"`, place the real weights under `ASKWELL_MODELS_DIR` per `M6-AUDIO-DEPLOY-125`'s walkthrough (Kokoro `v1.0` alongside the existing Whisper `small`), then `podman compose restart voice` and recheck. Nothing past this point can be exercised for real without both models present — stop and note it in your results rather than guessing at the outcome.

### 3. Confirm the document you will ask about is indexed

Open `http://127.0.0.1:8000` in a browser and confirm at least one document is listed as ready in your library, and that it actually contains an answerable fact (a notice period, a renewal term, anything with a specific value). Note the fact and its answer for comparison later.

### 4. Record and convert a real spoken question

Record yourself asking, out loud, a question your indexed document can answer — for example *"What is the notice period?"* — and convert it the same way `M6-STT-BE-127`'s walkthrough did:

```
ffmpeg -i question.wav -f s16le -acodec pcm_s16le -ar 16000 -ac 1 question.pcm
podman cp question.pcm $(podman compose ps -q api):/tmp/question.pcm
```

### 5. Have a way to speak a real turn and watch both text and audio arrive

Save this as `/tmp/voice_client.py`, then copy it into the `api` container. It streams the `.pcm` file in, sends `end`, and prints every event and the size of every binary audio frame as it arrives, with a timestamp so you can see whether audio started before the text finished:

```python
import asyncio
import json
import sys
import time

import websockets

PCM_PATH = sys.argv[1]
CHUNK = 3200  # 100ms at 16kHz/mono/16-bit

async def main() -> None:
    start = time.monotonic()
    async with websockets.connect("ws://127.0.0.1:8000/voice/ws") as ws:
        print(f"{time.monotonic() - start:.2f}s turn:", json.loads(await ws.recv()))

        with open(PCM_PATH, "rb") as f:
            data = f.read()
        for i in range(0, len(data), CHUNK):
            await ws.send(data[i : i + CHUNK])
        await ws.send(json.dumps({"type": "end"}))

        while True:
            message = await ws.recv()
            elapsed = time.monotonic() - start
            if isinstance(message, bytes):
                print(f"{elapsed:.2f}s audio bytes: {len(message)}")
            else:
                event = json.loads(message)
                print(f"{elapsed:.2f}s event:", event)
                if event.get("type") == "status":
                    return

asyncio.run(main())
```

```
podman cp /tmp/voice_client.py $(podman compose ps -q api):/tmp/voice_client.py
```

---

## The walkthrough

### 6. Speak the real question and confirm audio starts before the answer finishes

```
podman compose exec api python3 /tmp/voice_client.py /tmp/question.pcm
```

**Expect, in order:**
- `turn:` line.
- One or more `transcript` events whose text reads back close to what you actually asked.
- A `confidence` event.
- `text` events building up the answer, word by word.
- At least one `citation` event, if your document's fact came with a source.
- At least one `audio bytes: <n>` line, appearing **before** the final `text` event and before `status: completed` — this is the ticket's whole point. Note the timestamp of the first audio frame versus the timestamp of the last `text` event: the audio line should come first, proving speech started before the answer text was complete.
- `event: {'type': 'status', 'status': 'completed'}`.

Compare the joined `text` events against the fact you noted in step 3 — the answer should actually address your question.

### 7. Confirm the citation marker is on screen but never appears in what was spoken

You cannot hear the audio from this raw dump, but you can confirm what was *sent* to be spoken by checking the `voice` container's own log of the request it served:

```
podman compose logs voice | grep -i "POST /synthesize" | tail -5
```

Compare the joined `text` events from step 6 (which should still contain a raw marker like `[1]`) against the citation events printed. **Expect:** the `text` events carry the marker unchanged — this is the Validation Rule that screen rendering is unchanged in voice mode. If you want to hear the difference directly, replace the print in step 5's script with a `.pcm` file writer for `audio bytes` frames and play the result back with `aplay -f S16_LE -r 24000 -c 1 out.pcm` (24 kHz mono PCM16, per this ticket's own wire format) — you should hear the answer's first sentence naming the source document by name ("...from the [document name]...") rather than a filename and page number being read aloud, and no subsequent sentence repeating that mention if the same document is cited again.

### 8. Confirm the audio queue plays back with no gap or overlap

Re-run step 6 while writing every `audio bytes` frame to a single file in order (append each frame's raw bytes as it arrives), then play the concatenated result:

```
aplay -f S16_LE -r 24000 -c 1 /tmp/answer.pcm
```

**Expect:** one continuous-sounding answer, sentence following sentence with a natural pause between them, no silence gap long enough to sound broken and no sentence audibly cut off or overlapping the next.

### 9. Ask a question that produces a very short answer and confirm no audible seam

Record and convert a question you know produces a one- or two-word answer (a yes/no question about your document works well), then repeat step 6/8 against it.

**Expect:** a single `audio bytes` frame (or very few), and playback that sounds like one clean utterance — no seam from being synthesized as multiple fragments.

### 10. Stop mid-answer and confirm audio stops promptly

Ask a question you expect a longer answer to, and this time send a `stop` control message partway through instead of letting the turn finish. Adjust step 5's script (or run it interactively) to send:

```python
await asyncio.sleep(1.5)  # after a couple of text/audio events have already arrived
await ws.send(json.dumps({"type": "stop"}))
```

**Expect:** no further `audio bytes` frames appear after the `stop` is sent, even though the answer's text may have already had a complete sentence buffered beyond the last one spoken. `status` arrives promptly rather than after a further pause.

### 11. Confirm the turn's transcript and answer are both logged like any other

Using the `turn_id` printed in step 6:

```
scripts/dev.sh psql -c "select role, content from messages m join audit_interactions a on a.payload->>'turn_id' = '<turn_id-from-step-6>' order by m.id;"
```

**Expect:** a `user` row (or however your schema records the transcript) and an `assistant` row whose `content` is the full answer text from step 6, markers and all — the same content a typed question's answer would produce, stored the same way.

### 12. Stop the voice container and confirm synthesis fails loudly, not silently

```
podman compose stop voice
podman compose exec api python3 /tmp/voice_client.py /tmp/question.pcm
```

**Expect:** `transcript`/`confidence` events still appear (transcription needs `voice` too, so this may instead fail earlier at that step depending on which call reaches the stopped container first) and ultimately `status: failed` — no invented audio, no `completed` status standing in for a request that never actually synthesized anything.

```
podman compose logs api | grep voice_turn_driver_failed | tail -1
```

**Expect:** a line naming the `turn_id` from this step. Bring the container back before continuing:

```
podman compose up -d voice
```

### 13. Confirm text asking still works, untouched

Open `http://127.0.0.1:8000` in a browser and ask a typed question against the same document.

**Expect:** the Ask screen behaves exactly as before — this speech path is additive to the voice channel only, and the typed answer's on-screen rendering is unchanged.

---

## Known gaps

- **No microphone button, no Ask-screen voice mode.** `web/` has no voice UI at all (`M6-VUI-FE-135`), so this walkthrough drives the WebSocket directly with pre-recorded audio, the same way `M6-STT-BE-127`'s and `M6-AUDIO-API-126`'s did.
- **No voice selection or speed control.** Kokoro's `af_heart` preset and default speed are used for every turn; both are explicitly out of scope for this ticket.
- **The 3.5s/8s time-to-first-audio budget is not measured here.** Step 6 asks you to compare timestamps qualitatively (audio before the last text event); a real latency measurement against the budget is a separate, later verification.
- **No low-confidence confirmation step.** A low-confidence transcript from `M6-STT-BE-127` still proceeds straight into an answer here; deciding to show the transcript and ask before answering is `M6-STT-FE-129`'s screen-level concern, not this backend ticket's.
- **Non-English speech and no-speech turns are not re-tested here.** Those paths were exercised in `M6-STT-BE-127`'s walkthrough and are unchanged by this ticket; a language-unsupported or silent turn still ends before generation is ever reached, so no synthesis call happens.
- **Fact-citations (memory-derived claims) are not exercised in this walkthrough** unless your test document's answer happens to draw on stored memory rather than a document passage — only a document citation gets a natural spoken mention; a memory-fact citation has no filename to build one from.
