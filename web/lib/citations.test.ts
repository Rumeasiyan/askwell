/**
 * Grouping citation events into provenance cards. `M1-CITE-FE-043`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { AskCitationData } from "./ask.ts";
import {
  anchorLabel,
  applyCitation,
  documentHref,
  pageLabel,
  stepCitations,
  type CitationCard,
} from "./citations.ts";

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

// --- documentHref's origin (M1-VIEW-FE-048) -----------------------------------
// The context rail's own "which answer, which claim, which citation" —
// carried as query parameters so a return trip through a real page load
// (not a client-side transition, per the card's own `Link`) still resolves.

test("documentHref carries no origin params when none is given", () => {
  const url = new URL(documentHref(fullCard()), "http://example.test");
  assert.equal(url.searchParams.has("turn"), false);
  assert.equal(url.searchParams.has("claim"), false);
  assert.equal(url.searchParams.has("chunk"), false);
});

test("documentHref carries turn, claim and chunk together when an origin is given", () => {
  const url = new URL(
    documentHref(fullCard({ chunkId: "c9" }), { turnId: "t1", claimOrdinal: 2 }),
    "http://example.test",
  );
  assert.equal(url.searchParams.get("turn"), "t1");
  assert.equal(url.searchParams.get("claim"), "2");
  assert.equal(url.searchParams.get("chunk"), "c9");
});

// --- stepCitations (M1-VIEW-FE-048) -------------------------------------------

function stepCard(id: string): CitationCard {
  return fullCard({ chunkId: id, documentId: `doc-${id}` });
}

test("a single citation cannot be stepped", () => {
  const step = stepCitations([stepCard("a")], "a");
  assert.equal(step.canStep, false);
  assert.equal(step.previousCard, null);
  assert.equal(step.nextCard, null);
});

test("the first of several citations has no previous, only a next", () => {
  const cards = [stepCard("a"), stepCard("b"), stepCard("c")];
  const step = stepCitations(cards, "a");
  assert.equal(step.canStep, true);
  assert.equal(step.currentIndex, 0);
  assert.equal(step.previousCard, null);
  assert.equal(step.nextCard?.chunkId, "b");
});

test("the last of several citations has no next, only a previous", () => {
  const cards = [stepCard("a"), stepCard("b"), stepCard("c")];
  const step = stepCitations(cards, "c");
  assert.equal(step.currentIndex, 2);
  assert.equal(step.previousCard?.chunkId, "b");
  assert.equal(step.nextCard, null);
});

test("a middle citation steps both ways, including across documents", () => {
  const cards = [stepCard("a"), stepCard("b"), stepCard("c")];
  const step = stepCitations(cards, "b");
  assert.equal(step.previousCard?.documentId, "doc-a");
  assert.equal(step.nextCard?.documentId, "doc-c");
});

test("a chunk id that matches nothing cannot step, rather than stepping from an unknown position", () => {
  const cards = [stepCard("a"), stepCard("b")];
  const step = stepCitations(cards, "not-here");
  assert.equal(step.canStep, false);
  assert.equal(step.currentIndex, -1);
});

test("no chunk id at all cannot step", () => {
  const cards = [stepCard("a"), stepCard("b")];
  const step = stepCitations(cards, null);
  assert.equal(step.canStep, false);
});
