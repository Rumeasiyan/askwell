# Screen: Voice

Asking out loud and hearing the answer. A mode of Ask, not a separate product.

> **This document is the specification. Any mockup is a reference.**

**Route:** Ask, with voice active. Same conversation, same tools, same log.
**Phase:** 5

---

## 1. What it is for

Asking without typing — hands busy, reading from paper, thinking aloud.

`../build-plan.md` Phase 5 sets the budget: **3.5s to first audio on `accelerated`, 8s on `standard`.** Miss it and people abandon voice permanently after two tries, so latency is the feature and everything else is secondary.

---

## 2. Shape

Voice does not take over the screen. The conversation stays visible, transcript and answer text appear as they always do, and the voice control sits in the composer.

**Everything spoken is also written.** A spoken answer with no text is unciteable, unskimmable and gone the moment it finishes — and the citations are the product. Voice changes the input and adds audio output; it removes nothing.

---

## 3. The turn

1. **Hold or click to speak.** Push-to-talk by default, with a hands-free toggle for someone who wants it.
2. **Listening** — live level meter, so the user can see it is hearing them. A dead-looking mic is the single most common reason people abandon voice.
3. **Silero VAD detects the pause** and closes the turn. No stop button needed, though one exists.
4. **Transcript appears** — as text, immediately, before any answer.
5. **Answer streams** as text and speaks sentence by sentence, so audio starts before the full answer exists.
6. **Stop control**, always available while speaking.

---

## 4. Decisions already made

| Issue | Decision |
| ----- | -------- |
| [#13](https://github.com/Rumeasiyan/askwell/issues/13) | **No barge-in.** A visible stop control instead. It solves the real problem — being stuck in a long answer — at a fraction of the cost |
| [#15](https://github.com/Rumeasiyan/askwell/issues/15) | **Latency indicator appears only once the budget is passed.** Nothing on a healthy turn; prevents the user concluding it has hung and retrying |

---

## 5. States

| State | What is shown / heard |
| ----- | --------------------- |
| **Idle** | Mic control in the composer. Nothing else changes |
| **Mic permission not granted** | Voice disabled with the reason and how to enable it in the browser. Not an error — nothing is broken |
| **Listening** | Live level meter, elapsed time |
| **No speech detected** | Silent return to idle. No error sound, no dialogue. Speaking to a machine and getting nothing is embarrassing enough |
| **Transcribing** | Brief, with the partial transcript if available |
| **Low confidence** | **Show the transcript and ask before answering.** Answering the wrong question confidently is worse than one extra tap |
| **Answering** | Text streams, audio follows sentence by sentence, stop control visible |
| **Past latency budget** | Indicator fades in (#15). Only then |
| **User speaks over the answer** | Nothing happens. No barge-in (#13). The stop control is the way out |
| **TTS unavailable** | Answer delivered as text with a note. Voice is a mode; falling back is correct |
| **Connection drops mid-turn** | Reconnect. If generation completed server-side it appears in the conversation (#14) |
| **Abstention, spoken** | Spoken plainly and shown in full on screen. **Not softened because it is being said aloud** — a spoken hedge is exactly how C5 gets eroded |
| **Non-English speech** | States that Askwell handles English in this version. Does not attempt a poor transcription |

---

## 6. Constraints that hold in voice

- **Citations are not spoken aloud** — "supplier-agreement-2024.pdf, page fourteen" read out is unbearable. They appear on screen as always, and the spoken answer says *"from the 2024 supply agreement"* where it matters. C4 is satisfied by the screen, not the audio.
- **Abstention is spoken in full.** No shortening, no apologetic tone.
- Voice turns are logged like any other (`../audit-log.md`), with the transcript.

---

## 7. Open

1. **Hands-free turn detection** without push-to-talk needs a VAD threshold that works in a noisy room. Getting this wrong makes the product appear to interrupt itself.
2. **Audio retention.** Currently the transcript is kept and the audio is not. Keeping audio would help debug bad transcription and is a meaningful amount of disk on a laptop.
