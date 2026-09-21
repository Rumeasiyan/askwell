# Manual test — M6-STT-FE-129: Low confidence — show the transcript and confirm before answering

## What this ticket built

Backend (`api/src/askwell/voice_stt.py`): once Whisper returns a transcript with a `confidence`
below `Settings.stt_confirmation_confidence_threshold` (`api/src/askwell/config.py`, default
`0.6`), the driver calls `turn.request_confirmation()` and awaits the returned future instead of
storing and answering immediately. `VoiceTurn.request_confirmation` (in `voice_channel.py`) emits
a `{"type": "confirmation", "required": true}` event over the socket. The client resolves the
future by sending `{"type": "confirm"}` or `{"type": "edit", "text": ...}`; if neither arrives
within `Settings.stt_confirmation_timeout_seconds` (default `120`), the `asyncio.wait_for` times
out, `turn.confirmation_pending` is cleared, and the turn ends as `completed` with **nothing
stored** — no `messages` row, no audit record (`AGENTS.md` §3 C6: only a confirmed or edited
transcript is recorded). At or above the threshold, the transcript is stored and answered exactly
as before this ticket.

Frontend (`web/lib/voice.ts`, `web/components/ask/voice-control.tsx`): `nextFromChannelEvent`
gains the `confirmation` case, moving `transcribing` → `confirming`. `MicControl` renders an
editable `<textarea>` (seeded from the live `transcript` state) plus **Confirm** and **Speak
again** buttons while `confirming`. `handleConfirm` compares the current field value against
`confirmOriginalRef` (captured the instant the `confirmation` event arrived) — unchanged sends
`{"type": "confirm"}`, changed sends `{"type": "edit", "text": ...}` — and calls
`recordVoiceConfirmation()` either way (the local-only counter, C1: nothing transmitted).
**Speak again** abandons the held turn client-side (closes the socket, resets to idle) rather than
sending anything — the same outcome as the server-side timeout, just user-initiated. If the user
ignores the confirmation and the server times out, the `status: "completed"` event arrives with
`reason: null`; `statusLabel`'s idle branch keeps the transcript visible (`docs/ux/voice.md` §5,
"retained in the composer") rather than reverting to the bare "Press and hold to speak" prompt.
There is no setting anywhere that disables the confirmation outright — `stt_confirmation_
confidence_threshold` only moves where it fires, matching the ticket's own validation rule.

**Same known limitation as every voice ticket since `M6-AUDIO-DEPLOY-125`**: Whisper and Kokoro
weights are not present in this environment, so a real spoken turn fails at transcription before
any `confidence` value — or `confirmation` event — is ever produced. The `confirming` state and
everything it renders is therefore not reachable live here. Part 1 (the automated suite) is the
primary evidence for the state machine and counter; Part 2 covers what is reachable live; Part 3
states plainly what neither can show.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m6-stt-fe-129` (or later, once merged).
- A machine with a working microphone and a browser that grants it permission (`getUserMedia`
  requires `https:` or `localhost`/`127.0.0.1`).
- `podman compose up -d` — the full stack, not just `api`.
- After pulling code changes: `scripts/dev.sh build-api`, `scripts/dev.sh web-build`, then
  `podman compose up -d --force-recreate api` (`compose restart` reuses the old image).

## Part 1 — automated suite, read the output

```
scripts/dev.sh web-check
scripts/dev.sh test
```

**What you should see in `web-check`:** typecheck, lint, build and the token/contrast/offline
guards clean, and `web/lib/voice.test.ts` passing, including this ticket's own cases: a
`confirmation` event with `required: true` moves `transcribing` → `confirming`; the first `text`
delta moves `confirming` → `answering` the same way it does from any other state; a `status:
"completed"` event while `confirming` (the walked-away timeout) returns to idle with `reason:
null` — leaving `statusLabel` to keep showing the retained transcript; and the confirmation
counter (`recordVoiceConfirmation` / `getVoiceConfirmationCount` /
`resetVoiceConfirmationCountForTests`) increments correctly.

**What you should see in `test`:** `api/tests/test_voice_stt.py` passing — including the
below-threshold path holding the turn on `request_confirmation`, `confirm` and `edit` both
resolving it and storing the resulting text, and the timeout path storing nothing and returning
`completed`.

## Part 2 — cold start, everything reachable without real weights

1. With the stack up, open `http://127.0.0.1:8000/` in the browser.
   **What you should see:** the Ask screen loads — the first-run "Ask your own material" card if
   nothing has been added yet, otherwise the composer directly.

2. If the first-run card is showing, click **Add a source**, add one small `.txt` or `.md` file,
   and wait for the library to report it `ready`.
   **What you should see:** back on the Ask screen, the composer (text box, mic button, **Ask**
   button) is visible, with no confirmation textarea or **Confirm**/**Speak again** buttons.

3. Press and hold the mic button and speak a short sentence, then release.
   **What you should see:** "Listening…" with the level meter moving while held, then briefly
   "Transcribing…" on release. No confirmation box appears yet — `confirming` is not reached
   until a `confirmation` event arrives.

4. Wait for the turn to finish.
   **What you should see:** the label settles on "Askwell could not answer that." — transcription
   failing for lack of Whisper weights (`M6-AUDIO-DEPLOY-125`'s known gap), not this ticket's own
   code — and the mic returns to its press-and-hold idle label. No confirmation textarea was ever
   shown, consistent with no `confidence` value ever having been produced to compare against the
   threshold.

5. Immediately press and hold the mic again and speak a different short question.
   **What you should see:** a fresh "Listening…" cycle starts right away, with nothing left over
   from the previous attempt (no stale transcript or confirmation UI bleeding into the new one).

## Part 3 — what Parts 1–2 do not, and cannot, show here

The ticket's acceptance criteria center on the `confirming` state: a low-confidence transcript
shown with a confirmation before any answer, a confident transcript proceeding directly, editing
the transcript before confirming, "speak again" replacing it, and an ignored confirmation
returning to idle with the transcript retained. None of this is reachable through the running
stack in this environment, because `build_stt_driver`'s real driver always fails at the
transcription step without Whisper weights present — the turn never reaches a `confidence` value,
so `nextFromChannelEvent`'s `confirmation` case is never triggered and the textarea's render
condition (`status.state === "confirming"`) is never true in the browser here.

What stands in for it instead, and what it does and does not cover:

- **The confidence-threshold branch itself** (`confidence < settings.stt_confirmation_confidence_
  threshold` → `request_confirmation` → `asyncio.wait_for`) is exercised directly in
  `api/tests/test_voice_stt.py` with a faked `/transcribe` response, covering both branches
  (above/below threshold) and both resolutions (`confirm`/`edit`) plus the timeout. This is
  complete coverage of the server-side gate, just not of a real Whisper confidence score against
  real garbled speech.
- **The `confirming` UI itself** — the editable textarea, the **Confirm**/**Speak again** buttons,
  `handleConfirm`'s `confirm`-vs-`edit` branch, `handleSpeakAgain`'s socket close — has no
  automated coverage beyond the state-machine transitions in `voice.test.ts`
  (`voice-control.tsx` has no rendered-component test harness; see `docs/decisions.md`). Reading
  `web/components/ask/voice-control.tsx:552-583` is the verification performed for the button
  wiring.
- **"Editing is the escape" for a genuinely unusual transcript** (the ticket's own edge case, e.g.
  a reference number transcribed wrong): the textarea is a plain, unrestricted `<textarea>` bound
  to the same `transcript` state shown elsewhere, so any text is a valid edit — verified by
  reading the code, not by typing a real reference number into a real low-confidence transcript.
- **The walked-away timeout's visible effect** — the confirmation box disappearing at
  `stt_confirmation_timeout_seconds` (120s default) with the transcript retained as plain text —
  was exercised at the state-machine level (`voice.test.ts`'s "status completed while confirming"
  case) and by reading `statusLabel`'s idle branch
  (`web/components/ask/voice-control.tsx:722-733`), not by actually waiting 120 seconds against a
  real held turn in the browser.
- **The default threshold's real-world tuning** — whether `0.6` actually makes confirmation
  uncommon, the ticket's own stated Assumption — cannot be assessed at all without real Whisper
  confidence scores from real speech, which this environment cannot produce.

## Known gaps

- The `confirming` state's entire UI — textarea, Confirm, Speak again, and the transcript-retained
  idle state after a timeout — was never observed rendering or responding to a click in a browser
  here. Confirming this ticket's core behaviour live needs Whisper and Kokoro weights present
  (`M6-AUDIO-DEPLOY-125`), the same gap carried by every voice ticket to date.
- The 120-second walked-away timeout was verified by code read and by the instantaneous
  state-machine test case, not by an actual elapsed wait against a live held turn.
- No per-word confidence exists (ticket's own Out of Scope) — the confirmation is all-or-nothing
  per turn, not flagged per word, and nothing here should be read as a defect for that.
- The default threshold (`0.6`) and timeout (`120s`) are, by the ticket's own admission, "a guess
  until real use" — not verified against real usage in this pass.
