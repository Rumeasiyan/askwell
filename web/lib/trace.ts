/**
 * The trace panel's data: `GET /ask/{message_id}/trace` (`askwell.ask.
 * ask_trace`, `M5-TRACE-BE-125`), rendered by `M5-TRACE-FE-119`.
 *
 * `docs/ux/trace.md` §2: a numbered vertical sequence of steps, each with a
 * plain-language summary and a duration, raw detail expandable underneath.
 * The server returns `steps` exactly as stored (C4: never recomputed), so
 * this module's job is turning that raw, differently-shaped-per-`kind`
 * object into the summary line a non-technical reader needs — the deeper
 * formatting of what is *inside* a step (scores, passages, a query's own
 * syntax highlighting) is `M5-TRACE-FE-120`'s own scope, added below the
 * `M5-TRACE-FE-119` reading functions this docstring originally described.
 * The fallback for a step this module does not specifically know how to
 * phrase is its raw `kind`, never a blank line — an unfamiliar step kind is
 * still a row in the sequence.
 */

export interface TraceStep {
  kind: string;
  [key: string]: unknown;
}

/** The turn's own backend, named once rather than per step (`docs/ux/
 * trace.md` §3's "Backend" row) — `askwell.ask` writes exactly this shape
 * onto every `trace`, local or (once M8 lands) online. */
export interface TraceBackend {
  mode: string;
  model: string;
}

/** One call `run_tool_loop` (`M5-LOOP-BE-116`) was about to make when the
 * 8-call ceiling cut it off — `LoopResult.pending_calls`, carried onto
 * `trace.loop_pending_calls` verbatim. */
export interface PendingToolCall {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface TraceData {
  steps: TraceStep[];
  steps_truncated: boolean;
  trace_rotated: boolean;
  status?: string;
  backend?: TraceBackend;
  loop_stopped_reason?: string | null;
  loop_pending_calls?: PendingToolCall[];
  injection_flagged?: boolean;
  injection_patterns?: string[];
  [key: string]: unknown;
}

/** A turn still generating has no persisted row yet — served straight from
 * the live registry (`askwell.ask.ask_trace`'s own docstring) — so a poll
 * while `status === "running"` is expected to see the list grow, not an
 * error. */
export async function fetchTrace(messageId: string, signal?: AbortSignal): Promise<TraceData> {
  const response = await fetch(`/ask/${messageId}/trace`, {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about that trace.`);
  }
  return (await response.json()) as TraceData;
}

/** "340 ms" under a second, "8.2 s" at or over one — `docs/ux/trace.md` §2's
 * own worked example uses exactly this split. `null` in, `null` out: a step
 * that carries no timing at all (`memory_retrieve`, `abstain`,
 * `inline_clarification` — none of `askwell.ask`'s trace-step literals for
 * these carry `ms`/`duration_ms`) states nothing rather than inventing a
 * zero, which is Validation Rule's "timings always visible" — for a step
 * that has one — not "every step must have a number". */
export function formatDuration(ms: number | null): string | null {
  if (ms === null) return null;
  const rounded = Math.max(0, Math.round(ms));
  if (rounded >= 1000) return `${(rounded / 1000).toFixed(1)} s`;
  return `${rounded} ms`;
}

/** Every `kind` writes its timing under a different key — `ms` (a float,
 * `_run_generation`'s own retrieve/compose steps) or `duration_ms` (an
 * int, every tool/loop/SQL-execution step). Reading both rather than
 * picking one keeps this module agnostic of which stage produced the
 * step. */
function stepDurationMs(step: TraceStep): number | null {
  const raw = step.duration_ms ?? step.ms;
  return typeof raw === "number" ? raw : null;
}

const TOOL_LABELS: Record<string, string> = {
  document_search: "Searched your files",
  database_query: "Queried your database",
  schema_lookup: "Looked up schema",
  document_listing: "Listed your documents",
  current_date: "Checked today's date",
};

const SQL_OUTCOME_SUMMARIES: Record<string, (step: TraceStep) => string> = {
  no_connections: () => "No connected databases",
  source_attention: () => "A connected database needs attention",
  source_importing: () => "A connected database is still importing",
  ambiguous: (step) => {
    const candidates = Array.isArray(step.candidates) ? (step.candidates as string[]) : [];
    return candidates.length > 0
      ? `More than one database could answer this: ${candidates.join(", ")}`
      : "More than one database could answer this";
  },
  rejected: (step) => `Generated SQL was rejected${step.reason ? ` (${String(step.reason)})` : ""}`,
  source_gone: () => "The database this question would have used is no longer connected",
  dry_run_failed: (step) => `Query failed validation${step.reason ? `: ${String(step.reason)}` : ""}`,
  timeout: () => "Query timed out",
  executed: (step) => {
    const rows = typeof step.rows === "number" ? step.rows : null;
    if (rows === null) return "Queried your database";
    const truncated = step.truncated === true ? ", truncated" : "";
    return `Queried your database — ${rows} row${rows === 1 ? "" : "s"}${truncated}`;
  },
};

/** One row's plain-language line — `docs/ux/trace.md` §2's "what it did".
 * Every branch reads only fields that kind actually carries; an unfamiliar
 * or malformed step falls back to naming its own `kind` literally rather
 * than throwing or rendering nothing. */
export function stepSummary(step: TraceStep): string {
  switch (step.kind) {
    case "retrieve": {
      const hits = Array.isArray(step.hits) ? (step.hits as { score: number }[]) : [];
      if (hits.length === 0) return "Searched your files — nothing came back";
      const top = Math.max(...hits.map((hit) => hit.score));
      return `Searched your files — ${hits.length} passage${hits.length === 1 ? "" : "s"}, top score ${top.toFixed(2)}`;
    }
    case "abstain": {
      const reason = typeof step.reason_code === "string" ? step.reason_code.replaceAll("_", " ") : null;
      return reason ? `Nothing matched — ${reason}` : "Nothing matched";
    }
    case "memory_retrieve": {
      const facts = Array.isArray(step.memory_fact_ids) ? step.memory_fact_ids.length : 0;
      const notes = Array.isArray(step.schema_note_ids) ? step.schema_note_ids.length : 0;
      return `Checked your memory — ${facts} fact${facts === 1 ? "" : "s"}, ${notes} schema note${notes === 1 ? "" : "s"}`;
    }
    case "inline_clarification": {
      const subject = typeof step.subject === "string" ? step.subject : "a detail";
      return step.skipped === true ? `Skipped a question about ${subject}` : `Asked about ${subject}`;
    }
    case "compose": {
      const claims = typeof step.claims === "number" ? step.claims : 0;
      const citations = typeof step.citations === "number" ? step.citations : 0;
      return `Wrote the answer — ${claims} claim${claims === 1 ? "" : "s"}, ${citations} cited`;
    }
    case "schema":
      return "Looked up schema";
    case "sql": {
      const outcome = typeof step.outcome === "string" ? step.outcome : null;
      const summarize = outcome ? SQL_OUTCOME_SUMMARIES[outcome] : undefined;
      return summarize ? summarize(step) : "Queried your database";
    }
    case "tool": {
      const tool = typeof step.tool === "string" ? step.tool : null;
      const base = (tool && TOOL_LABELS[tool]) || (tool ? `Called ${tool}` : "Called a tool");
      const outcome = typeof step.outcome === "string" ? step.outcome : null;
      return outcome && outcome !== "ok" ? `${base} — ${outcome.replaceAll("_", " ")}` : base;
    }
    default:
      return step.kind;
  }
}

/** The Testing Notes' own edge case: "a step with no detail worth expanding
 * — no expander rather than an empty one." A step whose only fields are
 * `kind` plus whatever `stepDurationMs`/`stepSummary` already surfaced has
 * nothing left an expander would add. */
export function hasExpandableDetail(step: TraceStep): boolean {
  const shown = new Set(["kind", "ms", "duration_ms", "outcome"]);
  return Object.keys(step).some((key) => !shown.has(key) && step[key] !== undefined);
}

/** One row, precomputed for rendering — `AskScreen`'s `TracePanel` maps
 * `steps` through this rather than repeating the field lookups per kind
 * inline in JSX. */
export interface TraceRow {
  index: number;
  summary: string;
  duration: string | null;
  expandable: boolean;
  step: TraceStep;
}

export function traceRows(steps: TraceStep[]): TraceRow[] {
  return steps.map((step, index) => ({
    index: index + 1,
    summary: stepSummary(step),
    duration: formatDuration(stepDurationMs(step)),
    expandable: hasExpandableDetail(step),
    step,
  }));
}

/** One retrieved passage's id and comparable score — `retrieve`'s own
 * `hits`, sorted highest first so the near-miss the abstention trace exists
 * to show (`docs/ux/trace.md` §3) reads as the top of the list, not
 * something to hunt for. */
export interface RetrievedHit {
  chunkId: string;
  score: number;
}

export function retrievedHits(step: TraceStep): RetrievedHit[] {
  const hits = Array.isArray(step.hits) ? (step.hits as { chunk_id: string; score: number }[]) : [];
  return hits
    .map((hit) => ({ chunkId: hit.chunk_id, score: hit.score }))
    .sort((a, b) => b.score - a.score);
}

export function retrievalThreshold(step: TraceStep): number | null {
  return typeof step.threshold === "number" ? step.threshold : null;
}

/** A `memory_retrieve` step carries only ids (`askwell.ask`'s own
 * `memory_fact_ids`/`schema_note_ids`) — the origin, subject and value a
 * reader needs come from `GET /memory/facts/{kind}/{id}`
 * (`lib/memory-chips.ts::fetchFactDetail`), fetched per id by the panel. */
export interface MemoryFactRef {
  factKind: "memory" | "schema_note";
  factId: string;
}

export function memoryFactRefs(step: TraceStep): MemoryFactRef[] {
  const facts = Array.isArray(step.memory_fact_ids) ? (step.memory_fact_ids as string[]) : [];
  const notes = Array.isArray(step.schema_note_ids) ? (step.schema_note_ids as string[]) : [];
  return [
    ...facts.map((factId): MemoryFactRef => ({ factKind: "memory", factId })),
    ...notes.map((factId): MemoryFactRef => ({ factKind: "schema_note", factId })),
  ];
}

/** A database turn's query, validation outcome and rejection/failure
 * reason, read the same way whether it came from the single-shot SQL turn
 * (`kind: "sql"`) or a `database_query` tool call inside the loop
 * (`kind: "tool"`, `tool: "database_query"`) — `docs/ux/trace.md` §3 draws
 * no distinction between the two, and a reader should not have to know
 * which path answered. `null` when a step carries neither shape. */
export interface SqlStepInfo {
  query: string | null;
  outcome: string;
  reason: string | null;
  rows: number | null;
  truncated: boolean | null;
}

export function sqlStepInfo(step: TraceStep): SqlStepInfo | null {
  if (step.kind === "sql") {
    return {
      query: typeof step.query === "string" ? step.query : null,
      outcome: typeof step.outcome === "string" ? step.outcome : "unknown",
      reason: typeof step.reason === "string" ? step.reason : null,
      rows: typeof step.rows === "number" ? step.rows : null,
      truncated: typeof step.truncated === "boolean" ? step.truncated : null,
    };
  }
  if (step.kind === "tool" && step.tool === "database_query") {
    const detail = (step.detail && typeof step.detail === "object" ? step.detail : {}) as Record<
      string,
      unknown
    >;
    const outcome = typeof step.outcome === "string" ? step.outcome : "unknown";
    return {
      query: typeof detail.query === "string" ? detail.query : null,
      outcome,
      // `askwell.agent.tools._err`'s own `**detail` kwargs — the same
      // `reason` code `kind: "sql"` carries for the single-shot path, not
      // a second, differently-shaped message.
      reason: typeof detail.reason === "string" ? detail.reason : null,
      rows: typeof detail.row_count === "number" ? detail.row_count : null,
      truncated: null,
    };
  }
  return null;
}

/** A tool call's own injection flag (`M5-TOOLS-BE-114`'s `ToolStep`) —
 * information, never an alarm (`docs/ux/trace.md` §3, this ticket's own
 * Scope). */
export function toolInjectionPatterns(step: TraceStep): string[] | null {
  if (step.kind !== "tool" || step.injection_flagged !== true) return null;
  return Array.isArray(step.injection_patterns) ? (step.injection_patterns as string[]) : [];
}

/** What the tool loop was about to do when the 8-call ceiling stopped it —
 * `trace.loop_pending_calls`, only meaningful when `loop_stopped_reason`
 * says the ceiling is why the turn stopped (`docs/ux/trace.md` §3's
 * "Tool-ceiling stop"). */
export function toolCeilingPendingCalls(trace: TraceData): PendingToolCall[] | null {
  if (trace.loop_stopped_reason !== "tool_ceiling") return null;
  return trace.loop_pending_calls ?? [];
}

// A local counter of trace opens (this ticket's own Analytics Events line) —
// in-memory only, never persisted or transmitted (C1), same shape as
// `lib/ask.ts`'s `inlineClarificationsShownCount`.
let traceOpensCount = 0;

export function recordTraceOpened(): void {
  traceOpensCount += 1;
}

export function getTraceOpensCount(): number {
  return traceOpensCount;
}
