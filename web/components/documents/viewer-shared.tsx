"use client";

import { useState } from "react";

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

/**
 * The deleted-source state, `docs/ux/source-viewer.md` §4, `M2-DELETE-FE-062`:
 * "Deleted on <date>. Askwell no longer has the contents." The citation
 * resolves honestly instead of breaking (issue 11, issue 231) — no relocate
 * offer, no rail, nothing that implies the content might come back the way
 * a moved file's does.
 */
export function DeletedSourceNotice({
  filename,
  deletedAt,
}: {
  filename: string;
  deletedAt: string | null;
}) {
  const date = deletedAt !== null ? new Date(deletedAt).toLocaleDateString() : null;
  return (
    <section className="flex flex-col gap-2 p-4">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>{filename}</h1>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Deleted{date !== null ? ` on ${date}` : ""}. Askwell no longer has the contents.
      </p>
    </section>
  );
}

/**
 * The moved/renamed state, `M1-VIEW-BE-049`. Names the missing path and
 * offers relocation — never says "deleted", which `documents.py`'s own
 * `moved`/`root_unavailable` split exists to keep this component from ever
 * having to guess between.
 *
 * The typed path is the same seam `add-screen.tsx`'s `Locate` form uses for
 * nominating a folder: `M7-TAURI-FE-182` replaces the text field with the
 * platform's own file dialog without this component's request or its
 * hash-mismatch handling changing at all.
 */
export function MovedFileNotice({
  documentId,
  filename,
  path,
  onRelocated,
}: {
  documentId: string;
  filename: string;
  path: string;
  onRelocated: () => void;
}) {
  const [candidate, setCandidate] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const response = await fetch(`/documents/${documentId}/relocate`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: candidate }),
      });
      const body = (await response.json()) as { error?: string; relocated?: boolean };
      if (response.ok && body.relocated === true) {
        onRelocated();
        return;
      }
      setProblem(body.error ?? "That path could not be used.");
    } catch {
      setProblem("Askwell could not be reached.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3 p-4">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>{filename}</h1>
      <p className="ask-prose">
        {filename} has moved. Askwell last found it at <code>{path}</code>, but that path no
        longer resolves. Nothing was deleted.
      </p>
      <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-2">
        <label htmlFor={`relocate-${documentId}`} style={{ fontSize: "var(--t-ui)" }}>
          Where is it now?
        </label>
        <div className="flex gap-2">
          <input
            id={`relocate-${documentId}`}
            value={candidate}
            onChange={(event) => setCandidate(event.target.value)}
            placeholder={path}
            spellCheck={false}
            autoComplete="off"
            className="ask-input flex-1 px-3"
            style={{ fontFamily: "var(--font-app)", fontSize: "var(--t-ui)" }}
          />
          <button
            type="submit"
            disabled={busy || candidate.trim() === ""}
            className="ask-action-primary px-4"
            style={{ fontSize: "var(--t-ui)" }}
          >
            Relocate
          </button>
        </div>
      </form>
      {problem !== null ? <p className="ask-prose ask-pdf-page-note">{problem}</p> : null}
    </section>
  );
}

/** The whole root unreachable — unmounted, removed or unreadable — as
 * distinct from one file having moved. `M1-VIEW-BE-049`'s own edge case:
 * conflating the two would ask someone to relocate every file in a folder
 * that is simply not connected right now. */
export function RootUnavailableNotice({ filename, reason }: { filename: string; reason: string | null }) {
  return (
    <section className="flex flex-col gap-2 p-4">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>{filename}</h1>
      <p className="ask-prose">
        Askwell cannot reach the folder that holds this file right now.
        {reason !== null ? ` ${reason}` : ""}
      </p>
    </section>
  );
}
