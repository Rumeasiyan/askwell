/**
 * A web-sourced result, distinct from `CitationCard` (`lib/citations.ts`) —
 * mirrors `askwell.websearch.WebCitationRecord` (`api/src/askwell/websearch.py`)
 * minus `claim_ordinal`, which belongs to per-claim attribution
 * (`M6.5-WEB-FE-191`, out of this ticket's scope). `M6.5-WEB-FE-190`.
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

/** "Retrieved 22 Sept 2026" — same phrasing shape as `document-dates.ts`'s
 * `addedDateLabel`, so a date reads the same way whether it names when a
 * document was added or when a web page was fetched. */
export function retrievedDateLabel(retrievedAt: string): string {
  return `Retrieved ${new Date(retrievedAt).toLocaleDateString()}`;
}
