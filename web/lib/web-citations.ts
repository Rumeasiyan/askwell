/**
 * A web-sourced result, distinct from `CitationCard` (`lib/citations.ts`) —
 * mirrors `askwell.websearch.WebCitationRecord` (`api/src/askwell/websearch.py`).
 * `M6.5-WEB-FE-190`, `claimOrdinals` added by `M6.5-WEB-FE-191`.
 *
 * Deliberately its own type rather than `CitationCard` with optional fields:
 * a web result has no `chunkId`, no `documentId`, nothing traceable to the
 * user's own material, and `design-system.md` §7's own rule ("a shared
 * component with a flag is exactly how the distinction erodes") applies to
 * the data shape as much as the component built on it.
 */
export interface WebResult {
  domain: string;
  title: string;
  url: string;
  passage: string;
  /** ISO timestamp. A page can change or vanish after the answer; this is
   * what keeps the citation honest later (`../web-search.md` §3). */
  retrievedAt: string;
  /** Every claim ordinal this result supports, in the order first cited —
   * `CitationCard.claimOrdinals`'s own "one card, several claims" shape,
   * mirrored here so one result reused by two sentences in the escalation's
   * own answer is one card, not two (`M6.5-WEB-FE-191`). These ordinals
   * share the *same* numbering space `ClaimSpan` (`ask-screen.tsx`) already
   * uses for document claims — `POST /ask/{id}/escalate/web`'s own response
   * numbers them past however many claims the turn's answer already had, so
   * a claim key can only ever belong to one kind of source, never both. */
  claimOrdinals: number[];
}

/** The raw per-citation shape `POST /ask/{id}/escalate/web` returns, one row
 * per (claim, result) pair — before `applyWebCitation` groups repeats of the
 * same URL into one `WebResult`, the same relationship `AskCitationData` has
 * to `CitationCard` via `applyCitation` (`lib/citations.ts`). */
export interface WebCitationEntry {
  claimOrdinal: number;
  domain: string;
  title: string;
  url: string;
  passage: string;
  retrievedAt: string;
}

/**
 * Fold one `WebCitationEntry` into the result list, grouped by `url` —
 * `applyCitation`'s own grouping rule, for the same reason: a single web
 * page cited by two claims in one escalation is one card with two claim
 * ordinals, never a duplicate card (`M6.5-WEB-FE-191`, the ticket's own
 * "single claim supported by both a document and a web page" edge case
 * extended to "one web page supporting two claims").
 */
export function applyWebCitation(
  results: readonly WebResult[],
  entry: WebCitationEntry,
): WebResult[] {
  const index = results.findIndex((result) => result.url === entry.url);
  if (index === -1) {
    return [
      ...results,
      {
        domain: entry.domain,
        title: entry.title,
        url: entry.url,
        passage: entry.passage,
        retrievedAt: entry.retrievedAt,
        claimOrdinals: [entry.claimOrdinal],
      },
    ];
  }

  const existing = results[index]!;
  if (existing.claimOrdinals.includes(entry.claimOrdinal)) return results.slice();
  const updated: WebResult = {
    ...existing,
    claimOrdinals: [...existing.claimOrdinals, entry.claimOrdinal],
  };
  return results.map((result, i) => (i === index ? updated : result));
}

const TITLE_TRUNCATE_AT = 90;
const URL_TRUNCATE_AT = 70;

/**
 * Truncates at `maxLength`, visibly (an ellipsis), never past it. The full
 * value is always still what the caller has — this only decides what is
 * shown, never what is stored or linked to.
 */
export function truncate(value: string, maxLength: number): string {
  const trimmed = value.trim();
  if (trimmed.length <= maxLength) return trimmed;
  return `${trimmed.slice(0, maxLength).trimEnd()}…`;
}

export function truncatedTitle(title: string): string {
  return truncate(title, TITLE_TRUNCATE_AT);
}

/** Truncated from the end, never the start — the scheme and domain stay
 * visible, which is what keeps a shortened URL from reading as a different
 * one (the domain is also always rendered in full, separately). */
export function truncatedUrl(url: string): string {
  return truncate(url, URL_TRUNCATE_AT);
}

/** "Retrieved 22 Sept 2026" — when the page was fetched, labelled as
 * exactly that; a web page has no document date of its own here. */
export function retrievedDateLabel(retrievedAt: string): string {
  return `Retrieved ${new Date(retrievedAt).toLocaleDateString()}`;
}
