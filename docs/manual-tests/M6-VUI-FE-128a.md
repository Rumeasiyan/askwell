# Manual test — M6-VUI-FE-128a: Mic capture, the voice socket client, and the composer's base voice states

## What this ticket built

`web/lib/voice.ts` (pure wire parsing, the four-state machine, PCM conversion) and
`web/components/ask/voice-control.tsx` (`MicControl`, replacing the permanently-disabled
Phase 1 stub in `ask-screen.tsx`). Pressing and holding the mic button now opens a real
`WebSocket` to `askwell.voice_channel`'s `/voice/ws`, streams 16 kHz mono PCM16 audio captured
with `getUserMedia`, and drives the composer through `idle → listening → transcribing →
answering`, all observable in the button's own tooltip text and `data-voice-state` attribute.

**Known limitation going in, carried from every voice ticket since `M6-AUDIO-DEPLOY-125`**:
Whisper and Kokoro weights are not present in this environment (C1 forbids fetching them here),
so a real spoken turn will reach the backend, fail at transcription, and the composer will
return to idle with **"Askwell could not answer that."** rather than showing a transcript. Part
2 below still exercises the full frontend path — capture, socket, all four states except the
tail of `answering` — against that honest failure, and Part 3 covers what the missing weights
make impossible to click through live.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m6-vui-fe-128a`.
- A machine with a working microphone and a browser that will grant it permission
  (`getUserMedia` requires either `https:` or `localhost`/`127.0.0.1` — the stack's own address
  qualifies).
- `podman compose up -d` — bring up the full stack, not just `api`.
- After pulling code changes: `scripts/dev.sh build-api`, `scripts/dev.sh web-build`, then
  `podman compose up -d --force-recreate api` (`compose restart` reuses the existing image and
  will not pick up a rebuild).

## Part 1 — automated suite, read the output

```
scripts/dev.sh web-check
```

**What you should see:** typecheck, lint, build and the token/contrast/offline guards all
clean, and `web/lib/voice.test.ts`'s cases passing — every wire-event shape parses (or returns
`null` for garbage), `voiceSocketUrl` upgrades `http:`/`https:` to `ws:`/`wss:` correctly, and
`nextVoiceStatus` covers every transition this ticket's acceptance criteria name: permission
denied and no-device both land on idle with their own stated reason from any starting state, a
stray `capture_ended` with nothing actually listening changes nothing, a connection lost while
already idle is a no-op, and a `status: failed` event returns to idle with a reason rather than
hanging. At the time this was written: 324 web tests, 25 new for this ticket.

## Part 2 — cold start, click-through with a real microphone

1. With the stack up, open `http://127.0.0.1:8000/` in the browser.
   **What you should see:** the Ask screen loads — either the first-run "Ask your own material"
   card if nothing has been added yet, or the composer directly if a corpus already exists. The
   micro-line at the top reads "Askwell 0.5.x · nothing leaves this machine".

2. If the first-run card is showing, click **Add a source**, add any one file (a `.txt` or
   `.md` file is enough), and wait for the library to report it `ready` before continuing — the
   voice turn needs something to search, though the acceptance criteria for this ticket land
   before that point.
   **What you should see:** back on the Ask screen, the composer (a text box with a mic button
   and an "Ask" button beside it) is now visible.

3. Look at the mic button, to the left of "Ask", without touching it.
   **What you should see:** a small microphone icon inside a round button, and beside it a
   tooltip-style label reading "Press and hold to speak". The button is not greyed out or
   marked disabled — this is the change this ticket makes: the Phase 1 stub always read
   `aria-disabled` and did nothing when clicked.

4. Press and hold the mouse button down on the mic icon.
   **What you should see:** the browser's own microphone permission prompt appears (first time
   only — a browser remembers the choice per site after that).

5. Click **Allow**.
   **What you should see:** the prompt closes and, within well under a second, the label beside
   the mic changes to "Listening…" and the button gains a visibly different appearance (a
   `data-voice-state="listening"` attribute drives `.ask-mic-control`'s styling in
   `web/app/globals.css`) — this is the composer's `listening` state, driven by capture actually
   starting (`onopen`/`capture_started`), not by the button press alone.

6. While still holding the button down, say a short sentence out loud.
   **What you should see:** nothing changes in the label yet — audio is streaming up over the
   socket, but nothing on the wire signals a transcript until you release.

7. Release the mouse button.
   **What you should see:** the label changes immediately to "Transcribing…" — this is the
   `transcribing` state, reached the instant capture actually stops
   (`capture_ended`/`teardownCapture`), not before. It stays on "Transcribing…" (or updates to
   partial transcript text, if any arrives) until the backend responds.

8. Wait a few seconds.
   **What you should see, given no Whisper weights in this environment (see the note above):**
   the label settles on **"Askwell could not answer that."** and the button returns to its
   idle appearance. This is the ticket's own acceptance criterion in its honest-failure form —
   the composer returns to idle with a stated reason rather than hanging in "Transcribing…"
   forever. **If Whisper and Kokoro weights are present** (a deployment where
   `M6-AUDIO-DEPLOY-125`'s known gap has since been closed), the label instead fills in with the
   live transcript, then the label changes to the streaming answer text as it arrives — the
   `answering` state — and spoken audio plays from the browser sentence by sentence.

9. Type a question into the text box directly, ignoring voice entirely, and press **Ask**.
   **What you should see:** the normal typed-question flow works exactly as before this ticket
   — voice failing or succeeding does not touch the text path.

## Part 3 — permission refusal, no device, and a dropped connection

10. In the browser's site settings for this address, revoke the microphone permission just
    granted (in Chrome: click the padlock/site-info icon in the address bar → Site settings →
    Microphone → Block; in Firefox: the same icon → Clear permission — the exact path varies by
    browser, but every browser has one). Reload the page.

11. Press and hold the mic button again.
    **What you should see:** either a fresh permission prompt (deny it this time) or, if the
    browser remembers the block, no prompt at all. Either way, within a moment the label reads
    **"Microphone access was denied. Allow it in your browser's site settings to use voice."**
    and the button sits at idle — never stuck showing "Listening…". Confirm the text box and
    **Ask** button still work normally; voice being refused does not disable typing.

12. On a machine or browser profile with no microphone attached at all (a VM with no audio
    device, or a browser configured to report none), press and hold the mic button.
    **What you should see:** the label reads **"No microphone was found on this device."** —
    distinct wording from permission denial, per `states-and-edge-cases.md` §5's own distinction
    between "nothing to grant" and "the browser can fix this".

13. Grant permission again, press and hold the mic button to start a turn, and — while the
    label still reads "Listening…" — stop the `voice` container to simulate the connection
    dropping mid-turn:
    ```
    podman compose stop voice
    ```
    Then release the mic button.
    **What you should see:** within a few seconds the socket's `onerror`/`onclose` fires, and
    the label reads **"The connection to Askwell was lost. Try again."** with the button back
    at idle — never left hanging in "Transcribing…". Bring the container back with
    `podman compose start voice` before continuing.

14. Press and hold the mic button, then — while still holding it — press and hold it again with
    a second finger/pointer, or otherwise attempt a second press before releasing the first.
    **What you should see:** nothing additional happens; the acceptance criterion is one socket
    per turn, and `startCapture`'s own idle-only guard (`web/components/ask/voice-control.tsx`)
    is what refuses the second press rather than opening a second connection. Confirm with the
    browser's network inspector (WebSocket frames tab) that only one `/voice/ws` connection
    exists for the attempt.

## What this does not prove

Whether a real transcript and a real spoken answer actually arrive correctly — that needs
Whisper and Kokoro weights present, which this environment does not have (`M6-AUDIO-DEPLOY-125`'s
known gap, carried by every voice ticket since). The low-confidence confirmation step
(`M6-STT-FE-129`), the level meter, the stop control, and the latency indicator
(`M6-VUI-FE-132` … `135`) are not built yet and are not exercised here.

## Known gaps

- **No live weights in this environment.** Steps 8 and the `answering` half of the state
  machine can only be watched as the honest failure path here; a deployment with real Whisper
  and Kokoro weights is needed to see a transcript and a spoken answer arrive for real.
- **Hands-free voice does not exist.** Push-to-talk is the only mode, settled in `voice.md` §7 —
  there is no toggle to test.
- **No level meter, no visible stop control, no latency indicator.** `voice.md` §3/§5 describe
  all three; this ticket deliberately does not build them (`M6-VUI-FE-132` through `135`). Their
  absence here is not a defect.
- **No low-confidence confirmation.** A transcript this ticket receives is used as-is; asking
  "did I hear that right?" before answering is `M6-STT-FE-129`.
- **The transcript and answer render only inside the mic control's own tooltip label, not into
  the conversation.** Folding a voice turn into the same turn list `AskProvider` tracks is a
  real design decision deferred to its own ticket
  ([issue #460](https://github.com/Rumeasiyan/askwell/issues/460)), not built here.
- **Non-English speech** (`voice.md` §5's own state) is not specifically handled by this
  ticket — Whisper's own language detection, once weights are present, is what a later ticket
  would need to surface distinctly.
