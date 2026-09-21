# Manual test — M6-VUI-FE-132: Voice control in the composer with a live level meter

## What this ticket built

On top of `M6-VUI-FE-128a`'s mic capture and four-state machine, `web/components/ask/voice-control.tsx`
now shows a **live level meter** and **elapsed time** while listening, and swaps the tooltip
copy to "Your microphone appears silent — check that it isn't muted." when the mic has produced
no audible buffer for 1.5s straight (`MIC_SILENCE_WARNING_MS`, `web/lib/voice.ts`). The meter is
`rmsLevel` of the same capture buffer already being sent over the socket — no second signal
path — rendered as a 40×4px track (`.ask-mic-meter` / `.ask-mic-meter-fill`, `web/app/globals.css`)
scaled by `transform: scaleX()`. Elapsed time is a plain wall-clock diff, ticked every 200ms,
formatted `m:ss` uncapped (`formatElapsed`).

**Same known limitation as `M6-VUI-FE-128a`, carried from `M6-AUDIO-DEPLOY-125`**: Whisper and
Kokoro weights are not present in this environment, so a real spoken turn reaches the backend,
fails at transcription, and returns to idle with "Askwell could not answer that." The meter,
elapsed time and silence detection all sit entirely on the client side of that boundary, so
Part 2 exercises all of this ticket's acceptance criteria in full despite the missing weights.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m6-vui-fe-132`.
- A machine with a working microphone and a browser that will grant it permission
  (`getUserMedia` requires either `https:` or `localhost`/`127.0.0.1`).
- `podman compose up -d` — bring up the full stack, not just `api`.
- After pulling code changes: `scripts/dev.sh build-api`, `scripts/dev.sh web-build`, then
  `podman compose up -d --force-recreate api` (`compose restart` reuses the existing image and
  will not pick up a rebuild).

## Part 1 — automated suite, read the output

```
scripts/dev.sh web-check
```

**What you should see:** typecheck, lint, build and the token/contrast/offline guards clean,
and `web/lib/voice.test.ts` passing, including cases for `rmsLevel` (silence, full-scale, mixed
buffers), `micAppearsSilent` (below/at/above `MIC_SILENCE_WARNING_MS`), and `formatElapsed`
(zero, sub-minute, multi-hour uncapped).

## Part 2 — cold start, click-through with a real microphone

1. With the stack up, open `http://127.0.0.1:8000/` in the browser.
   **What you should see:** the Ask screen loads — either the first-run "Ask your own material"
   card if nothing has been added yet, or the composer directly if a corpus already exists.

2. If the first-run card is showing, click **Add a source**, add any one file (a `.txt` or
   `.md` file is enough), and wait for the library to report it `ready`.
   **What you should see:** back on the Ask screen, the composer — a text box with a mic
   button and an "Ask" button beside it — is visible. The rest of the conversation area (empty
   state or prior turns) is unchanged and still visible above the composer.

3. Press and hold the mic button, and grant microphone permission if prompted.
   **What you should see:** within well under a second the label changes to "Listening…", the
   button gains a `data-voice-state="listening"` appearance, and **immediately beside the
   label a thin horizontal bar (the level meter) and a running timer reading `0:00` appear** —
   this is the ticket's own addition over `M6-VUI-FE-128a`. Nothing else on screen changes:
   the conversation above the composer, any prior turns, and the text box itself remain exactly
   as before.

4. While still holding the button, speak at normal volume for several seconds, varying your
   volume — quiet, then loud, then quiet again.
   **What you should see:** the meter's fill visibly grows and shrinks in step with your voice
   — near-empty on quiet syllables and near-full on loud ones — updating smoothly rather than
   in visible steps (it is driven by the ~11 capture buffers per second already being sent).
   The timer keeps counting up (`0:01`, `0:02`, …) throughout, including during any pause
   between words.

5. Keep holding the button for at least 65 seconds without releasing.
   **What you should see:** the timer passes `0:59` and continues to `1:00`, `1:01`, etc. — it
   does not reset to `0:00` or roll over oddly at the minute mark. This is the ticket's own
   long-listening edge case.

6. Release the mouse button.
   **What you should see:** the meter and timer both disappear immediately (they are
   listening-only indicators), and the label changes to "Transcribing…" exactly as in
   `M6-VUI-FE-128a`.

7. Wait a few seconds.
   **What you should see, given no Whisper weights in this environment:** the label settles on
   "Askwell could not answer that." and the button returns to idle. Confirm the conversation
   area above the composer was never hidden or replaced at any point during steps 3–7 — this
   ticket's own acceptance criterion that voice never takes over the screen.

8. Type a question into the text box directly, ignoring voice entirely, and press **Ask**.
   **What you should see:** the transcript (your typed question) and the answer appear in the
   conversation exactly as any typed exchange always has — confirming voice's presence changes
   nothing about the typed path, and that when a voice turn does succeed on a deployment with
   real weights, the same rendering path is what would show it (per `M6-VUI-FE-128a`'s own
   deferral of turn-list integration to issue #460 — see Known gaps below).

## Part 3 — muted microphone and device switch

9. Press and hold the mic button to start listening, then mute the microphone at the **system**
   level (not the browser) — on Linux, via the system volume mixer's input mute; on macOS, System
   Settings → Sound → Input, drag input volume to zero or use a hardware mute key; on Windows,
   the taskbar sound icon → input device → mute.
   **What you should see:** within about 1.5 seconds the meter's fill drops to and stays at
   zero, and the label changes to "Your microphone appears silent — check that it isn't muted."
   — not a continued claim of "Listening…". The timer keeps counting throughout; muting does
   not stop or reset it.

10. Unmute the microphone while still holding the button, then speak.
    **What you should see:** the meter responds again and the label returns to "Listening…"
    within a moment — the silence state is not sticky once real audio resumes.

11. Release the button to clean up, then, on a machine with more than one audio input device
    available, press and hold the mic button again, speak briefly, and while still holding it,
    switch the OS's default microphone to a different input device (via the system's own sound
    settings, not anything inside Askwell — there is no in-app device picker per the ticket's
    own known gap).
    **What you should see:** the meter continues to respond to whichever device the OS now
    treats as default and picks up sound from it — `getUserMedia`'s stream follows the OS
    default, and the meter reads directly from the same stream. (If only one input device is
    available, this step cannot be exercised — note it as skipped rather than failed.)

12. Release the button.
    **What you should see:** meter and timer disappear, label proceeds through "Transcribing…"
    to the same honest-failure or real-answer outcome as steps 6–8.

## What this does not prove

Whether a real transcript and a real spoken answer actually arrive — that needs Whisper and
Kokoro weights present, which this environment does not have (`M6-AUDIO-DEPLOY-125`'s known
gap). Low-confidence confirmation (`M6-STT-FE-129`), the stop control and the latency indicator
(`M6-VUI-FE-134`/`135`) are separate tickets and not exercised here beyond what already exists
from prior tickets.

## Known gaps

- **No hands-free toggle.** The ticket text names one in scope, but `docs/ux/voice.md` §7
  settles push-to-talk as the only mode for v1 and the code (`voice-control.tsx`) implements
  only press-and-hold. There is no toggle to click and none is a defect here — it is a standing
  product decision, not something this ticket left unbuilt.
- **No live weights in this environment.** A real transcript and spoken answer can only be
  seen on a deployment with Whisper and Kokoro weights present.
- **No device picker inside Askwell.** The system's own default input device is what the meter
  and capture follow; there is nothing to select from within the app, per the ticket's own
  stated assumption.
- **The transcript and answer render only inside the mic control's own tooltip label, not into
  the conversation turn list.** Folding a voice turn into the same turn list `AskProvider`
  tracks is deferred to its own ticket (issue #460), unchanged by this ticket.
- **No stop control and no latency indicator** — `M6-VUI-FE-134`/`135`, not built by this
  ticket.
