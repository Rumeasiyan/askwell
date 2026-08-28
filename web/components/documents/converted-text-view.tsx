"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { locateOnPage, pageNote, searchTargets } from "@/lib/pdf-highlight";

import { PageNav, UnrenderableFallback, highlightSpan } from "./viewer-shared";

/**
 * Word, PowerPoint, plain text, Markdown and HTML: converted text with
 * structure preserved and the heading anchored. `M1-VIEW-FE-047`.
 *
 * Nothing here renders the original layout — `extract_docx`/`extract_pptx`/
 * `extract_text` already reduced each format to one `document_pages` row per
 * heading, slide or approximate page, and this is that row read back and
 * shown at the cited position, the same "one anchor, fetched by ordinal"
 * shape `document-viewer.tsx`'s PDF path already uses for its own fallback
 * text, generalised to be the primary renderer here rather than a fallback.
 */

interface PageBody {
  text: string | null;
  has_text: boolean;
  anchor_label: string | null;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "loaded"; body: PageBody };

export function ConvertedTextView({
  documentId,
  filename,
  pageNumber,
  pageCount,
  quotedSpan,
  passage,
  onChangePage,
}: {
  documentId: string;
  filename: string;
  pageNumber: number;
  pageCount: number | null;
  quotedSpan: string | null;
  passage: string | null;
  onChangePage: (page: number) => void;
}) {
  const requestKey = `${documentId}:${pageNumber}`;
  // Loading is derived from whether the last completed fetch matches the
  // page this render is for, rather than reset by the effect itself — an
  // effect that unconditionally sets its own "loading" state as its first
  // act is the cascading-render pattern `react-hooks/set-state-in-effect`
  // flags, and comparing keys here is the fix React's own docs recommend.
  const [result, setResult] = useState<{ key: string; state: LoadState } | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/documents/${documentId}/pages/${pageNumber}`, {
          cache: "no-store",
        });
        if (!response.ok) {
          if (!cancelled) setResult({ key: requestKey, state: { kind: "error" } });
          return;
        }
        const body = (await response.json()) as PageBody;
        if (!cancelled) setResult({ key: requestKey, state: { kind: "loaded", body } });
      } catch {
        if (!cancelled) setResult({ key: requestKey, state: { kind: "error" } });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, pageNumber, requestKey]);

  const state: LoadState = result?.key === requestKey ? result.state : { kind: "loading" };

  const range = useMemo(() => {
    if (state.kind !== "loaded" || state.body.text === null) return null;
    const targets = searchTargets({ quotedSpan, passage: passage ?? "" });
    return targets.length > 0 ? locateOnPage(state.body.text, targets) : null;
  }, [state, quotedSpan, passage]);

  const notFound =
    state.kind === "loaded" &&
    range === null &&
    state.body.has_text &&
    pageNote(state.body.text ?? "", false) === "not-found";

  useEffect(() => {
    if (state.kind !== "loaded" || bodyRef.current === null) return;
    const div = bodyRef.current;
    div.textContent = state.body.text ?? "";
    if (range !== null) {
      highlightSpan(div, range.start, range.end);
      div.querySelector("mark")?.scrollIntoView({ block: "center" });
    }
  }, [state, range]);

  if (state.kind === "loading") {
    return <p className="ask-micro p-4">Opening…</p>;
  }

  if (state.kind === "error") {
    return (
      <UnrenderableFallback
        filename={filename}
        documentId={documentId}
        note="This section could not be read."
      />
    );
  }

  const { body } = state;

  return (
    <section className="flex flex-col gap-3 p-4">
      <header className="flex items-baseline justify-between gap-3">
        <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>{filename}</h1>
        <PageNav pageNumber={pageNumber} pageCount={pageCount} onChange={onChangePage} />
      </header>

      {body.anchor_label !== null ? (
        <h2 style={{ fontSize: "var(--t-ui)", fontWeight: 600 }}>{body.anchor_label}</h2>
      ) : (
        <p className="ask-prose ask-pdf-page-note">
          This document has no headings here — showing the passage at its position in the
          document.
        </p>
      )}

      {notFound ? (
        <p className="ask-prose ask-pdf-page-note">
          The exact passage could not be pinpointed here — showing the cited section instead.
        </p>
      ) : null}

      {body.has_text ? (
        <div ref={bodyRef} className="ask-prose" style={{ whiteSpace: "pre-wrap" }} />
      ) : (
        <p className="ask-prose">This section has no extracted text.</p>
      )}
    </section>
  );
}
