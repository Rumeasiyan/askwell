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
