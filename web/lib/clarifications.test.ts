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
  isBlankAnswer,
  mergeIncoming,
  rowCountLabel,
  savedConfirmation,
  totalSentence,
  type ClarificationsState,
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

// --- savedConfirmation, isBlankAnswer ---------------------------------------

test("savedConfirmation names the affected material, not a generic toast", () => {
  assert.equal(
    savedConfirmation({ count: 3, label: "3 documents" }),
    "Saved. Re-reading 3 documents.",
  );
});

test("isBlankAnswer treats whitespace-only input as blank", () => {
  assert.equal(isBlankAnswer(""), true);
  assert.equal(isBlankAnswer("   "), true);
  assert.equal(isBlankAnswer("  status code  "), false);
});

// --- mergeIncoming (issue 272) -----------------------------------------------

function group(sourceId: string, itemIds: string[]): ClarificationsState["groups"][number] {
  return {
    source_id: sourceId,
    source_name: sourceId,
    count: itemIds.length,
    items: itemIds.map((id) => ({ id, subject: id, question: "?", options: null, evidence: null })),
  };
}

test("mergeIncoming adds a brand-new group without touching existing ones", () => {
  const current: ClarificationsState = { groups: [group("a", ["1"])], total: 1 };
  const incoming: ClarificationsState = {
    groups: [group("a", ["1"]), group("b", ["2"])],
    total: 2,
  };

  const merged = mergeIncoming(current, incoming);

  assert.equal(merged.total, 2);
  assert.deepEqual(
    merged.groups.map((g) => g.source_id),
    ["b", "a"],
  );
  assert.strictEqual(merged.groups[1], current.groups[0], "the existing group is untouched, not rebuilt");
});

test("mergeIncoming appends only the new items in an existing group", () => {
  const current: ClarificationsState = { groups: [group("a", ["1"])], total: 1 };
  const incoming: ClarificationsState = { groups: [group("a", ["1", "2"])], total: 2 };

  const merged = mergeIncoming(current, incoming);

  assert.equal(merged.total, 2);
  assert.deepEqual(
    merged.groups.at(0)?.items.map((i) => i.id),
    ["1", "2"],
  );
});

test("mergeIncoming returns the same reference when nothing new arrived", () => {
  const current: ClarificationsState = { groups: [group("a", ["1"])], total: 1 };
  const incoming: ClarificationsState = { groups: [group("a", ["1"])], total: 1 };

  assert.strictEqual(mergeIncoming(current, incoming), current);
});

test("mergeIncoming never drops an item already answered locally and gone from the fetch", () => {
  const current: ClarificationsState = { groups: [group("a", ["1"])], total: 1 };
  const incoming: ClarificationsState = { groups: [], total: 0 };

  const merged = mergeIncoming(current, incoming);

  assert.deepEqual(
    merged.groups.at(0)?.items.map((i) => i.id),
    ["1"],
  );
});
