/**
 * Locating a cited passage inside a rendered PDF page's own text. `M1-VIEW-FE-046`.
 *
 * Pure and DOM-free, so the search rule is checkable without a browser or a
 * PDF — the same reasoning `segmentClaims`/`applyCitation` already follow for
 * their own pure cores (`lib/claims.ts`, `lib/citations.ts`).
 *
 * `askwell.agent.claims.locate_quoted_span` does the equivalent search
 * server-side, against the chunk's own stored text; this is the client-side
 * half, against pdf.js's own extracted text for the *rendered* page — a
 * second, independent extractor (pypdfium2 server-side, pdf.js client-side)
 * reading the same bytes, which is exactly why an exact-string match can fail
 * even when the server found one: this is not a bug to paper over with a
 * fuzzier search, it is the ticket's own edge case ("the passage cannot be
 * located exactly"), and `null` here is what triggers that fallback.
 */

/** Runs of whitespace collapse to one space wherever they appear — pdf.js and
 * pypdfium2 do not agree on how many spaces a line break or a column gap
 * becomes, and a search that requires an exact run length would fail on
 * every page for a reason that has nothing to do with the passage being
 * genuinely absent. */
const WHITESPACE_RUN = /\s+/g;

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The first case-insensitive occurrence of `needle` in `haystack`, tolerant
 * of whitespace differences between the two, as a real character range into
 * `haystack` — not into some normalised copy, so the caller can map it
 * straight onto the DOM text it came from. `null` when no such occurrence
 * exists at all. */
export function locateSpan(
  haystack: string,
  needle: string,
): { start: number; end: number } | null {
  const trimmed = needle.trim();
  if (trimmed === "") return null;

  const pattern = trimmed
    .split(WHITESPACE_RUN)
    .map((word) => escapeRegExp(word))
    .join("\\s+");

  const match = new RegExp(pattern, "i").exec(haystack);
  if (match === null) return null;
  return { start: match.index, end: match.index + match[0].length };
}

/**
 * The search text to look for on the cited page, in priority order.
 *
 * `quotedSpan` is the claim's own words, already verified server-side to
 * occur verbatim in the cited chunk (`askwell.agent.claims`) — the tightest,
 * most trustworthy target when it exists. Falling back to the full `passage`
 * (the chunk's whole content) when it does not still gives a real search
 * target for the ordinary case where the model's claim was a paraphrase
 * rather than a quotation; a page that matches neither is genuinely a case
 * the exact position cannot be pinpointed for, not a search that needed to
 * try harder.
 */
export function searchTargets(card: { quotedSpan: string | null; passage: string }): string[] {
  const targets: string[] = [];
  if (card.quotedSpan !== null && card.quotedSpan.trim() !== "") targets.push(card.quotedSpan);
  if (card.passage.trim() !== "") targets.push(card.passage);
  return targets;
}

/** The first target that actually locates on this page's text, or `null` if
 * none do — the caller's signal to fall back to a page-level highlight with
 * the "could not be pinpointed" note. */
export function locateOnPage(
  pageText: string,
  targets: readonly string[],
): { start: number; end: number } | null {
  for (const target of targets) {
    const found = locateSpan(pageText, target);
    if (found !== null) return found;
  }
  return null;
}

/**
 * Which note the viewer owes the reader when nothing was highlighted.
 *
 * Two failures look identical on screen and mean opposite things. A page with
 * no embedded text layer is a **scan**: page-level is the best any citation can
 * ever do there, because OCR gives text without character offsets, and saying
 * so tells the reader the system is working as designed. A page that has text
 * and still did not match is a **miss** — the passage should have been findable
 * and was not, which is a defect the reader should be able to report.
 *
 * Rendering the miss message for a scan tells somebody their scanned contract
 * is broken every single time they open it, and buries real misses in noise
 * nobody will ever chase.
 */
export type PageNote = "located" | "scanned" | "not-found";

export function pageNote(pageText: string, located: boolean): PageNote {
  if (located) return "located";
  // Whitespace only counts as no text layer: pdf.js yields empty items for a
  // scanned page, and a page carrying nothing but spaces is the same to a
  // reader looking for their passage.
  return pageText.trim() === "" ? "scanned" : "not-found";
}
