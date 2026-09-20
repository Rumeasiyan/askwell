# Manual test — M6-AUDIO-API-126, the voice WebSocket transport

**Ticket:** `M6-AUDIO-API-126` — bidirectional audio transport, for voice only
**Version under test:** `0.5.2`
**Time:** about 20 minutes
**Who can run it:** anyone who can paste lines into a terminal. No microphone or speaker needed — see "Where this stops on purpose" below.

**What is being checked.** A WebSocket at `/voice/ws` on the `api` container that carries audio in, audio out, transcript and text on one connection; a dropped connection can reconnect and recover a turn that finished on the server; and a slow reader gets backpressure rather than the server's memory growing.

**Where this stops on purpose.** There is no microphone button and no Ask-screen voice mode yet — `web/` has no voice UI, and `M6-STT-BE-127`/`M6-TTS-BE-130` (transcription and synthesis) have not landed. Today the channel accepts audio, applies backpressure, and ends the turn the moment the client signals end-of-speech — it never invents a transcript or an answer. That means "speak a question and hear it answered", the scenario in the ticket's own testing notes, is not something this build can do yet; this walkthrough drives the channel directly, from a terminal, the same way `M6-AUDIO-DEPLOY-125`'s walkthrough drove the voice container's `/health` directly because nothing else existed to route through.

---

## Before you start

You need a terminal and Podman. You do not need Python on the host, a microphone, or real Whisper/Kokoro weights.

### 1. Confirm the stack builds and comes up

```
scripts/dev.sh build-api
podman compose up -d
podman compose ps
```

**Expect:** an `api` row, state `Up`. (`voice` may show `starting` or restarting if you have no model weights in place — that is `M6-AUDIO-DEPLOY-125`'s concern, not this one; this channel is mounted on `api`, not `voice`, and does not depend on the voice container being healthy.)

### 2. Have a way to speak to the channel

The channel is a WebSocket, and there is no browser control for it yet, so this walkthrough talks to it with a small Python script run **inside the `api` container**, where the `websockets` package Askwell already depends on is installed — not on the host, whose Python (3.14) is not what this project targets.

Save this as `/tmp/voice_client.py` on your own machine, then copy it in:

```python
import asyncio
import json
import sys

import websockets

TURN_ID = sys.argv[1] if len(sys.argv) > 1 else None
URI = "ws://127.0.0.1:8000/voice/ws" + (f"?turn_id={TURN_ID}" if TURN_ID else "")


async def main() -> None:
    async with websockets.connect(URI) as ws:
        first = json.loads(await ws.recv())
        print("turn:", first)

        if TURN_ID is None:
            for i in range(3):
                await ws.send(f"frame-{i}".encode())
            await ws.send(json.dumps({"type": "end"}))

        while True:
            message = await ws.recv()
            if isinstance(message, bytes):
                print("audio bytes:", message)
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

### 3. Connect and speak a short question

```
podman compose exec api python3 /tmp/voice_client.py
```

**Expect**, in order:
- `turn: {'type': 'turn', 'turn_id': '<a uuid>'}` — printed immediately on connecting.
- `event: {'type': 'status', 'status': 'completed'}` — printed shortly after the script sends its three fake audio frames and the `end` control message.

**Record** the `turn_id` printed — you need it for step 5. No `transcript`, `text` or `audio bytes` lines appear, and that is correct today: nothing behind this channel produces them yet (see "Where this stops on purpose").

### 4. Confirm the turn was logged with a transcript field, even though it is empty

```
podman compose logs api | grep voice_turn_finished | tail -1
```

**Expect:** a line naming the `turn_id` from step 3 and `status=completed`. This is the same audit path every other turn goes through — voice turns are not a separate, unlogged thing.

### 5. Reconnect after the turn already finished

Using the `turn_id` from step 3:

```
podman compose exec api python3 /tmp/voice_client.py <turn_id-from-step-3>
```

**Expect:**
- `turn: {'type': 'turn', 'turn_id': '<the same uuid>'}` — same id back, not a new one.
- `event: {'type': 'status', 'status': 'completed'}` — arrives immediately, with no audio bytes at all, because the turn had already finished and its queue's closing sentinel was already consumed by the first connection. This is "if generation completed server-side, the answer appears in the conversation" (the ticket's acceptance criterion) holding for a turn with nothing to replay.

### 6. Reconnect mid-turn — the connection drops before you finish speaking

This stands in for the ticket's wifi-blip scenario. Toggling the host's real network interface would take your whole machine offline mid-test, which is disproportionate for what this checks; closing the WebSocket partway through has the same effect from the server's point of view, since the turn lives independently of any one connection (see `api/src/askwell/voice_channel.py`'s module docstring).

Start a connection, send frames, and disconnect **before** sending `end` — for example, run this and press Ctrl-C after the `turn:` line prints but before it would otherwise finish:

```
podman compose exec api python3 -c "
import asyncio, json, websockets

async def main():
    async with websockets.connect('ws://127.0.0.1:8000/voice/ws') as ws:
        first = json.loads(await ws.recv())
        print('turn:', first)
        await ws.send(b'frame-1')
        await ws.send(b'frame-2')
        print('sent 2 frames, not ending — Ctrl-C now')
        await asyncio.sleep(30)

asyncio.run(main())
"
```

**Record** the `turn_id`, then Ctrl-C once you see "sent 2 frames".

Reconnect to the same turn and finish it:

```
podman compose exec api python3 /tmp/voice_client.py <turn_id-from-this-step>
```

Note this reconnect will hang, because the second script (unlike the first) sends no new frames — the turn is still `listening`, waiting on audio that the dropped connection never finished sending. That itself is the point: reconnecting **resumes the same turn** rather than starting a fresh one, which you can confirm from the `turn_id` matching. Press Ctrl-C to end the hung script, then send an explicit end so the turn does not sit open indefinitely:

```
podman compose exec api python3 -c "
import asyncio, json, websockets

async def main():
    async with websockets.connect('ws://127.0.0.1:8000/voice/ws?turn_id=<turn_id-from-this-step>') as ws:
        print('turn:', json.loads(await ws.recv()))
        await ws.send(json.dumps({'type': 'end'}))
        print('status:', json.loads(await ws.recv()))

asyncio.run(main())
"
```

**Expect:** the same `turn_id` throughout, and a final `status: completed`.

### 7. Confirm a spoken "stop" ends the turn as failed, not completed

```
podman compose exec api python3 -c "
import asyncio, json, websockets

async def main():
    async with websockets.connect('ws://127.0.0.1:8000/voice/ws') as ws:
        print('turn:', json.loads(await ws.recv()))
        await ws.send(json.dumps({'type': 'stop'}))
        print('status:', json.loads(await ws.recv()))

asyncio.run(main())
"
```

**Expect:** `status: {'type': 'status', 'status': 'failed'}`.

### 8. Confirm the channel is bound to loopback, like every other surface

```
scripts/verify-localhost-binding.sh
```

**Expect:** all checks pass, including that port 8000 (which `/voice/ws` is mounted on, alongside every other HTTP surface) is bound to `127.0.0.1` only. This is the ticket's own validation rule — "the channel is bound to localhost like every other surface" — and it is enforced by the same compose-level binding as the rest of `api`, not by anything specific to this channel, which is exactly why one shared script checks it rather than this ticket adding its own.

### 9. Confirm text asking still works, untouched

Open `http://127.0.0.1:8000` in a browser and ask a question as usual.

**Expect:** the Ask screen behaves exactly as before — this channel is additive; nothing about `askwell.ask`'s own SSE stream changed.

---

## Known gaps

- **No transcript, no answer text, no synthesised audio — ever, in this build.** `_default_driver` (`api/src/askwell/voice_channel.py`) only drains incoming audio and ends the turn; it has nothing to hand audio to until `M6-STT-BE-127` and `M6-TTS-BE-130` land. Do not report the absence of a transcript or spoken answer as a defect of this ticket.
- **No voice UI.** There is no microphone control anywhere in `web/`. This walkthrough talks to the WebSocket directly because there is nothing else built yet to route through, the same situation `M6-AUDIO-DEPLOY-125`'s walkthrough was in for the voice container's health endpoint.
- **Backpressure (step in scope, not exercised above) is not manually observable against `_default_driver`.** The default driver drains `audio_in` as fast as frames arrive, so nothing stalls the producer in this build; the automated test (`api/tests/test_voice_channel.py::test_audio_in_backpressure_blocks_the_producer_rather_than_growing_memory`) exercises it directly against the queue with a deliberately slow consumer, which is the only way to see it before a real, slower driver exists.
- **Streaming a very long spoken question as separate chunks (not one buffered blob) is likewise not distinguishable from outside with `_default_driver`**, since nothing downstream reports per-chunk receipt yet. Covered by `test_long_input_streams_as_separate_chunks_not_one_buffered_blob` in the same file.
- **Audio is never persisted**, by design — nothing here writes to `conversations` or `messages`. There is nothing to check for in the database yet; that lands once a real transcript and answer exist to store.
