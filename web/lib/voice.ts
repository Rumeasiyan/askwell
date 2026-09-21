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

export type VoiceState = "idle" | "listening" | "transcribing" | "answering";

export interface VoiceStatus {
  state: VoiceState;
  /** Set only on `idle` — why voice stopped, or why it never started. Never
   * set on the other three states: they are only ever reached because
   * something is actually happening, so there is nothing to explain. */
  reason: string | null;
}

export const VOICE_IDLE: VoiceStatus = { state: "idle", reason: null };

export const MIC_PERMISSION_DENIED_REASON =
  "Microphone access was denied. Allow it in your browser's site settings to use voice.";
export const MIC_NO_DEVICE_REASON = "No microphone was found on this device.";
export const MIC_UNAVAILABLE_REASON = "The microphone could not be started.";
export const VOICE_CONNECTION_LOST_REASON = "The connection to Askwell was lost. Try again.";
export const VOICE_FAILED_REASON = "Askwell could not answer that.";

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
  | { kind: "channel_event"; event: VoiceChannelEvent };

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
    // several before the answer begins.
    return current.state === "answering" ? current : { state: "answering", reason: null };
  }
  if (event.type === "status") {
    if (event.status === "failed") return { state: "idle", reason: VOICE_FAILED_REASON };
    if (event.status === "completed") return VOICE_IDLE;
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
