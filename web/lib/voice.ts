/**
 * Pure logic behind the voice composer: the socket URL, the wire event
 * shapes `askwell.voice_channel` sends, the base state machine
 * (`docs/ux/voice.md` §5) and the PCM conversion the capture and playback
 * paths need. `M6-VUI-FE-128a`.
 *
 * Kept separate from `components/ask/voice-control.tsx` so all of it is
 * testable with `node:test` alone — nothing here touches `getUserMedia`,
 * `WebSocket` or `AudioContext`, the same split `lib/ask.ts` makes between
 * SSE parsing and the browser `fetch` that feeds it.
 */

export type VoiceState = "idle" | "listening" | "transcribing" | "confirming" | "answering";

export interface VoiceStatus {
  state: VoiceState;
  /** Set only on `idle` — why voice stopped, or why it never started. Never
   * set on the other states: they are only ever reached because something
   * is actually happening, so there is nothing to explain. */
  reason: string | null;
}

export const VOICE_IDLE: VoiceStatus = { state: "idle", reason: null };

export const MIC_PERMISSION_DENIED_REASON =
  "Microphone access was denied. Allow it in your browser's site settings to use voice.";
export const MIC_NO_DEVICE_REASON = "No microphone was found on this device.";
export const MIC_UNAVAILABLE_REASON = "The microphone could not be started.";
export const VOICE_CONNECTION_LOST_REASON = "The connection to Askwell was lost. Try again.";
export const VOICE_FAILED_REASON = "Askwell could not answer that.";
/** `M6-VUI-FE-135`. Matches `askwell.voice_stt`'s own `unsupported_language`
 * outcome: no transcription is attempted at all for it
 * (`askwell.voice.transcribe`'s own docstring) — this states the situation
 * rather than presenting a poor transcript or a generic error. */
export const VOICE_NON_ENGLISH_REASON =
  "Askwell handles English in this version. Speak your question in English to use voice.";
/** `M6-VUI-FE-135`. Read once from the Permissions API (`navigator.
 * permissions.query`, never a second `getUserMedia` prompt — the ticket's
 * own Out of Scope: "requesting permission repeatedly, one request, then
 * the explanation") so a browser that already denied the mic disables voice
 * with this reason before the control is ever pressed, not only after a
 * denied attempt. Pure so the mapping is testable without the Permissions
 * API itself. */
export function micPermissionReason(state: "granted" | "denied" | "prompt" | null): string | null {
  return state === "denied" ? MIC_PERMISSION_DENIED_REASON : null;
}
/** `M6-VUI-FE-133`. Deliberately does not claim "partial" — the voice
 * channel's own `status` event carries `VoiceTurn.status`
 * (`"completed"`/`"failed"`), never `askwell.ask`'s own `"stopped"` vs
 * `"completed"` distinction (`_generate`'s token loop is the only place
 * that knows whether stop actually landed before generation finished), so
 * a client here cannot honestly tell "stop cut the answer off" apart from
 * "stop landed after the text was already complete and only cut off
 * audio" (`docs/ux/voice.md` §5's own edge case). The `messages`/
 * `audit_interactions` record is correct either way (`askwell.ask`'s own
 * `partial = status == "stopped" or truncated`) — this label just never
 * asserts more than the one real local fact it has: the user pressed stop.
 * Filed as issue 471 — the wire gap, not a bug in this ticket's own code. */
export const VOICE_STOPPED_REASON = "Stopped.";

/** Matches `askwell.voice_channel`'s own wire shapes: the `_Event.kind`
 * union plus the one-shot `turn`/`status` messages `voice_ws` sends
 * directly. `citation`/`fact_citation` are forwarded verbatim server-side
 * and are not this ticket's to render (`M6-STT-FE-129` and later), so they
 * are typed loosely on purpose. */
export type VoiceChannelEvent =
  | { type: "turn"; turn_id: string }
  | { type: "transcript"; text: string }
  | { type: "text"; text: string }
  | { type: "confidence"; value: number }
  | { type: "language"; language: string | null; supported: boolean }
  | { type: "citation"; [key: string]: unknown }
  | { type: "fact_citation"; [key: string]: unknown }
  | { type: "voice"; available: boolean; reason: string | null }
  | { type: "confirmation"; required: boolean }
  | { type: "status"; status: "listening" | "completed" | "failed" };

export function parseVoiceEvent(raw: string): VoiceChannelEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  if (typeof (parsed as { type?: unknown }).type !== "string") return null;
  return parsed as VoiceChannelEvent;
}

/** Every local fact the composer's state machine reacts to, alongside a
 * parsed channel event. `mic_denied`/`mic_no_device`/`mic_error` and
 * `capture_started`/`capture_ended` are real local actions (permission
 * actually resolved, audio actually flowing or actually stopped) —
 * never fabricated ahead of the fact that produced them. */
export type VoiceControlAction =
  | { kind: "mic_denied" }
  | { kind: "mic_no_device" }
  | { kind: "mic_error" }
  | { kind: "capture_started" }
  | { kind: "capture_ended" }
  | { kind: "connection_lost" }
  | { kind: "stop_pressed" }
  | { kind: "channel_event"; event: VoiceChannelEvent };

/** Whether pressing-and-holding the mic may start a new turn right now
 * (`docs/ux/voice.md` §5 "user speaks over the answer": nothing happens).
 * Pure so `startCapture`'s guard is covered without a browser —
 * `M6-VUI-FE-133`, closing issue 463. */
export function canStartCapture(status: VoiceStatus): boolean {
  return status.state === "idle";
}

/** Whether the stop control is live right now (`docs/ux/voice.md` §4 #13:
 * a visible stop control, no barge-in). Visible, and only meaningful,
 * while an answer is actually being generated or spoken — before that
 * there is nothing running to stop, and once a turn has already returned
 * to idle a second press is inert by construction rather than needing its
 * own re-entrancy flag. */
export function canStop(status: VoiceStatus): boolean {
  return status.state === "answering";
}

/**
 * The composer's state machine — the four base states this ticket owns.
 * `docs/ux/voice.md` §5's own validation rule: state is derived from a real
 * local action or a real channel event, never shown optimistically ahead of
 * one.
 */
export function nextVoiceStatus(current: VoiceStatus, action: VoiceControlAction): VoiceStatus {
  switch (action.kind) {
    case "mic_denied":
      return { state: "idle", reason: MIC_PERMISSION_DENIED_REASON };
    case "mic_no_device":
      return { state: "idle", reason: MIC_NO_DEVICE_REASON };
    case "mic_error":
      return { state: "idle", reason: MIC_UNAVAILABLE_REASON };
    case "capture_started":
      return { state: "listening", reason: null };
    case "capture_ended":
      // Only a real transition: releasing the mic while it was never
      // actually listening (a stray pointerup) changes nothing.
      return current.state === "listening" ? { state: "transcribing", reason: null } : current;
    case "connection_lost":
      return current.state === "idle" ? current : { state: "idle", reason: VOICE_CONNECTION_LOST_REASON };
    case "stop_pressed":
      // Only a real transition: not visible/live outside `answering`
      // (`canStop`), so a second press — or a stray one after the turn
      // already finished on its own — changes nothing.
      return canStop(current) ? { state: "idle", reason: VOICE_STOPPED_REASON } : current;
    case "channel_event":
      return nextFromChannelEvent(current, action.event);
    default:
      return current;
  }
}

function nextFromChannelEvent(current: VoiceStatus, event: VoiceChannelEvent): VoiceStatus {
  if (event.type === "text") {
    // The first answer token is the real signal that generation started —
    // `transcript` deltas never mean this on their own, a turn can emit
    // several before the answer begins. This also covers leaving
    // `confirming`: generation only ever starts server-side once
    // `askwell.voice_stt` has a confirmed or edited transcript to answer,
    // so the first `text` event is as real a signal there as anywhere else.
    return current.state === "answering" ? current : { state: "answering", reason: null };
  }
  if (event.type === "confirmation" && event.required) {
    // `askwell.voice_stt` is holding this turn below the confidence
    // threshold (`M6-STT-FE-129`, `docs/ux/voice.md` §5 "Low confidence") —
    // shown instead of a plain `transcribing` state, with generation not
    // yet asked for.
    return { state: "confirming", reason: null };
  }
  if (event.type === "language" && !event.supported) {
    // `askwell.voice_stt`'s `unsupported_language` outcome: no transcript,
    // no answer, the turn just ends. Stated unconditionally — this is a
    // real fact about *this* turn regardless of what state it interrupts.
    return { state: "idle", reason: VOICE_NON_ENGLISH_REASON };
  }
  if (event.type === "status") {
    if (event.status === "failed") return { state: "idle", reason: VOICE_FAILED_REASON };
    if (event.status === "completed") {
      // The `language` event above always lands before the closing
      // `status: "completed"` the server sends for the same turn
      // (`askwell.voice_stt`'s own ordering) — this only preserves a reason
      // that was just set for *this* turn's own idle transition, never a
      // stale one, since every other state this switch can be in carries
      // `reason: null` by construction (`VoiceStatus`'s own invariant).
      return current.state === "idle" && current.reason !== null ? current : VOICE_IDLE;
    }
  }
  return current;
}

/**
 * Latency budget from end of speech to first audio (`docs/ux/voice.md` §1,
 * `M6-VUI-FE-134`): 3.5s on `accelerated`, 8s on every other profile —
 * `standard`, `light`, `workstation` and unknown alike, since only
 * `accelerated` and `standard` have a stated figure. An unknown profile
 * getting the `standard` budget is itself the ticket's own edge case.
 */
export const VOICE_LATENCY_BUDGET_ACCELERATED_MS = 3500;
export const VOICE_LATENCY_BUDGET_STANDARD_MS = 8000;

export function voiceLatencyBudgetMs(tier: string | null): number {
  return tier === "accelerated" ? VOICE_LATENCY_BUDGET_ACCELERATED_MS : VOICE_LATENCY_BUDGET_STANDARD_MS;
}

/** Reassures rather than alarms — the ticket's own copy requirement. */
export const VOICE_LATENCY_COPY = "Taking longer than usual…";

/**
 * Local-only tally of budget misses (C1: nothing transmitted), kept for
 * later measurement rather than sent anywhere. Module-level rather than
 * component state so it survives `MicControl` remounting mid-session.
 */
let voiceLatencyBudgetMissCount = 0;

export function recordVoiceLatencyBudgetMiss(): void {
  voiceLatencyBudgetMissCount += 1;
}

export function getVoiceLatencyBudgetMissCount(): number {
  return voiceLatencyBudgetMissCount;
}

export function resetVoiceLatencyBudgetMissCountForTests(): void {
  voiceLatencyBudgetMissCount = 0;
}

/**
 * Local-only tally of confirmations (`M6-STT-FE-129`'s own Analytics
 * Events requirement, C1: nothing transmitted) — how often the low-
 * confidence gate actually fires, kept for later measurement of whether
 * `stt_confirmation_confidence_threshold` is tuned right (the ticket's own
 * Assumption: "if it fires on most turns, the threshold is wrong"). Counts
 * every resolution — a plain `confirm` and an `edit` both mean the gate
 * did its job, so both count. Module-level for the same reason the latency
 * counter above is: it must survive `MicControl` remounting mid-session.
 */
let voiceConfirmationCount = 0;

export function recordVoiceConfirmation(): void {
  voiceConfirmationCount += 1;
}

export function getVoiceConfirmationCount(): number {
  return voiceConfirmationCount;
}

export function resetVoiceConfirmationCountForTests(): void {
  voiceConfirmationCount = 0;
}

/**
 * Live level meter + elapsed time while listening (`docs/ux/voice.md` §2,
 * §5, `M6-VUI-FE-132`). Kept pure and separate from `voice-control.tsx` for
 * the same reason the rest of this module is: testable without a browser.
 */

/** RMS of one capture buffer, 0..1. Cheap enough to run on every
 * `onaudioprocess` callback (~11/s at the default 4096-sample buffer) —
 * no windowing or smoothing, a meter does not need broadcast-quality
 * ballistics. */
export function rmsLevel(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sumSquares = 0;
  for (let i = 0; i < samples.length; i++) {
    const sample = samples[i] ?? 0;
    sumSquares += sample * sample;
  }
  return Math.min(1, Math.sqrt(sumSquares / samples.length));
}

/** Below this RMS, a buffer counts as silence — a muted system mic still
 * delivers real callbacks, just all at or near zero. */
export const MIC_LEVEL_SILENCE_THRESHOLD = 0.01;

/** How long the mic can stay silent while listening before the interface
 * says so, rather than continuing to claim it is listening (the ticket's
 * own edge case: "the interface says the microphone appears silent rather
 * than pretending to listen"). Long enough that a person taking a breath
 * mid-sentence never trips it. */
export const MIC_SILENCE_WARNING_MS = 1500;

export const MIC_SILENT_REASON = "Your microphone appears silent — check that it isn't muted.";

/** Pure: given how long it has been since the last audible buffer, is this
 * still just "listening", or has it gone silent long enough to say so. */
export function micAppearsSilent(msSinceAudible: number): boolean {
  return msSinceAudible >= MIC_SILENCE_WARNING_MS;
}

/** `m:ss`, unbounded minutes — the ticket's own edge case ("a very long
 * listening period — elapsed time keeps counting rather than resetting")
 * ruled out anything that wraps at 60 minutes or rolls over to hours. */
export function formatElapsed(elapsedMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function voiceSocketUrl(location: { protocol: string; host: string }): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/voice/ws`;
}

/** 16 kHz mono PCM16 little-endian — fixed by `askwell.voice.transcribe`'s
 * own docstring, referenced from `askwell.voice_channel`. */
export const VOICE_CAPTURE_SAMPLE_RATE = 16000;

/** Kokoro's own output rate (`askwell.voice_channel`'s `VoiceTurn.audio_out`
 * docstring: "24 kHz for the bundled model"). Nothing on the wire states the
 * rate, so this is a fixed assumption to revisit alongside the model. */
export const VOICE_PLAYBACK_SAMPLE_RATE = 24000;

/** Box-filter decimation from the device's native rate down to 16 kHz —
 * adequate for VAD and STT, and the simplest resampler that does not alias
 * as badly as nearest-neighbour would. A no-op when the device is already
 * at 16 kHz. */
export function downsampleTo16k(input: Float32Array, inputSampleRate: number): Float32Array {
  if (inputSampleRate === VOICE_CAPTURE_SAMPLE_RATE) return input;
  const ratio = inputSampleRate / VOICE_CAPTURE_SAMPLE_RATE;
  const outputLength = Math.round(input.length / ratio);
  const output = new Float32Array(outputLength);
  let inStart = 0;
  for (let outIndex = 0; outIndex < outputLength; outIndex++) {
    const inEnd = Math.round((outIndex + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (let i = inStart; i < inEnd && i < input.length; i++) {
      sum += input[i] ?? 0;
      count++;
    }
    output[outIndex] = count > 0 ? sum / count : 0;
    inStart = inEnd;
  }
  return output;
}

export function floatTo16BitPCM(input: Float32Array): Int16Array<ArrayBuffer> {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const clamped = Math.max(-1, Math.min(1, input[i] ?? 0));
    output[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return output;
}

/** One outgoing audio frame: the device's own capture buffer, downsampled
 * and quantised to exactly what `askwell.voice_channel`'s receive loop
 * expects on the wire. */
export function encodeAudioFrame(input: Float32Array, inputSampleRate: number): ArrayBuffer {
  const pcm = floatTo16BitPCM(downsampleTo16k(input, inputSampleRate));
  return pcm.buffer;
}

/** The inverse, for the audio this channel sends back. */
export function pcm16ToFloat32(buffer: ArrayBuffer): Float32Array<ArrayBuffer> {
  const view = new DataView(buffer);
  const length = Math.floor(buffer.byteLength / 2);
  const output = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    output[i] = view.getInt16(i * 2, true) / 0x8000;
  }
  return output;
}
