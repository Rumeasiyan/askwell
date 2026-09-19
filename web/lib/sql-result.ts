/**
 * A database-answered turn's stored result snapshot, and the pure display
 * logic around it. `M4-RESULT-FE-109`.
 *
 * The shape mirrors `askwell.ask`'s own `sql_result` dict exactly (snake_case
 * kept, same as `AskCitationData`) — it is the literal JSON the `done` event
 * carries, `messages.sql_result` read straight back, never re-derived.
 *
 * Pagination here is entirely client-side over `rows`, which is already the
 * full (limit-capped) snapshot the server executed and stored — never a
 * re-query. That is the ticket's own assumption: "the page the user reads is
 * internally consistent" only holds if paging never asks the database for
 * anything new.
 */
export interface SqlResultData {
  engine: string;
  source_id: string;
  query: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  duration_ms: number;
}

export const SQL_RESULT_PAGE_SIZE = 50;

/**
 * The ticket's own edge case: "a single-value result — rendered as a number
 * in the answer rather than a one-cell table." One column, one row is the
 * whole snapshot, not merely the current page — a truncated one-row result
 * (theoretically possible with a `LIMIT 1` a user asked for) still counts,
 * since there is still exactly one thing to show.
 */
export function isSingleValue(result: Pick<SqlResultData, "columns" | "rows">): boolean {
  return result.columns.length === 1 && result.rows.length === 1;
}

/**
 * "Labelled as the first N of possibly more where the limit was reached"
 * (this ticket's own Detailed Description) — `null` when the injected limit
 * was never hit, so an ordinary complete result shows no label at all.
 */
export function truncationLabel(
  result: Pick<SqlResultData, "row_count" | "truncated">,
): string | null {
  if (!result.truncated) return null;
  const rows = result.row_count;
  return `First ${rows} row${rows === 1 ? "" : "s"} shown — there may be more.`;
}

export type CellKind = "null" | "empty" | "value";

export interface CellDisplay {
  kind: CellKind;
  text: string;
}

/**
 * A single cell, rendered distinguishably by kind (this ticket's own edge
 * case: "a result with null values — rendered distinguishably from empty
 * strings"). `NULL` reads as apparatus, an empty string as nothing at all —
 * the caller styles `kind` rather than trying to tell them apart from text
 * alone.
 */
export function formatCell(value: unknown): CellDisplay {
  if (value === null || value === undefined) return { kind: "null", text: "NULL" };
  if (typeof value === "string") {
    return value === "" ? { kind: "empty", text: "" } : { kind: "value", text: value };
  }
  if (typeof value === "boolean") return { kind: "value", text: value ? "true" : "false" };
  if (typeof value === "object") return { kind: "value", text: JSON.stringify(value) };
  return { kind: "value", text: String(value) };
}

/** Right-aligns a column whose values are all numeric (nulls aside) —
 * "column headers and types respected" without the server sending a type
 * alongside each column name. Left-aligned is the safe default for every
 * other case, including a column with no non-null value to judge by. */
export function columnAlign(rows: readonly (readonly unknown[])[], columnIndex: number): "left" | "right" {
  let sawNumber = false;
  for (const row of rows) {
    const value = row[columnIndex];
    if (value === null || value === undefined) continue;
    if (typeof value !== "number") return "left";
    sawNumber = true;
  }
  return sawNumber ? "right" : "left";
}

export interface SqlResultPage {
  rows: unknown[][];
  page: number;
  pageCount: number;
  hasPrevious: boolean;
  hasNext: boolean;
}

/**
 * Pure paging over an already-fetched row list — checkable without a
 * browser, the same reason `conversationWindow` (`lib/ask.ts`) is pure.
 * `page` clamps into range rather than throwing, so a stale page number
 * (rows shrank, though they never do post-snapshot) degrades to the last
 * page instead of an empty one.
 */
export function paginateSqlRows(
  rows: readonly (readonly unknown[])[],
  page: number,
  pageSize: number = SQL_RESULT_PAGE_SIZE,
): SqlResultPage {
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const clamped = Math.min(Math.max(page, 1), pageCount);
  const start = (clamped - 1) * pageSize;
  return {
    rows: rows.slice(start, start + pageSize).map((row) => [...row]),
    page: clamped,
    pageCount,
    hasPrevious: clamped > 1,
    hasNext: clamped < pageCount,
  };
}

/**
 * A database answer that never reached `sql_result` — rejected, a failed
 * dry run, a timeout, a query-time failure, or the source vanishing
 * mid-turn (`askwell.ask._sql_query_disclosure`, `M4-RESULT-FE-110`).
 * `outcome` mirrors the server's own trace step verbatim (`"rejected"`,
 * `"timeout"`, `"dry_run_failed"`, …) — this module never re-derives it
 * from the refusal text, which is prose meant for a person, not a value to
 * pattern-match on.
 */
export interface SqlQueryDisclosure {
  query: string;
  outcome: string;
}

/** The exact trailing comment `askwell.sql.limit.INJECTED_LIMIT_COMMENT`
 * attaches to a `LIMIT` clause it added — never one the model wrote. Kept
 * as one literal here rather than imported, the same way this module
 * already mirrors `askwell.ask`'s wire shapes without importing Python. */
const INJECTED_LIMIT_COMMENT = "Added by Askwell";

export interface QuerySegment {
  text: string;
  injected: boolean;
}

/**
 * Splits a query into plain text and the injected `LIMIT` clause, so the
 * caller can render the clause distinguishably (`ask.md` §4: "`LIMIT`
 * visible if injected") without re-parsing SQL client-side. Matches the
 * clause and its trailing comment together — `LIMIT 1000 /* Added by
 * Askwell *\/` — rather than only the comment, since the comment alone,
 * highlighted on its own, would not visually point at what it is marking.
 * A query with no injected limit (the model's own cap, or none needed)
 * comes back as a single, unmarked segment.
 */
export function segmentInjectedLimit(query: string): QuerySegment[] {
  const pattern = new RegExp(`\\bLIMIT\\s+\\d+\\s*\\/\\*\\s*${INJECTED_LIMIT_COMMENT}\\s*\\*\\/`, "i");
  const match = pattern.exec(query);
  if (match === null) return [{ text: query, injected: false }];
  const before = query.slice(0, match.index);
  const after = query.slice(match.index + match[0].length);
  const segments: QuerySegment[] = [];
  if (before !== "") segments.push({ text: before, injected: false });
  segments.push({ text: match[0], injected: true });
  if (after !== "") segments.push({ text: after, injected: false });
  return segments;
}

// A local counter of SQL disclosures expanded (this ticket's own Analytics
// Events line) — in-memory only, never persisted or transmitted (C1), same
// shape as `answer-annotations.ts`'s `conflictsPresentedCount`.
let sqlDisclosuresExpandedCount = 0;

export function recordSqlDisclosureExpanded(): void {
  sqlDisclosuresExpandedCount += 1;
}

export function getSqlDisclosuresExpandedCount(): number {
  return sqlDisclosuresExpandedCount;
}

/** Where "View full result" (`SqlResultTable`) opens the database source
 * view (`docs/ux/source-viewer.md` §2's database row) — the same
 * query-string-on-one-static-route shape `documentHref` (`lib/citations.ts`)
 * uses under this app's static export, `result` in place of `id` since a
 * query result has no document id to key on. */
export function sqlResultHref(messageId: string, turnId?: string): string {
  const params = new URLSearchParams({ result: messageId });
  if (turnId !== undefined) params.set("turn", turnId);
  return `/documents/?${params.toString()}`;
}
