/**
 * `M1-LIB-FE-050`: the pure library logic — filtering and the specific
 * causes a needs-attention row expands to. What the row renders is a DOM
 * concern; what belongs to *which* source and passes *which* filter is not,
 * and is what can be silently wrong.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { FailedDocument, FlaggedDocument, SourceCoverage } from "./ingest.ts";
import {
  DEFAULT_FILTERS,
  addedSentence,
  attentionCauses,
  matchesFilters,
  type LibraryFilters,
} from "./library.ts";

function source(over: Partial<SourceCoverage> = {}): SourceCoverage {
  return {
    id: "s1",
    name: "papers",
    status: "ready",
    kind: "file",
    added_at: "2026-08-28T00:00:00Z",
    last_error: null,
    open_clarifications: 0,
    total: 10,
    ready: 10,
    failed: 0,
    running: 0,
    outstanding: 0,
    flagged: 0,
    askable: true,
    fraction: 1,
    ...over,
  };
}

function failure(over: Partial<FailedDocument> = {}): FailedDocument {
  return {
    document_id: "d1",
    filename: "broken.pdf",
    source_id: "s1",
    stage: "extracting",
    error: "The file is corrupt.",
    attempts: 3,
    ...over,
  };
}

function flaggedDoc(over: Partial<FlaggedDocument> = {}): FlaggedDocument {
  return {
    document_id: "d2",
    filename: "scan.pdf",
    source_id: "s1",
    confidence: 0.4,
    poor_pages: [3, 4],
    ...over,
  };
}

// --- filters ------------------------------------------------------------

test("the default filters match every source", () => {
  assert.equal(matchesFilters(source(), DEFAULT_FILTERS), true);
});

test("a kind filter excludes a source of a different kind", () => {
  const filters: LibraryFilters = { ...DEFAULT_FILTERS, kind: "csv" };
  assert.equal(matchesFilters(source({ kind: "file" }), filters), false);
  assert.equal(matchesFilters(source({ kind: "csv" }), filters), true);
});

test("a status filter excludes a source in a different status", () => {
  const filters: LibraryFilters = { ...DEFAULT_FILTERS, status: "attention" };
  assert.equal(matchesFilters(source({ status: "ready" }), filters), false);
  assert.equal(matchesFilters(source({ status: "attention" }), filters), true);
});

test("has-open-clarifications excludes a source with none", () => {
  const filters: LibraryFilters = { ...DEFAULT_FILTERS, onlyOpenClarifications: true };
  assert.equal(matchesFilters(source({ open_clarifications: 0 }), filters), false);
  assert.equal(matchesFilters(source({ open_clarifications: 2 }), filters), true);
});

test("filters combine — a source must pass every one set", () => {
  const filters: LibraryFilters = { kind: "file", status: "ready", onlyOpenClarifications: false };
  assert.equal(matchesFilters(source({ kind: "file", status: "attention" }), filters), false);
  assert.equal(matchesFilters(source({ kind: "file", status: "ready" }), filters), true);
});

// --- needs-attention expansion -------------------------------------------

test("a failed document is named with a fixable, retryable cause", () => {
  const causes = attentionCauses("s1", [failure()], []);
  assert.equal(causes.length, 1);
  assert.equal(causes[0]?.documentId, "d1");
  assert.equal(causes[0]?.filename, "broken.pdf");
  assert.equal(causes[0]?.fixable, true);
  assert.match(causes[0]?.sentence ?? "", /corrupt/);
});

test("a flagged scan is named as read-only information, not a failure to retry", () => {
  const causes = attentionCauses("s1", [], [flaggedDoc()]);
  assert.equal(causes.length, 1);
  assert.equal(causes[0]?.fixable, false);
  assert.match(causes[0]?.sentence ?? "", /40%/);
  assert.match(causes[0]?.sentence ?? "", /3, 4/);
});

test("failures and flagged scans for one source both appear, neither hiding the other", () => {
  const causes = attentionCauses("s1", [failure()], [flaggedDoc()]);
  assert.equal(causes.length, 2);
});

test("a cause belonging to a different source is not attributed to this one", () => {
  const causes = attentionCauses("s1", [failure({ source_id: "s2" })], [
    flaggedDoc({ source_id: "s2" }),
  ]);
  assert.equal(causes.length, 0);
});

// --- added date -----------------------------------------------------------

test("the added sentence renders a stable calendar date, not a relative one", () => {
  const rendered = addedSentence("2026-08-28T12:00:00Z");
  assert.match(rendered, /2026/);
  assert.doesNotMatch(rendered, /ago/);
});
