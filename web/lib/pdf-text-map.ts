/**
 * Mapping a character range in a page's flattened text back onto the pdf.js
 * text-layer items it came from. `M1-VIEW-FE-046`.
 *
 * pdf.js exposes a page's text as an array of items (one per run pdfium's
 * text object stream produced) rather than as one string — `lib/pdf-highlight.ts`
 * searches the flattened string, so this is the piece that turns a match back
 * into "which of the rendered `<span>` elements does the highlight belong in,
 * and at what offset inside it." Pure and DOM-free so the offset arithmetic
 * is checkable without a browser.
 */

export interface PageTextItem {
  text: string;
  /** pdf.js's own `hasEOL` — whether a line break follows this run in
   * reading order. Joining without it would glue the last word of one line
   * to the first word of the next, which can turn a real match into one that
   * only exists in the flattened string. */
  hasEOL: boolean;
}

export interface ItemSpan {
  index: number;
  start: number;
  end: number;
}

/** The page's text, flattened to one searchable string, and the character
 * range within it that each item occupies — the two are built together so
 * they can never drift apart. */
export function buildPageText(items: readonly PageTextItem[]): {
  pageText: string;
  spans: ItemSpan[];
} {
  let pageText = "";
  const spans: ItemSpan[] = [];
  items.forEach((item, index) => {
    const start = pageText.length;
    pageText += item.text;
    spans.push({ index, start, end: pageText.length });
    if (item.hasEOL) pageText += "\n";
  });
  return { pageText, spans };
}

export interface ItemHit {
  index: number;
  localStart: number;
  localEnd: number;
}

/** Every item `range` touches, each with the offsets local to that one item
 * — a match spanning three items (a highlight crossing a line break, say)
 * comes back as three hits, one per item, so the caller can highlight each
 * item's own DOM node independently rather than needing one node to hold
 * text it does not contain. */
export function itemsInRange(spans: readonly ItemSpan[], range: { start: number; end: number }): ItemHit[] {
  const hits: ItemHit[] = [];
  for (const span of spans) {
    const overlapStart = Math.max(span.start, range.start);
    const overlapEnd = Math.min(span.end, range.end);
    if (overlapStart < overlapEnd) {
      hits.push({ index: span.index, localStart: overlapStart - span.start, localEnd: overlapEnd - span.start });
    }
  }
  return hits;
}
