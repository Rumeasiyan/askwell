"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { locateOnPage, searchTargets } from "@/lib/pdf-highlight";

import { UnrenderableFallback, highlightSpan } from "./viewer-shared";

/**
 * A spreadsheet, as the table it is rather than the one row a citation
 * names. `M1-VIEW-FE-047`.
 *
 * `extract_xlsx` writes one `document_pages` anchor per non-empty row,
 * `" | "`-joined cell by cell (`extract_xlsx._row_text`) — reversed here
 * into cells for display. Windowed by hand rather than pulling in a
 * virtualisation dependency: a fixed row height and one scroll listener are
 * enough to keep a many-thousand-row sheet to a few dozen live DOM rows,
 * which is the ticket's own edge case ("a spreadsheet with thousands of
 * rows — virtualised, landing on the cited row").
 */

interface Row {
  page_number: number;
  anchor_label: string | null;
  text: string | null;
  has_text: boolean;
}

type LoadState = { kind: "loading" } | { kind: "error" } | { kind: "loaded"; rows: Row[] };

const ROW_HEIGHT = 32;
const VIEWPORT_HEIGHT = 480;
const OVERSCAN = 8;
const NO_ROWS: Row[] = [];

export function SpreadsheetView({
  documentId,
  filename,
  pageNumber,
  quotedSpan,
  passage,
}: {
  documentId: string;
  filename: string;
  pageNumber: number;
  quotedSpan: string | null;
  passage: string | null;
}) {
  // Loading is derived by comparing the last completed fetch's own document
  // id against this render's, rather than reset synchronously by the effect
  // — the same fix `converted-text-view.tsx` uses for the identical
  // `react-hooks/set-state-in-effect` pattern.
  const [result, setResult] = useState<{ documentId: string; state: LoadState } | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const highlightedRowRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/documents/${documentId}/pages`, { cache: "no-store" });
        if (!response.ok) {
          if (!cancelled) setResult({ documentId, state: { kind: "error" } });
          return;
        }
        const rows = (await response.json()) as Row[];
        if (!cancelled) setResult({ documentId, state: { kind: "loaded", rows } });
      } catch {
        if (!cancelled) setResult({ documentId, state: { kind: "error" } });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const state: LoadState = result?.documentId === documentId ? result.state : { kind: "loading" };

  useEffect(() => {
    if (state.kind !== "loaded" || scrollerRef.current === null) return;
    const index = state.rows.findIndex((row) => row.page_number === pageNumber);
    if (index === -1) return;
    const target = Math.max(0, index * ROW_HEIGHT - VIEWPORT_HEIGHT / 2);
    // Assigning `scrollTop` fires a native `scroll` event just as a user's
    // own scroll would, which `onScroll` below picks up — so the visible
    // window updates from that real browser event rather than from a second,
    // synchronous `setState` call sitting in this effect.
    scrollerRef.current.scrollTop = target;
  }, [state, pageNumber]);

  useEffect(() => {
    if (highlightedRowRef.current === null) return;
    const div = highlightedRowRef.current;
    const targets = searchTargets({ quotedSpan, passage: passage ?? "" });
    const text = div.dataset["rowText"] ?? "";
    const range = targets.length > 0 ? locateOnPage(text, targets) : null;
    if (range !== null) {
      div.textContent = text;
      highlightSpan(div, range.start, range.end);
    }
  }, [scrollTop, quotedSpan, passage]);

  const rows = state.kind === "loaded" ? state.rows : NO_ROWS;
  const totalHeight = rows.length * ROW_HEIGHT;
  const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const endIndex = Math.min(
    rows.length,
    Math.ceil((scrollTop + VIEWPORT_HEIGHT) / ROW_HEIGHT) + OVERSCAN,
  );
  const visible = useMemo(() => rows.slice(startIndex, endIndex), [rows, startIndex, endIndex]);

  if (state.kind === "loading") {
    return <p className="ask-micro p-4">Opening…</p>;
  }

  if (state.kind === "error" || rows.length === 0) {
    return (
      <UnrenderableFallback
        filename={filename}
        documentId={documentId}
        note="This spreadsheet could not be read as a table."
      />
    );
  }

  return (
    <section className="flex flex-col gap-3 p-4">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>{filename}</h1>
      <div
        ref={scrollerRef}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        style={{ height: VIEWPORT_HEIGHT, overflow: "auto", border: "1px solid var(--rule)" }}
      >
        <div style={{ position: "relative", height: totalHeight }}>
          {visible.map((row, offset) => {
            const index = startIndex + offset;
            const isHighlighted = row.page_number === pageNumber;
            const cells = (row.text ?? "").split(" | ");
            return (
              <div
                key={row.page_number}
                ref={isHighlighted ? highlightedRowRef : undefined}
                data-row-text={row.text ?? ""}
                className={isHighlighted ? "ask-micro ask-row-highlight" : "ask-micro"}
                style={{
                  position: "absolute",
                  top: index * ROW_HEIGHT,
                  left: 0,
                  right: 0,
                  height: ROW_HEIGHT,
                  display: "flex",
                  alignItems: "center",
                  gap: "0.75rem",
                  padding: "0 0.5rem",
                  borderBottom: "1px solid var(--rule)",
                  overflow: "hidden",
                  whiteSpace: "nowrap",
                }}
              >
                {isHighlighted
                  ? row.text
                  : cells.map((cell, cellIndex) => <span key={cellIndex}>{cell}</span>)}
              </div>
            );
          })}
        </div>
      </div>
      {rows.find((row) => row.page_number === pageNumber)?.anchor_label !== undefined ? (
        <p className="ask-micro">
          {rows.find((row) => row.page_number === pageNumber)?.anchor_label}
        </p>
      ) : null}
    </section>
  );
}
