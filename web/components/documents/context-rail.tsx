"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { fillComposer } from "@/components/ask/ask-screen";
import { useAsk } from "@/components/ask/ask-state";
import { segmentClaims } from "@/lib/claims";
import { documentHref, stepCitations, type CitationCard } from "@/lib/citations";

/**
 * The source viewer's own right-hand rail. `M1-VIEW-FE-048`,
 * `docs/ux/source-viewer.md` §2/§3.
 *
 * Reads the live turn straight out of `AskProvider` (`useAsk`, above the
 * router in `shell.tsx`) rather than fetching anything of its own — the
 * answer that sent someone here is already in memory, and re-deriving it
 * from the server would risk disagreeing with what the user is actually
 * looking at back on the Ask screen.
 *
 * **Arriving without a turn is not an error.** No `turn` query parameter
 * (the library, once it links here), or a `turn` that no longer matches any
 * live turn (the tab was reloaded, which drops `AskProvider`'s in-memory
 * state entirely) both fall through to plain source context and no return
 * control — the edge case named explicitly in the ticket's own Edge Cases:
 * "no broken return."
 */
export function ContextRail({
  documentId,
  filename,
  pageNumber,
  passage,
  turnId,
  claimOrdinal,
  chunkId,
}: {
  documentId: string;
  filename: string;
  pageNumber: number | null;
  passage: string | null;
  turnId: string | null;
  claimOrdinal: number | null;
  chunkId: string | null;
}) {
  const { turns } = useAsk();
  const turn = turnId !== null ? (turns.find((candidate) => candidate.id === turnId) ?? null) : null;

  const claimText =
    turn !== null && claimOrdinal !== null
      ? (segmentClaims(turn.answer).find((claim) => claim.ordinal === claimOrdinal)?.text ?? null)
      : null;

  // Stepping needs to know its own place among the answer's citations — the
  // ticket's own edge case says the controls are *absent*, not disabled,
  // when there is only one to step to.
  const cards = turn?.citations ?? [];
  const { currentIndex, previousCard, nextCard, canStep } = stepCitations(cards, chunkId);

  return (
    <aside
      aria-label="Source context"
      className="hidden shrink-0 flex-col gap-4 overflow-y-auto p-4 @3xl:flex"
      style={{ width: "var(--margin-rail)", borderLeft: "1px solid var(--rule)" }}
    >
      {turn !== null ? (
        <OriginBlock question={turn.question} claimText={claimText} turnId={turn.id} claimOrdinal={claimOrdinal} />
      ) : (
        <div className="flex flex-col gap-1">
          <p className="ask-micro">Source</p>
          <p className="ask-prose" style={{ color: "var(--muted)" }}>
            {filename}
            {pageNumber !== null ? ` · p. ${pageNumber}` : ""}
          </p>
        </div>
      )}

      {canStep ? (
        <CitationStepper
          turnId={turnId!}
          previousCard={previousCard}
          nextCard={nextCard}
          position={`${currentIndex + 1} of ${cards.length}`}
        />
      ) : null}

      <SearchInSource />

      <CopyPassage filename={filename} pageNumber={pageNumber} passage={passage} />

      <AskAboutSource documentId={documentId} filename={filename} />
    </aside>
  );
}

/**
 * `docs/ux/source-viewer.md` §4's superseded state: "this version was
 * replaced on <date>, with a link to current. Old answers cited the old
 * version and must still resolve to it." — the edge case is exactly that
 * this banner must render *without* breaking the pane it sits above, which
 * is why it is a sibling here rather than something the pane's own renderer
 * has to know about. `GET /documents/{id}` is reused for the new version's
 * filename rather than the metadata endpoint growing a join of its own
 * (issue 141's own recommendation (1): no banner endpoint built ahead of
 * the screen that needed it).
 */
export function SupersededBanner({
  supersededBy,
  supersededAt,
}: {
  supersededBy: string;
  supersededAt: string | null;
}) {
  const [filename, setFilename] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetch(`/documents/${supersededBy}`, { cache: "no-store" })
      .then((response) => (response.ok ? (response.json() as Promise<{ filename: string }>) : null))
      .then((body) => {
        if (!cancelled && body !== null) setFilename(body.filename);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [supersededBy]);

  const date = supersededAt !== null ? new Date(supersededAt).toLocaleDateString() : null;

  return (
    <p className="ask-prose ask-pdf-page-note">
      This version was replaced{date !== null ? ` on ${date}` : ""}.{" "}
      <Link href={`/documents/?id=${supersededBy}`} className="ask-navigates">
        Open the current version{filename !== null ? ` (${filename})` : ""}
      </Link>
      .
    </p>
  );
}

/**
 * Next/previous across every passage the answer cited — including across
 * documents, the ticket's own scope line. A real, plain `router.push`
 * rather than a `Link` for the disabled end: a `Link` still renders an `<a>`
 * with somewhere to go even when visually dimmed, and the ticket's own edge
 * case for one citation is "absent rather than inert" — the same standard
 * applies at either end of more than one.
 */
function CitationStepper({
  turnId,
  previousCard,
  nextCard,
  position,
}: {
  turnId: string;
  previousCard: CitationCard | null;
  nextCard: CitationCard | null;
  position: string;
}) {
  const router = useRouter();

  return (
    <nav aria-label="Cited passages" className="flex items-center gap-2 ask-micro">
      <button
        type="button"
        disabled={previousCard === null}
        onClick={() =>
          previousCard !== null &&
          router.push(
            documentHref(previousCard, { turnId, claimOrdinal: previousCard.claimOrdinals[0]! }),
          )
        }
        className="ask-navigates px-2 py-1"
        style={{ border: "1px solid var(--rule)" }}
      >
        Previous citation
      </button>
      <span>{position}</span>
      <button
        type="button"
        disabled={nextCard === null}
        onClick={() =>
          nextCard !== null &&
          router.push(documentHref(nextCard, { turnId, claimOrdinal: nextCard.claimOrdinals[0]! }))
        }
        className="ask-navigates px-2 py-1"
        style={{ border: "1px solid var(--rule)" }}
      >
        Next citation
      </button>
    </nav>
  );
}

function OriginBlock({
  question,
  claimText,
  turnId,
  claimOrdinal,
}: {
  question: string;
  claimText: string | null;
  turnId: string;
  claimOrdinal: number | null;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="ask-micro">From your question</p>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        {question}
      </p>
      {claimText !== null ? (
        <>
          <p className="ask-micro">Supporting the claim</p>
          <p className="ask-prose">&ldquo;{claimText}&rdquo;</p>
        </>
      ) : null}
      <Link
        href={claimOrdinal !== null ? `/?turn=${turnId}&claim=${claimOrdinal}` : "/"}
        className="ask-navigates w-fit px-3 py-1"
        style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
      >
        Back to answer
      </Link>
    </div>
  );
}

/** Plain text find — `docs/ux/source-viewer.md` §3's own wording. `window.find`
 * is the browser's native page-text search; there is nothing in the DOM this
 * viewer keeps a separate, searchable copy of, so reaching for a second
 * search index would be new state that can disagree with what is on screen. */
function SearchInSource() {
  const [query, setQuery] = useState("");
  const supported = typeof window !== "undefined" && "find" in window;

  const findNext = (): void => {
    if (query.trim() === "" || !supported) return;
    (window as unknown as { find: (text: string) => boolean }).find(query);
  };

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="ask-source-search" className="ask-micro">
        Search this source
      </label>
      <div className="flex gap-2">
        <input
          id="ask-source-search"
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") findNext();
          }}
          className="ask-input ask-prose px-2 py-1"
          style={{ flex: 1 }}
          placeholder="Find in this document"
          disabled={!supported}
        />
        <button
          type="button"
          onClick={findNext}
          disabled={!supported || query.trim() === ""}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)" }}
        >
          Find
        </button>
      </div>
    </div>
  );
}

function CopyPassage({
  filename,
  pageNumber,
  passage,
}: {
  filename: string;
  pageNumber: number | null;
  passage: string | null;
}) {
  const [copied, setCopied] = useState(false);
  if (passage === null || passage.trim() === "") return null;

  const copy = (): void => {
    const label = pageNumber !== null ? `${filename}, p. ${pageNumber}` : filename;
    void navigator.clipboard.writeText(`"${passage.trim()}" — ${label}`).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <button
      type="button"
      onClick={copy}
      className="ask-navigates w-fit px-3 py-1"
      style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
    >
      {copied ? "Copied" : "Copy passage"}
    </button>
  );
}

/** `docs/ux/source-viewer.md` §3, `library.md` §"Ask about this source": ask,
 * scoped to this document. Sets the pending scope before navigating —
 * `fillComposer`'s own module-level slot (`ask-screen.tsx`) is read as soon
 * as `Composer` mounts, so the scope survives even though the route change
 * itself is not synchronous. */
function AskAboutSource({ documentId, filename }: { documentId: string; filename: string }) {
  const router = useRouter();

  const ask = (): void => {
    fillComposer("", { sourceId: documentId, filename });
    router.push("/");
  };

  return (
    <button
      type="button"
      onClick={ask}
      className="ask-navigates w-fit px-3 py-1"
      style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
    >
      Ask about this source
    </button>
  );
}
