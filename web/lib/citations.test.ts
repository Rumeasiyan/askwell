/**
 * Grouping citation events into provenance cards. `M1-CITE-FE-043`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { AskCitationData } from "./ask.ts";
import { anchorLabel, applyCitation, documentHref, pageLabel, type CitationCard } from "./citations.ts";

function citation(over: Partial<AskCitationData> = {}): AskCitationData {
  return {
    message_id: "m1",
    index: 1,
    claim_ordinal: 1,
    chunk_id: "c1",
    document_id: "d1",
    filename: "contract.pdf",
    anchor_kind: null,
    heading: null,
    page_from: 3,
    page_to: 3,
    passage: "Notice is ninety days.",
    quoted_span: "ninety days",
    ...over,
  };
}

test("a first citation for a chunk becomes a new card", () => {
  const cards = applyCitation([], citation());
  assert.equal(cards.length, 1);
  assert.equal(cards[0]?.chunkId, "c1");
  assert.deepEqual(cards[0]?.claimOrdinals, [1]);
});

test("two claims citing the same passage produce one card, two leaders", () => {
  // The ticket's own edge case, by name.
  let cards = applyCitation([], citation({ claim_ordinal: 1 }));
  cards = applyCitation(cards, citation({ claim_ordinal: 2, index: 2 }));
  assert.equal(cards.length, 1);
  assert.deepEqual(cards[0]?.claimOrdinals, [1, 2]);
});

test("the server resending an identical frame does not draw a second leader", () => {
  let cards = applyCitation([], citation({ claim_ordinal: 1 }));
  cards = applyCitation(cards, citation({ claim_ordinal: 1 }));
  assert.equal(cards.length, 1);
  assert.deepEqual(cards[0]?.claimOrdinals, [1]);
});

test("a citation for a different chunk is a second, separate card", () => {
  let cards = applyCitation([], citation({ chunk_id: "c1", claim_ordinal: 1 }));
  cards = applyCitation(cards, citation({ chunk_id: "c2", claim_ordinal: 2, index: 2 }));
  assert.equal(cards.length, 2);
  assert.deepEqual(
    cards.map((c) => c.chunkId),
    ["c1", "c2"],
  );
});

// --- pageLabel / anchorLabel --------------------------------------------------

function card(over: Partial<CitationCard> = {}): Pick<CitationCard, "pageFrom" | "pageTo" | "anchorKind" | "heading"> {
  return { pageFrom: null, pageTo: null, anchorKind: null, heading: null, ...over };
}

test("a single page renders as one number", () => {
  assert.equal(pageLabel(card({ pageFrom: 4, pageTo: 4 })), "p. 4");
});

test("a page range renders as a range", () => {
  assert.equal(pageLabel(card({ pageFrom: 4, pageTo: 6 })), "pp. 4–6");
});

test("no page at all renders no page label", () => {
  assert.equal(pageLabel(card()), null);
});

test("a heading, when extraction found one, wins over the anchor kind", () => {
  assert.equal(anchorLabel(card({ anchorKind: "slide", heading: "Q3 revenue" })), "Q3 revenue");
});

test("an anchor kind with no heading renders its human label", () => {
  assert.equal(anchorLabel(card({ anchorKind: "sheet_row" })), "Row");
});

test("neither a heading nor an anchor kind renders nothing", () => {
  assert.equal(anchorLabel(card()), null);
});

// --- documentHref -------------------------------------------------------------
// `M1-VIEW-FE-046`: a query-string route, not `/documents/{id}` — a dynamic
// path segment cannot exist under this app's static export.

function fullCard(over: Partial<CitationCard> = {}): CitationCard {
  return {
    chunkId: "c1",
    documentId: "d1",
    filename: "contract.pdf",
    anchorKind: null,
    heading: null,
    pageFrom: 3,
    pageTo: 3,
    passage: "Notice is ninety days.",
    quotedSpan: "ninety days",
    claimOrdinals: [1],
    ...over,
  };
}

test("documentHref carries the id, page, quoted span and passage", () => {
  const href = documentHref(fullCard());
  const url = new URL(href, "http://example.test");
  assert.equal(url.pathname, "/documents/");
  assert.equal(url.searchParams.get("id"), "d1");
  assert.equal(url.searchParams.get("page"), "3");
  assert.equal(url.searchParams.get("span"), "ninety days");
  assert.equal(url.searchParams.get("passage"), "Notice is ninety days.");
});

test("documentHref omits page when there is none, rather than sending page=null", () => {
  const url = new URL(documentHref(fullCard({ pageFrom: null, pageTo: null })), "http://example.test");
  assert.equal(url.searchParams.has("page"), false);
});

test("documentHref omits a blank quoted span rather than searching for nothing", () => {
  const url = new URL(documentHref(fullCard({ quotedSpan: "  " })), "http://example.test");
  assert.equal(url.searchParams.has("span"), false);
});
