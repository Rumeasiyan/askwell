/**
 * Pure formatting for the memory screen. `M3-MEM-FE-083`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  applyMemoryFilters,
  deleteAllConfirmationCopy,
  deletedSourceNote,
  factDateLabel,
  inferredReviewSentence,
  memorySources,
  NO_FILTERS,
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

test("no filters returns every row", () => {
  const rows = [row({ id: "a" }), row({ id: "b", origin: "inferred" })];
  assert.deepEqual(applyMemoryFilters(rows, NO_FILTERS), rows);
});

test("inferred-only narrows to guesses", () => {
  const rows = [row({ id: "a", origin: "clarification" }), row({ id: "b", origin: "inferred" })];
  const filtered = applyMemoryFilters(rows, { ...NO_FILTERS, inferredOnly: true });
  assert.deepEqual(filtered.map((r) => r.id), ["b"]);
});

test("unused-only narrows to zero-usage rows", () => {
  const rows = [row({ id: "a", usageCount: 3 }), row({ id: "b", usageCount: 0 })];
  const filtered = applyMemoryFilters(rows, { ...NO_FILTERS, unusedOnly: true });
  assert.deepEqual(filtered.map((r) => r.id), ["b"]);
});

test("a source filter narrows to that source only", () => {
  const rows = [
    row({ id: "a", sourceId: "s1" }),
    row({ id: "b", sourceId: "s2" }),
    row({ id: "c", sourceId: null }),
  ];
  const filtered = applyMemoryFilters(rows, { ...NO_FILTERS, sourceId: "s1" });
  assert.deepEqual(filtered.map((r) => r.id), ["a"]);
});

test("filters combine narrowing further, not widening", () => {
  const rows = [
    row({ id: "a", origin: "inferred", usageCount: 0, sourceId: "s1" }),
    row({ id: "b", origin: "inferred", usageCount: 5, sourceId: "s1" }),
  ];
  const filtered = applyMemoryFilters(rows, { inferredOnly: true, unusedOnly: true, sourceId: "s1" });
  assert.deepEqual(filtered.map((r) => r.id), ["a"]);
});

test("memorySources de-duplicates, in first-seen order, and skips sourceless rows", () => {
  const rows = [
    row({ id: "a", sourceId: "s1", sourceName: "sales-2024" }),
    row({ id: "b", sourceId: null }),
    row({ id: "c", sourceId: "s2", sourceName: "hr" }),
    row({ id: "d", sourceId: "s1", sourceName: "sales-2024" }),
  ];
  assert.deepEqual(memorySources(rows), [
    { id: "s1", name: "sales-2024" },
    { id: "s2", name: "hr" },
  ]);
});

test("delete-all-memory copy names the count and singularises one", () => {
  assert.equal(
    deleteAllConfirmationCopy(1),
    "Delete all 1 fact Askwell has learned? This cannot be undone.",
  );
  assert.equal(
    deleteAllConfirmationCopy(7),
    "Delete all 7 facts Askwell has learned? This cannot be undone.",
  );
});
