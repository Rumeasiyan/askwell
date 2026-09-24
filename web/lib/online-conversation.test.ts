/**
 * Online AI in one conversation: the marker, the gate before the first send,
 * and each turn's backend label. `M8-ONLINE-FE-171`.
 *
 * `answer_reset` (issue 733) is replayed as a recorded stream through the same
 * parser and reducer the Ask screen uses.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { applyAskEvent, type AskTurnState, parseSseFrame } from "./ask.ts";
import { applyCitation, type CitationCard } from "./citations.ts";
import {
  DISCLOSURE_UNDEFINED,
  machineLine,
  markerView,
  needsDisclosure,
  type OnlineConversationState,
  sendAllowed,
  turnBackendLabel,
} from "./online-conversation.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");

function state(overrides: Partial<OnlineConversationState> = {}): OnlineConversationState {
  return {
    conversation_id: "c1",
    ai_backend: "local",
    destination: null,
    expires_in_seconds: null,
    available: true,
    unavailable_reason: null,
    used_online: false,
    ended_reason: null,
    disclosure: { defined: false, version: null, text: null, confirmed: false },
    send_permitted: false,
    ...overrides,
  };
}

const ONLINE_UNDEFINED = state({
  ai_backend: "online",
  destination: "api.provider.example:443",
  expires_in_seconds: 3600,
  used_online: true,
});

const ONLINE_CONFIRMED = state({
  ai_backend: "online",
  destination: "api.provider.example:443",
  expires_in_seconds: 3600,
  used_online: true,
  disclosure: { defined: true, version: "1", text: "Your question.", confirmed: true },
  send_permitted: true,
});

// --- the gate ------------------------------------------------------------------

test("while the payload is undefined, an online conversation cannot send, and says so", () => {
  assert.equal(needsDisclosure(ONLINE_UNDEFINED), true);
  assert.equal(sendAllowed(ONLINE_UNDEFINED), false);
  assert.match(DISCLOSURE_UNDEFINED, /not yet defined/);
  assert.match(DISCLOSURE_UNDEFINED, /will not send anything/);
  assert.match(DISCLOSURE_UNDEFINED, /Nothing has left this machine/);
});

test("a defined but unconfirmed statement still holds the send back", () => {
  const unconfirmed = state({
    ...ONLINE_CONFIRMED,
    disclosure: { defined: true, version: "1", text: "Your question.", confirmed: false },
    send_permitted: false,
  });
  assert.equal(needsDisclosure(unconfirmed), true);
  assert.equal(sendAllowed(unconfirmed), false);
});

test("confirmed once, it is not asked again, including after a lapse and a switch back on", () => {
  assert.equal(needsDisclosure(ONLINE_CONFIRMED), false);
  assert.equal(sendAllowed(ONLINE_CONFIRMED), true);
  // The server keeps the confirmation per conversation; the screen only reads it.
  const lapsed = state({ used_online: true, disclosure: ONLINE_CONFIRMED.disclosure });
  assert.equal(needsDisclosure(lapsed), false);
});

test("a local conversation, or none yet, always sends", () => {
  assert.equal(sendAllowed(null), true);
  assert.equal(sendAllowed(state()), true);
  assert.equal(sendAllowed(state({ used_online: true })), true);
});

// --- the marker ----------------------------------------------------------------

test("an online conversation is marked with where it goes and until when", () => {
  const view = markerView(ONLINE_UNDEFINED, Date.UTC(2026, 8, 24, 12, 0));
  assert.equal(view.kind, "online");
  assert.ok(view.kind === "online");
  assert.match(view.text, /^Online AI is on for this conversation until /);
  assert.match(view.text, /api\.provider\.example:443/);
});

test("resumed after it lapsed, the conversation is still marked, as local now", () => {
  const view = markerView(state({ used_online: true }));
  assert.equal(view.kind, "was_online");
  assert.ok(view.kind === "was_online");
  assert.match(view.text, /was on in this conversation earlier/);
  assert.match(view.text, /nothing you ask here leaves this machine/);
});

test("ended by the provider, the marker names which no it was and whose fix it is", () => {
  const quota = markerView(state({ used_online: true, ended_reason: "provider_quota_exhausted" }));
  assert.equal(quota.kind, "was_online");
  assert.ok(quota.kind === "was_online");
  assert.equal(
    quota.text,
    "Online AI was on in this conversation earlier, until your provider account ran out of " +
      "quota. It is local now: nothing you ask here leaves this machine. Add more with your " +
      "provider, then switch online AI back on if you want it.",
  );

  const key = markerView(state({ used_online: true, ended_reason: "provider_rejected_key" }));
  assert.ok(key.kind === "was_online");
  assert.match(key.text, /until your provider rejected your key\./);
  assert.match(key.text, /replace it in Settings/);
  assert.doesNotMatch(key.text, /quota/, "the two refusals have different fixes");

  for (const view of [quota, key]) {
    assert.ok(view.kind === "was_online");
    assert.doesNotMatch(view.text, /Askwell/, "the provider's no, not Askwell's error");
  }
});

test("ended by removing or replacing the key, the marker says so", () => {
  const removed = markerView(state({ used_online: true, ended_reason: "key_removed" }));
  assert.ok(removed.kind === "was_online");
  assert.match(removed.text, /earlier, until you removed your provider key\. It is local now/);
  const replaced = markerView(state({ used_online: true, ended_reason: "key_replaced" }));
  assert.ok(replaced.kind === "was_online");
  assert.match(replaced.text, /one for a different provider\. It is local now/);
});

test("ended any other way, or for a reason this screen does not know, the plain marker", () => {
  for (const ended_reason of ["disabled", "lapsed", "restart", "something_new", null]) {
    const view = markerView(state({ used_online: true, ended_reason }));
    assert.ok(view.kind === "was_online");
    assert.equal(
      view.text,
      "Online AI was on in this conversation earlier. It is local now: nothing you ask here " +
        "leaves this machine.",
    );
  }
});

test("a mixed conversation labels each turn by the backend that wrote it", () => {
  const ended = state({ used_online: true, ended_reason: "provider_quota_exhausted" });
  const online = { status: "completed", modelIdentity: { source: "online", display_name: "big-1" } };
  const local = { status: "completed", modelIdentity: { source: "shipped", display_name: "q.gguf" } };
  assert.deepEqual(
    [online, online, local, local].map((turn) => turnBackendLabel(turn, ended)),
    ["Answered online · big-1", "Answered online · big-1", "Answered locally", "Answered locally"],
  );
});

test("a conversation never switched on carries no marker", () => {
  assert.deepEqual(markerView(null), { kind: "none" });
  assert.deepEqual(markerView(state()), { kind: "none" });
});

test("the screen stops saying nothing leaves the machine while online", () => {
  assert.equal(machineLine(null), "nothing leaves this machine");
  assert.equal(machineLine(state({ used_online: true })), "nothing leaves this machine");
  assert.equal(machineLine(ONLINE_UNDEFINED), "online AI is on for this conversation");
});

// --- each turn's backend -----------------------------------------------------

test("switched online mid-thread, the earlier local turns are marked as local", () => {
  const earlier = { status: "completed", modelIdentity: { source: "shipped", display_name: "Qwen" } };
  const later = { status: "completed", modelIdentity: { source: "online", display_name: "big-model" } };
  assert.equal(turnBackendLabel(earlier, ONLINE_CONFIRMED), "Answered locally");
  assert.equal(turnBackendLabel(later, ONLINE_CONFIRMED), "Answered online · big-model");
});

test("an online conversation's turn that stayed local says so (issue 734)", () => {
  const sqlTurn = { status: "completed", modelIdentity: { source: "shipped", display_name: "Qwen" } };
  assert.equal(turnBackendLabel(sqlTurn, ONLINE_CONFIRMED), "Answered locally");
});

test("no label where there is nothing to distinguish, or no answer yet", () => {
  const turn = { status: "completed", modelIdentity: { source: "shipped", display_name: "Qwen" } };
  assert.equal(turnBackendLabel(turn, null), null);
  assert.equal(turnBackendLabel(turn, state()), null);
  for (const status of ["queued", "running", "failed"]) {
    assert.equal(turnBackendLabel({ ...turn, status }, ONLINE_CONFIRMED), null);
  }
});

// --- answer_reset (issue 733) ---------------------------------------------------------

test("a recorded answer_reset stream withdraws the online half and keeps the steps", () => {
  const frames = [
    'event: step\ndata: {"message_id":"m1","conversation_id":"c1","label":"Writing your answer.","kind":"compose"}',
    'event: token\ndata: {"message_id":"m1","conversation_id":"c1","text":"Online half [1]."}',
    'event: citation\ndata: {"message_id":"m1","index":1,"claim_ordinal":0,"chunk_id":"k1","document_id":"d1","filename":"a.pdf","anchor_kind":null,"heading":null,"page_from":1,"page_to":1,"passage":"p","quoted_span":null}',
    'event: answer_reset\ndata: {"message_id":"m1","conversation_id":"c1","reason":"The online provider stopped."}',
    'event: step\ndata: {"message_id":"m1","conversation_id":"c1","label":"The online provider stopped. Answering with the local model instead.","kind":"backend"}',
    'event: token\ndata: {"message_id":"m1","conversation_id":"c1","text":"Local whole."}',
  ];
  let turn: AskTurnState & { citations: CitationCard[] } = {
    serverId: null,
    steps: [],
    answer: "",
    citations: [],
  };
  for (const frame of frames) {
    const event = parseSseFrame(frame);
    assert.ok(event !== null, `parsed: ${frame.slice(0, 30)}`);
    if (event.event === "citation") {
      turn = { ...turn, citations: applyCitation(turn.citations, event.data) };
    } else if (event.event === "answer_reset") {
      // What `AskProvider` does with it: the reducer, plus the cards.
      turn = { ...turn, ...applyAskEvent(turn, event), citations: [] };
    } else {
      turn = { ...turn, ...applyAskEvent(turn, event) };
    }
  }
  assert.equal(turn.answer, "Local whole.");
  assert.deepEqual(turn.citations, []);
  assert.deepEqual(
    turn.steps.map((step) => step.kind),
    ["compose", "backend"],
  );
});

test("the provider clears cards and chips on answer_reset, not only the text", () => {
  const provider = readFileSync(join(WEB, "components", "ask", "ask-state.tsx"), "utf8");
  assert.match(
    provider,
    /event\.event === "answer_reset"[\s\S]{0,300}citations: \[\], factChips: \[\]/,
  );
});

// --- no global setting, and the composer is where it lives ---------------------

test("the switch, the marker and the disclosure all sit in the composer's sticky band", () => {
  const screen = readFileSync(join(WEB, "components", "ask", "ask-screen.tsx"), "utf8");
  const composer = screen.slice(screen.indexOf("function Composer()"));
  const band = composer.slice(0, composer.indexOf("function TurnDivider"));
  assert.match(band, /sticky bottom-0/);
  for (const piece of ["<OnlineMarker />", "<OnlineDisclosure />", "<OnlineSwitch />"]) {
    assert.ok(band.includes(piece), `${piece} renders inside the sticky composer`);
  }
  assert.match(band, /disabled=\{value\.trim\(\) === "" \|\| !canSend\}/);
});
