"use client";

import { useEffect, useState } from "react";

import {
  EMPTY_MEMORY_COPY,
  EMPTY_MEMORY_CTA,
  deletedSourceNote,
  factDateLabel,
  fetchMemoryScreen,
  inferredReviewSentence,
  originLabel,
  usageSentence,
  type MemoryRow,
  type MemoryScreenState,
} from "@/lib/memory";

/**
 * The memory screen: the list, confidence markers and the usage count.
 * `docs/ux/memory.md`, `M3-MEM-FE-083`.
 *
 * Interactions — Edit, Confirm, Delete, History, Filter, Add a fact — are
 * `M3-MEM-FE-084`'s own territory (Out of Scope here). This screen only
 * reads and renders: both fact kinds together, the confidence marker,
 * source, usage count, and a fact's struck-through history when it has one.
 */
export function MemoryScreen() {
  const [state, setState] = useState<MemoryScreenState | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    fetchMemoryScreen(controller.signal)
      .then((screen) => {
        if (live) setState(screen);
      })
      .catch((error: unknown) => {
        if (live && !controller.signal.aborted) setFailure(String(error));
      });
    return () => {
      live = false;
      controller.abort();
    };
  }, []);

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>Memory</h1>
        <p className="ask-prose mt-1" style={{ color: "var(--muted)" }}>
          What Askwell believes about your material, and where each belief came from.
        </p>
        {state !== null && state.inferredCount > 0 ? (
          <p className="ask-micro mt-1" style={{ color: "var(--inferred)" }}>
            {inferredReviewSentence(state.inferredCount)}
          </p>
        ) : null}
      </div>

      {failure !== null ? (
        <p className="ask-prose" style={{ color: "var(--alarm)" }}>
          Askwell is not answering about memory.
        </p>
      ) : state === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading memory…
        </p>
      ) : state.rows.length === 0 ? (
        <EmptyMemory />
      ) : (
        <div className="flex flex-col gap-2">
          {state.rows.map((row) => (
            <MemoryRowCard key={`${row.factKind}:${row.id}`} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}

function EmptyMemory() {
  return (
    <div
      className="flex flex-col gap-2 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <p className="ask-prose">{EMPTY_MEMORY_COPY}</p>
      <a className="ask-navigates ask-micro" href="/clarifications">
        {EMPTY_MEMORY_CTA}
      </a>
    </div>
  );
}

function MemoryRowCard({ row }: { row: MemoryRow }) {
  const deletedNote = deletedSourceNote(row);
  const date = factDateLabel(row.createdAt);

  return (
    <div
      className="flex flex-col gap-1.5 px-4 py-3"
      style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-1.5 ask-micro" style={{ fontFamily: "var(--font-mono)" }}>
          <span className="ask-confidence-marker" data-supplied={row.origin !== "inferred"} aria-hidden="true" />
          {row.subject}
        </span>
        {row.sourceName !== null ? (
          <span className="ask-micro" style={{ color: "var(--muted)" }}>
            {row.sourceName}
          </span>
        ) : null}
      </div>
      <p className="ask-prose">{row.value}</p>
      <p className="ask-micro" style={{ color: row.origin === "inferred" ? "var(--inferred)" : "var(--muted)" }}>
        {originLabel(row.origin)}
        {date !== null ? ` · ${date}` : ""} · {usageSentence(row.usageCount)}
      </p>
      {deletedNote !== null ? (
        <p className="ask-micro" style={{ color: "var(--muted)" }}>
          {deletedNote}
        </p>
      ) : null}
      {row.history.length > 0 ? <MemoryHistory row={row} /> : null}
    </div>
  );
}

/** `docs/ux/memory.md` §5, "Conflicting facts": the later value wins as the
 * row itself; every earlier value stays visible here, struck through,
 * rather than discarded. */
function MemoryHistory({ row }: { row: MemoryRow }) {
  return (
    <div className="flex flex-col gap-0.5 mt-1" style={{ borderLeft: "2px solid var(--rule)", paddingLeft: "8px" }}>
      {row.history.map((entry, index) => {
        const date = factDateLabel(entry.createdAt);
        return (
          <p key={index} className="ask-micro" style={{ color: "var(--muted)", textDecoration: "line-through" }}>
            {entry.value}
            {date !== null ? ` · ${date}` : ""}
          </p>
        );
      })}
    </div>
  );
}
