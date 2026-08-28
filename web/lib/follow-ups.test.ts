/**
 * Suggested follow-ups after a completed answer. `M1-CONV-FE-180`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { CitationCard } from "./citations.ts";
import { followUpSuggestions, getFollowUpUsedCount, recordFollowUpUsed } from "./follow-ups.ts";

function card(over: Partial<CitationCard> = {}): CitationCard {
  return {
    chunkId: "c1",
    documentId: "d1",
    filename: "master-services-agreement.pdf",
    anchorKind: null,
    heading: "Termination",
    pageFrom: 3,
    pageTo: 3,
    passage: "Notice is ninety days.",
    quotedSpan: "ninety days",
    claimOrdinals: [1],
    ...over,
  };
}

test("a completed, grounded turn gets a heading-derived suggestion", () => {
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: 1,
    citations: [card()],
    answer: "Notice is ninety days.",
  });
  // One, not one plus filler. Three is a maximum, not a quota.
  assert.deepEqual(suggestions, [
    "What else does master-services-agreement.pdf say about Termination?",
  ]);
});

test("an abstained turn (null source count) gets no suggestions", () => {
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: null,
    citations: [],
    answer: "Nothing in your files answers this.",
  });
  assert.deepEqual(suggestions, []);
});

test("a turn still running gets no suggestions", () => {
  const suggestions = followUpSuggestions({
    status: "running",
    sourceCount: null,
    citations: [card()],
    answer: "Notice is",
  });
  assert.deepEqual(suggestions, []);
});

test("distinct citations from the same document only contribute one suggestion", () => {
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: 1,
    citations: [card(), card({ chunkId: "c2", heading: "Renewal" })],
    answer: "Notice is ninety days.",
  });
  // One, not one plus filler. Three is a maximum, not a quota.
  assert.deepEqual(suggestions, [
    "What else does master-services-agreement.pdf say about Termination?",
  ]);
});

test("a citation with no heading falls back to a distinctive term from the answer", () => {
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: 1,
    citations: [card({ heading: null }), card({ chunkId: "c2", filename: "invoice.pdf", heading: null })],
    answer: "Meridian Meridian Meridian owes ninety days.",
  });
  assert.deepEqual(suggestions, ["What else mentions meridian?"]);
});

test("never padded past what was actually derived", () => {
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: 1,
    citations: [],
    answer: "3 June 2026.",
  });
  assert.deepEqual(suggestions, []);
});

test("caps at three even with many distinct headings", () => {
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: 3,
    citations: [
      card({ chunkId: "c1", filename: "a.pdf", heading: "Alpha" }),
      card({ chunkId: "c2", filename: "b.pdf", heading: "Beta" }),
      card({ chunkId: "c3", filename: "c.pdf", heading: "Gamma" }),
      card({ chunkId: "c4", filename: "d.pdf", heading: "Delta" }),
    ],
    answer: "Answer text.",
  });
  assert.equal(suggestions.length, 3);
});

test("the local usage counter increments and never resets on its own", () => {
  const before = getFollowUpUsedCount();
  recordFollowUpUsed();
  assert.equal(getFollowUpUsedCount(), before + 1);
});


test("one real suggestion stays one — nothing is added to reach three", () => {
  // The ticket's own edge case, asserted rather than assumed: "three
  // suggestions are a maximum, not a quota, and padding produces generic
  // filler that trains the user to ignore the whole row."
  //
  // This is the test that was missing. The three that existed asserted the
  // padding *as correct*, so the gate passed and the behaviour the ticket
  // forbids was the behaviour under test.
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: 1,
    citations: [card()],
    answer: "Notice is ninety days.",
  });
  assert.equal(suggestions.length, 1);
  for (const suggestion of suggestions) {
    // Every one has to name something out of this answer. A suggestion that
    // reads identically under every answer was derived from none of them.
    assert.ok(
      suggestion.includes("master-services-agreement.pdf") || suggestion.includes("Termination"),
      `not derived from the answer: ${suggestion}`,
    );
  }
});

test("two documents give two suggestions, not two plus filler", () => {
  const suggestions = followUpSuggestions({
    status: "completed",
    sourceCount: 2,
    citations: [
      card({ chunkId: "c1", filename: "a.pdf", heading: "Alpha" }),
      card({ chunkId: "c2", filename: "b.pdf", heading: "Beta" }),
    ],
    answer: "Both say ninety days.",
  });
  assert.deepEqual(suggestions, [
    "What else does a.pdf say about Alpha?",
    "What else does b.pdf say about Beta?",
  ]);
});
