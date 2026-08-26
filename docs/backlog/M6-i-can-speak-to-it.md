# M6 — I can speak to it

**Goal:** Ask out loud, hear the answer, and always see it written down too. Voice is a mode of Ask, not a separate product.

**Phase:** 5 (`../build-plan.md`) · **Depends on:** M5 · **Tickets:** 12 · **Estimated:** 30–43 hours

**Exit condition:** A spoken question is transcribed, answered in text and speech, and stopped on demand; the accelerated profile reaches first audio within 3.5 seconds and the standard profile within 8; an abstention is spoken in full without softening; and every voice turn is logged with its transcript like any other.

> **Latency is the feature.** Miss the budget and people abandon voice permanently after two tries.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Audio transport | `AUDIO` | The voice container and the bidirectional channel |
| Speech to text | `STT` | Transcription, turn detection, low confidence |
| Speech synthesis | `TTS` | Sentence streaming and the text fallback |
| Voice interface | `VUI` | The composer control, stop, latency indicator, states |
| Performance | `PERF` | Budget measurement |

---

### M6-AUDIO-DEPLOY-125 — Voice container with transcription and synthesis

**Type:** Story

**User Story**
- **Actor:** someone whose hands are busy.
- **User Need:** speech recognition and speech synthesis running locally.
- **Business Value:** voice that phones home would break the one promise the product cannot break.
- *As someone reading from paper while asking questions, I want speech handled on my own machine, so that voice does not become the thing that leaks my material.*

**Context / Background**
**Detailed Description:** Add the voice service to the stack, carrying Whisper `small` for English transcription, Silero voice activity detection, and Kokoro-82M for synthesis. It routes outbound through the egress proxy like everything else and therefore reaches nothing. **Assumption carried forward and flagged here:** speech-to-text stays containerised on CPU. Whisper `small` on CPU is likely adequate, but it is untested, and if the accelerated profiles need GPU transcription this service becomes a second native process and the installer changes.

**Scope**
- Voice service in the stack with the models loaded from local files.
- Health reporting for transcription and synthesis separately.
- Model files supplied locally, never fetched at runtime.
- A recorded decision point for whether transcription must move to a native process.

**Out of Scope**
- The transport (M6-AUDIO-API-126) and the interface.
- Any language other than English.

**Acceptance Criteria**
- **Acceptance Criteria:** The voice service starts with local model files and reports transcription and synthesis health separately. It makes no outbound requests. A missing model file produces a clear refusal naming the path.
- **Edge Cases:** Transcription available but synthesis not — reported separately so the interface can fall back to text rather than disabling voice entirely. The service unavailable — voice mode is disabled with the reason while text asking is unaffected. Insufficient memory on a light profile — voice is degraded and the profile already says so.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §5 TTS unavailable; `../ux/voice.md` §5 idle.
- **Validation Rules:** No model is downloaded at runtime.
- **Audit / Logging Requirements:** Service start and model load are logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).
- **Assumption flagged:** if transcription must run natively for GPU access, this ticket's scope moves to the installer's native supervision and the estimate is not valid — that would be a new ticket in M7.

**Real-World Example Scenarios**
- A user with no internet connection uses voice normally, because everything it needs is on the disk.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-DEPLOY-009, M0-STACK-SEC-010.
- **API / Data Touchpoints:** Health surface.
- **Assumptions:** Whisper `small` on CPU meets the standard-profile budget. Untested.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up cold with the voice model files in place. Confirm the health surface reports transcription and synthesis separately as available. Remove the synthesis model and restart — confirm transcription still reports available and synthesis reports the missing path. Confirm the proxy's refusal counter does not increase during any of this.
- **Other scenarios:** Stop the voice service and confirm text asking is unaffected.
- **Known gaps:** Nothing can be spoken yet. Transcription is untested against the latency budget on CPU.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:5`, deployment, `constraint:local-first`
- **Granularity:** One service with three models.

---

### M6-AUDIO-API-126 — Bidirectional audio transport, for voice only

**Type:** Story

**User Story**
- **Actor:** someone speaking a question.
- **User Need:** audio flowing in and speech flowing back over one connection.
- **Business Value:** this is the only place a bidirectional channel is needed, and keeping it here is what let five phases ship on one-way streaming.
- *As someone speaking to Askwell, I want the audio to flow smoothly both ways, so that the conversation does not stutter.*

**Context / Background**
**Detailed Description:** A WebSocket channel carries microphone audio in and synthesised speech out, plus the transcript and the answer text. It is used for voice and nothing else; answers, step labels and ingestion progress remain on server-sent streaming. Reconnection recovers a turn whose generation completed server-side.

**Scope**
- The channel with audio in, audio out, transcript and text events.
- Reconnection recovering a completed turn.
- Backpressure so a slow client does not stall generation.

**Out of Scope**
- Migrating any other stream to this channel.
- Barge-in — there is none.

**Acceptance Criteria**
- **Acceptance Criteria:** Audio flows in and synthesised speech flows out over one connection, with the transcript and answer text arriving on the same channel. A dropped connection reconnects and, if generation completed server-side, the answer appears in the conversation. No other feature uses this channel.
- **Edge Cases:** A very long spoken question — streamed rather than buffered whole. A client that stops reading audio — backpressure applies rather than memory growing. A reconnect mid-synthesis — the remaining audio is not replayed from the start, and the text is complete regardless.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §5 connection drops mid-turn.
- **Validation Rules:** The channel is bound to localhost like every other surface.
- **Audit / Logging Requirements:** Voice turns are logged like any other, with the transcript.
- **Analytics Events:** Local counter of voice turns — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user's wifi blips mid-answer; the connection re-establishes and the completed answer is in the conversation.

**Dependencies & Assumptions**
- **Dependencies:** M6-AUDIO-DEPLOY-125, M1-ASK-BE-040.
- **API / Data Touchpoints:** The voice service; `conversations`, `messages`.
- **Assumptions:** Server-side continuation from M1 already covers the abandoned-turn case, so reconnection is a delivery problem rather than a generation one.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open Ask, activate voice and speak a short question. Confirm the transcript appears and the answer arrives as both text and audio. Mid-answer, disable and re-enable the network interface. Confirm the connection recovers and the completed answer is in the conversation.
- **Other scenarios:** Speak a two-minute question and confirm it streams rather than buffering.
- **Known gaps:** No transcription or synthesis behaviour yet, only transport.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:5`, api
- **Granularity:** One channel with four event kinds. Upper bound.

---

### M6-STT-BE-127 — English transcription

**Type:** Story

**User Story**
- **Actor:** someone asking a question out loud.
- **User Need:** an accurate transcript of what they said.
- **Business Value:** everything downstream is only as good as the transcript.
- *As someone thinking aloud, I want what I said transcribed accurately, so that the answer addresses my actual question.*

**Context / Background**
**Detailed Description:** Transcribe captured audio with Whisper `small`, English only, producing a transcript with a confidence measure. The transcript appears as text immediately, before any answer, because everything spoken is also written.

**Scope**
- Transcription with a confidence measure.
- Transcript delivered as text before the answer begins.
- Non-English speech detected and handled with the English-only statement.

**Out of Scope**
- Low-confidence confirmation (M6-STT-FE-129).
- Any language other than English; the Tamil hedge does not extend to speech.

**Acceptance Criteria**
- **Acceptance Criteria:** Spoken English produces a transcript with a confidence measure, delivered before the answer starts. Non-English speech produces the English-only statement rather than a poor transcription. The transcript is stored with the turn.
- **Edge Cases:** Background noise with no speech — no transcript, handled by the no-speech path. Very quiet speech — transcribed with low confidence rather than silently discarded. A question containing a reference number — transcribed as accurately as the model allows, and the low-confidence path is what catches the rest.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §3 step 4 and §5 transcribing; `../states-and-edge-cases.md` §5.
- **Validation Rules:** English only; no attempt at another language.
- **Audit / Logging Requirements:** The transcript is part of the interaction record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks about a supplier by name and the transcript gets the name right, so the retrieval does too.

**Dependencies & Assumptions**
- **Dependencies:** M6-AUDIO-API-126.
- **API / Data Touchpoints:** Voice service; `messages`.
- **Assumptions:** Audio is retained only long enough to transcribe; the transcript is kept and the audio is not, which is an open trade-off recorded in `../ux/voice.md` §7.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, activate voice and speak a question about an indexed document. Confirm the transcript appears as text before any answer and matches what you said. Speak in another language and confirm the English-only statement rather than a garbled transcript.
- **Other scenarios:** Speak quietly and confirm a low-confidence transcript rather than silence.
- **Known gaps:** Audio is not retained, so a bad transcription cannot be replayed for debugging. English only.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:5`, voice
- **Granularity:** One transcription path.

---

### M6-STT-BE-128 — Turn detection and the silent timeout

**Type:** Story

**User Story**
- **Actor:** someone who has finished speaking.
- **User Need:** the turn to close on its own.
- **Business Value:** a stop button after every sentence makes voice slower than typing.
- *As someone asking a question aloud, I want Askwell to notice I have finished, so that I do not have to press anything.*

**Context / Background**
**Detailed Description:** Voice activity detection closes the turn on a pause. Push-to-talk is the default with a hands-free toggle available. If no speech is detected at all, the interface returns silently to idle — no error sound, no dialogue, because speaking to a machine and getting nothing is embarrassing enough.

**Scope**
- Voice activity detection closing a turn on a pause.
- Push-to-talk as the default with a hands-free toggle.
- Silent return to idle when no speech is detected.
- A manual stop control for closing a turn early.

**Out of Scope**
- Barge-in during an answer — there is none.
- Tuning hands-free detection for a noisy room, which is an open question.

**Acceptance Criteria**
- **Acceptance Criteria:** A pause after speech closes the turn. Push-to-talk works and releasing closes the turn. Hands-free can be enabled and closes on a pause. No speech produces a silent return to idle with no error.
- **Edge Cases:** A long thinking pause mid-question — the pause threshold is forgiving enough not to cut the user off, and this is tuned rather than guessed. Continuous background noise in hands-free mode — the turn does not close, and the elapsed-time display is what tells the user something is wrong. Releasing push-to-talk before speaking — silent return to idle.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §3 and §5 listening and no-speech-detected.
- **Validation Rules:** No error sound on a silent turn.
- **Audit / Logging Requirements:** A turn with no speech produces no interaction record, because nothing was asked.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user holds the control, asks a question, releases, and the answer starts — with no button pressing between.

**Dependencies & Assumptions**
- **Dependencies:** M6-STT-BE-127.
- **API / Data Touchpoints:** Voice service.
- **Assumptions:** Getting hands-free detection wrong makes the product appear to interrupt itself, which is why push-to-talk is the default.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, activate voice in push-to-talk mode, hold, ask a question with a thinking pause in the middle, and release. Confirm the whole question was captured, including after the pause. Enable hands-free, speak, then stop speaking, and confirm the turn closes on its own. Activate and say nothing — confirm a silent return to idle with no sound and no dialogue.
- **Other scenarios:** Speak in a noisy room in hands-free mode and observe the behaviour honestly; if it is unusable, that is the open question being answered.
- **Known gaps:** Hands-free thresholds are untuned for noisy environments.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:5`, voice
- **Granularity:** Detection plus two modes plus one silent path.

---

### M6-STT-FE-129 — Low confidence: show the transcript and confirm before answering

**Type:** Story

**User Story**
- **Actor:** someone whose question was half heard.
- **User Need:** to correct it before the assistant answers the wrong question.
- **Business Value:** answering the wrong question confidently is worse than one extra tap.
- *As someone who mumbles occasionally, I want to see and confirm what was heard when it is uncertain, so that I do not get a confident answer to a question I did not ask.*

**Context / Background**
**Detailed Description:** When transcription confidence is low, show the transcript and ask for confirmation before answering, with the option to edit it or to speak again. Above the confidence threshold, no confirmation is required — the extra tap must not become the normal path.

**Scope**
- Confidence threshold and the confirmation state.
- Edit-the-transcript and speak-again actions.
- Threshold configurable, defaulting to a value tuned so confirmation is uncommon.

**Out of Scope**
- Per-word confidence display.

**Acceptance Criteria**
- **Acceptance Criteria:** A low-confidence transcript is shown with a confirmation before any answer. A confident transcript proceeds directly. The transcript can be edited before confirming. Speaking again replaces it.
- **Edge Cases:** Confidence low because the question was genuinely unusual, such as a reference number — editing is the escape and must be easy. The user ignoring the confirmation and walking away — the turn does not answer, and it does not sit forever; it returns to idle and the transcript is retained in the composer.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §5 low confidence; `../states-and-edge-cases.md` §5.
- **Validation Rules:** The confirmation must never be skippable by a setting that turns it off entirely.
- **Audit / Logging Requirements:** The confirmed or edited transcript is what is recorded.
- **Analytics Events:** Local counter of confirmations — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks about invoice INV-2024-0917, sees a garbled transcript, types the number, and confirms.

**Dependencies & Assumptions**
- **Dependencies:** M6-STT-BE-128.
- **API / Data Touchpoints:** Transcript confidence; the composer.
- **Assumptions:** The default threshold makes confirmation uncommon; if it fires on most turns, the threshold is wrong and voice becomes slower than typing.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, activate voice and speak clearly — confirm the answer starts without a confirmation step. Then speak deliberately unclearly and confirm the transcript is shown with a confirmation. Edit it, confirm, and check that the answer addresses the edited question.
- **Other scenarios:** Trigger the confirmation and walk away — confirm the turn returns to idle with the transcript retained.
- **Known gaps:** No per-word confidence. The threshold is a guess until real use.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:5`, voice, frontend
- **Granularity:** One threshold and one confirmation state.

---

### M6-TTS-BE-130 — Sentence-streamed speech synthesis

**Type:** Story

**User Story**
- **Actor:** someone waiting to hear an answer.
- **User Need:** audio starting before the whole answer exists.
- **Business Value:** the budget is 3.5 seconds to first audio on an accelerated machine, and waiting for a complete answer before speaking makes that impossible.
- *As someone who asked out loud, I want to hear the answer start quickly, so that the pause does not feel like a failure.*

**Context / Background**
**Detailed Description:** Synthesise sentence by sentence as the answer streams, so audio starts before generation finishes. Text streams to the screen as it always does. Citations are not spoken aloud — reading a filename and page number out is unbearable — and the spoken answer refers to sources naturally instead, with the citations satisfying the constraint on screen.

**Scope**
- Sentence segmentation of the streaming answer and synthesis per sentence.
- Audio queue playing in order without gaps.
- Citation suppression in speech with natural source reference instead.

**Out of Scope**
- Voice selection and speed controls beyond a sensible default.

**Acceptance Criteria**
- **Acceptance Criteria:** Audio begins before the answer completes. Sentences play in order without gaps or overlap. Citations are not read aloud, while appearing on screen as always. The spoken answer refers to a source naturally where it matters.
- **Edge Cases:** A sentence containing a long identifier — spoken as best it can be, and the screen carries the exact text. A very short answer — synthesised as one unit without an audible seam. The answer stopped mid-sentence — audio stops promptly rather than finishing the buffered sentence and ignoring the stop.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §3 step 5, §6 constraints.
- **Validation Rules:** Citations are satisfied by the screen, never by the audio, and the screen rendering is unchanged in voice mode.
- **Audit / Logging Requirements:** The turn is logged like any other with its transcript.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user hears the answer begin two seconds after they finish speaking, while the text and its source cards fill in on screen.

**Dependencies & Assumptions**
- **Dependencies:** M6-AUDIO-API-126, M1-ASK-API-038.
- **API / Data Touchpoints:** Voice service; the streaming answer.
- **Assumptions:** Sentence segmentation of streaming text is reliable enough not to produce unnatural breaks.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question by voice about an indexed document. Time the gap between finishing speaking and hearing the first audio. Confirm the answer plays smoothly with no gaps, that no filename or page number is read aloud, and that the source cards appear on screen as usual.
- **Other scenarios:** Stop mid-answer and confirm audio ceases promptly.
- **Known gaps:** No voice selection or rate control. Budget compliance is measured separately.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:5`, voice
- **Granularity:** Segmentation, synthesis, queueing.

---

### M6-TTS-BE-131 — Fall back to text when synthesis is unavailable

**Type:** Task

**User Story**
- **Actor:** someone whose synthesis model failed to load.
- **User Need:** the answer delivered as text with a note.
- **Business Value:** voice is a mode, not a separate product; falling back to text is correct rather than an error.
- *As someone whose speaker output has stopped working, I want the answer anyway, so that a voice problem is not a product problem.*

**Context / Background**
**Detailed Description:** When synthesis is unavailable, the answer is delivered as text with a note that the voice is unavailable. Transcription can continue to work independently, so speaking the question and reading the answer remains a usable mode.

**Scope**
- Detection of synthesis unavailability, separate from transcription.
- Text delivery with a note.
- Recovery without a reload when synthesis returns.

**Out of Scope**
- Repairing the synthesis service.

**Acceptance Criteria**
- **Acceptance Criteria:** With synthesis unavailable, a voice question is transcribed, answered as text, and a note explains the voice is unavailable. Transcription continues to work. When synthesis returns, the next answer is spoken without a reload.
- **Edge Cases:** Synthesis failing mid-answer — the remaining answer is text with the note, rather than the turn failing. Both transcription and synthesis unavailable — voice mode is disabled with the reason and typing is unaffected.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §5 TTS unavailable; `../states-and-edge-cases.md` §5.
- **Validation Rules:** A voice failure never blocks an answer.
- **Audit / Logging Requirements:** Availability transitions are logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user on a light profile finds synthesis too heavy; the answer arrives as text with a note rather than not at all.

**Dependencies & Assumptions**
- **Dependencies:** M6-TTS-BE-130, M6-AUDIO-DEPLOY-125.
- **API / Data Touchpoints:** Health surface.
- **Assumptions:** Transcription and synthesis fail independently often enough to be worth separating.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with the synthesis model removed. Activate voice, ask a question, and confirm it is transcribed and answered as text with a note about the voice. Restore the model, restart the voice service, ask again, and confirm the answer is spoken without reloading the page.
- **Other scenarios:** Stop synthesis mid-answer and confirm the rest arrives as text.
- **Known gaps:** No automatic repair.

**Effort & Granularity Check**
- **Estimate:** 1–2 hours · **Priority:** High
- **Labels / Component:** `phase:5`, voice
- **Granularity:** One fallback path.

---

### M6-VUI-FE-132 — Voice control in the composer with a live level meter

**Type:** Story

**User Story**
- **Actor:** someone speaking into a laptop and unsure it is listening.
- **User Need:** visible evidence that the microphone is picking them up.
- **Business Value:** a dead-looking microphone is the single most common reason people abandon voice.
- *As someone talking to a machine, I want to see that it hears me, so that I do not stop halfway through wondering.*

**Context / Background**
**Detailed Description:** The voice control sits in the composer and voice does not take over the screen. The conversation stays visible, and transcript and answer text appear as they always do. While listening, a live level meter and elapsed time are shown.

**Scope**
- Voice control in the composer with push-to-talk and the hands-free toggle.
- Live level meter and elapsed time while listening.
- The conversation remaining fully visible and usable.

**Out of Scope**
- A separate voice screen — there is none, deliberately.

**Acceptance Criteria**
- **Acceptance Criteria:** The control is in the composer and activating it does not take over the screen. A live meter responds to speech. Elapsed time is shown. The transcript and answer render in the conversation exactly as for a typed question.
- **Edge Cases:** A muted microphone at the system level — the meter shows nothing and the interface says the microphone appears silent rather than pretending to listen. Switching input devices mid-session — the meter follows the new device. A very long listening period — elapsed time keeps counting rather than resetting.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §2 and §5 idle and listening.
- **Validation Rules:** Everything spoken is also written, without exception.
- **Audit / Logging Requirements:** None beyond the turn.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user speaks and watches the meter move, so they keep going rather than stopping to check.

**Dependencies & Assumptions**
- **Dependencies:** M6-STT-BE-128, M1-ASK-FE-039.
- **API / Data Touchpoints:** The voice channel.
- **Assumptions:** Browser microphone access provides a level signal adequate for a meter.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open Ask and find the voice control in the composer. Activate it and speak — confirm the meter moves and elapsed time counts. Confirm the conversation behind it is still fully visible. Complete the turn and confirm the transcript and answer appear in the conversation exactly as a typed exchange would.
- **Other scenarios:** Mute the microphone at the system level and confirm the interface says it appears silent.
- **Known gaps:** No device picker inside Askwell; the system's device is used.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:5`, frontend, voice
- **Granularity:** One control with two indicators.

---

### M6-VUI-FE-133 — Stop control, and deliberately no barge-in

**Type:** Story

**User Story**
- **Actor:** someone trapped in a long spoken answer.
- **User Need:** a visible way out.
- **Business Value:** a stop control solves the real problem — being stuck in a long answer — at a fraction of the cost of barge-in.
- *As someone who realises after two sentences that this is not what I asked, I want to stop it, so that I can ask again immediately.*

**Context / Background**
**Detailed Description:** A stop control is always available while speaking. There is no barge-in: speaking over the answer does nothing, and the stop control is the way out. Stopping ends generation and audio, keeps the partial answer marked as partial, and returns to idle ready for the next question.

**Scope**
- Stop control visible whenever audio is playing or generation is running.
- Stop ending both generation and audio promptly.
- Partial answer retained and marked.

**Out of Scope**
- Barge-in — explicitly not in v1.

**Acceptance Criteria**
- **Acceptance Criteria:** The stop control is visible while speaking. Pressing it stops audio and generation promptly and the partial answer is kept and marked partial. Speaking over the answer does nothing.
- **Edge Cases:** Stop pressed as the answer is completing — the completed answer is kept and not marked partial. Stop pressed twice — the second is inert. Stop during synthesis but after generation completed — the text answer is complete and only the audio stops.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §4 and §5 user speaks over the answer.
- **Validation Rules:** A stopped answer is always marked partial.
- **Audit / Logging Requirements:** The stop is recorded on the interaction.
- **Analytics Events:** Local counter of stops — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user hears the answer going the wrong way, presses stop, and asks a better question five seconds later.

**Dependencies & Assumptions**
- **Dependencies:** M6-TTS-BE-130, M1-ASK-API-038.
- **API / Data Touchpoints:** The voice channel; `messages`.
- **Assumptions:** Stopping audio promptly means discarding the queued buffer, not waiting for the current sentence.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question by voice that produces a long answer. While it is speaking, talk over it and confirm nothing happens. Then press stop and confirm audio ceases within a moment, generation ends, and the partial answer is in the conversation marked partial. Ask a new question immediately and confirm it works.
- **Other scenarios:** Press stop just as the answer completes and confirm it is not wrongly marked partial.
- **Known gaps:** No barge-in, deliberately.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:5`, frontend, voice
- **Granularity:** One control and one stop path.

---

### M6-VUI-FE-134 — Latency indicator, only once the budget is passed

**Type:** Task

**User Story**
- **Actor:** someone waiting longer than usual for a spoken answer.
- **User Need:** a signal that it is still working, only when the wait is genuinely long.
- **Business Value:** it costs nothing on a healthy turn and prevents the user concluding it has hung and retrying.
- *As someone whose machine is having a slow moment, I want to know it is still working, so that I do not ask again and make it worse.*

**Context / Background**
**Detailed Description:** An indicator appears only once the profile's latency budget has already been passed — 3.5 seconds on accelerated, 8 on standard. Nothing appears on a healthy turn. The indicator says it is taking longer than usual, not that something is wrong.

**Scope**
- Budget per profile and the elapsed measurement from end of speech.
- The indicator appearing only past budget, fading in rather than snapping.
- Copy that reassures rather than alarms.

**Out of Scope**
- Any indicator on a healthy turn.

**Acceptance Criteria**
- **Acceptance Criteria:** On a healthy turn nothing appears. Past the profile's budget the indicator fades in. The copy says it is taking longer than usual. It disappears when audio begins.
- **Edge Cases:** A turn that passes the budget and then completes immediately — the indicator appears and clears without flicker, or does not appear at all if the completion is within a moment. An unknown profile — the standard budget is used and that is stated in settings. A turn that fails past the budget — the failure message replaces the indicator.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/voice.md` §4 and §5 past latency budget; `../ux/ask.md` §5.
- **Validation Rules:** The indicator must never appear before the budget is passed.
- **Audit / Logging Requirements:** Budget misses are recorded on the interaction for later measurement.
- **Analytics Events:** Local counter of budget misses — nothing transmitted (C1).

**Real-World Example Scenarios**
- On a light profile the indicator appears at eight seconds and the user waits rather than repeating themselves.

**Dependencies & Assumptions**
- **Dependencies:** M6-TTS-BE-130.
- **API / Data Touchpoints:** Profile configuration; the voice channel.
- **Assumptions:** Elapsed time is measured from end of speech, which is what the user experiences.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start on a standard profile and ask a short voice question — confirm no indicator appears. Then ask a heavy question that runs past eight seconds and confirm the indicator fades in with reassuring copy and clears when audio starts.
- **Other scenarios:** Force a failure past the budget and confirm the failure message replaces the indicator.
- **Known gaps:** Budget values come from the profile and are not measured per machine.

**Effort & Granularity Check**
- **Estimate:** 1–2 hours · **Priority:** Medium
- **Labels / Component:** `phase:5`, frontend, voice
- **Granularity:** One indicator with one trigger.

---

### M6-VUI-FE-135 — Voice states: permission denied, non-English, abstention spoken in full

**Type:** Story

**User Story**
- **Actor:** someone whose browser has not granted microphone access.
- **User Need:** an explanation and a path, not an error.
- **Business Value:** nothing is broken; a browser permission is not something Askwell can fix, and presenting it as a failure teaches the wrong thing.
- *As someone who declined the microphone prompt by reflex, I want to be told how to enable it, so that I can try voice when I am ready.*

**Context / Background**
**Detailed Description:** Build the remaining voice states: microphone permission not granted, with the reason and how to enable it; non-English speech, stating the product handles English in this version; and **abstention spoken in full and shown in full — not softened because it is being said aloud**, since a spoken hedge is exactly how the abstention constraint gets eroded.

**Scope**
- Permission-denied state with an explanation and instructions.
- Non-English speech state.
- Abstention spoken in full, in the same words as on screen, without an apologetic tone.

**Out of Scope**
- Requesting permission repeatedly — one request, then the explanation.

**Acceptance Criteria**
- **Acceptance Criteria:** Denied permission disables voice with an explanation and instructions rather than an error. Non-English speech produces the English-only statement. An abstention is spoken completely, matching the screen text, with no softening, no apology and no hedge.
- **Edge Cases:** Permission granted after being denied — voice becomes available without a reload where the browser allows it. An abstention in a long voice session — spoken in full every time, never abbreviated after the first. A partial answer spoken — the ungrounded part is stated aloud as not covered, not glossed over.
- **Permissions / Roles:** Single user — no roles. Not applicable. The microphone permission is the browser's, not the product's.
- **UI States:** `../ux/voice.md` §5 in full; `../ux/voice.md` §6 constraints that hold in voice.
- **Validation Rules:** Abstention wording is identical in voice and text.
- **Audit / Logging Requirements:** Voice abstentions are recorded like any other.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks aloud about something not in their files and hears the full abstention, including what was searched, exactly as it reads on screen.

**Dependencies & Assumptions**
- **Dependencies:** M6-VUI-FE-133, M2-ABSTAIN-FE-055.
- **API / Data Touchpoints:** Browser permission state; the answer path.
- **Assumptions:** Reading the full abstention aloud is acceptable in length; shortening it is the failure mode this ticket exists to prevent.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start in a browser profile where microphone permission is denied. Open Ask and confirm voice is disabled with an explanation and instructions, not an error. Grant permission and confirm voice becomes available. Speak a question in another language and confirm the English-only statement. Then ask a question your corpus does not cover and confirm the abstention is spoken completely and matches the screen word for word.
- **Other scenarios:** Ask a partially covered question by voice and confirm the uncovered part is stated aloud.
- **Known gaps:** Permission recovery without a reload depends on the browser.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:5`, frontend, voice, `constraint:grounding`
- **Granularity:** Three states.

---

### M6-PERF-TEST-136 — Measure voice latency against the profile budgets

**Type:** Task

**User Story**
- **Actor:** the maintainer accepting the voice phase.
- **User Need:** a measurement of end of speech to first audio on each profile.
- **Business Value:** the phase's acceptance is the budget, and latency is the feature.
- *As someone signing off voice, I want the latency measured rather than felt, so that the acceptance criterion means something.*

**Context / Background**
**Detailed Description:** Measure the interval from end of speech to first audio across repeated turns on each available profile, reporting median and worst case against 3.5 seconds on accelerated and 8 on standard. Break the interval down by stage — transcription, retrieval, generation to first sentence, synthesis — so a miss is attributable.

**Scope**
- Repeatable measurement harness for the voice path with a fixed audio input.
- Per-stage breakdown.
- Reporting against the profile budget with median and worst case.

**Out of Scope**
- Optimisation work, which follows from what the measurement shows.

**Acceptance Criteria**
- **Acceptance Criteria:** The harness reports median and worst-case first-audio latency per profile with a per-stage breakdown. Results are recorded for comparison. A miss identifies which stage caused it.
- **Edge Cases:** A machine that cannot run the accelerated profile — reported as not measured rather than as a pass. A first turn after startup, which is slower because of model warm-up — reported separately from steady state, because the user experiences both.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Latency is measured from end of speech, as the user experiences it, not from the start of processing.
- **Audit / Logging Requirements:** Results recorded with profile, model and date.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- The standard profile misses the budget by two seconds, and the breakdown shows transcription is the cause — which is exactly the evidence needed to decide whether transcription must move to a native process.

**Dependencies & Assumptions**
- **Dependencies:** M6-TTS-BE-130, M6-VUI-FE-134.
- **API / Data Touchpoints:** The voice path; the trace.
- **Assumptions:** **This measurement is what answers the open question about containerised versus native transcription.** If the standard profile misses the budget because of transcription, a follow-up ticket moves it to a native process and changes the installer.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start on each available profile. Run the measurement with a fixed recording, twenty turns, discarding the first as warm-up but reporting it separately. Read the median and worst case against the budget and the per-stage breakdown. Then perform a manual voice turn and confirm the felt experience matches the measurement.
- **Other scenarios:** Run on a light profile and record the honest result, which is expected to miss.
- **Known gaps:** Measurement is on one machine per profile and is not portable. Optimisation is out of scope here.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:5`, test, performance, voice
- **Granularity:** One harness with one breakdown.
