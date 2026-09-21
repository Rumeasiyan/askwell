"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  encodeAudioFrame,
  nextVoiceStatus,
  parseVoiceEvent,
  pcm16ToFloat32,
  voiceSocketUrl,
  VOICE_IDLE,
  VOICE_PLAYBACK_SAMPLE_RATE,
  type VoiceStatus,
} from "@/lib/voice";

/**
 * The mic control and the voice composer's base state machine
 * (`docs/ux/voice.md` §2, §3, §5 — the four base states only).
 * `M6-VUI-FE-128a`.
 *
 * Replaces the Phase 1 stub (`M1-ASK-FE-039a`): `getUserMedia` capture, a
 * `WebSocket` against `askwell.voice_channel` (`/voice/ws`), and
 * idle/listening/transcribing/answering as the one state every dependent
 * ticket (`M6-STT-FE-129`'s low-confidence confirmation; `M6-VUI-FE-132`
 * through `135`'s level meter, stop control and latency indicator) reads
 * and extends. All the wire parsing and PCM conversion this needs is pure
 * and lives in `lib/voice.ts`, testable without a browser; this file is only
 * the browser API wiring around it.
 *
 * **Push-to-talk** (`voice.md` §7, settled for v1): holding the button is
 * what makes "transcribing" an honest state rather than a guess — releasing
 * is a real local fact (capture actually stopped), where waiting for the
 * server's own VAD pause (`M6-STT-BE-128`) to say so would leave the
 * composer unable to show anything between "still listening" and "here is
 * the transcript" at all.
 *
 * **Rendering the transcript and answer into the conversation itself is not
 * this ticket's scope.** `AskProvider` (`ask-state.tsx`) only knows how to
 * drive a turn through `POST /ask`; a voice turn arrives over its own
 * socket with its own `turn_id` and never touches that path, and folding
 * the two together is a real design decision (how a voice turn's transcript
 * becomes a question in the same conversation `AskProvider` tracks, and how
 * `conversation_id` threading — issue 156 — interacts with it) that
 * belongs to its own ticket rather than a guess made here. Filed as issue
 * https://github.com/Rumeasiyan/askwell/issues/460. This control shows the
 * transcript and answer text itself, in place, which is enough for every
 * state transition in this ticket's acceptance criteria to be observable.
 */
export function MicControl() {
  const [status, setStatus] = useState<VoiceStatus>(VOICE_IDLE);
  const [transcript, setTranscript] = useState("");
  const [answer, setAnswer] = useState("");
  // Handlers created once (in `onopen`/`onmessage`) close over whatever
  // `status` was at creation time unless they read a ref instead — the same
  // stale-closure fix `ask-screen.tsx`'s `Composer` already applies to its
  // own `value`.
  const statusRef = useRef(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const streamRef = useRef<MediaStream | null>(null);
  const captureContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const playCursorRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);

  const teardownCapture = useCallback((): void => {
    processorRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    const context = captureContextRef.current;
    captureContextRef.current = null;
    if (context !== null && context.state !== "closed") void context.close();
  }, []);

  const teardownPlayback = useCallback((): void => {
    const context = playbackContextRef.current;
    playbackContextRef.current = null;
    playCursorRef.current = 0;
    if (context !== null && context.state !== "closed") void context.close();
  }, []);

  const closeSocket = useCallback((): void => {
    const socket = socketRef.current;
    socketRef.current = null;
    if (socket !== null && socket.readyState <= WebSocket.OPEN) socket.close();
  }, []);

  // Unmounting mid-turn must not leave a mic open or a socket dangling —
  // the Ask screen persists across the app (`ask-state.tsx`'s own reason for
  // living above the router), but this control does not have to.
  useEffect(
    () => () => {
      teardownCapture();
      teardownPlayback();
      closeSocket();
    },
    [teardownCapture, teardownPlayback, closeSocket],
  );

  const playAudioChunk = useCallback((chunk: ArrayBuffer): void => {
    if (playbackContextRef.current === null || playbackContextRef.current.state === "closed") {
      const AudioContextCtor: typeof AudioContext =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      playbackContextRef.current = new AudioContextCtor({ sampleRate: VOICE_PLAYBACK_SAMPLE_RATE });
      playCursorRef.current = 0;
    }
    const context = playbackContextRef.current;
    const floats = pcm16ToFloat32(chunk);
    if (floats.length === 0) return;
    const buffer = context.createBuffer(1, floats.length, VOICE_PLAYBACK_SAMPLE_RATE);
    buffer.copyToChannel(floats, 0);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    // One queued chunk is one synthesized sentence (`askwell.voice_channel`'s
    // own docstring) — scheduling each after the last keeps sentences in
    // order without ever overlapping or leaving a gap.
    const startAt = Math.max(context.currentTime, playCursorRef.current);
    source.start(startAt);
    playCursorRef.current = startAt + buffer.duration;
  }, []);

  const handleChannelMessage = useCallback(
    (event: MessageEvent<string | ArrayBuffer>): void => {
      if (typeof event.data !== "string") {
        playAudioChunk(event.data);
        return;
      }
      const parsed = parseVoiceEvent(event.data);
      if (parsed === null) return;
      if (parsed.type === "transcript") setTranscript((current) => current + parsed.text);
      if (parsed.type === "text") setAnswer((current) => current + parsed.text);
      setStatus((current) => nextVoiceStatus(current, { kind: "channel_event", event: parsed }));
      if (parsed.type === "status") {
        teardownCapture();
        teardownPlayback();
        closeSocket();
      }
    },
    [playAudioChunk, teardownCapture, teardownPlayback, closeSocket],
  );

  const handleConnectionLost = useCallback((): void => {
    teardownCapture();
    teardownPlayback();
    closeSocket();
    // Only a real drop: a clean close *after* `status` already returned the
    // composer to idle is not a lost connection, it is the turn finishing
    // (`voice.md` §5's "Connection drops mid-turn" is specifically the
    // other case — while a turn is still live).
    setStatus((current) => nextVoiceStatus(current, { kind: "connection_lost" }));
  }, [teardownCapture, teardownPlayback, closeSocket]);

  const startCapture = useCallback(async (): Promise<void> => {
    // A press while transcribing or answering is ignored, not a second
    // socket (the ticket's own acceptance criterion) — and idle is the only
    // state this function knows how to leave.
    if (statusRef.current.state !== "idle") return;
    if (navigator.mediaDevices?.getUserMedia === undefined) {
      setStatus(nextVoiceStatus(statusRef.current, { kind: "mic_error" }));
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (error) {
      const name = error instanceof DOMException ? error.name : "";
      const kind =
        name === "NotAllowedError" || name === "PermissionDeniedError"
          ? "mic_denied"
          : name === "NotFoundError" || name === "OverconstrainedError"
            ? "mic_no_device"
            : "mic_error";
      setStatus(nextVoiceStatus(statusRef.current, { kind }));
      return;
    }
    // A second press could have landed while permission was being asked —
    // still guarded against a stray socket, this time with a stream to
    // release again rather than never having opened one.
    if (statusRef.current.state !== "idle") {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    streamRef.current = stream;
    setTranscript("");
    setAnswer("");

    const socket = new WebSocket(voiceSocketUrl(window.location));
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;

    socket.onopen = (): void => {
      const AudioContextCtor: typeof AudioContext =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const captureContext = new AudioContextCtor();
      captureContextRef.current = captureContext;
      const source = captureContext.createMediaStreamSource(stream);
      sourceRef.current = source;
      const processor = captureContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      processor.onaudioprocess = (audioEvent): void => {
        if (socketRef.current?.readyState !== WebSocket.OPEN) return;
        const input = audioEvent.inputBuffer.getChannelData(0);
        socketRef.current.send(encodeAudioFrame(input, captureContext.sampleRate));
      };
      source.connect(processor);
      // A muted node between the processor and the destination: some
      // browsers stop calling `onaudioprocess` once a node has no path to
      // the destination at all, and connecting straight to the destination
      // would feed the mic back out of the speakers.
      const silence = captureContext.createGain();
      silence.gain.value = 0;
      processor.connect(silence);
      silence.connect(captureContext.destination);
      setStatus(nextVoiceStatus(statusRef.current, { kind: "capture_started" }));
    };
    socket.onmessage = handleChannelMessage;
    socket.onerror = handleConnectionLost;
    socket.onclose = handleConnectionLost;
  }, [handleChannelMessage, handleConnectionLost]);

  const stopCapture = useCallback((): void => {
    if (statusRef.current.state !== "listening") return;
    teardownCapture();
    const socket = socketRef.current;
    if (socket !== null && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "end" }));
    }
    setStatus(nextVoiceStatus(statusRef.current, { kind: "capture_ended" }));
  }, [teardownCapture]);

  const label = statusLabel(status, transcript, answer);
  const busy = status.state === "transcribing" || status.state === "answering";

  return (
    <span className="ask-mic-wrap">
      <button
        type="button"
        aria-pressed={status.state === "listening"}
        aria-describedby="ask-mic-reason"
        aria-label={busy ? label : "Voice input — press and hold to speak"}
        data-voice-state={status.state}
        className="ask-mic-control"
        onPointerDown={(event) => {
          event.preventDefault();
          void startCapture();
        }}
        onPointerUp={stopCapture}
        onPointerLeave={stopCapture}
        onPointerCancel={stopCapture}
      >
        <MicIcon />
        <span className="ask-sr-only">Voice input</span>
      </button>
      <span role="tooltip" id="ask-mic-reason" className="ask-mic-reason" aria-live="polite">
        {label}
      </span>
    </span>
  );
}

function statusLabel(status: VoiceStatus, transcript: string, answer: string): string {
  switch (status.state) {
    case "listening":
      return "Listening…";
    case "transcribing":
      return transcript.trim() === "" ? "Transcribing…" : transcript;
    case "answering":
      return answer.trim() === "" ? "Answering…" : answer;
    case "idle":
    default:
      return status.reason ?? "Press and hold to speak";
  }
}

function MicIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      aria-hidden="true"
    >
      <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" />
      <path d="M3 8.5a5 5 0 0 0 10 0" strokeLinecap="round" />
      <path d="M8 13.5v1.5" strokeLinecap="round" />
    </svg>
  );
}
