/**
 * The trace panel's pure logic: turning `askwell.ask.ask_trace`'s raw,
 * per-`kind` step shapes into a plain-language summary, a duration, and
 * whether an expander is worth showing at all. `M5-TRACE-FE-119`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { CitationCard } from "./citations.ts";
import {
  buildTraceCopyText,
  formatDuration,
  hasExpandableDetail,
  hitCitation,
  memoryFactRefs,
  retrievalThreshold,
  retrievedHits,
  sqlStepInfo,
  stepSummary,
  toolCeilingPendingCalls,
  toolInjectionPatterns,
  traceRows,
  type TraceData,
} from "./trace.ts";

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

// --- retrievedHits / retrievalThreshold (M5-TRACE-FE-120) -----------------

test("retrievedHits sorts highest score first, so a near-miss reads as the top of the list", () => {
  const hits = retrievedHits({
    kind: "retrieve",
    hits: [
      { chunk_id: "a", score: 0.4 },
      { chunk_id: "b", score: 0.61 },
      { chunk_id: "c", score: 0.2 },
    ],
  });
  assert.deepEqual(
    hits.map((hit) => hit.chunkId),
    ["b", "a", "c"],
  );
});

test("retrievalThreshold reads the stored threshold, null when absent", () => {
  assert.equal(retrievalThreshold({ kind: "retrieve", threshold: 0.65 }), 0.65);
  assert.equal(retrievalThreshold({ kind: "retrieve" }), null);
});

// --- memoryFactRefs ----------------------------------------------------------

test("memoryFactRefs lists facts before schema notes, each tagged with its own kind", () => {
  const refs = memoryFactRefs({
    kind: "memory_retrieve",
    memory_fact_ids: ["f1"],
    schema_note_ids: ["n1", "n2"],
  });
  assert.deepEqual(refs, [
    { factKind: "memory", factId: "f1" },
    { factKind: "schema_note", factId: "n1" },
    { factKind: "schema_note", factId: "n2" },
  ]);
});

// --- sqlStepInfo -------------------------------------------------------------

test("sqlStepInfo reads a single-shot SQL step's rejection in full", () => {
  const info = sqlStepInfo({
    kind: "sql",
    outcome: "rejected",
    reason: "not_a_single_read",
    query: "DELETE FROM invoices",
  });
  assert.deepEqual(info, {
    query: "DELETE FROM invoices",
    outcome: "rejected",
    reason: "not_a_single_read",
    rows: null,
    truncated: null,
  });
});

test("sqlStepInfo reads a database_query tool step's rejection the same way as the single-shot path", () => {
  const info = sqlStepInfo({
    kind: "tool",
    tool: "database_query",
    outcome: "rejected",
    detail: { reason: "write_detected", query: "UPDATE invoices SET paid = true" },
  });
  assert.deepEqual(info, {
    query: "UPDATE invoices SET paid = true",
    outcome: "rejected",
    reason: "write_detected",
    rows: null,
    truncated: null,
  });
});

test("sqlStepInfo reads an executed database_query tool step's row count", () => {
  const info = sqlStepInfo({
    kind: "tool",
    tool: "database_query",
    outcome: "ok",
    detail: { query: "SELECT 1", row_count: 7 },
  });
  assert.deepEqual(info, { query: "SELECT 1", outcome: "ok", reason: null, rows: 7, truncated: null });
});

test("sqlStepInfo is null for a step that is neither SQL shape", () => {
  assert.equal(sqlStepInfo({ kind: "retrieve" }), null);
  assert.equal(sqlStepInfo({ kind: "tool", tool: "document_search" }), null);
});

// --- toolInjectionPatterns ----------------------------------------------------

test("toolInjectionPatterns is null for an unflagged tool step", () => {
  assert.equal(
    toolInjectionPatterns({ kind: "tool", tool: "database_query", injection_flagged: false }),
    null,
  );
});

test("toolInjectionPatterns names the patterns found on a flagged tool step", () => {
  assert.deepEqual(
    toolInjectionPatterns({
      kind: "tool",
      tool: "database_query",
      injection_flagged: true,
      injection_patterns: ["ignore previous instructions"],
    }),
    ["ignore previous instructions"],
  );
});

test("toolInjectionPatterns is null for a non-tool step even if it happens to carry the flag", () => {
  assert.equal(toolInjectionPatterns({ kind: "sql", injection_flagged: true }), null);
});

// --- toolCeilingPendingCalls --------------------------------------------------

test("toolCeilingPendingCalls is null when the turn did not stop at the ceiling", () => {
  const trace: TraceData = { steps: [], steps_truncated: false, trace_rotated: false };
  assert.equal(toolCeilingPendingCalls(trace), null);
});

test("toolCeilingPendingCalls names what the loop was about to do when the ceiling stopped it", () => {
  const trace: TraceData = {
    steps: [],
    steps_truncated: false,
    trace_rotated: false,
    loop_stopped_reason: "tool_ceiling",
    loop_pending_calls: [{ tool: "database_query", arguments: { question: "and then?" } }],
  };
  assert.deepEqual(toolCeilingPendingCalls(trace), [
    { tool: "database_query", arguments: { question: "and then?" } },
  ]);
});

// --- hitCitation (M5-TRACE-FE-121) --------------------------------------------

function card(over: Partial<CitationCard> = {}): CitationCard {
  return {
    chunkId: "c1",
    documentId: "d1",
    filename: "contract.pdf",
    anchorKind: null,
    heading: null,
    pageFrom: 3,
    pageTo: 3,
    passage: "Notice is ninety days.",
    quotedSpan: "ninety days",
    claimOrdinals: [1],
    ...over,
  };
}

test("hitCitation finds the citation card the answer actually used for a hit", () => {
  const cards = [card({ chunkId: "c1" }), card({ chunkId: "c2", documentId: "d2" })];
  assert.equal(hitCitation({ chunkId: "c2", score: 0.7 }, cards), cards[1]);
});

test("hitCitation is null for a candidate the answer never cited", () => {
  assert.equal(hitCitation({ chunkId: "unused", score: 0.5 }, [card()]), null);
});

// --- buildTraceCopyText (M5-TRACE-FE-121) -------------------------------------

test("buildTraceCopyText includes the question, backend, steps, scores and threshold", () => {
  const trace: TraceData = {
    steps: [
      { kind: "retrieve", ms: 340, threshold: 0.65, hits: [{ chunk_id: "c1", score: 0.81 }] },
      { kind: "compose", ms: 8200, claims: 1, citations: 1 },
    ],
    steps_truncated: false,
    trace_rotated: false,
    backend: { mode: "local", model: "qwen2.5-7b" },
  };
  const text = buildTraceCopyText(trace, "What are the payment terms?");
  assert.match(text, /Question: What are the payment terms\?/);
  assert.match(text, /Backend: local · qwen2\.5-7b/);
  assert.match(text, /Threshold 0\.65/);
  assert.match(text, /Score 0\.81/);
  assert.match(text, /Wrote the answer/);
});

test("buildTraceCopyText states a rotated trace rather than copying nothing", () => {
  const trace: TraceData = { steps: [], steps_truncated: false, trace_rotated: true };
  const text = buildTraceCopyText(trace, "A question");
  assert.match(text, /cleared/);
});

test("buildTraceCopyText states truncation from the ring buffer, not just steps left out", () => {
  const trace: TraceData = {
    steps: [{ kind: "retrieve", ms: 1, threshold: 0.65, hits: [] }],
    steps_truncated: true,
    trace_rotated: false,
  };
  const text = buildTraceCopyText(trace, "A question");
  assert.match(text, /Some steps from this turn were left out/);
});

test("buildTraceCopyText truncates a very long trace and says so in the copied text", () => {
  const hits = Array.from({ length: 5000 }, (_, index) => ({ chunk_id: `c${index}`, score: 0.5 }));
  const trace: TraceData = {
    steps: [{ kind: "retrieve", ms: 1, threshold: 0.65, hits }],
    steps_truncated: false,
    trace_rotated: false,
  };
  const text = buildTraceCopyText(trace, "A question");
  assert.match(text, /\[Trace truncated for length\.\]$/);
  assert.ok(text.length < 21_000);
});
