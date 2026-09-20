/**
 * The trace panel's pure logic: turning `askwell.ask.ask_trace`'s raw,
 * per-`kind` step shapes into a plain-language summary, a duration, and
 * whether an expander is worth showing at all. `M5-TRACE-FE-119`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDuration, hasExpandableDetail, stepSummary, traceRows } from "./trace.ts";

// --- formatDuration ----------------------------------------------------------

test("a duration under a second renders in milliseconds", () => {
  assert.equal(formatDuration(340), "340 ms");
});

test("a duration at or over a second renders in seconds, one decimal place", () => {
  assert.equal(formatDuration(8200), "8.2 s");
  assert.equal(formatDuration(1000), "1.0 s");
});

test("no duration at all renders nothing rather than a fabricated zero", () => {
  assert.equal(formatDuration(null), null);
});

// --- stepSummary ---------------------------------------------------------

test("a retrieve step names the hit count and the top score", () => {
  const summary = stepSummary({
    kind: "retrieve",
    ms: 340,
    hits: [
      { chunk_id: "a", score: 0.81 },
      { chunk_id: "b", score: 0.4 },
    ],
  });
  assert.equal(summary, "Searched your files — 2 passages, top score 0.81");
});

test("a retrieve step with no hits says so plainly", () => {
  assert.equal(stepSummary({ kind: "retrieve", hits: [] }), "Searched your files — nothing came back");
});

test("an executed SQL step names the row count", () => {
  const summary = stepSummary({ kind: "sql", outcome: "executed", rows: 7, truncated: false });
  assert.equal(summary, "Queried your database — 7 rows");
});

test("a truncated SQL result says so", () => {
  const summary = stepSummary({ kind: "sql", outcome: "executed", rows: 1000, truncated: true });
  assert.equal(summary, "Queried your database — 1000 rows, truncated");
});

test("a rejected SQL step names the rejection reason", () => {
  const summary = stepSummary({ kind: "sql", outcome: "rejected", reason: "not_a_single_select" });
  assert.equal(summary, "Generated SQL was rejected (not_a_single_select)");
});

test("an unrecognised SQL outcome falls back to a generic line rather than throwing", () => {
  assert.equal(stepSummary({ kind: "sql", outcome: "something_new" }), "Queried your database");
});

test("a tool step names the tool in plain language", () => {
  assert.equal(
    stepSummary({ kind: "tool", tool: "document_search", outcome: "ok", duration_ms: 120 }),
    "Searched your files",
  );
});

test("a tool step that failed names the outcome", () => {
  assert.equal(
    stepSummary({ kind: "tool", tool: "database_query", outcome: "tool_error", duration_ms: 5 }),
    "Queried your database — tool error",
  );
});

test("an unfamiliar tool name is still named, not hidden", () => {
  assert.equal(stepSummary({ kind: "tool", tool: "future_tool", outcome: "ok" }), "Called future_tool");
});

test("a memory_retrieve step counts facts and schema notes separately", () => {
  const summary = stepSummary({
    kind: "memory_retrieve",
    memory_fact_ids: ["1"],
    schema_note_ids: ["2", "3"],
  });
  assert.equal(summary, "Checked your memory — 1 fact, 2 schema notes");
});

test("an unrecognised step kind falls back to naming its own kind rather than a blank line", () => {
  assert.equal(stepSummary({ kind: "future_kind" }), "future_kind");
});

// --- hasExpandableDetail ---------------------------------------------------

test("a step with fields beyond kind/timing/outcome is expandable", () => {
  assert.equal(hasExpandableDetail({ kind: "sql", outcome: "rejected", reason: "x", query: "SELECT 1" }), true);
});

test("a step with nothing but kind and outcome has no expander — the ticket's own edge case", () => {
  assert.equal(hasExpandableDetail({ kind: "sql", outcome: "no_connections" }), false);
});

// --- traceRows -------------------------------------------------------------

test("traceRows numbers steps from 1 in the order they were given", () => {
  const rows = traceRows([{ kind: "schema", ms: 40 }, { kind: "compose", ms: 8200, claims: 3, citations: 3 }]);
  assert.deepEqual(
    rows.map((row) => row.index),
    [1, 2],
  );
  assert.equal(rows[0]!.duration, "40 ms");
  assert.equal(rows[1]!.duration, "8.2 s");
  assert.equal(rows[1]!.summary, "Wrote the answer — 3 claims, 3 cited");
});
