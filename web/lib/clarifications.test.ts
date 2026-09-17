/**
 * `M3-REVIEW-FE-072`: the pure clarifications logic — sentence formatting,
 * which is the only part here that can silently disagree with itself between
 * the badge and the screen.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NONE_PENDING_COPY,
  currentInference,
  evidenceDisplay,
  groupSentence,
  rowCountLabel,
  totalSentence,
} from "./clarifications.ts";

test("totalSentence singular", () => {
  assert.equal(totalSentence(1), "1 question");
});

test("totalSentence plural, including zero", () => {
  assert.equal(totalSentence(4), "4 questions");
  assert.equal(totalSentence(0), "0 questions");
});

test("groupSentence matches totalSentence's own shape", () => {
  assert.equal(groupSentence(3), totalSentence(3));
  assert.equal(groupSentence(1), totalSentence(1));
});

test("the empty state teaches the feature rather than reporting an absence", () => {
  assert.ok(NONE_PENDING_COPY.toLowerCase().includes("askwell asks when"));
  assert.ok(!NONE_PENDING_COPY.toLowerCase().startsWith("no items"));
});

// --- currentInference ----------------------------------------------------

test("currentInference reads the field M3-RAISE-BE-071 merges onto every evidence kind", () => {
  assert.equal(currentInference({ kind: "passage", current_inference: "status code" }), "status code");
});

test("currentInference is null when there was nothing safe to guess, not a fake one", () => {
  assert.equal(currentInference({ kind: "passage" }), null);
  assert.equal(currentInference(null), null);
});

// --- evidenceDisplay -------------------------------------------------------

test("evidenceDisplay formats a column distribution with its remainder", () => {
  const display = evidenceDisplay({
    kind: "column_distribution",
    row_count: 40112,
    values: [
      { value: "A", count: 31204 },
      { value: "T", count: 6890 },
    ],
    remainder_count: 2018,
  });
  assert.deepEqual(display, {
    kind: "distribution",
    rowCount: 40112,
    values: [
      { value: "A", count: 31204 },
      { value: "T", count: 6890 },
    ],
    remainderCount: 2018,
  });
});

test("evidenceDisplay carries a passage's document, page and text", () => {
  const display = evidenceDisplay({
    kind: "passage",
    samples: [{ document: "sales-2024.sql", page: 3, text: "st_cd marks status" }],
  });
  assert.deepEqual(display, {
    kind: "passage",
    samples: [{ document: "sales-2024.sql", page: 3, text: "st_cd marks status" }],
  });
});

test("evidenceDisplay reports unavailable evidence by its own reason rather than an empty block", () => {
  const display = evidenceDisplay({ kind: "unavailable", reason: "no locatable passage for 'st_cd'" });
  assert.deepEqual(display, { kind: "unavailable", reason: "no locatable passage for 'st_cd'" });
});

test("evidenceDisplay is null for a missing evidence column", () => {
  assert.equal(evidenceDisplay(null), null);
});

// --- rowCountLabel -----------------------------------------------------------

test("rowCountLabel is comma-grouped and pluralised", () => {
  assert.equal(rowCountLabel(40112), "40,112 rows");
  assert.equal(rowCountLabel(1), "1 row");
});
