"use client";

import { useState } from "react";
import Link from "next/link";

import {
  SQL_RESULT_PAGE_SIZE,
  columnAlign,
  formatCell,
  isSingleValue,
  paginateSqlRows,
  recordSqlDisclosureExpanded,
  segmentInjectedLimit,
  sqlResultHref,
  truncationLabel,
  type SqlQueryDisclosure,
  type SqlResultData,
} from "@/lib/sql-result";

/**
 * A database-answered turn's result. `M4-RESULT-FE-109`.
 *
 * Four states, this ticket's own granularity note ("one table with four
 * states"): a single value rendered as a number rather than a one-cell
 * table, a zero-row result with its own honest message, a paginated table
 * for everything else, and that table with a truncation label on top of it
 * when the injected `LIMIT` was actually reached. The query is shown in
 * every one of them — `states-and-edge-cases.md` §4's "disclosure is
 * unconditional" applies as much to a result that came back empty as to one
 * that came back rejected.
 *
 * `SqlQueryCard`, below, is this same disclosure's sibling for the branches
 * that never reach a `sql_result` at all — a rejection, a timeout, a failed
 * dry run — `M4-RESULT-FE-110`.
 */
export function SqlResultTable({
  result,
  messageId,
  turnId,
}: {
  result: SqlResultData;
  messageId: string | null;
  turnId: string;
}) {
  return (
    <div
      className="ask-card-raised flex flex-col gap-2 p-3"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--rule)",
        borderLeft: "2px solid var(--provenance)",
        borderRadius: "var(--radius)",
      }}
    >
      {isSingleValue(result) ? (
        <SingleValue result={result} />
      ) : result.row_count === 0 ? (
        <ZeroRows />
      ) : (
        <ResultTable result={result} />
      )}
      <QueryDisclosure query={result.query} />
      {messageId !== null ? (
        <Link
          href={sqlResultHref(messageId, turnId)}
          className="ask-navigates ask-micro w-fit"
          style={{ textTransform: "none" }}
        >
          View full result and query
        </Link>
      ) : null}
    </div>
  );
}

function SingleValue({ result }: { result: SqlResultData }) {
  const cell = formatCell(result.rows[0]?.[0]);
  return (
    <p
      className="ask-prose"
      style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)", color: "var(--ink)" }}
    >
      {cell.kind === "value" ? cell.text : cell.kind === "null" ? "NULL" : "—"}
    </p>
  );
}

function ZeroRows() {
  return (
    <p className="ask-prose" style={{ color: "var(--muted)" }}>
      No matching records.
    </p>
  );
}

function ResultTable({ result }: { result: SqlResultData }) {
  const [page, setPage] = useState(1);
  const paged = paginateSqlRows(result.rows, page, SQL_RESULT_PAGE_SIZE);
  const label = truncationLabel(result);

  return (
    <div className="flex flex-col gap-2">
      <p className="ask-micro" style={{ textTransform: "none" }}>
        {result.row_count} row{result.row_count === 1 ? "" : "s"}
        {label !== null ? ` · ${label}` : ""}
      </p>

      {/* Horizontal scroll rather than a broken layout for a very wide
          result (this ticket's own edge case) — the table keeps its natural
          column widths and the container clips, instead of every cell being
          squeezed to fit. */}
      <div style={{ overflowX: "auto", border: "1px solid var(--rule)" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              {result.columns.map((column, index) => (
                <th
                  key={column + index}
                  className="ask-micro"
                  style={{
                    textAlign: columnAlign(result.rows, index),
                    padding: "0.375rem 0.625rem",
                    borderBottom: "1px solid var(--rule-strong)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((value, cellIndex) => {
                  const cell = formatCell(value);
                  return (
                    <td
                      key={cellIndex}
                      className="ask-prose"
                      style={{
                        textAlign: columnAlign(result.rows, cellIndex),
                        padding: "0.375rem 0.625rem",
                        borderBottom: "1px solid var(--rule)",
                        color: cell.kind === "null" ? "var(--muted)" : "var(--ink)",
                        fontStyle: cell.kind === "null" ? "italic" : "normal",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {cell.kind === "null" ? "NULL" : cell.text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {paged.pageCount > 1 ? (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setPage((value) => value - 1)}
            disabled={!paged.hasPrevious}
            className="ask-micro"
            style={{
              background: "none",
              border: "1px solid var(--rule-strong)",
              padding: "0.125rem 0.5rem",
              cursor: paged.hasPrevious ? "pointer" : "default",
              opacity: paged.hasPrevious ? 1 : 0.4,
            }}
          >
            Previous
          </button>
          <span className="ask-micro" style={{ textTransform: "none" }}>
            Page {paged.page} of {paged.pageCount}
          </span>
          <button
            type="button"
            onClick={() => setPage((value) => value + 1)}
            disabled={!paged.hasNext}
            className="ask-micro"
            style={{
              background: "none",
              border: "1px solid var(--rule-strong)",
              padding: "0.125rem 0.5rem",
              cursor: paged.hasNext ? "pointer" : "default",
              opacity: paged.hasNext ? 1 : 0.4,
            }}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The query, shown unconditionally (`states-and-edge-cases.md` §4: "the
 * query is the citation") — collapsed behind a disclosure rather than
 * always open, since most readers trust the table and only some want to
 * check the SQL itself. `M4-RESULT-FE-110`: this is the one control both
 * `SqlResultTable` (an executed query) and `SqlQueryCard` (every other
 * outcome) render, so the two can never drift on what "expand" shows.
 *
 * `recordSqlDisclosureExpanded` fires on the transition into `expanded`
 * only, never on the way back out — the ticket's own Analytics Events line
 * ("disclosures expanded"), a count of how often, not how long.
 *
 * A very long query scrolls rather than wraps or truncates (the ticket's
 * own edge case) — `maxHeight` plus `overflow: auto` on a `pre` that keeps
 * its own line breaks, instead of `white-space: pre-wrap` forcing every
 * line to re-flow to the container width.
 */
export function QueryDisclosure({ query }: { query: string }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const segments = segmentInjectedLimit(query);

  const toggle = (): void => {
    setExpanded((value) => {
      if (!value) recordSqlDisclosureExpanded();
      return !value;
    });
  };

  const copy = (): void => {
    void navigator.clipboard.writeText(query).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => setCopied(false),
    );
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        className="ask-micro w-fit"
        style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}
      >
        {expanded ? "Hide query" : "Show query"}
      </button>
      {expanded ? (
        <div className="flex flex-col gap-2">
          <pre
            className="ask-micro"
            style={{
              textTransform: "none",
              whiteSpace: "pre",
              overflow: "auto",
              maxHeight: "16rem",
              color: "var(--muted)",
              background: "var(--paper)",
              border: "1px solid var(--rule)",
              borderRadius: "var(--radius)",
              padding: "0.5rem 0.625rem",
              margin: 0,
            }}
          >
            {segments.map((segment, index) =>
              segment.injected ? (
                <mark
                  key={index}
                  style={{
                    background: "var(--provenance)",
                    color: "var(--paper)",
                    borderRadius: "2px",
                  }}
                >
                  {segment.text}
                </mark>
              ) : (
                <span key={index}>{segment.text}</span>
              ),
            )}
          </pre>
          <button
            type="button"
            onClick={copy}
            className="ask-navigates ask-micro w-fit"
            style={{
              border: "1px solid var(--rule-strong)",
              padding: "0.125rem 0.5rem",
              textTransform: "none",
            }}
          >
            {copied ? "Copied" : "Copy query"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The disclosure for a database answer that never reached `sql_result` — a
 * rejected query, a failed dry run, a timeout, a query-time failure, or the
 * source vanishing mid-turn (`SqlQueryDisclosure`, `lib/sql-result.ts`,
 * `M4-RESULT-FE-110`). The refusal or timeout message itself is already the
 * turn's ordinary answer text, rendered by `AnswerProse` above this — this
 * card adds only what that prose cannot: the query the check was run
 * against, which is the whole reason a rejection is legible rather than a
 * bare "something went wrong". Same card shell and `QueryDisclosure` as
 * `SqlResultTable`, so a database answer looks like one system whether or
 * not the query ran.
 */
export function SqlQueryCard({ disclosure }: { disclosure: SqlQueryDisclosure }) {
  return (
    <div
      className="ask-card-raised flex flex-col gap-2 p-3"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--rule)",
        borderLeft: "2px solid var(--provenance)",
        borderRadius: "var(--radius)",
      }}
    >
      <QueryDisclosure query={disclosure.query} />
    </div>
  );
}
