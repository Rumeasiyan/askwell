/**
 * The voice composer's state machine and wire helpers. `M6-VUI-FE-128a`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canStartCapture,
  canStop,
  downsampleTo16k,
  encodeAudioFrame,
  floatTo16BitPCM,
  formatElapsed,
  getVoiceConfirmationCount,
  getVoiceLatencyBudgetMissCount,
  micAppearsSilent,
  micPermissionReason,
  MIC_LEVEL_SILENCE_THRESHOLD,
  MIC_NO_DEVICE_REASON,
  MIC_PERMISSION_DENIED_REASON,
  MIC_SILENCE_WARNING_MS,
  MIC_UNAVAILABLE_REASON,
  nextVoiceStatus,
  parseVoiceEvent,
  pcm16ToFloat32,
  recordVoiceConfirmation,
  recordVoiceLatencyBudgetMiss,
  resetVoiceConfirmationCountForTests,
  resetVoiceLatencyBudgetMissCountForTests,
  rmsLevel,
  voiceLatencyBudgetMs,
  VOICE_CONNECTION_LOST_REASON,
  VOICE_FAILED_REASON,
  VOICE_IDLE,
  VOICE_NON_ENGLISH_REASON,
  voiceSocketUrl,
  VOICE_STOPPED_REASON,
} from "./voice.ts";

// --- parseVoiceEvent ---------------------------------------------------------

test("a transcript frame parses", () => {
  const event = parseVoiceEvent('{"type": "transcript", "text": "hello"}');
  assert.deepEqual(event, { type: "transcript", text: "hello" });
});

test("malformed JSON parses to null rather than throwing", () => {
  assert.equal(parseVoiceEvent("{not json"), null);
});

test("a frame with no type string parses to null", () => {
  assert.equal(parseVoiceEvent('{"value": 1}'), null);
  assert.equal(parseVoiceEvent("42"), null);
});

// --- voiceSocketUrl -----------------------------------------------------------

test("voiceSocketUrl upgrades http to ws on the same host", () => {
  assert.equal(
    voiceSocketUrl({ protocol: "http:", host: "localhost:8000" }),
    "ws://localhost:8000/voice/ws",
  );
});

test("voiceSocketUrl upgrades https to wss", () => {
  assert.equal(
    voiceSocketUrl({ protocol: "https:", host: "askwell.local" }),
    "wss://askwell.local/voice/ws",
  );
});

// --- nextVoiceStatus: local actions -------------------------------------------

test("permission denied returns idle with the reason stated, from any state", () => {
  const result = nextVoiceStatus(
    { state: "listening", reason: null },
    { kind: "mic_denied" },
  );
  assert.deepEqual(result, { state: "idle", reason: MIC_PERMISSION_DENIED_REASON });
});

test("no input device returns idle with its own reason", () => {
  assert.deepEqual(nextVoiceStatus(VOICE_IDLE, { kind: "mic_no_device" }), {
    state: "idle",
    reason: MIC_NO_DEVICE_REASON,
  });
});

test("an unexpected capture error returns idle with a stated reason", () => {
  assert.deepEqual(nextVoiceStatus(VOICE_IDLE, { kind: "mic_error" }), {
    state: "idle",
    reason: MIC_UNAVAILABLE_REASON,
  });
});

test("audio actually flowing moves idle to listening", () => {
  assert.deepEqual(nextVoiceStatus(VOICE_IDLE, { kind: "capture_started" }), {
    state: "listening",
    reason: null,
  });
});

test("releasing the mic while listening moves to transcribing", () => {
  assert.deepEqual(
    nextVoiceStatus({ state: "listening", reason: null }, { kind: "capture_ended" }),
    { state: "transcribing", reason: null },
  );
});

test("a stray capture_ended outside listening changes nothing — never optimistic", () => {
  const idle = VOICE_IDLE;
  assert.equal(nextVoiceStatus(idle, { kind: "capture_ended" }), idle);
});

test("a second capture_started while already listening is a no-op, not a new state", () => {
  const listening = { state: "listening" as const, reason: null };
  const result = nextVoiceStatus(listening, { kind: "capture_started" });
  assert.deepEqual(result, { state: "listening", reason: null });
});

test("connection_lost from a live state returns idle with the reason stated", () => {
  assert.deepEqual(
    nextVoiceStatus({ state: "answering", reason: null }, { kind: "connection_lost" }),
    { state: "idle", reason: VOICE_CONNECTION_LOST_REASON },
  );
});

test("connection_lost while already idle changes nothing — no reason overwritten", () => {
  const idle = VOICE_IDLE;
  assert.equal(nextVoiceStatus(idle, { kind: "connection_lost" }), idle);
});

// --- nextVoiceStatus: channel events -------------------------------------------

test("the first text delta moves transcribing to answering", () => {
  const result = nextVoiceStatus(
    { state: "transcribing", reason: null },
    { kind: "channel_event", event: { type: "text", text: "The " } },
  );
  assert.deepEqual(result, { state: "answering", reason: null });
});

test("a later text delta while already answering changes nothing", () => {
  const answering = { state: "answering" as const, reason: null };
  const result = nextVoiceStatus(answering, {
    kind: "channel_event",
    event: { type: "text", text: "answer." },
  });
  assert.deepEqual(result, answering);
});

test("a transcript delta alone does not advance past transcribing", () => {
  const transcribing = { state: "transcribing" as const, reason: null };
  const result = nextVoiceStatus(transcribing, {
    kind: "channel_event",
    event: { type: "transcript", text: "hello" },
  });
  assert.equal(result, transcribing);
});

test("a confirmation-required event moves transcribing to confirming", () => {
  const transcribing = { state: "transcribing" as const, reason: null };
  const result = nextVoiceStatus(transcribing, {
    kind: "channel_event",
    event: { type: "confirmation", required: true },
  });
  assert.deepEqual(result, { state: "confirming", reason: null });
});

test("the first text delta moves confirming to answering, same as transcribing", () => {
  const confirming = { state: "confirming" as const, reason: null };
  const result = nextVoiceStatus(confirming, {
    kind: "channel_event",
    event: { type: "text", text: "The " },
  });
  assert.deepEqual(result, { state: "answering", reason: null });
});

test("status completed while confirming (the walked-away timeout) returns to idle", () => {
  const confirming = { state: "confirming" as const, reason: null };
  const result = nextVoiceStatus(confirming, {
    kind: "channel_event",
    event: { type: "status", status: "completed" },
  });
  assert.deepEqual(result, VOICE_IDLE);
});

test("status completed returns to idle with no reason", () => {
  const result = nextVoiceStatus(
    { state: "answering", reason: null },
    { kind: "channel_event", event: { type: "status", status: "completed" } },
  );
  assert.deepEqual(result, VOICE_IDLE);
});

test("status failed returns to idle with a stated reason", () => {
  const result = nextVoiceStatus(
    { state: "answering", reason: null },
    { kind: "channel_event", event: { type: "status", status: "failed" } },
  );
  assert.deepEqual(result, { state: "idle", reason: VOICE_FAILED_REASON });
});

// --- language / non-English speech (`M6-VUI-FE-135`) -------------------------

test("an unsupported-language event ends the turn with the English-only reason", () => {
  const result = nextVoiceStatus(
    { state: "transcribing", reason: null },
    { kind: "channel_event", event: { type: "language", language: "ta", supported: false } },
  );
  assert.deepEqual(result, { state: "idle", reason: VOICE_NON_ENGLISH_REASON });
});

test("the language event overrides listening too — the turn is over regardless of what it interrupts", () => {
  const result = nextVoiceStatus(
    { state: "listening", reason: null },
    { kind: "channel_event", event: { type: "language", language: null, supported: false } },
  );
  assert.deepEqual(result, { state: "idle", reason: VOICE_NON_ENGLISH_REASON });
});

test("status completed after language keeps the English-only reason rather than clearing it", () => {
  const afterLanguage = nextVoiceStatus(
    { state: "transcribing", reason: null },
    { kind: "channel_event", event: { type: "language", language: "ta", supported: false } },
  );
  const afterStatus = nextVoiceStatus(afterLanguage, {
    kind: "channel_event",
    event: { type: "status", status: "completed" },
  });
  assert.deepEqual(afterStatus, { state: "idle", reason: VOICE_NON_ENGLISH_REASON });
});

test("status completed with no prior reason still resets to plain idle", () => {
  const result = nextVoiceStatus(
    { state: "answering", reason: null },
    { kind: "channel_event", event: { type: "status", status: "completed" } },
  );
  assert.deepEqual(result, VOICE_IDLE);
});

// --- micPermissionReason (`M6-VUI-FE-135`) ------------------------------------

test("a denied permission state maps to the explanation and instructions", () => {
  assert.equal(micPermissionReason("denied"), MIC_PERMISSION_DENIED_REASON);
});

test("granted or prompt states have nothing to explain", () => {
  assert.equal(micPermissionReason("granted"), null);
  assert.equal(micPermissionReason("prompt"), null);
  assert.equal(micPermissionReason(null), null);
});

test("a confidence event passes through unchanged — not this ticket's state to change", () => {
  const transcribing = { state: "transcribing" as const, reason: null };
  const result = nextVoiceStatus(transcribing, {
    kind: "channel_event",
    event: { type: "confidence", value: 0.4 },
  });
  assert.equal(result, transcribing);
});

// --- canStartCapture / canStop / stop_pressed (`M6-VUI-FE-133`) ---------------

test("canStartCapture is true only when idle", () => {
  assert.equal(canStartCapture(VOICE_IDLE), true);
  assert.equal(canStartCapture({ state: "listening", reason: null }), false);
  assert.equal(canStartCapture({ state: "transcribing", reason: null }), false);
  assert.equal(canStartCapture({ state: "answering", reason: null }), false);
});

test("canStop is true only while answering", () => {
  assert.equal(canStop(VOICE_IDLE), false);
  assert.equal(canStop({ state: "listening", reason: null }), false);
  assert.equal(canStop({ state: "transcribing", reason: null }), false);
  assert.equal(canStop({ state: "answering", reason: null }), true);
});

test("pressing stop while answering returns idle, marked stopped", () => {
  const result = nextVoiceStatus(
    { state: "answering", reason: null },
    { kind: "stop_pressed" },
  );
  assert.deepEqual(result, { state: "idle", reason: VOICE_STOPPED_REASON });
});

test("pressing stop is inert outside answering — speaking over the answer, or a stray press, does nothing", () => {
  const idle = VOICE_IDLE;
  assert.equal(nextVoiceStatus(idle, { kind: "stop_pressed" }), idle);
  const listening = { state: "listening" as const, reason: null };
  assert.equal(nextVoiceStatus(listening, { kind: "stop_pressed" }), listening);
  const transcribing = { state: "transcribing" as const, reason: null };
  assert.equal(nextVoiceStatus(transcribing, { kind: "stop_pressed" }), transcribing);
});

test("a second stop_pressed once already idle is inert — the second press is a no-op", () => {
  const stopped = nextVoiceStatus(
    { state: "answering", reason: null },
    { kind: "stop_pressed" },
  );
  assert.equal(nextVoiceStatus(stopped, { kind: "stop_pressed" }), stopped);
});

test("speaking over the answer does nothing — canStartCapture blocks a press while answering, matching issue 463", () => {
  const answering = { state: "answering" as const, reason: null };
  // `startCapture` itself early-returns on `!canStartCapture(status)` before
  // ever calling `getUserMedia` — this is that guard's own predicate,
  // tested directly since `web/` has no `.test.tsx` harness to exercise the
  // component itself (docs/decisions.md, this date).
  assert.equal(canStartCapture(answering), false);
});

// --- voiceLatencyBudgetMs ------------------------------------------------------

test("accelerated gets the 3.5s budget", () => {
  assert.equal(voiceLatencyBudgetMs("accelerated"), 3500);
});

test("standard gets the 8s budget", () => {
  assert.equal(voiceLatencyBudgetMs("standard"), 8000);
});

test("an unknown or unrecognised profile falls back to the standard 8s budget", () => {
  assert.equal(voiceLatencyBudgetMs(null), 8000);
  assert.equal(voiceLatencyBudgetMs("light"), 8000);
  assert.equal(voiceLatencyBudgetMs("workstation"), 8000);
});

// --- voice latency budget-miss counter ------------------------------------------

test("recordVoiceLatencyBudgetMiss tallies locally only", () => {
  resetVoiceLatencyBudgetMissCountForTests();
  assert.equal(getVoiceLatencyBudgetMissCount(), 0);
  recordVoiceLatencyBudgetMiss();
  recordVoiceLatencyBudgetMiss();
  assert.equal(getVoiceLatencyBudgetMissCount(), 2);
  resetVoiceLatencyBudgetMissCountForTests();
});

// --- voice confirmation counter (`M6-STT-FE-129`) ------------------------------

test("recordVoiceConfirmation tallies locally only", () => {
  resetVoiceConfirmationCountForTests();
  assert.equal(getVoiceConfirmationCount(), 0);
  recordVoiceConfirmation();
  assert.equal(getVoiceConfirmationCount(), 1);
  resetVoiceConfirmationCountForTests();
});

// --- PCM conversion -----------------------------------------------------------

test("downsampleTo16k is a no-op already at 16 kHz", () => {
  const input = new Float32Array([0.1, 0.2, 0.3]);
  assert.equal(downsampleTo16k(input, 16000), input);
});

test("downsampleTo16k halves the length at 32 kHz", () => {
  const input = new Float32Array(320).fill(0.5);
  const output = downsampleTo16k(input, 32000);
  assert.equal(output.length, 160);
  assert.ok(output.every((sample) => Math.abs(sample - 0.5) < 1e-9));
});

test("floatTo16BitPCM clamps and scales full-scale samples", () => {
  const output = floatTo16BitPCM(new Float32Array([1, -1, 0, 2, -2]));
  assert.deepEqual(Array.from(output), [0x7fff, -0x8000, 0, 0x7fff, -0x8000]);
});

test("encodeAudioFrame produces one Int16 sample per 16 kHz frame", () => {
  const input = new Float32Array(320).fill(0.25);
  const buffer = encodeAudioFrame(input, 32000);
  assert.equal(buffer.byteLength, 160 * 2);
});

test("pcm16ToFloat32 round-trips floatTo16BitPCM within quantisation error", () => {
  const original = new Float32Array([0.5, -0.25, 0, 0.999]);
  const buffer = floatTo16BitPCM(original).buffer;
  const restored = pcm16ToFloat32(buffer);
  for (let i = 0; i < original.length; i++) {
    assert.ok(Math.abs((restored[i] ?? 0) - (original[i] ?? 0)) < 0.001);
  }
});

// --- rmsLevel (M6-VUI-FE-132 level meter) --------------------------------------

test("rmsLevel of silence is zero", () => {
  assert.equal(rmsLevel(new Float32Array(256)), 0);
});

test("rmsLevel of a full-scale constant buffer is 1", () => {
  assert.equal(rmsLevel(new Float32Array(64).fill(1)), 1);
});

test("rmsLevel of an empty buffer is zero, not NaN", () => {
  assert.equal(rmsLevel(new Float32Array(0)), 0);
});

test("rmsLevel never exceeds 1 even past full scale", () => {
  assert.equal(rmsLevel(new Float32Array(8).fill(4)), 1);
});

test("a quiet buffer sits below the silence threshold", () => {
  assert.ok(rmsLevel(new Float32Array(256).fill(0.0001)) < MIC_LEVEL_SILENCE_THRESHOLD);
});

// --- micAppearsSilent -----------------------------------------------------------

test("mic does not appear silent before the warning window elapses", () => {
  assert.equal(micAppearsSilent(MIC_SILENCE_WARNING_MS - 1), false);
});

test("mic appears silent once the warning window has fully elapsed", () => {
  assert.equal(micAppearsSilent(MIC_SILENCE_WARNING_MS), true);
  assert.equal(micAppearsSilent(MIC_SILENCE_WARNING_MS + 5000), true);
});

// --- formatElapsed ----------------------------------------------------------------

test("formatElapsed renders zero as 0:00", () => {
  assert.equal(formatElapsed(0), "0:00");
});

test("formatElapsed pads seconds under ten", () => {
  assert.equal(formatElapsed(65_000), "1:05");
});

test("formatElapsed keeps counting past an hour rather than resetting", () => {
  assert.equal(formatElapsed(3_661_000), "61:01");
});

test("formatElapsed never goes negative", () => {
  assert.equal(formatElapsed(-500), "0:00");
});
