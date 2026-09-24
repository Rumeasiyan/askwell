/**
 * The pure label formatting `M2-PARTIAL-FE-058`'s conflict card uses.
 * `useDocumentDate` itself is a fetch-backed hook and is exercised by the
 * component tests that render it, not here.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  documentDateLabel,
  sortByDateAndSupersession,
  supersededDateLabel,
  type DocumentDate,
} from "./document-dates.ts";

/**
 * `M7-FIX-FE-170`: the date beside each conflicting position is the
 * document's own, at the precision it is known, with where it came from.
 */

const ADDED = "2026-09-23T10:00:00Z";

function own(
  documentDate: string | null,
  documentDatePrecision: DocumentDate["documentDatePrecision"],
  documentDateSource: DocumentDate["documentDateSource"],
): DocumentDate {
  return {
    addedAt: ADDED,
    documentDate,
    documentDatePrecision,
    documentDateSource,
    supersededBy: null,
    supersededAt: null,
  };
}

test("nothing is shown while the date has not loaded", () => {
  assert.equal(documentDateLabel(undefined), null);
});

test("a year from a file name stays a year, never 1 January", () => {
  assert.deepEqual(documentDateLabel(own("2026", "year", "filename"), "en-GB"), {
    date: "2026",
    source: "from the file name",
  });
});

test("a month stays a month", () => {
  assert.deepEqual(documentDateLabel(own("2026-03", "month", "filename"), "en-GB"), {
    date: "March 2026",
    source: "from the file name",
  });
});

test("a day from the file's properties is a full date, not shifted by the time zone", () => {
  assert.deepEqual(documentDateLabel(own("2026-03-01", "day", "metadata"), "en-GB"), {
    date: "1 March 2026",
    source: "from the file's properties",
  });
});

test("an undated document says the date is unknown and never shows when it was added", () => {
  const label = documentDateLabel(own(null, null, null), "en-GB");
  assert.deepEqual(label, { date: "Date unknown", source: null });
  assert.doesNotMatch(JSON.stringify(label), /2026|Added|23/);
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

function date(documentDate: string | null, addedAt = "2026-09-24T00:00:00Z"): DocumentDate {
  return {
    addedAt,
    documentDate,
    documentDatePrecision: documentDate === null ? null : "day",
    documentDateSource: documentDate === null ? null : "metadata",
    supersededBy: null,
    supersededAt: null,
  };
}

function superseded(documentDate: string, supersededAt: string | null): DocumentDate {
  return { ...date(documentDate), supersededBy: "x", supersededAt };
}

test("three or more conflicting sources are ordered by date, newest first", () => {
  const cards = [
    { documentId: "a", label: "oldest" },
    { documentId: "b", label: "newest" },
    { documentId: "c", label: "middle" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["a", date("2024-01-01")],
    ["b", date("2026-01-01")],
    ["c", date("2025-01-01")],
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
    ["a", superseded("2026-06-01", "2026-07-01T00:00:00Z")],
    ["b", date("2025-01-01")],
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
    ["newest", date("2026-06-01")],
    ["oldest", date("2024-06-01")],
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
    ["superseded", superseded("2026-01-01", null)],
    ["dated", date("2025-01-01")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["dated", "unloaded", "superseded"]);
});

/**
 * `M7-FIX-BE-170a`: the order comes from the document's own date, never
 * from when it happened to be added.
 */

test("a 2024 file added after a 2026 one still sorts as the older", () => {
  const cards = [
    { documentId: "old-added-late", label: "2024" },
    { documentId: "new-added-early", label: "2026" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["old-added-late", date("2024", "2026-09-24T12:00:00Z")],
    ["new-added-early", date("2026", "2026-09-01T12:00:00Z")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["2026", "2024"]);
});

test("the fixture's two store-hours files order by their filename years", () => {
  const cards = [
    { documentId: "2025", label: "store_hours_2025.pdf" },
    { documentId: "2026", label: "store_hours_2026.pdf" },
  ];
  const year = (value: string): DocumentDate => ({
    ...date(value, "2026-09-24T00:00:00Z"),
    documentDatePrecision: "year",
    documentDateSource: "filename",
  });
  const dates = new Map<string, DocumentDate>([
    ["2025", year("2025")],
    ["2026", year("2026")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["store_hours_2026.pdf", "store_hours_2025.pdf"]);
});

test("an undated document sorts as a not-yet-loaded one does, whatever its added date", () => {
  const cards = [
    { documentId: "undated", label: "undated" },
    { documentId: "unloaded", label: "unloaded" },
    { documentId: "dated", label: "dated" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["undated", date(null, "2030-01-01T00:00:00Z")],
    ["dated", date("2019-05")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["dated", "undated", "unloaded"]);
});

test("a month-precision date outranks an earlier full date", () => {
  const cards = [
    { documentId: "day", label: "2025-12-31" },
    { documentId: "month", label: "2026-03" },
  ];
  const dates = new Map<string, DocumentDate>([
    ["day", date("2025-12-31")],
    ["month", date("2026-03")],
  ]);
  const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.label);
  assert.deepEqual(sorted, ["2026-03", "2025-12-31"]);
});

test("a bare year and a full date within it order the more specific first, whatever the input order", () => {
  const dates = new Map<string, DocumentDate>([
    ["year", date("2026")],
    ["day", date("2026-03-15")],
  ]);
  for (const cards of [
    [{ documentId: "year" }, { documentId: "day" }],
    [{ documentId: "day" }, { documentId: "year" }],
  ]) {
    const sorted = sortByDateAndSupersession(cards, dates).map((card) => card.documentId);
    assert.deepEqual(sorted, ["day", "year"]);
  }
});
