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
