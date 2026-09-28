/**
 * `M9-FIX-FE-204`, GH-728: the resolve offer lists each cited document once,
 * in the order the conflict records use.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { CitationCard } from "./citations.ts";
import { conflictChoices } from "./conflict-resolution.ts";
import type { DocumentDate } from "./document-dates.ts";

function card(chunkId: string, documentId: string, filename: string): CitationCard {
  return {
    chunkId,
    documentId,
    filename,
    anchorKind: null,
    heading: null,
    pageFrom: 1,
    pageTo: 1,
    passage: "",
    quotedSpan: null,
    claimOrdinals: [1],
  };
}

function dated(documentDate: string | null): DocumentDate {
  return {
    addedAt: "2026-09-23T10:00:00Z",
    documentDate,
    documentDatePrecision: documentDate === null ? null : "year",
    documentDateSource: documentDate === null ? null : "filename",
    supersededBy: null,
    supersededAt: null,
  };
}

test("a document cited for two positions is offered once", () => {
  const choices = conflictChoices(
    [card("c1", "d1", "policy.pdf"), card("c2", "d1", "policy.pdf"), card("c3", "d2", "other.pdf")],
    new Map(),
  );
  assert.deepEqual(
    choices.map((choice) => choice.documentId),
    ["d1", "d2"],
  );
});

test("choices follow the records' date order, not the citation stream's", () => {
  const choices = conflictChoices(
    [card("c1", "old", "store_hours_2025.pdf"), card("c2", "new", "store_hours_2026.pdf")],
    new Map([
      ["old", dated("2025-01-01")],
      ["new", dated("2026-01-01")],
    ]),
  );
  assert.deepEqual(
    choices.map((choice) => choice.filename),
    ["store_hours_2026.pdf", "store_hours_2025.pdf"],
  );
});
