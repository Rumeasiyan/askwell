"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import type { TextItem } from "pdfjs-dist/types/src/display/api";

import { documentFormat } from "@/lib/document-format";
import { locateOnPage, searchTargets,
  pageNote,
  type PageNote,
} from "@/lib/pdf-highlight";
import { buildPageText, itemsInRange } from "@/lib/pdf-text-map";

import { ContextRail, SupersededBanner } from "./context-rail";
import { ConvertedTextView } from "./converted-text-view";
import { SpreadsheetView } from "./spreadsheet-view";
import {
  MovedFileNotice,
  PageNav,
  RootUnavailableNotice,
  UnrenderableFallback,
  highlightSpan,
} from "./viewer-shared";

/**
 * The source viewer. `M1-VIEW-FE-046`.
 *
 * `/documents/{id}?page=...` — the route `M1-CITE-FE-043` guessed at
 * (`docs/decisions.md`, 2026-08-28) — cannot exist under this app's own
 * `output: "export"` (`next.config.ts`): a dynamic path segment needs every
 * value it will ever take enumerated at build time via `generateStaticParams`,
 * and a document id is not known until someone adds one. `web/app/documents/page.tsx`
 * is one static page; `id`, `page`, `span` and `passage` travel as query
 * parameters instead, read here with `useSearchParams`, and
 * `provenance-margin.tsx`'s card `href` was updated in the same change this
 * file was added in. Recorded as a decision, superseding the earlier guess —
 * `docs/decisions.md`.
 */

interface DocumentMetadata {
  id: string;
  filename: string;
  path: string;
  mime: string | null;
  page_count: number | null;
  anchor_kind: string | null;
  status: string;
  available: boolean;
  moved: boolean;
  missing_since: string | null;
  root_unavailable: boolean;
  root_reason: string | null;
  superseded_by: string | null;
  superseded_at: string | null;
}

type ViewerState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "moved"; meta: DocumentMetadata }
  | { kind: "root_unavailable"; meta: DocumentMetadata }
  | { kind: "unsupported"; meta: DocumentMetadata }
  | { kind: "ready"; meta: DocumentMetadata }
  | { kind: "converted"; meta: DocumentMetadata }
  | { kind: "spreadsheet"; meta: DocumentMetadata };

const RENDER_SCALE = 1.4;

interface OcrPanel {
  text: string | null;
  has_text: boolean;
  low_confidence: boolean;
}

export function DocumentViewer() {
  const searchParams = useSearchParams();
  const documentId = searchParams.get("id");
  const requestedPage = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const quotedSpan = searchParams.get("span");
  const passage = searchParams.get("passage");

  // The context rail's own origin, `M1-VIEW-FE-048`: which answer, which
  // claim, which citation among that answer's own list this is. All three
  // travel together — `documentHref`'s own `origin` param never sets one
  // without the others — so reading them here as a single optional group
  // rather than three independent nullable reads.
  const turnParam = searchParams.get("turn");
  const claimParam = searchParams.get("claim");
  const chunkParam = searchParams.get("chunk");
  const claimOrdinal = claimParam !== null ? Number.parseInt(claimParam, 10) : null;

  const [state, setState] = useState<ViewerState>({ kind: "loading" });
  // Bumped after a successful relocation to re-run the metadata fetch below —
  // `documentId` itself does not change, so nothing else would.
  const [reloadToken, setReloadToken] = useState(0);
  const [pageNumber, setPageNumber] = useState(Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1);
  const [pinpointNote, setPinpointNote] = useState<PageNote>("located");
  const [fallbackText, setFallbackText] = useState<string | null>(null);
  const [ocrPanel, setOcrPanel] = useState<OcrPanel | null>(null);
  const pageContainerRef = useRef<HTMLDivElement | null>(null);

  // Metadata: whether the document exists, is a PDF, and is still on disk.
  // `documentId === null` never reaches the effect at all — that is a fact
  // about the URL this component was given, knowable during render, not an
  // external system to synchronise with.
  useEffect(() => {
    if (documentId === null) return;
    let cancelled = false;
    void (async () => {
      let response: Response;
      try {
        response = await fetch(`/documents/${documentId}`, { cache: "no-store" });
      } catch {
        if (!cancelled) setState({ kind: "error", message: "Askwell could not be reached." });
        return;
      }
      if (cancelled) return;
      if (!response.ok) {
        setState({ kind: "error", message: "This document could not be opened." });
        return;
      }
      const meta = (await response.json()) as DocumentMetadata;
      if (cancelled) return;
      if (!meta.available) {
        // `moved` and `root_unavailable` are different facts
        // (`askwell.documents._availability`) and stay different states here
        // — never both collapsed into one "file is gone" message.
        setState({ kind: meta.root_unavailable ? "root_unavailable" : "moved", meta });
        return;
      }
      switch (documentFormat(meta.mime)) {
        case "pdf":
          setState({ kind: "ready", meta });
          break;
        case "converted-text":
          setState({ kind: "converted", meta });
          break;
        case "spreadsheet":
          setState({ kind: "spreadsheet", meta });
          break;
        case "unsupported":
          setState({ kind: "unsupported", meta });
          break;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, reloadToken]);

  // Rendering: only once metadata says this is a PDF that is actually there.
  useEffect(() => {
    if (state.kind !== "ready" || documentId === null) return;
    const id = documentId;
    const containerRef = pageContainerRef.current;
    if (containerRef === null) return;
    // Reassigned to a concretely non-null type — a nested `function`
    // declaration (`renderPage`, below) does not inherit narrowing applied
    // to a captured outer variable the way an inline arrow function would.
    const container: HTMLDivElement = containerRef;

    let cancelled = false;
    let pdf: PDFDocumentProxy | null = null;
    setPinpointNote("located");
    setFallbackText(null);
    setOcrPanel(null);

    void (async () => {
      const pdfjsLib = await import("pdfjs-dist");
      pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
        "pdfjs-dist/build/pdf.worker.min.mjs",
        import.meta.url,
      ).toString();

      let loaded: PDFDocumentProxy;
      try {
        // pdf.js's default loader issues HTTP Range requests against this
        // URL on its own — `documents.py`'s `FileResponse` answers them with
        // `206 Partial Content` — so the cited page's bytes arrive first and
        // the rest of a large document streams in behind it, without this
        // component deciding any byte order itself.
        loaded = await pdfjsLib.getDocument({ url: `/documents/${id}/file` }).promise;
      } catch {
        // The ticket's own edge case: "an unrenderable PDF — extracted text
        // with a note and an open-in-system-app option." pdf.js failing to
        // open the document at all is the same case as one page failing to
        // render — both fall back to whatever `document_pages.text` already
        // has for the requested page, which extraction wrote independently
        // of whether pdf.js can open the file.
        if (!cancelled) await loadFallbackText(id, pageNumber);
        return;
      }
      if (cancelled) {
        void loaded.cleanup();
        return;
      }
      pdf = loaded;

      const target = Math.min(Math.max(pageNumber, 1), pdf.numPages);
      if (target !== pageNumber) setPageNumber(target);
      await renderPage(pdf, target);
    })();

    async function loadFallbackText(documentId: string, page: number): Promise<void> {
      try {
        const response = await fetch(`/documents/${documentId}/pages/${page}`, { cache: "no-store" });
        const body = response.ok ? ((await response.json()) as { text: string | null }) : null;
        if (!cancelled) setFallbackText(body?.text ?? "");
      } catch {
        if (!cancelled) setFallbackText("");
      }
    }

    async function renderPage(doc: PDFDocumentProxy, number: number): Promise<void> {
      let page: PDFPageProxy;
      try {
        page = await doc.getPage(number);
      } catch {
        if (!cancelled) await loadFallbackText(id, number);
        return;
      }
      if (cancelled) return;

      const viewport = page.getViewport({ scale: RENDER_SCALE });

      container.replaceChildren();
      const pageEl = document.createElement("div");
      pageEl.className = "ask-pdf-page";
      pageEl.style.position = "relative";
      pageEl.style.width = `${viewport.width}px`;
      pageEl.style.height = `${viewport.height}px`;
      pageEl.style.setProperty("--total-scale-factor", String(RENDER_SCALE));

      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      pageEl.appendChild(canvas);

      const textLayerDiv = document.createElement("div");
      textLayerDiv.className = "ask-pdf-text-layer";
      pageEl.appendChild(textLayerDiv);

      const ctx = canvas.getContext("2d");
      if (ctx === null) return;

      try {
        await page.render({ canvas, canvasContext: ctx, viewport }).promise;
      } catch {
        if (!cancelled) await loadFallbackText(id, number);
        return;
      }
      if (cancelled) return;

      container.appendChild(pageEl);

      const textContent = await page.getTextContent();
      if (cancelled) return;

      const pdfjsLib = await import("pdfjs-dist");
      const textLayer = new pdfjsLib.TextLayer({
        textContentSource: textContent,
        container: textLayerDiv,
        viewport,
      });
      await textLayer.render();
      if (cancelled) return;

      const items = textContent.items
        .filter((item): item is TextItem => "str" in item)
        .map((item) => ({ text: item.str, hasEOL: item.hasEOL }));
      const { pageText, spans } = buildPageText(items);
      const targets = searchTargets({ quotedSpan, passage: passage ?? "" });
      const range = targets.length > 0 ? locateOnPage(pageText, targets) : null;

      if (range !== null) {
        const hits = itemsInRange(spans, range);
        for (const hit of hits) highlightSpan(textLayer.textDivs[hit.index], hit.localStart, hit.localEnd);
        const firstHit = hits[0];
        if (firstHit !== undefined) {
          textLayer.textDivs[firstHit.index]?.scrollIntoView({ block: "center" });
        }
      } else {
        // A scan and a genuine miss are the same event here and opposite facts
        // for the reader, so they are told apart by whether the page has a text
        // layer at all rather than left to share one message.
        const note = pageNote(pageText, false);
        setPinpointNote(note);
        pageEl.scrollIntoView({ block: "start" });
        // The "image" rendering kind, `M1-VIEW-FE-047`: a scanned page's own
        // OCR text, alongside the page image already on screen — this is
        // what lets someone discover a bad scan is why an answer was wrong.
        if (note === "scanned") await loadOcrPanel(id, number);
      }
    }

    async function loadOcrPanel(documentId: string, page: number): Promise<void> {
      try {
        const response = await fetch(`/documents/${documentId}/pages/${page}`, {
          cache: "no-store",
        });
        const body = response.ok
          ? ((await response.json()) as {
              text: string | null;
              has_text: boolean;
              low_confidence: boolean;
            })
          : null;
        if (!cancelled) {
          setOcrPanel(
            body === null
              ? { text: null, has_text: false, low_confidence: false }
              : { text: body.text, has_text: body.has_text, low_confidence: body.low_confidence },
          );
        }
      } catch {
        if (!cancelled) setOcrPanel({ text: null, has_text: false, low_confidence: false });
      }
    }

    return () => {
      cancelled = true;
      if (pdf !== null) void pdf.cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pageNumber is read, not written, by this effect except to clamp it once on load
  }, [state.kind, documentId, quotedSpan, passage]);

  if (documentId === null) {
    return (
      <section className="flex flex-col gap-2 p-4">
        <p className="ask-prose">No document was specified.</p>
      </section>
    );
  }

  if (state.kind === "loading") {
    return <p className="ask-micro p-4">Opening…</p>;
  }

  if (state.kind === "error") {
    return (
      <section className="flex flex-col gap-2 p-4">
        <p className="ask-prose">{state.message}</p>
      </section>
    );
  }

  const rail = (meta: DocumentMetadata): ReactNode => (
    <ContextRail
      documentId={meta.id}
      filename={meta.filename}
      pageNumber={pageNumber}
      passage={passage}
      turnId={turnParam}
      claimOrdinal={claimOrdinal}
      chunkId={chunkParam}
    />
  );

  const banner = (meta: DocumentMetadata): ReactNode =>
    meta.superseded_by !== null ? (
      <SupersededBanner supersededBy={meta.superseded_by} supersededAt={meta.superseded_at} />
    ) : null;

  if (state.kind === "moved") {
    return (
      <div className="flex min-w-0 flex-1 gap-4">
        <MovedFileNotice
          documentId={state.meta.id}
          filename={state.meta.filename}
          path={state.meta.path}
          onRelocated={() => setReloadToken((token) => token + 1)}
        />
        {rail(state.meta)}
      </div>
    );
  }

  if (state.kind === "root_unavailable") {
    return (
      <div className="flex min-w-0 flex-1 gap-4">
        <RootUnavailableNotice filename={state.meta.filename} reason={state.meta.root_reason} />
        {rail(state.meta)}
      </div>
    );
  }

  if (state.kind === "unsupported") {
    return (
      <div className="flex min-w-0 flex-1 gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {banner(state.meta)}
          <UnrenderableFallback
            filename={state.meta.filename}
            documentId={documentId ?? ""}
            note={`Askwell does not render ${state.meta.mime ?? "this format"} in the viewer yet.`}
          />
        </div>
        {rail(state.meta)}
      </div>
    );
  }

  if (state.kind === "converted") {
    return (
      <div className="flex min-w-0 flex-1 gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {banner(state.meta)}
          <ConvertedTextView
            documentId={state.meta.id}
            filename={state.meta.filename}
            pageNumber={pageNumber}
            pageCount={state.meta.page_count}
            quotedSpan={quotedSpan}
            passage={passage}
            onChangePage={setPageNumber}
          />
        </div>
        {rail(state.meta)}
      </div>
    );
  }

  if (state.kind === "spreadsheet") {
    return (
      <div className="flex min-w-0 flex-1 gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {banner(state.meta)}
          <SpreadsheetView
            documentId={state.meta.id}
            filename={state.meta.filename}
            pageNumber={pageNumber}
            quotedSpan={quotedSpan}
            passage={passage}
          />
        </div>
        {rail(state.meta)}
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-1 gap-4">
      <section className="flex min-w-0 flex-1 flex-col gap-3 p-4">
        {banner(state.meta)}
        <header className="flex items-baseline justify-between gap-3">
          <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
            {state.meta.filename}
          </h1>
          <PageNav
            pageNumber={pageNumber}
            pageCount={state.meta.page_count}
            onChange={setPageNumber}
          />
        </header>

        {pinpointNote === "scanned" ? (
          <p className="ask-prose ask-pdf-page-note">
            This page is a scan, so the citation points to the whole page rather than to a
            passage on it. Askwell read it with OCR, which recovers the words but not where
            on the page they sit.
          </p>
        ) : null}
        {pinpointNote === "not-found" ? (
          <p className="ask-prose ask-pdf-page-note">
            The exact passage could not be pinpointed on this page — showing the cited page
            instead.
          </p>
        ) : null}
        {ocrPanel !== null && ocrPanel.low_confidence ? (
          <p className="ask-prose ask-pdf-page-note">
            This scan read poorly — Askwell has low confidence in the text below.
          </p>
        ) : null}

        {fallbackText !== null ? (
          <UnrenderableFallback
            filename={state.meta.filename}
            documentId={state.meta.id}
            note="This page could not be rendered. Its extracted text is shown instead."
            text={fallbackText}
          />
        ) : ocrPanel !== null ? (
          <div className="flex gap-4" style={{ alignItems: "flex-start" }}>
            <div ref={pageContainerRef} style={{ overflow: "auto" }} />
            <div className="flex flex-col gap-2" style={{ flex: 1, minWidth: 0 }}>
              <h2 className="ask-micro">What Askwell read from this page</h2>
              {ocrPanel.has_text && ocrPanel.text !== null && ocrPanel.text !== "" ? (
                <p className="ask-prose" style={{ whiteSpace: "pre-wrap" }}>
                  {ocrPanel.text}
                </p>
              ) : (
                <p className="ask-prose">Nothing was read from this page.</p>
              )}
            </div>
          </div>
        ) : (
          <div ref={pageContainerRef} style={{ overflow: "auto" }} />
        )}
      </section>
      {rail(state.meta)}
    </div>
  );
}
