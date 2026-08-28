/**
 * The SSE parsing, streaming and English-only heuristic that back the Ask
 * screen. `M1-ASK-FE-039`.
 *
 * The wire format tested here is `askwell.ask._sse`'s own output
 * (`api/src/askwell/ask.py`): `event: <kind>\ndata: <json>\n\n`. A change to
 * either side that drifts from the other is exactly what these tests exist
 * to catch — it would otherwise surface only as a silent, empty answer.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { looksNonEnglish, nextToDispatch, parseSseFrame, readSseEvents } from "./ask.ts";

// --- parseSseFrame -----------------------------------------------------------

test("a step frame parses with its label and kind", () => {
  const event = parseSseFrame(
    'event: step\ndata: {"message_id": "m1", "label": "Searching your files.", "kind": "retrieve"}',
  );
  assert.deepEqual(event, {
    event: "step",
    data: { message_id: "m1", label: "Searching your files.", kind: "retrieve" },
  });
});

test("a token frame parses with its text", () => {
  const event = parseSseFrame('event: token\ndata: {"message_id": "m1", "text": "Meridian"}');
  assert.deepEqual(event, { event: "token", data: { message_id: "m1", text: "Meridian" } });
});

test("a citation frame parses with its chunk", () => {
  const event = parseSseFrame(
    'event: citation\ndata: {"message_id": "m1", "index": 1, "chunk_id": "c1", ' +
      '"document_id": "d1", "page_from": 3, "page_to": 3}',
  );
  assert.deepEqual(event, {
    event: "citation",
    data: { message_id: "m1", index: 1, chunk_id: "c1", document_id: "d1", page_from: 3, page_to: 3 },
  });
});

test("a done frame parses with status and reason", () => {
  const event = parseSseFrame(
    'event: done\ndata: {"message_id": "m1", "status": "completed", "reason": null}',
  );
  assert.deepEqual(event, {
    event: "done",
    data: { message_id: "m1", status: "completed", reason: null },
  });
});

test("an event kind this screen does not know parses to null rather than throwing", () => {
  assert.equal(parseSseFrame('event: ping\ndata: {}'), null);
});

test("a frame with no data line is null, not a parse error", () => {
  assert.equal(parseSseFrame("event: step"), null);
});

// --- readSseEvents -----------------------------------------------------------

/** A `Response` whose body delivers the given chunks, one `read()` at a time. */
function responseFromChunks(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream);
}

test("events split across several chunks still parse whole", async () => {
  // A frame's boundary lands mid-chunk here on purpose — the point is that
  // the parser buffers rather than assuming one network read is one frame.
  const response = responseFromChunks([
    'event: step\ndata: {"message_id": "m1", "l',
    'abel": "Searching your files.", "kind": "retrieve"}\n\nevent: token\nda',
    'ta: {"message_id": "m1", "text": "Hi"}\n\n',
  ]);
  const events = [];
  for await (const event of readSseEvents(response)) events.push(event);
  assert.equal(events.length, 2);
  assert.equal(events[0]?.event, "step");
  assert.equal(events[1]?.event, "token");
});

test("a stream with nothing in it yields no events", async () => {
  const response = responseFromChunks([]);
  const events = [];
  for await (const event of readSseEvents(response)) events.push(event);
  assert.equal(events.length, 0);
});

test("a done event ends the sequence naturally, and iteration reflects it", async () => {
  const response = responseFromChunks([
    'event: step\ndata: {"message_id": "m1", "label": "Searching your files.", "kind": "retrieve"}\n\n' +
      'event: done\ndata: {"message_id": "m1", "status": "completed", "reason": null}\n\n',
  ]);
  const events = [];
  for await (const event of readSseEvents(response)) events.push(event);
  assert.equal(events.length, 2);
  assert.equal(events[1]?.event, "done");
});

// --- nextToDispatch: queued, not interleaved (conversation.md §5) -----------

test("a lone queued turn is dispatched", () => {
  const turns = [{ id: "a", status: "queued" }];
  assert.equal(nextToDispatch(turns), "a");
});

test("nothing dispatches while a turn is already running", () => {
  const turns = [
    { id: "a", status: "running" },
    { id: "b", status: "queued" },
  ];
  assert.equal(nextToDispatch(turns), null);
});

test("a second question asked mid-answer waits its turn, first in first out", () => {
  const turns = [
    { id: "a", status: "running" },
    { id: "b", status: "queued" },
    { id: "c", status: "queued" },
  ];
  // Nothing dispatches yet — one answer at a time.
  assert.equal(nextToDispatch(turns), null);
  // Once "a" finishes, "b" is next — not "c", and not both at once.
  const afterFirstFinishes = turns.map((turn) => (turn.id === "a" ? { ...turn, status: "completed" } : turn));
  assert.equal(nextToDispatch(afterFirstFinishes), "b");
});

test("nothing queued and nothing running dispatches nothing", () => {
  assert.equal(nextToDispatch([{ id: "a", status: "completed" }]), null);
});

// --- looksNonEnglish ---------------------------------------------------------

test("an ordinary English question is not flagged", () => {
  assert.equal(looksNonEnglish("What are the payment terms with Meridian?"), false);
});

test("a short question with one non-Latin word is not flagged", () => {
  assert.equal(looksNonEnglish("What does élite mean here?"), false);
});

test("a question written in a non-Latin script is flagged", () => {
  // Tamil: "when will the goods arrive?"
  assert.equal(looksNonEnglish("பொருட்கள் எப்போத் வரும்?"), true);
});

test("too few letters to judge is not flagged", () => {
  assert.equal(looksNonEnglish("42?"), false);
});
