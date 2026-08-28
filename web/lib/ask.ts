/**
 * One turn, over server-sent events. `M1-ASK-FE-039`.
 *
 * `POST /ask` (`askwell.ask`, `M1-ASK-API-038`) answers with a
 * `text/event-stream` body rather than one JSON response, so this is a
 * `fetch` read against `response.body`, not `EventSource` — the browser's own
 * `EventSource` only ever issues `GET`, and a question is a `POST` body, not
 * a query string. `readSseEvents` is the parser both this module and, later,
 * a reconnect against `GET /ask/{message_id}/stream` can share; only the
 * request that opens the stream differs.
 *
 * Four event kinds, matching the server exactly (`askwell.ask._Event`):
 * `step` before and during retrieval, `token` as the answer is generated,
 * `citation` as the model's own `[index]` references resolve, `done` once.
 */

export interface AskStepData {
  message_id: string;
  label: string;
  kind: string;
}

export interface AskTokenData {
  message_id: string;
  text: string;
}

export interface AskCitationData {
  message_id: string;
  index: number;
  claim_ordinal: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  anchor_kind: string | null;
  heading: string | null;
  page_from: number | null;
  page_to: number | null;
  passage: string;
  quoted_span: string | null;
}

export type AskStatus = "completed" | "stopped" | "failed";

export interface AskDoneData {
  message_id: string;
  status: AskStatus;
  reason: string | null;
}

export type AskEvent =
  | { event: "step"; data: AskStepData }
  | { event: "token"; data: AskTokenData }
  | { event: "citation"; data: AskCitationData }
  | { event: "done"; data: AskDoneData };

/**
 * One `event:`/`data:` block, already split from the stream on a blank line.
 * Returns `null` for a frame naming an event kind this screen does not act
 * on (a keep-alive comment, say) rather than throwing — a stream outliving
 * this module's knowledge of every event the server might ever add is not a
 * parse failure.
 */
export function parseSseFrame(frame: string): AskEvent | null {
  let eventName: string | null = null;
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  if (eventName === null || dataLines.length === 0) return null;

  const data: unknown = JSON.parse(dataLines.join("\n"));
  switch (eventName) {
    case "step":
      return { event: "step", data: data as AskStepData };
    case "token":
      return { event: "token", data: data as AskTokenData };
    case "citation":
      return { event: "citation", data: data as AskCitationData };
    case "done":
      return { event: "done", data: data as AskDoneData };
    default:
      return null;
  }
}

/**
 * Read every event out of an SSE response body as it arrives.
 *
 * Frames are separated by a blank line (`\n\n`), per the SSE wire format
 * `askwell.ask._sse` writes. Buffering rather than assuming one chunk is one
 * frame: a `TextDecoderStream`-free `fetch` body delivers whatever the
 * network happened to batch, which is not the same thing.
 */
export async function* readSseEvents(response: Response): AsyncGenerator<AskEvent> {
  if (response.body === null) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseSseFrame(frame);
        if (event !== null) yield event;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Ask one question and call back with every event as it streams.
 *
 * Resolves once the connection ends — on `done`, or because the browser (not
 * the server, which keeps generating regardless, `askwell.ask`'s own module
 * docstring) closed it. Throws only for a request `POST /ask` itself refused
 * (an unknown `conversation_id`, an empty question past validation) — a
 * failure *during* generation arrives as an ordinary `done` event with
 * `status: "failed"`, never a rejection.
 */
export async function streamAsk(
  question: string,
  options: { conversationId: string | null; sourceId?: string | null; signal?: AbortSignal },
  onEvent: (event: AskEvent) => void,
): Promise<void> {
  const response = await fetch("/ask", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      question,
      conversation_id: options.conversationId,
      source_id: options.sourceId ?? null,
    }),
    ...(options.signal ? { signal: options.signal } : {}),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered ${response.status} to that question.`);
  }
  for await (const event of readSseEvents(response)) {
    onEvent(event);
  }
}

/** Ends generation early. A 404 means the turn already finished — not an error to surface. */
export async function stopAsk(messageId: string): Promise<void> {
  const response = await fetch(`/ask/${messageId}/stop`, { method: "POST" });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Askwell answered ${response.status} to stop.`);
  }
}

/**
 * Which queued turn, if any, should start streaming next.
 *
 * Pure so "queued, not interleaved" (`conversation.md` §5) is checkable
 * without a browser: `null` whenever a turn is already `running` — one
 * answer at a time — otherwise the earliest `queued` turn, first in first
 * out, or `null` if nothing is waiting.
 */
export function nextToDispatch<T extends { id: string; status: string }>(
  turns: readonly T[],
): string | null {
  if (turns.some((turn) => turn.status === "running")) return null;
  return turns.find((turn) => turn.status === "queued")?.id ?? null;
}

/**
 * A heuristic, not a language detector.
 *
 * No language identification runs anywhere in Askwell yet (v1 is
 * English-only by scope, `AGENTS.md` §1) and adding one is out of this
 * ticket's reach — `docs/ux/ask.md` §5 still needs *something* said rather
 * than a poor answer attempted. This catches the unambiguous case, a
 * question written in a non-Latin script, the same reasoning
 * `extract_ocr.py`'s own script-based routing already relies on. It does
 * **not** catch a question written in French or German — those pass through
 * un-flagged, same as any other v1 gap. Revisit once real usage shows this
 * matters, rather than reaching for a detection library nothing else here
 * depends on.
 */
export function looksNonEnglish(question: string): boolean {
  const letters = question.match(/\p{L}/gu);
  if (letters === null || letters.length < 4) return false;
  const nonLatin = letters.filter((letter) => !/[\p{Script=Latin}]/u.test(letter));
  return nonLatin.length / letters.length > 0.3;
}


/**
 * One turn, after one streamed event has been applied to it.
 *
 * Pure, and separated from the component for the reason the bug that produced
 * it was possible at all. The first version of this read the turn out of a ref
 * that an effect refreshed after each render, so two tokens arriving in the
 * same frame both read the same `answer` and the second overwrote the first —
 * an answer silently missing words, with nothing on screen or in any log
 * saying so. React can batch, coalesce and replay updates whenever it likes;
 * the only durable fix is to derive the next turn from the previous *turn*
 * rather than from a snapshot taken at some other moment.
 *
 * The `citation` kind is deliberately not handled here — grouping one into
 * a provenance card is `applyCitation` (`lib/citations.ts`)'s job, kept in
 * its own module rather than folded in here to avoid this file importing
 * `CitationCard` for a kind it does nothing else with.
 */
export function applyAskEvent<T extends AskTurnState>(
  turn: T,
  event: AskEvent,
): Partial<AskTurnState> {
  switch (event.event) {
    case "step":
      return {
        serverId: turn.serverId ?? event.data.message_id,
        steps: [...turn.steps, { label: event.data.label, kind: event.data.kind }],
      };
    case "token":
      return { answer: turn.answer + event.data.text };
    default:
      return {};
  }
}

/** The part of a turn `applyAskEvent` reads and writes. */
export interface AskTurnState {
  serverId: string | null;
  steps: { label: string; kind: string }[];
  answer: string;
}
