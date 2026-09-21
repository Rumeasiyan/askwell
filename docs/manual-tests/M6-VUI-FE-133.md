# Manual test — M6-VUI-FE-133: Stop control, and deliberately no barge-in

## What this ticket built

`web/lib/voice.ts` gains `canStop` (true only while `state === "answering"`) and a
`stop_pressed` action on `nextVoiceStatus` that returns to idle with reason `VOICE_STOPPED_REASON`
("Stopped.") — inert everywhere else, including a second press once already idle.
`web/components/ask/voice-control.tsx`'s `MicControl` renders a **Stop** button only while
`canStop(status)` is true, and `handleStop` sends `{"type": "stop"}` on the socket, tears down
playback immediately (`teardownPlayback`, closing the `AudioContext`), and clears the latency
watch — all before waiting for any server acknowledgement. Server-side, `voice_channel.py`'s
`stop` control message sets `VoiceTurn.stop_requested`; `voice_tts.py`'s `_speak_answer` mirrors
that onto `AskTurn.stop_requested`, the same flag `askwell.ask`'s own token loop and
`POST /ask/{id}/stop` use, so the `messages` row is marked `partial = status == "stopped" or
truncated` regardless of whether the client that requested the stop was voice or text.
`statusLabel` keeps the partial answer visible with "Stopped." appended, never replacing it.
No barge-in exists anywhere in this path: `canStartCapture` only permits a new press from
`idle`, so a press while `answering` (or `listening`/`transcribing`) is a silent no-op.

**Same known limitation as every voice ticket since `M6-AUDIO-DEPLOY-125`**: Whisper and Kokoro
weights are not present in this environment, so a real spoken turn fails at transcription —
well before any answer text arrives, which means `answering` is never reached and the Stop
button never actually renders in this environment's live path. Part 3 below covers exactly what
that blocks and why the automated suite (Part 1) is the primary evidence for this ticket's core
behaviour, with Part 2 covering everything reachable live.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m6-vui-fe-133` (or later, once merged).
- A machine with a working microphone and a browser that grants it permission
  (`getUserMedia` requires `https:` or `localhost`/`127.0.0.1`).
- `podman compose up -d` — the full stack, not just `api`.
- After pulling code changes: `scripts/dev.sh build-api`, `scripts/dev.sh web-build`, then
  `podman compose up -d --force-recreate api` (`compose restart` reuses the old image).

## Part 1 — automated suite, read the output

```
scripts/dev.sh web-check
```

**What you should see:** typecheck, lint, build and the token/contrast/offline guards clean,
and `web/lib/voice.test.ts` passing, including this ticket's own cases: `canStartCapture` is
true only when idle; `canStop` is true only while answering; pressing stop while answering
returns idle with reason `"Stopped."`; pressing stop while idle, listening, or transcribing
changes nothing; a second stop press once already idle is inert; and pressing-and-holding the
mic while answering is blocked by the same `canStartCapture` guard (issue 463) — the "speaking
over the answer does nothing" acceptance criterion, since there is no `.test.tsx` harness here
to drive the rendered button itself (`docs/decisions.md`).

## Part 2 — cold start, everything reachable without real weights

1. With the stack up, open `http://127.0.0.1:8000/` in the browser.
   **What you should see:** the Ask screen loads — the first-run "Ask your own material" card
   if nothing has been added yet, otherwise the composer directly.

2. If the first-run card is showing, click **Add a source**, add one small `.txt` or `.md`
   file, and wait for the library to report it `ready`.
   **What you should see:** back on the Ask screen, the composer (text box, mic button, **Ask**
   button) is visible, with no **Stop** button next to the mic.

3. Look at the composer without touching the mic.
   **What you should see:** only the mic button is present. No **Stop** button renders at
   idle — matching `canStop(VOICE_IDLE) === false`.

4. Press and hold the mic button and keep it held while speaking a short sentence.
   **What you should see:** the label reads "Listening…" with the level meter moving and the
   elapsed timer counting up. Still no **Stop** button — `canStop` is false while `listening`.

5. While still holding the mic from step 4, without releasing it, try pressing the mic a second
   time or clicking anywhere else on the composer.
   **What you should see:** nothing changes — one held press is the only capture in progress,
   and there is nothing here for a second interaction to start.

6. Release the mic.
   **What you should see:** the label changes to "Transcribing…" briefly. Still no **Stop**
   button — `canStop` is false while `transcribing`.

7. While the label still reads "Transcribing…" (a narrow window, usually under a second here
   since there are no Whisper weights to actually transcribe against), press and hold the mic
   button again.
   **What you should see:** nothing happens — no new "Listening…" state starts, no second
   socket opens, and the transcribing turn continues to its failure on its own. This is
   `canStartCapture` blocking a press outside `idle`, the same guard that later blocks a press
   during `answering` — visible here because `transcribing` is reachable live and `answering`
   is not.

8. Wait for the turn to finish.
   **What you should see:** the label settles on "Askwell could not answer that." (transcription
   failing for lack of weights, not this ticket's own code) and the mic returns to its
   press-and-hold idle label. No **Stop** button was visible at any point in this walkthrough,
   consistent with the answer never having started.

9. Immediately press and hold the mic again and ask a different short question.
   **What you should see:** a fresh "Listening…" cycle starts right away — idle accepts a new
   turn immediately, with nothing left over from the previous one (no stale transcript or
   answer text bleeding into the new attempt).

## Part 3 — what Parts 1–2 do not, and cannot, show here

The ticket's acceptance criteria center on the `answering` state: the Stop button rendering
while an answer is being generated or spoken, a press there ending audio and generation
promptly, the partial answer being kept and marked, and speaking over a running answer doing
nothing. None of this is reachable through the running stack in this environment, because
`build_tts_driver`'s real driver (`api/src/askwell/voice_tts.py`) always fails at the
transcription step without Whisper weights present (`M6-AUDIO-DEPLOY-125`'s known gap) — the
turn never emits a `text` event, so `nextVoiceStatus` never transitions to `answering`, so the
Stop button's own render condition (`canStop(status)`) is never true in the browser here.

What stands in for it instead, and what it does and does not cover:

- **`canStop`, `stop_pressed`, and the "speaking over the answer" guard** are exercised directly
  as pure functions in Part 1 (`web/lib/voice.test.ts`) — this is complete coverage of the state
  machine itself, just not of the rendered button or the real audio teardown.
- **`handleStop`'s side effects** — sending `{"type": "stop"}`, calling `teardownPlayback` to
  discard whatever `AudioContext` buffer is queued or playing, and closing the socket — have no
  automated coverage at all (`voice-control.tsx` has no test harness; see `docs/decisions.md`
  for why) and were not exercised live here either. Reading the code
  (`web/components/ask/voice-control.tsx:424-434`) is the only verification performed.
- **The server-side partial marking** (`ask_turn.stop_requested` → `askwell.ask`'s
  `partial = status == "stopped" or truncated` on the `messages` row) was verified by reading
  `api/src/askwell/voice_tts.py:290-296` and `api/src/askwell/ask.py`, not by watching a real
  stopped turn's row in the database — that would need a real answer in flight to stop.
- **The two edge cases that depend on exact timing** — stop pressed as the answer is completing
  (kept, not marked partial) and stop pressed during synthesis but after generation finished
  (only audio stops) — have no coverage here beyond the code read above. They depend on the
  server's token loop and TTS queue racing against a real stop message, which needs a real
  answer actually streaming.
- **The wire's own honesty gap** (`web/lib/voice.ts`'s `VOICE_STOPPED_REASON` comment, issue
  471): the voice channel's `status` event only ever carries `"completed"` or `"failed"`
  (`voice_tts.py`: `turn.status = "failed" if ask_turn.status == "failed" else "completed"`),
  never a distinct "stopped" value — so the client's "Stopped." label is a true statement about
  what the user did, not a claim about what the server's event said. This was confirmed by
  reading the code, not by observing the wire live.

## Known gaps

- The Stop button's actual rendering and click handling were never observed running in a
  browser — only reasoned about from code and covered by pure-function unit tests, per Part 3
  above. Confirming this ticket's core UI behaviour needs Whisper and Kokoro weights present
  (`M6-AUDIO-DEPLOY-125`), same gap carried by every voice ticket to date.
- The two timing-dependent edge cases (stop as the answer completes; stop during synthesis but
  after generation) are unverified beyond a code read — they need a real in-flight answer to
  race a stop message against.
- The audit/database side of "the stop is recorded on the interaction" was verified by reading
  `askwell.ask`'s partial-marking logic, not by inspecting an actual stopped row.
- Local stop counter, if the ticket intends one beyond the existing latency-miss counter, was
  not found in `web/lib/voice.ts` — only `recordVoiceLatencyBudgetMiss`/
  `getVoiceLatencyBudgetMissCount` exist. Nothing in this ticket's diff adds a distinct local
  tally of stops, so "Analytics Events: Local counter of stops" in the ticket has no
  corresponding code; flagged rather than assumed implemented.
