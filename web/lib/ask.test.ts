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

import {
  applyAskEvent,
  conversationOf,
  isAbstained,
  isFirstAnswer,
  type AskTurnState,
  CONVERSATION_PAGE_SIZE,
  conversationWindow,
  dividerLabel,
  liveTurnId,
  looksNonEnglish,
  nextToDispatch,
  parseSseFrame,
  readSseEvents,
} from "./ask.ts";

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

test("a citation frame parses with its chunk and card data", () => {
  const event = parseSseFrame(
    'event: citation\ndata: {"message_id": "m1", "index": 1, "claim_ordinal": 1, ' +
      '"chunk_id": "c1", "document_id": "d1", "filename": "contract.pdf", ' +
      '"anchor_kind": null, "heading": null, "page_from": 3, "page_to": 3, ' +
      '"passage": "Notice is ninety days.", "quoted_span": null}',
  );
  assert.deepEqual(event, {
    event: "citation",
    data: {
      message_id: "m1",
      index: 1,
      claim_ordinal: 1,
      chunk_id: "c1",
      document_id: "d1",
      filename: "contract.pdf",
      anchor_kind: null,
      heading: null,
      page_from: 3,
      page_to: 3,
      passage: "Notice is ninety days.",
      quoted_span: null,
    },
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

// --- conversationWindow: paging older turns in on scroll (conversation.md §5, §7) --

test("fewer turns than the page size shows all of them with nothing more to page in", () => {
  const turns = Array.from({ length: 5 }, (_, i) => ({ id: String(i) }));
  assert.deepEqual(conversationWindow(turns, CONVERSATION_PAGE_SIZE), { turns, hasMore: false });
});

test("exactly the page size shows all of them, still with nothing more", () => {
  const turns = Array.from({ length: CONVERSATION_PAGE_SIZE }, (_, i) => ({ id: String(i) }));
  const result = conversationWindow(turns, CONVERSATION_PAGE_SIZE);
  assert.equal(result.turns.length, CONVERSATION_PAGE_SIZE);
  assert.equal(result.hasMore, false);
});

test("more turns than revealed shows only the newest, and says more remain", () => {
  const turns = Array.from({ length: 25 }, (_, i) => ({ id: String(i) }));
  const result = conversationWindow(turns, 20);
  assert.equal(result.turns.length, 20);
  assert.equal(result.turns[0]!.id, "5");
  assert.equal(result.turns[19]!.id, "24");
  assert.equal(result.hasMore, true);
});

test("revealing everything after paging in shows the true first turn and no more", () => {
  const turns = Array.from({ length: 25 }, (_, i) => ({ id: String(i) }));
  const result = conversationWindow(turns, 25);
  assert.equal(result.turns.length, 25);
  assert.equal(result.turns[0]!.id, "0");
  assert.equal(result.hasMore, false);
});

test("revealing more than exist never renders a shorter conversation as if it were the whole one — it is simply capped at the whole one", () => {
  const turns = Array.from({ length: 3 }, (_, i) => ({ id: String(i) }));
  const result = conversationWindow(turns, 999);
  assert.equal(result.turns.length, 3);
  assert.equal(result.hasMore, false);
});

// --- liveTurnId: which turn renders full (conversation.md §2, §5) -----------

test("a lone turn is live, whatever its status", () => {
  assert.equal(liveTurnId([{ id: "a", status: "queued" }]), "a");
  assert.equal(liveTurnId([{ id: "a", status: "completed" }]), "a");
});

test("the second turn becomes live once asked, displacing the first", () => {
  const turns = [
    { id: "a", status: "completed" },
    { id: "b", status: "queued" },
  ];
  assert.equal(liveTurnId(turns), "b");
});

test("a question asked mid-answer does not steal live status from the streaming turn", () => {
  const turns = [
    { id: "a", status: "completed" },
    { id: "b", status: "running" },
    { id: "c", status: "queued" },
  ];
  assert.equal(liveTurnId(turns), "b");
});

test("nothing is live before any question is asked", () => {
  assert.equal(liveTurnId([]), null);
});

// --- dividerLabel: time grouping (conversation.md §4) ------------------------

const DAY_MS = 86_400_000;

test("no divider between two turns on the same calendar day", () => {
  const morning = new Date(2026, 7, 28, 9, 0, 0).getTime();
  const evening = new Date(2026, 7, 28, 21, 0, 0).getTime();
  assert.equal(dividerLabel(morning, evening, evening), null);
});

test("a non-positive day gap — a defensive fallback, not reachable via ordinary chronological turns — reads 'earlier today'", () => {
  const today = new Date(2026, 7, 28, 9, 0, 0).getTime();
  const yesterday = today - DAY_MS;
  assert.equal(dividerLabel(today, yesterday, today), "earlier today");
});

test("a turn from the day before now divides as 'yesterday'", () => {
  const now = Date.now();
  const yesterday = now - DAY_MS;
  assert.equal(dividerLabel(yesterday, now, now), "yesterday");
});

test("a turn from further back divides with a calendar date", () => {
  const now = new Date(2026, 7, 28).getTime();
  const lastWeek = new Date(2026, 7, 20).getTime();
  assert.equal(dividerLabel(lastWeek, now, now), "August 20");
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


// --- applying streamed events ------------------------------------------------

function turnState(over: Partial<AskTurnState> = {}): AskTurnState {
  return { serverId: null, steps: [], answer: "", ...over };
}

test("tokens arriving in one frame all survive", () => {
  // The bug this replaced: each patch read the turn from a ref an effect
  // refreshed after render, so both tokens saw answer="" and the second
  // overwrote the first. The answer lost words with nothing saying so.
  let turn = turnState();
  for (const text of ["The ", "contract ", "may be ", "terminated."]) {
    turn = { ...turn, ...applyAskEvent(turn, { event: "token", data: { message_id: "m1", conversation_id: "conv1", text } }) };
  }
  assert.equal(turn.answer, "The contract may be terminated.");
});

test("steps accumulate rather than replacing one another", () => {
  let turn = turnState();
  for (const label of ["Searching", "Reading", "Answering"]) {
    turn = {
      ...turn,
      ...applyAskEvent(turn, { event: "step", data: { label, kind: "retrieval", message_id: "m1" } }),
    };
  }
  assert.deepEqual(
    turn.steps.map((step) => step.label),
    ["Searching", "Reading", "Answering"],
  );
});

test("the server's message id is captured once and not overwritten", () => {
  let turn = turnState();
  turn = {
    ...turn,
    ...applyAskEvent(turn, {
      event: "step",
      data: { label: "a", kind: "retrieval", message_id: "first" },
    }),
  };
  turn = {
    ...turn,
    ...applyAskEvent(turn, {
      event: "step",
      data: { label: "b", kind: "retrieval", message_id: "second" },
    }),
  };
  // It is what `/ask/{id}/stop` addresses; changing it mid-turn would aim stop
  // at something else.
  assert.equal(turn.serverId, "first");
});


// --- the first answer ---------------------------------------------------------

function withFetch<T>(reply: () => Response, body: () => T): T {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => reply()) as typeof fetch;
  try {
    return body();
  } finally {
    globalThis.fetch = original;
  }
}

test("the first completed answer is recognised as the first", () => {
  return withFetch(
    () => new Response(JSON.stringify({ started: 1, completed: 1, stopped: 0 }), { status: 200 }),
    () => isFirstAnswer().then((first) => assert.equal(first, true)),
  );
});

test("the second answer is not, so the note is said once", () => {
  return withFetch(
    () => new Response(JSON.stringify({ started: 2, completed: 2, stopped: 0 }), { status: 200 }),
    () => isFirstAnswer().then((first) => assert.equal(first, false)),
  );
});

test("a counts endpoint that fails costs the note, never the answer", () => {
  return withFetch(
    () => new Response("nope", { status: 500 }),
    () => isFirstAnswer().then((first) => assert.equal(first, false)),
  );
});


// --- staying in one conversation ---------------------------------------------

test("the conversation id is read off whichever event arrives first", () => {
  // The browser cannot know it: the server resolves an existing conversation or
  // creates one. Every event carries it, so the first is enough.
  assert.equal(
    conversationOf({
      event: "step",
      data: { label: "Searching", kind: "retrieval", message_id: "m1", conversation_id: "c1" },
    } as never),
    "c1",
  );
  assert.equal(
    conversationOf({
      event: "token",
      data: { message_id: "m1", conversation_id: "c1", text: "Yes." },
    }),
    "c1",
  );
});

test("an event without one yields null rather than a broken id", () => {
  // Older turns replayed from before this shipped, and anything malformed. A
  // null starts a fresh conversation, which is the previous behaviour — wrong,
  // but not as wrong as sending a conversation id that is the string
  // "undefined".
  assert.equal(conversationOf({ event: "token", data: { message_id: "m1" } } as never), null);
  assert.equal(
    conversationOf({ event: "token", data: { message_id: "m1", conversation_id: 7 } } as never),
    null,
  );
});

// --- isAbstained -------------------------------------------------------------

test("a completed turn with no answer text and a reason abstained", () => {
  assert.equal(
    isAbstained({ status: "completed", answer: "", reason: "Nothing in your files answers this." }),
    true,
  );
});

test("an ordinary answered turn did not abstain", () => {
  assert.equal(isAbstained({ status: "completed", answer: "Ninety days.", reason: null }), false);
});

test("a truncated but answered turn — completed, a reason, but real text — did not abstain", () => {
  // `askwell.ask._run_generation`'s other `completed` + non-null `reason`
  // combination: "Reached the answer length limit." always comes with
  // answer text already streamed, which is exactly what distinguishes it
  // from an abstention.
  assert.equal(
    isAbstained({
      status: "completed",
      answer: "Ninety days, per",
      reason: "Reached the answer length limit.",
    }),
    false,
  );
});

test("a running or failed turn never reads as abstained, whatever its answer", () => {
  assert.equal(isAbstained({ status: "running", answer: "", reason: null }), false);
  assert.equal(
    isAbstained({ status: "failed", answer: "", reason: "Askwell could not reach the assistant." }),
    false,
  );
});
