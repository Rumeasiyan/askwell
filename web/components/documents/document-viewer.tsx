"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist";
import type { TextItem } from "pdfjs-dist/types/src/display/api";

import { locateOnPage, searchTargets,
  pageNote,
  type PageNote,
} from "@/lib/pdf-highlight";
import { buildPageText, itemsInRange } from "@/lib/pdf-text-map";

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
  mime: string | null;
  page_count: number | null;
  anchor_kind: string | null;
  status: string;
  available: boolean;
}

type ViewerState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "unsupported"; filename: string; mime: string | null }
  | { kind: "ready"; meta: DocumentMetadata };

const RENDER_SCALE = 1.4;

function highlightSpan(div: HTMLElement | undefined, start: number, end: number): void {
  if (div === undefined) return;
  const text = div.textContent ?? "";
  const before = text.slice(0, start);
  const match = text.slice(start, end);
  const after = text.slice(end);

  div.replaceChildren();
  if (before !== "") div.appendChild(document.createTextNode(before));
  const mark = document.createElement("mark");
  mark.className = "ask-pdf-highlight";
  mark.textContent = match;
  div.appendChild(mark);
  if (after !== "") div.appendChild(document.createTextNode(after));
}

export function DocumentViewer() {
  const searchParams = useSearchParams();
  const documentId = searchParams.get("id");
  const requestedPage = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const quotedSpan = searchParams.get("span");
  const passage = searchParams.get("passage");

  const [state, setState] = useState<ViewerState>({ kind: "loading" });
  const [pageNumber, setPageNumber] = useState(Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1);
  const [pinpointNote, setPinpointNote] = useState<PageNote>("located");
  const [fallbackText, setFallbackText] = useState<string | null>(null);
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
        setState({
          kind: "error",
          message: `${meta.filename} is no longer at its recorded path.`,
        });
        return;
      }
      if (meta.mime !== "application/pdf") {
        setState({ kind: "unsupported", filename: meta.filename, mime: meta.mime });
        return;
      }
      setState({ kind: "ready", meta });
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId]);

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
        setPinpointNote(pageNote(pageText, false));
        pageEl.scrollIntoView({ block: "start" });
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

  if (state.kind === "unsupported") {
    return (
      <UnrenderableFallback
        filename={state.filename}
        documentId={documentId ?? ""}
        note={`Askwell does not render ${state.mime ?? "this format"} in the viewer yet.`}
      />
    );
  }

  return (
    <section className="flex flex-col gap-3 p-4">
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

      {fallbackText !== null ? (
        <UnrenderableFallback
          filename={state.meta.filename}
          documentId={state.meta.id}
          note="This page could not be rendered. Its extracted text is shown instead."
          text={fallbackText}
        />
      ) : (
        <div ref={pageContainerRef} style={{ overflow: "auto" }} />
      )}
    </section>
  );
}

function PageNav({
  pageNumber,
  pageCount,
  onChange,
}: {
  pageNumber: number;
  pageCount: number | null;
  onChange: (page: number) => void;
}) {
  return (
    <div className="flex items-center gap-2 ask-micro">
      <button
        type="button"
        onClick={() => onChange(Math.max(1, pageNumber - 1))}
        disabled={pageNumber <= 1}
        className="ask-navigates px-2 py-1"
        style={{ border: "1px solid var(--rule)" }}
      >
        Previous
      </button>
      <span>
        Page {pageNumber}
        {pageCount !== null ? ` of ${pageCount}` : ""}
      </span>
      <button
        type="button"
        onClick={() => onChange(pageCount !== null ? Math.min(pageCount, pageNumber + 1) : pageNumber + 1)}
        disabled={pageCount !== null && pageNumber >= pageCount}
        className="ask-navigates px-2 py-1"
        style={{ border: "1px solid var(--rule)" }}
      >
        Next
      </button>
    </div>
  );
}

/** The unrenderable-PDF and unsupported-format edge cases share one shape:
 * extracted text (when there is any) plus a note plus a way to fall back to
 * the system's own viewer — the ticket's own "extracted text with a note and
 * an open-in-system-app option." */
function UnrenderableFallback({
  filename,
  documentId,
  note,
  text,
}: {
  filename: string;
  documentId: string;
  note: string;
  text?: string;
}) {
  return (
    <section className="flex flex-col gap-3 p-4">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>{filename}</h1>
      <p className="ask-prose">{note}</p>
      {text !== undefined ? (
        <pre
          className="ask-prose"
          style={{ whiteSpace: "pre-wrap", background: "var(--surface)", padding: "1rem" }}
        >
          {text}
        </pre>
      ) : null}
      <a
        href={`/documents/${documentId}/file`}
        className="ask-navigates inline-block px-4 py-2 w-fit"
        style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
      >
        Open in system app
      </a>
    </section>
  );
}
