/**
 * Issue 199: a stored turn rebuilt as the Ask screen shows a live one.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { type HistoryCitation, type HistoryTurn, turnFromHistory, unavailablePassage } from "./conversations.ts";
import { isAbstained } from "./ask.ts";

function citation(overrides: Partial<HistoryCitation> = {}): HistoryCitation {
  return {
    claim_ordinal: 1,
    chunk_id: "chunk-1",
    document_id: "doc-1",
    filename: "Municipal Councils Ordinance.pdf",
    anchor_kind: "page",
    heading: null,
    page_from: 4,
    page_to: 4,
    passage: "The term of office shall continue for forty eight months.",
    quoted_span: "forty eight months",
    passage_unavailable: null,
    ...overrides,
  };
}

function turn(overrides: Partial<HistoryTurn> = {}): HistoryTurn {
  return {
    question_id: "q-1",
    message_id: "m-1",
    question: "How long is a councillor's term?",
    asked_at: "2026-10-05T11:00:00+00:00",
    answer: "The term is forty-eight months [1].",
    status: "completed",
    reason: null,
    db_state: null,
    summary: "Forty-eight months.",
    source_count: 1,
    sql_result: null,
    model_identity: { display_name: "Qwen3.5 4B (Q4_K_M)", source: "shipped" },
    citations: [citation()],
    ...overrides,
  };
}

test("an answered turn comes back finished, with its citation as a card", () => {
  const rebuilt = turnFromHistory(turn());
  assert.equal(rebuilt.id, "q-1");
  assert.equal(rebuilt.serverId, "m-1");
  assert.equal(rebuilt.status, "completed");
  assert.equal(rebuilt.answer, "The term is forty-eight months [1].");
  assert.equal(rebuilt.summary, "Forty-eight months.");
  assert.equal(rebuilt.sourceCount, 1);
  assert.equal(rebuilt.createdAt, Date.parse("2026-10-05T11:00:00+00:00"));
  assert.equal(rebuilt.citations.length, 1);
  assert.deepEqual(rebuilt.citations[0]?.claimOrdinals, [1]);
  assert.equal(rebuilt.citations[0]?.pageFrom, 4);
  assert.equal(rebuilt.citations[0]?.quotedSpan, "forty eight months");
});

test("two claims citing one passage make one card, as live", () => {
  const rebuilt = turnFromHistory(
    turn({ citations: [citation(), citation({ claim_ordinal: 2 })] }),
  );
  assert.equal(rebuilt.citations.length, 1);
  assert.deepEqual(rebuilt.citations[0]?.claimOrdinals, [1, 2]);
});

test("a passage that can no longer be shown keeps its card and says why", () => {
  const rebuilt = turnFromHistory(
    turn({ citations: [citation({ passage: null, passage_unavailable: "deleted" })] }),
  );
  const card = rebuilt.citations[0];
  assert.ok(card);
  assert.equal(card.passage, unavailablePassage("deleted"));
  assert.match(card.passage, /removed/);
  // No highlight into a passage that is not there.
  assert.equal(card.quotedSpan, null);
});

test("an abstention survives the round trip as an abstention", () => {
  const rebuilt = turnFromHistory(
    turn({ answer: "", reason: "Nothing in your files answers this.", citations: [], source_count: null }),
  );
  assert.ok(isAbstained(rebuilt));
  assert.equal(rebuilt.reason, "Nothing in your files answers this.");
});

test("a status the screen does not know reads as failed, with a reason", () => {
  const rebuilt = turnFromHistory(turn({ status: "mystery", answer: "", reason: null, citations: [] }));
  assert.equal(rebuilt.status, "failed");
  assert.equal(rebuilt.reason, "This answer did not finish.");
});
