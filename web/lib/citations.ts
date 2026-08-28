import type { AskCitationData } from "@/lib/ask";

/**
 * One provenance card, grouped by chunk rather than by citation event.
 * `M1-CITE-FE-043`.
 *
 * Two claims citing the same passage are the ticket's own edge case: one
 * card, two leaders, not a duplicate card. Grouping by `chunkId` here — the
 * same key `applyCitation` uses to find an existing card — is what makes
 * that true rather than merely stated.
 */
export interface CitationCard {
  chunkId: string;
  documentId: string;
  filename: string;
  anchorKind: string | null;
  heading: string | null;
  pageFrom: number | null;
  pageTo: number | null;
  passage: string;
  quotedSpan: string | null;
  /** Every claim ordinal this card supports, in the order first cited — one
   * leader per entry. */
  claimOrdinals: number[];
}

/**
 * Fold one `citation` event into the card list.
 *
 * Pure, so the merge and dedup rules are checkable without a browser. A
 * chunk not seen before becomes a new card; a chunk already carrying a card
 * gains the new claim ordinal, unless that ordinal is already on it — the
 * server resending an identical frame must not draw a second leader from a
 * claim that already has one.
 */
export function applyCitation(
  cards: readonly CitationCard[],
  data: AskCitationData,
): CitationCard[] {
  const index = cards.findIndex((card) => card.chunkId === data.chunk_id);
  if (index === -1) {
    return [
      ...cards,
      {
        chunkId: data.chunk_id,
        documentId: data.document_id,
        filename: data.filename,
        anchorKind: data.anchor_kind,
        heading: data.heading,
        pageFrom: data.page_from,
        pageTo: data.page_to,
        passage: data.passage,
        quotedSpan: data.quoted_span,
        claimOrdinals: [data.claim_ordinal],
      },
    ];
  }

  const existing = cards[index]!;
  if (existing.claimOrdinals.includes(data.claim_ordinal)) return cards.slice();
  const updated: CitationCard = {
    ...existing,
    claimOrdinals: [...existing.claimOrdinals, data.claim_ordinal],
  };
  return cards.map((card, i) => (i === index ? updated : card));
}

/** A page range as a human label — "p. 4" or "pp. 4–6" — `null` when there
 * is no page to show at all, which the caller falls back on `anchorKind`
 * or `heading` for (a slide, a sheet row, a non-paginated format). */
export function pageLabel(card: Pick<CitationCard, "pageFrom" | "pageTo">): string | null {
  if (card.pageFrom === null) return null;
  if (card.pageTo === null || card.pageTo === card.pageFrom) return `p. ${card.pageFrom}`;
  return `pp. ${card.pageFrom}–${card.pageTo}`;
}

// A local counter of card clicks (`../../docs/backlog/M1-it-answers-from-my-documents.md`
// ticket's own Analytics Events line) — in-memory only, never persisted or
// sent anywhere (C1). Module state rather than component state because the
// count is meant to survive the card that produced it being replaced by a
// later turn's margin.
let cardClickCount = 0;

export function recordCardClick(): void {
  cardClickCount += 1;
}

export function getCardClickCount(): number {
  return cardClickCount;
}

/** Which answer sent someone to the viewer, and which claim it supported —
 * the context rail's own two facts (`M1-VIEW-FE-048`, `docs/ux/source-viewer.md`
 * §2). Optional: a card can be opened with no turn in scope at all (arriving
 * from the library, once that links here — `states-and-edge-cases.md`'s own
 * edge case), and the rail falls back to plain source context rather than a
 * broken return. */
export interface CitationOrigin {
  turnId: string;
  claimOrdinal: number;
}

/**
 * Where a card's own link goes. `M1-VIEW-FE-046`, extended by `M1-VIEW-FE-048`.
 *
 * `/documents/{document_id}?page=...` — what `M1-CITE-FE-043` guessed at
 * (`docs/decisions.md`, 2026-08-28) — cannot exist under this app's own
 * `output: "export"`: a dynamic path segment needs every value it will ever
 * take enumerated at build time, and a document id is not one of those.
 * `id`, `page`, `span` and `passage` travel as query parameters onto the
 * single static `/documents/` route instead (`app/documents/page.tsx`,
 * `document-viewer.tsx`) — a decision superseding the earlier guess,
 * recorded in `docs/decisions.md`.
 *
 * `origin`, when given, adds `turn`, `claim` and `chunk` — the context rail's
 * "which answer, which claim" and, since `chunk` is unique per card, which
 * citation among the answer's own list is the one currently open, which is
 * what next/previous stepping needs to find its place.
 */
export function documentHref(card: CitationCard, origin?: CitationOrigin): string {
  const params = new URLSearchParams({ id: card.documentId });
  if (card.pageFrom !== null) params.set("page", String(card.pageFrom));
  if (card.quotedSpan !== null && card.quotedSpan.trim() !== "") params.set("span", card.quotedSpan);
  if (card.passage.trim() !== "") params.set("passage", card.passage);
  if (origin !== undefined) {
    params.set("turn", origin.turnId);
    params.set("claim", String(origin.claimOrdinal));
    params.set("chunk", card.chunkId);
  }
  return `/documents/?${params.toString()}`;
}

/** Where next/previous-citation stepping stands, among every passage one
 * answer cited (`M1-VIEW-FE-048`'s context rail). Pure, so "the controls are
 * absent rather than inert for a single citation" and "stepping wraps into
 * the next document" are both checkable without a browser — the same reason
 * `applyCitation` above is a pure fold rather than component state. */
export interface CitationStep {
  currentIndex: number;
  previousCard: CitationCard | null;
  nextCard: CitationCard | null;
  /** Stepping controls render only when this is true — more than one
   * citation exists *and* the current one was actually found among them.
   * A `chunkId` that does not match anything (a stale link, a reload that
   * lost the turn) degrades to no controls rather than a stepper stuck at
   * an unknown position. */
  canStep: boolean;
}

export function stepCitations(cards: readonly CitationCard[], chunkId: string | null): CitationStep {
  const currentIndex = chunkId !== null ? cards.findIndex((card) => card.chunkId === chunkId) : -1;
  const canStep = cards.length > 1 && currentIndex !== -1;
  return {
    currentIndex,
    canStep,
    previousCard: canStep && currentIndex > 0 ? cards[currentIndex - 1]! : null,
    nextCard: canStep && currentIndex < cards.length - 1 ? cards[currentIndex + 1]! : null,
  };
}

/** What the card shows for "filename, page or anchor" when there is no
 * page number to show — the anchor kind and, if extraction found a nearer
 * label, the heading. */
export function anchorLabel(
  card: Pick<CitationCard, "anchorKind" | "heading">,
): string | null {
  if (card.heading !== null && card.heading !== "") return card.heading;
  if (card.anchorKind === null) return null;
  const kind: Record<string, string> = {
    slide: "Slide",
    sheet_row: "Row",
    heading: "Section",
    page: "Page",
  };
  return kind[card.anchorKind] ?? card.anchorKind;
}
