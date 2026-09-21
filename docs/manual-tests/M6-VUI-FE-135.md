# Manual test — M6-VUI-FE-135: Permission denied, non-English, abstention spoken in full

## What this ticket built

`web/lib/voice.ts` gains `micPermissionReason` (maps the Permissions API's `"denied"` state to
`MIC_PERMISSION_DENIED_REASON`, everything else to `null`), `VOICE_NON_ENGLISH_REASON`, and a
new branch in `nextFromChannelEvent` that ends the turn with that reason the instant a
`language` event arrives with `supported: false` — regardless of what state it interrupts.
`web/components/ask/voice-control.tsx`'s `MicControl` reads the mic's permission state
proactively on mount via `navigator.permissions.query({ name: "microphone" })`, wires
`PermissionStatus.onchange` so a grant after a prior denial clears `permissionReason` without a
reload, and — as a second, earlier guard ahead of `getUserMedia` — refuses to call
`getUserMedia` at all once `permissionReason` is set, showing the reason and instructions in the
mic's tooltip instead. A browser without Permissions API support for `"microphone"` falls back
to the pre-existing behaviour: the first `getUserMedia` rejection itself sets the same reason.

The abstention half of the ticket needed no new wire shape: an abstained turn already reaches
the client as an ordinary `text` event carrying `askwell.agent.abstain.compose_abstention`'s
string, synthesised and streamed exactly like any other answer. What this ticket actually fixes
is a real display bug in `statusLabel`: previously, only the *stopped* idle branch kept `answer`
visible, so a turn that finished normally — an abstention included — had its full text replaced
by the bare "Press and hold to speak" prompt the instant `status: completed` arrived. Now a
`reason: null` idle state (a turn that ended on its own, not by a stop) keeps showing `answer`
too, so the full text stays on screen exactly as long as there is nothing else for the mic
control to say instead.

**Same known limitation as every voice ticket since `M6-AUDIO-DEPLOY-125`**: Whisper and Kokoro
weights are not present in this environment, so a real spoken turn fails at transcription before
any `language` or `text` event is ever produced. That blocks the non-English and abstention
states from being observed live — Part 3 covers exactly what that costs and why the automated
suite (Part 1) plus the permission-denied walkthrough (Part 2, which needs no weights at all
since it never reaches the server) are the primary evidence here.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m6-vui-fe-135` (or later, once merged).
- A machine with a working microphone and a browser that grants it permission
  (`getUserMedia` requires `https:` or `localhost`/`127.0.0.1`). Chrome or Firefox — both expose
  `navigator.permissions.query({ name: "microphone" })` and let a site's mic permission be
  toggled from the browser's own site-settings UI without a reload.
- `podman compose up -d` — the full stack, not just `api`.
- After pulling code changes: `scripts/dev.sh build-api`, `scripts/dev.sh web-build`, then
  `podman compose up -d --force-recreate api` (`compose restart` reuses the old image).

## Part 1 — automated suite, read the output

```
scripts/dev.sh web-check
```

**What you should see:** typecheck, lint, build and the token/contrast/offline guards clean,
and `web/lib/voice.test.ts` passing, including this ticket's own cases: `micPermissionReason`
maps `"denied"` to `MIC_PERMISSION_DENIED_REASON` and `"granted"`/`"prompt"`/`null` to `null`; a
`language` event with `supported: false` ends the turn with `VOICE_NON_ENGLISH_REASON`
regardless of the state it interrupts (including mid-`listening`); and a `status: completed`
event arriving after a `language` event keeps the English-only reason rather than clearing it
back to idle-with-no-reason.

## Part 2 — cold start, permission denied and recovery (no weights needed)

This state never touches the server — it is pure browser permission plumbing — so it is fully
observable in this environment.

1. Open the browser's site settings and explicitly **block** microphone access for
   `127.0.0.1:8000` (or `localhost:8000`) before loading the app. In Chrome: address-bar padlock
   → **Site settings** → **Microphone** → **Block**. In Firefox: padlock → **Permissions** →
   uncheck/clear **Use the Microphone**, then set it to **Block**.

2. Open `http://127.0.0.1:8000/` in that browser.
   **What you should see:** the Ask screen loads (first-run "Add a source" card if the library
   is empty, otherwise the composer directly). If the library already has a ready source, the
   composer's mic button and tooltip are visible immediately.

3. Look at the mic control without pressing it.
   **What you should see:** the tooltip next to the mic reads "Microphone access was denied.
   Allow it in your browser's site settings to use voice." — not an error message, not a red
   banner. The mic button's `aria-disabled` is true (inspect via accessibility tree or DevTools:
   `aria-disabled="true"` on the button).

4. Press and hold the mic button.
   **What you should see:** nothing happens — no permission prompt appears a second time, no
   "Listening…" state starts. This is the ticket's own Out of Scope holding: one request, then
   the explanation, never a repeat prompt.

5. Without reloading the page, open the browser's site settings again and change the microphone
   permission for this site to **Allow**.
   **What you should see:** within a moment, the mic tooltip changes back to "Voice input — press
   and hold to speak" (or the composer's ordinary idle prompt) on its own — no page reload. This
   is `PermissionStatus.onchange` firing and clearing `permissionReason`.

6. Press and hold the mic button now.
   **What you should see:** the ordinary "Listening…" state starts, with the level meter moving
   — voice is usable again without a reload, confirming the edge case in the ticket's Acceptance
   Criteria.

7. Reload the page with the permission still set to **Allow**.
   **What you should see:** the composer loads directly into the normal idle state — no denial
   tooltip, since `micPermissionReason` reads `"granted"` as `null` on mount.

## Part 3 — what Part 1 does not, and cannot, show here: non-English and abstention

Both remaining states depend on a `language` or `text` event reaching the client from a real
transcription/generation pass on the server, which needs Whisper and Kokoro weights present
(`M6-AUDIO-DEPLOY-125`'s known gap). Without them, `askwell.voice_stt`'s real driver fails before
either event type is ever produced, so the browser mic control never leaves `transcribing`
before returning to idle with `VOICE_FAILED_REASON` ("Askwell could not answer that.") — the
same generic failure path every prior voice ticket has hit in this environment, not this
ticket's own code.

What stands in for it instead, and what it does and does not cover:

- **The `language`-event branch in `nextFromChannelEvent`** (ends any state with
  `VOICE_NON_ENGLISH_REASON` on `supported: false`, and is not overwritten by a later
  `status: completed`) is exercised directly as a pure function in Part 1
  (`web/lib/voice.test.ts` lines 179–205) — complete coverage of the state transition itself,
  just not of a real non-English utterance reaching the browser through the STT pipeline.
- **`statusLabel`'s fix for a normally-completed turn keeping `answer` visible** — the actual
  code change behind "abstention spoken in full, shown in full" — has no automated test in
  `voice.test.ts` covering the `MicControl` component's render output directly, since there is
  no `.test.tsx` harness for this file (`docs/decisions.md`, same gap noted in the
  `M6-VUI-FE-133` manual test). Verified here by reading
  `web/components/ask/voice-control.tsx:598-616`: the `reason === null && answer.trim() !== ""`
  branch returns `answer.trim()` unconditionally, with no truncation, ellipsis, or wording
  change from what `askwell.agent.abstain.compose_abstention` produced server-side.
- **Wording match between spoken and on-screen abstention** — the ticket's own Validation Rule —
  was verified by reading, not by listening: `api/src/askwell/voice_tts.py`'s sentence-synthesis
  path speaks the same `text` deltas the client also appends to `answer` and renders via
  `statusLabel`; there is exactly one string, never a separate "spoken" variant.
- **A partial answer's ungrounded part stated aloud, not glossed over** (the ticket's own edge
  case) depends on `askwell.ask`'s existing partial-answer composition, unchanged by this
  ticket — not independently re-verified here beyond confirming `statusLabel` does not special-
  case or trim it.
- **Voice abstentions recorded like any other interaction** (Audit / Logging Requirement) was
  not independently re-verified for the voice path specifically; `voice_tts.py` and `ask.py`
  write through the same `messages`/`audit_interactions` path documented in `M6-VUI-FE-133`'s
  manual test for the partial-answer case, and nothing in this ticket's diff touches audit
  writing.

## Known gaps

- Non-English speech and abstention-spoken-in-full were never observed running end-to-end in a
  browser against a real STT/TTS pass — only reasoned about from code and covered by pure-
  function unit tests, per Part 3. Confirming both live needs Whisper and Kokoro weights present
  (`M6-AUDIO-DEPLOY-125`), the same gap carried by every voice ticket to date.
- The "abstention in a long voice session — spoken in full every time, never abbreviated after
  the first" edge case was not exercised across multiple turns in one session; `statusLabel`'s
  logic has no per-turn counter or history that could abbreviate it, so this is inferred from
  the code rather than observed across repeated turns.
- Safari was not tested. Its older/partial support for
  `navigator.permissions.query({ name: "microphone" })` is called out in the code comments as
  falling back to the pre-existing first-attempt-`getUserMedia` path, but that fallback path was
  not separately exercised here — Part 2 above used Chrome/Firefox, which support the proactive
  query.
- Local analytics counter for these three states: the ticket's Analytics Events line says "Local
  counter only — nothing transmitted (C1)" but `web/lib/voice.ts` has no counter for permission-
  denial, non-English, or abstention events — only `recordVoiceLatencyBudgetMiss`/
  `getVoiceLatencyBudgetMissCount` exist, for the unrelated latency-budget ticket. Flagged rather
  than assumed implemented, same shape as the gap noted in `M6-VUI-FE-133`'s manual test.
