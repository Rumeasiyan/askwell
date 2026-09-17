/**
 * Pure formatting for the memory screen. `M3-MEM-FE-083`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  deletedSourceNote,
  factDateLabel,
  inferredReviewSentence,
  originLabel,
  usageSentence,
  type MemoryRow,
} from "./memory.ts";

function row(over: Partial<MemoryRow> = {}): MemoryRow {
  return {
    factKind: "memory",
    id: "f1",
    subject: "rfq",
    value: "Request for Quotation",
    origin: "clarification",
    confidence: 1.0,
    sourceId: null,
    sourceName: null,
    sourceDeleted: false,
    createdAt: "2026-09-01T00:00:00+00:00",
    usageCount: 0,
    history: [],
    ...over,
  };
}

test("a user-supplied fact says 'You told me'", () => {
  assert.equal(originLabel("clarification"), "You told me");
  assert.equal(originLabel("manual"), "You told me");
  assert.equal(originLabel("correction"), "You told me");
});

test("an inferred fact says 'I guessed'", () => {
  assert.equal(originLabel("inferred"), "I guessed");
});

test("a null date renders nothing", () => {
  assert.equal(factDateLabel(null), null);
});

test("usage count is always shown, singular for one", () => {
  assert.equal(usageSentence(0), "used in 0 answers");
  assert.equal(usageSentence(1), "used in 1 answer");
  assert.equal(usageSentence(12), "used in 12 answers");
});

test("a fact from a live source carries no deleted-source note", () => {
  assert.equal(deletedSourceNote(row({ sourceDeleted: false })), null);
});

test("a fact from a deleted source says so", () => {
  assert.equal(deletedSourceNote(row({ sourceDeleted: true })), "learned from a source you deleted");
});

test("the inferred-review count is singular for one guess", () => {
  assert.equal(inferredReviewSentence(1), "1 guess to review");
  assert.equal(inferredReviewSentence(3), "3 guesses to review");
});
