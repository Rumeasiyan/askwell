# Manual test — M6-STT-BE-127, English transcription

**Ticket:** `M6-STT-BE-127` — transcribe captured audio with Whisper `small`, English only, with a confidence measure
**Version under test:** `0.5.3`
**Time:** about 30 minutes
**Who can run it:** anyone who can paste lines into a terminal, record a few seconds of their own voice, and run one common conversion command. Real Whisper `small` weights must already be in place — see step 2.

**What is being checked.** The voice WebSocket channel (`M6-AUDIO-API-126`) now has something behind it: a turn's buffered audio is sent to the `voice` container's `/transcribe`, and the result — a transcript, a confidence measure, or an unsupported-language verdict — comes back over the channel and is stored with the turn. Three outcomes matter: English speech produces an accurate transcript with a confidence number, before any answer exists to show; non-English speech produces a language verdict rather than a garbled attempt; and very quiet speech is still transcribed, at low confidence, rather than silently dropped.

**Where this stops on purpose.** There is still no microphone button and no Ask-screen voice mode — `web/` has no voice UI yet (`M6-VUI-FE-135` has not landed), and answering the transcribed question is a separate, later ticket (`M6-TTS-BE-130`'s dependency chain). This walkthrough drives the channel directly from a terminal with real recorded audio, the same way `M6-AUDIO-API-126`'s walkthrough did with fake frames — except the frames here are real speech, because that is the one thing this ticket adds.

---

## Before you start

You need a terminal, Podman, a way to record a few seconds of your own voice (a phone voice memo app, your computer's built-in recorder, or `arecord`/similar), and `ffmpeg` on your own machine to convert the recording — not inside any container, and not a new dependency of the product itself, just a common tool for preparing a test file.

### 1. Confirm the stack builds and comes up

```
scripts/dev.sh build-api
podman compose up -d
podman compose ps
```

**Expect:** `api` and `voice` rows, state `Up`.

### 2. Confirm real Whisper `small` weights are loaded, not missing

```
curl -s http://127.0.0.1:8090/health
```

**Expect:** the `transcription` object shows `"state": "loaded"`, with no `reason`. If it shows `"state": "missing"`, place real Whisper `small` weights (CTranslate2 format: `model.bin`, `config.json`, `vocabulary.*`) under `ASKWELL_MODELS_DIR/whisper-small/` per `M6-AUDIO-DEPLOY-125`'s walkthrough, then `podman compose restart voice` and recheck. Nothing past this point can be exercised for real without this — stop and note it in your results rather than guessing at the outcome.

### 3. Record three short test clips

Using any recorder, save three short `.wav` (or similar) files:

- **`question.wav`** — a few seconds of you asking a real English question about something in your library, for example *"What is the notice period?"* if you have a document that mentions one, or any short English sentence otherwise.
- **`quiet.wav`** — the same kind of sentence, spoken deliberately quietly or from across the room.
- **`french.wav`** (or any non-English language you can manage a sentence in) — a short sentence in that language.

Convert each to the raw format the voice channel expects — 16 kHz, mono, 16-bit signed little-endian PCM, no header:

```
ffmpeg -i question.wav -f s16le -acodec pcm_s16le -ar 16000 -ac 1 question.pcm
ffmpeg -i quiet.wav    -f s16le -acodec pcm_s16le -ar 16000 -ac 1 quiet.pcm
ffmpeg -i french.wav   -f s16le -acodec pcm_s16le -ar 16000 -ac 1 french.pcm
```

Copy all three into the `api` container:

```
podman cp question.pcm $(podman compose ps -q api):/tmp/question.pcm
podman cp quiet.pcm    $(podman compose ps -q api):/tmp/quiet.pcm
podman cp french.pcm   $(podman compose ps -q api):/tmp/french.pcm
```

### 4. Have a way to speak a real turn to the channel

Save this as `/tmp/voice_client.py` on your own machine, then copy it in — it streams a real `.pcm` file's bytes into the channel in chunks, sends `end`, and prints every event until the turn completes:

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
                print("audio bytes:", len(message))
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

### 5. Speak a real English question and get a transcript before any answer

```
podman compose exec api python3 /tmp/voice_client.py /tmp/question.pcm
```

**Expect, in order:**
- `turn: {'type': 'turn', 'turn_id': '<a uuid>'}`
- One or more `event: {'type': 'transcript', 'text': '...'}` lines whose text, joined together, reads back close to what you actually said.
- `event: {'type': 'confidence', 'value': <a number between 0 and 1>}`
- `event: {'type': 'status', 'status': 'completed'}`

No answer text and no synthesised audio appear — that is correct; this ticket produces a transcript, not an answer. **Record** the `turn_id` and the transcript text.

### 6. Confirm the transcript was stored with the turn

```
podman compose logs api | grep voice_turn_finished | tail -1
```

Then, using the `turn_id` from step 5:

```
scripts/dev.sh psql -c "select m.content from messages m join audit_interactions a on a.payload->>'turn_id' = '<turn_id-from-step-5>' order by m.id desc limit 1;"
```

**Expect:** the stored `content` matches the transcript printed in step 5, word for word — the same text that appeared on the wire is what got written to `messages`, not a re-derived or truncated copy.

### 7. Confirm the audit record carries a confidence measure, not the raw transcript twice

```
scripts/dev.sh psql -c "select payload from audit_interactions where payload->>'turn_id' = '<turn_id-from-step-5>';"
```

**Expect:** a JSON payload with `"status": "ok"`, a `"confidence_pct"` integer between 0 and 100, `"language": "en"`, and `"transcript_length"` matching the length of the transcript from step 5. The transcript text itself is not duplicated into the audit payload — only its length — which you can confirm by its absence from this row.

### 8. Speak quietly and confirm a low-confidence transcript, not silence

```
podman compose exec api python3 /tmp/voice_client.py /tmp/quiet.pcm
```

**Expect:** a `transcript` event still appears — some text, not nothing — followed by a `confidence` event whose value is noticeably lower than step 5's. This is the ticket's own edge case: quiet speech is transcribed at low confidence rather than discarded. If your quiet clip was quiet enough that Whisper's own no-speech detector dropped it entirely, you will see `status: completed` with no `transcript` or `confidence` event at all instead — that is the no-speech path (step 9), not a defect; re-record slightly louder and try again if you wanted to exercise this specific case.

### 9. Send silence and confirm no transcript, no stored turn

Create a silent clip and stream it:

```
ffmpeg -f lavfi -i anullsrc=r=16000:cl=mono -t 2 -f s16le -acodec pcm_s16le silence.pcm
podman cp silence.pcm $(podman compose ps -q api):/tmp/silence.pcm
podman compose exec api python3 /tmp/voice_client.py /tmp/silence.pcm
```

**Expect:** `turn:` line, then directly `event: {'type': 'status', 'status': 'completed'}` — no `transcript` or `confidence` event at all.

```
scripts/dev.sh psql -c "select count(*) from audit_interactions where payload->>'turn_id' = '<turn_id-from-this-step>';"
```

**Expect:** `0`. Background noise with no speech produces no interaction record at all, because nothing was asked.

### 10. Speak a non-English sentence and confirm the language verdict, not a garbled transcript

```
podman compose exec api python3 /tmp/voice_client.py /tmp/french.pcm
```

**Expect:**
- `event: {'type': 'language', 'language': '<detected language code, e.g. 'fr'>', 'supported': False}`
- No `transcript` or `confidence` event.
- `event: {'type': 'status', 'status': 'completed'}`

**Record** the `turn_id`, then check what was stored:

```
scripts/dev.sh psql -c "select content from messages m join audit_interactions a on a.payload->>'turn_id' = '<turn_id-from-this-step>' where m.conversation_id = a.payload->>'conversation_id' order by m.id desc limit 1;"
scripts/dev.sh psql -c "select payload from audit_interactions where payload->>'turn_id' = '<turn_id-from-this-step>';"
```

**Expect:** an empty-string `content` row (the turn is logged even though nothing intelligible was captured), and a payload with `"status": "unsupported_language"`, the detected `"language"`, and a `"language_probability_pct"`. Whisper never attempted an actual transcription of the non-English audio — there is no French (or other) text anywhere in the payload or the stored message, only the language verdict.

### 11. Confirm the exact English-only wording is not this ticket's job

There is no on-screen "Askwell only understands English" message yet — that copy is `M6-VUI-FE-135`'s. Step 10's `language` event is the whole of what this ticket delivers; do not report the absence of user-facing copy as a defect here.

### 12. Stop the voice container and confirm transcription fails loudly, not silently

```
podman compose stop voice
podman compose exec api python3 /tmp/voice_client.py /tmp/question.pcm
```

**Expect:** `turn:` line, then `event: {'type': 'status', 'status': 'failed'}` — no invented transcript, no `completed` status standing in for a request that never happened.

```
podman compose logs api | grep voice_turn_driver_failed | tail -1
```

**Expect:** a line naming the `turn_id` from this step. Bring the container back before continuing:

```
podman compose up -d voice
```

### 13. Confirm text asking still works, untouched

Open `http://127.0.0.1:8000` in a browser and ask a typed question against material you have already added.

**Expect:** the Ask screen behaves exactly as before — this transcription path is additive to the voice channel only.

---

## Known gaps

- **No microphone button, no Ask-screen voice mode.** `web/` has no voice UI at all (`M6-VUI-FE-135`), so this walkthrough drives the WebSocket directly with pre-recorded audio, the same way `M6-AUDIO-API-126`'s did with fake frames.
- **No English-only on-screen statement.** Step 10 confirms the `language` event carries the detected language; the copy shown to a user is a separate, later ticket. Do not report missing UI text as a defect of this ticket.
- **Answering the transcribed question is out of scope.** A turn ends the moment its transcript (or the lack of one) is settled; nothing here calls `askwell.ask` or produces an answer. That wiring is `M6-TTS-BE-130`'s dependency chain.
- **Turn detection (knowing when someone has stopped speaking) is not this ticket.** Every clip above is sent as one complete buffer followed by an explicit `end`, standing in for what Silero VAD (`M6-STT-BE-128`) will do automatically once it lands.
- **Audio is never retained.** Only the transcript is stored; a bad transcription from steps 5 or 8 cannot be replayed afterwards to diagnose why — this is a recorded trade-off (`docs/ux/voice.md` §7), not an oversight.
- **Confidence thresholds and low-confidence confirmation are not this ticket.** Step 8 shows a low number appear; deciding what counts as "low enough to ask before answering" is `M6-STT-FE-129`.
