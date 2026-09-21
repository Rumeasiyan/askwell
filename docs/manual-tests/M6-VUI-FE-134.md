# Manual test — M6-VUI-FE-134: Latency indicator, only once the budget is passed

## What this ticket built

`web/lib/voice.ts` gains `voiceLatencyBudgetMs` (3.5s on `accelerated`, 8s on `standard` and
every other/unknown profile), `VOICE_LATENCY_COPY` ("Taking longer than usual…"), and a
local-only (C1) budget-miss counter (`recordVoiceLatencyBudgetMiss` /
`getVoiceLatencyBudgetMissCount`). `web/components/ask/voice-control.tsx`'s `MicControl` reads
the hardware tier from `GET /setup` on mount, starts a timer the instant the mic is released
(`stopCapture`), and shows a small fading-in line under the mic button if that timer fires
before audio actually starts playing back. `web/app/globals.css` adds the fade (`opacity`
transition, no layout reservation so it renders on zero healthy turns) and
`web/app/settings/page.tsx` states the two budgets and the unknown-profile fallback in prose.

**Same known limitation as `M6-VUI-FE-128a`, carried from every voice ticket since
`M6-AUDIO-DEPLOY-125`**: Whisper and Kokoro weights are not present in this environment, so a
real spoken turn fails at transcription — usually well inside a second, i.e. before either
budget elapses. That means the live path alone cannot be trusted to demonstrate the indicator
firing; Part 2 below uses network throttling to hold a turn open past budget so the fade-in and
its clearing are both actually observed, and Part 4 covers what a full deployment would show
that this cannot.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m6-vui-fe-134`.
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
and `web/lib/voice.test.ts` passing including the new cases this ticket adds:
`voiceLatencyBudgetMs("accelerated")` is 3500, `voiceLatencyBudgetMs("standard")` is 8000, and
`null`/`"light"`/`"workstation"` all fall back to 8000 — the unknown-profile edge case. The
budget-miss counter tallies and resets locally with no network call anywhere near it. At the
time this was written: 328 web tests.

## Part 2 — cold start, a healthy turn shows nothing

1. With the stack up, open `http://127.0.0.1:8000/` in the browser.
   **What you should see:** the Ask screen loads — the first-run "Ask your own material" card
   if nothing has been added yet, otherwise the composer directly.

2. If the first-run card is showing, click **Add a source**, add one small `.txt` or `.md`
   file, and wait for the library to report it `ready`.
   **What you should see:** back on the Ask screen, the composer (text box, mic button, **Ask**
   button) is visible.

3. Look under the mic button without touching it.
   **What you should see:** nothing there at all — no empty box, no placeholder line, no
   reserved whitespace that would hint something might appear. This is the "nothing on a
   healthy turn" acceptance criterion: `.ask-mic-latency` has no layout footprint until
   `data-visible="true"` is set.

4. Press and hold the mic button, say a short sentence, and release quickly.
   **What you should see:** the label cycles "Listening…" → "Transcribing…" and, within about a
   second (no Whisper weights here), settles on **"Askwell could not answer that."** — and at
   no point during that short turn does the small line under the button appear. This is the
   healthy-turn case: the failure lands well inside even the 3.5s budget, so
   `voiceLatencyBudgetMs`'s timer never fires before `stopLatencyWatch` clears it.

## Part 3 — throttled, a turn that actually crosses the budget

5. Open the browser's DevTools, go to the Network panel, and set throttling to **Slow 3G** (or
   an equivalent custom profile with several seconds of added latency). Confirm in Settings
   (Part 4 below adds this note) or by having read `docs/BRAIN.md`/`/health` that the running
   profile is `standard` — throttling only needs to hold the turn open past 8s, not 3.5s.

6. Press and hold the mic button, say a short sentence, and release.
   **What you should see:** "Listening…" while held, then "Transcribing…" on release, same as
   Part 2 — nothing under the button yet.

7. Keep watching without touching anything, for up to 8 seconds after release.
   **What you should see:** at 8 seconds the small line under the mic button fades in (not a
   snap — `.ask-mic-latency`'s `transition: opacity 240ms ease`) reading exactly **"Taking
   longer than usual…"** — reassuring wording, not an error. The main label above it is
   unaffected and still reads "Transcribing…" or partial transcript text; this is a second,
   separate line.

8. Continue waiting for the (still-failing, no weights) turn to finish.
   **What you should see:** when the failure arrives, the main label changes to **"Askwell
   could not answer that."** and the small "Taking longer than usual…" line disappears —
   the failure message replaces the indicator rather than the two showing together
   (`handleChannelMessage`'s `stopLatencyWatch()` call on the `status: failed` event).

9. If Whisper and Kokoro weights are present (a deployment where `M6-AUDIO-DEPLOY-125`'s known
   gap has since been closed), repeat steps 6–7 and let the turn actually complete instead of
   failing.
   **What you should see:** the indicator fades in past budget exactly as in step 7, then
   disappears the instant the first sentence of spoken audio actually starts playing back
   (`playAudioChunk`'s `audioStartedRef` check) — not when the answer text starts streaming in,
   which can arrive noticeably earlier than synthesised audio.

## Part 4 — settings states the fallback, and a turn that clears fast after crossing budget

10. Click **Settings** in the navigation.
    **What you should see:** among the existing voice-related copy, a line reading "Voice's
    past-latency indicator waits 3.5 seconds on an `accelerated` hardware profile and 8 seconds
    on every other profile, including one that could not be determined." — this is the
    unknown-profile edge case's required disclosure, not just internal fallback behaviour.

11. With throttling still enabled from Part 3, press and hold the mic, say a short sentence,
    release, and this time stop the throttled request the instant you see the indicator fade in
    (switch DevTools throttling back to **No throttling** immediately after the line appears).
    **What you should see:** the queued response arrives quickly once throttling is lifted, and
    the indicator disappears cleanly — either replaced by the failure message or, on a full
    deployment, cleared the moment audio starts — with no flicker (the line does not flash on
    and off repeatedly before settling). This is the "passes budget then completes almost
    immediately" edge case from the ticket's acceptance criteria.

## What this does not prove

Whether a real transcript and spoken answer actually arrive, and whether the indicator's
clearing-on-first-audio path behaves correctly against real Kokoro output — this environment has
no Whisper/Kokoro weights (`M6-AUDIO-DEPLOY-125`'s known gap, carried by every voice ticket
since). Network throttling stands in for a genuinely slow turn; it was not confirmed here
against a real slow inference pass on underpowered hardware. The budget-miss counter's local
tally is not surfaced anywhere in the UI yet — there is nothing to look at that reads it back;
Part 1's automated test is the only current evidence it increments.

## Known gaps

- Budget values come from the profile's stated figures and are not measured per machine, per
  the ticket's own "Known gaps" note — a machine that is unusually slow even for its tier gets
  no earlier warning.
- The local budget-miss counter (`getVoiceLatencyBudgetMissCount`) has no UI surface — it exists
  for later measurement only, per the ticket's analytics-events requirement, and is not shown
  or exported anywhere yet.
- The `GET /setup` hardware-tier fetch happens once on mount and is never re-checked mid-session
  — a hot-pluggable-hardware change mid-session (not a realistic scenario on this product's
  single-machine model) would not update the budget until the page reloads.
- Live confirmation of the fade timing and the "clears on first audio" behaviour against real
  Whisper/Kokoro weights was not possible in this environment; Part 3's throttling approach is a
  stand-in, not a substitute.
