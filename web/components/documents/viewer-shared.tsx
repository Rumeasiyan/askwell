"use client";

/**
 * Pieces the source viewer's PDF, converted-text and spreadsheet renderers
 * all need. `M1-VIEW-FE-047`.
 *
 * Split out of `document-viewer.tsx` rather than imported from it, so the
 * per-format renderers and the viewer that routes to them do not import each
 * other.
 */

export function highlightSpan(div: HTMLElement | undefined, start: number, end: number): void {
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

export function PageNav({
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

/** The unrenderable-file edge case's shape: extracted text (when there is
 * any) plus a note plus a way to fall back to the system's own viewer — the
 * ticket's own "extracted text with a note and an open-in-system-app
 * option." */
export function UnrenderableFallback({
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
