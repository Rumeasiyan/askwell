/**
 * The pure label formatting `M2-PARTIAL-FE-058`'s conflict card uses.
 * `useDocumentDate` itself is a fetch-backed hook and is exercised by the
 * component tests that render it, not here.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { addedDateLabel, sortByDateAndSupersession, supersededDateLabel, type DocumentDate } from "./document-dates.ts";

test("no added date yet renders nothing", () => {
  assert.equal(addedDateLabel({ addedAt: null }), null);
});

test("an added date is labelled, since no other date source exists yet", () => {
  const label = addedDateLabel({ addedAt: "2026-08-28T00:00:00Z" });
  assert.match(label ?? "", /^Added /);
});

test("a live document has no superseded label", () => {
  assert.equal(supersededDateLabel({ supersededBy: null, supersededAt: null }), null);
});

test("a superseded document is labelled with its own supersession date", () => {
  const label = supersededDateLabel({
    supersededBy: "11111111-1111-1111-1111-111111111111",
    supersededAt: "2026-08-01T00:00:00Z",
  });
  assert.match(label ?? "", /^Superseded /);
});

test("a superseded document with no known supersession date still labels as superseded", () => {
  const label = supersededDateLabel({
    supersededBy: "11111111-1111-1111-1111-111111111111",
    supersededAt: null,
  });
  assert.equal(label, "Superseded");
});

/**
 * Issue GH-226: the conflicting-sources card list must be sorted by date and
 * supersession, never by the order citations arrived in the model's
 * stream — `docs/ux/ask.md` §5's own Validation Rule.
 */

function date(addedAt: string): DocumentDate {
  return { addedAt, supersededBy: null, supersededAt: null };
}

test("three or more conflicting sources are ordered by date, newest first", () => {
  const cards = [
    { documentId: "a", label: "oldest" },
    { documentId: "b", label: "newest" },
    { documentId: "c", label: "middle" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["a", date("2024-01-01T00:00:00Z")],
    ["b", date("2026-01-01T00:00:00Z")],
    ["c", date("2025-01-01T00:00:00Z")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["newest", "middle", "oldest"]);
});

test("a superseded source is demoted to the end rather than shown as an equal", () => {
  const cards = [
    { documentId: "a", label: "superseded-but-newer" },
    { documentId: "b", label: "current" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["a", { addedAt: "2026-06-01T00:00:00Z", supersededBy: "x", supersededAt: "2026-07-01T00:00:00Z" }],
    ["b", date("2025-01-01T00:00:00Z")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["current", "superseded-but-newer"]);
});

test("model/citation-stream order is not the ordering — sorting overrides input order", () => {
  // Cards arrive in the order the model cited them ([1], [2], [3]) — the
  // exact bug issue GH-226 named: this input order is the opposite of date
  // order, and the sort must still produce date order.
  const cards = [
    { documentId: "newest", label: "newest" },
    { documentId: "oldest", label: "oldest" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["newest", date("2026-06-01T00:00:00Z")],
    ["oldest", date("2024-06-01T00:00:00Z")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["newest", "oldest"]);
});

test("a card whose date has not loaded yet sorts after dated cards but before superseded ones", () => {
  const cards = [
    { documentId: "superseded", label: "superseded" },
    { documentId: "unloaded", label: "unloaded" },
    { documentId: "dated", label: "dated" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["superseded", { addedAt: "2026-01-01T00:00:00Z", supersededBy: "x", supersededAt: null }],
    ["dated", date("2025-01-01T00:00:00Z")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["dated", "unloaded", "superseded"]);
});
