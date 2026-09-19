/**
 * Pure display logic for a database-answered turn's stored result.
 * `M4-RESULT-FE-109`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  columnAlign,
  formatCell,
  getSqlDisclosuresExpandedCount,
  isSingleValue,
  paginateSqlRows,
  recordSqlDisclosureExpanded,
  segmentInjectedLimit,
  sqlResultHref,
  truncationLabel,
  type SqlResultData,
} from "./sql-result.ts";

function result(over: Partial<SqlResultData> = {}): SqlResultData {
  return {
    engine: "postgres",
    source_id: "s1",
    query: "SELECT * FROM shipments",
    columns: ["id", "status"],
    rows: [
      [1, "late"],
      [2, "on_time"],
    ],
    row_count: 2,
    truncated: false,
    duration_ms: 12,
    ...over,
  };
}

test("a single row, single column result is a single value", () => {
  assert.equal(isSingleValue(result({ columns: ["count"], rows: [[42]] })), true);
});

test("more than one column is never a single value, however many rows", () => {
  assert.equal(isSingleValue(result({ columns: ["id"], rows: [[1]] })), true);
  assert.equal(isSingleValue(result({ columns: ["id", "status"], rows: [[1, "late"]] })), false);
  assert.equal(isSingleValue(result({ columns: ["id"], rows: [[1], [2]] })), false);
});

test("truncation label is absent unless the injected limit was actually hit", () => {
  assert.equal(truncationLabel(result({ truncated: false })), null);
});

test("truncation label names the row count actually shown, singular and plural", () => {
  assert.equal(
    truncationLabel(result({ truncated: true, row_count: 200 })),
    "First 200 rows shown — there may be more.",
  );
  assert.equal(
    truncationLabel(result({ truncated: true, row_count: 1 })),
    "First 1 row shown — there may be more.",
  );
});

test("null and empty string are distinguishable cell kinds", () => {
  assert.deepEqual(formatCell(null), { kind: "null", text: "NULL" });
  assert.deepEqual(formatCell(undefined), { kind: "null", text: "NULL" });
  assert.deepEqual(formatCell(""), { kind: "empty", text: "" });
  assert.deepEqual(formatCell("late"), { kind: "value", text: "late" });
  assert.deepEqual(formatCell(42), { kind: "value", text: "42" });
  assert.deepEqual(formatCell(true), { kind: "value", text: "true" });
});

test("a numeric column right-aligns, nulls do not change that", () => {
  const rows = [[1], [null], [3]];
  assert.equal(columnAlign(rows, 0), "right");
});

test("a text column, and a column with nothing to judge by, left-align", () => {
  assert.equal(columnAlign([["a"], ["b"]], 0), "left");
  assert.equal(columnAlign([[null], [null]], 0), "left");
});

test("a mixed column left-aligns rather than guessing", () => {
  assert.equal(columnAlign([[1], ["two"]], 0), "left");
});

test("pagination clamps into range and reports neighbours correctly", () => {
  const rows = Array.from({ length: 120 }, (_, index) => [index]);
  const first = paginateSqlRows(rows, 1, 50);
  assert.equal(first.rows.length, 50);
  assert.equal(first.page, 1);
  assert.equal(first.pageCount, 3);
  assert.equal(first.hasPrevious, false);
  assert.equal(first.hasNext, true);

  const last = paginateSqlRows(rows, 99, 50);
  assert.equal(last.page, 3);
  assert.equal(last.rows.length, 20);
  assert.equal(last.hasNext, false);
  assert.equal(last.hasPrevious, true);
});

test("pagination of an empty result is one empty page, not zero pages", () => {
  const page = paginateSqlRows([], 1, 50);
  assert.equal(page.pageCount, 1);
  assert.equal(page.rows.length, 0);
  assert.equal(page.hasPrevious, false);
  assert.equal(page.hasNext, false);
});

test("the source-view link carries the message id and, when given, the turn", () => {
  assert.equal(sqlResultHref("m1"), "/documents/?result=m1");
  assert.equal(sqlResultHref("m1", "t1"), "/documents/?result=m1&turn=t1");
});

// --- `segmentInjectedLimit` (`M4-RESULT-FE-110`) ----------------------------

test("a query with no injected limit comes back as one unmarked segment", () => {
  const query = "SELECT id FROM orders WHERE status = 'open'";
  assert.deepEqual(segmentInjectedLimit(query), [{ text: query, injected: false }]);
});

test("an injected limit is marked distinctly from the query around it", () => {
  const query = "SELECT id FROM orders LIMIT 1000 /* Added by Askwell */";
  assert.deepEqual(segmentInjectedLimit(query), [
    { text: "SELECT id FROM orders ", injected: false },
    { text: "LIMIT 1000 /* Added by Askwell */", injected: true },
  ]);
});

test("a model-written LIMIT with no Askwell comment is never marked injected", () => {
  const query = "SELECT id FROM orders LIMIT 10";
  assert.deepEqual(segmentInjectedLimit(query), [{ text: query, injected: false }]);
});

// --- the local disclosures-expanded counter (this ticket's own Analytics Events line) ---

test("the disclosures-expanded counter only counts what was actually recorded", () => {
  const before = getSqlDisclosuresExpandedCount();
  recordSqlDisclosureExpanded();
  assert.equal(getSqlDisclosuresExpandedCount(), before + 1);
});
