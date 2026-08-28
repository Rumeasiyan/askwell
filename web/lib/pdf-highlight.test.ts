import { test } from "node:test";
import assert from "node:assert/strict";

import { locateOnPage, locateSpan, pageNote, searchTargets } from "./pdf-highlight.ts";

test("locates an exact substring", () => {
  const found = locateSpan("The term is ninety days from delivery.", "ninety days");
  assert.deepEqual(found, { start: 12, end: 23 });
});

test("is case-insensitive", () => {
  const found = locateSpan("The Term Is Ninety Days.", "ninety days");
  assert.notEqual(found, null);
});

test("tolerates a different amount of whitespace between words", () => {
  const found = locateSpan("ninety\n   days", "ninety days");
  assert.deepEqual(found, { start: 0, end: 14 });
});

test("returns null when the text is not on the page at all", () => {
  assert.equal(locateSpan("Nothing about delivery here.", "ninety days"), null);
});

test("returns null for an empty or all-whitespace needle", () => {
  assert.equal(locateSpan("Some page text.", ""), null);
  assert.equal(locateSpan("Some page text.", "   "), null);
});

test("a needle carrying regex metacharacters is matched literally", () => {
  const found = locateSpan("The price is $5.00 (approx).", "$5.00 (approx)");
  assert.notEqual(found, null);
});

test("searchTargets prefers the quoted span over the full passage", () => {
  assert.deepEqual(searchTargets({ quotedSpan: "ninety days", passage: "The term is ninety days." }), [
    "ninety days",
    "The term is ninety days.",
  ]);
});

test("searchTargets falls back to the passage alone when there is no quoted span", () => {
  assert.deepEqual(searchTargets({ quotedSpan: null, passage: "The term is ninety days." }), [
    "The term is ninety days.",
  ]);
});

test("searchTargets drops a blank quoted span rather than searching for nothing", () => {
  assert.deepEqual(searchTargets({ quotedSpan: "  ", passage: "The term is ninety days." }), [
    "The term is ninety days.",
  ]);
});

test("locateOnPage tries each target in order and returns the first hit", () => {
  const page = "The term is ninety days from delivery.";
  const found = locateOnPage(page, ["not on this page", "ninety days"]);
  assert.deepEqual(found, { start: 12, end: 23 });
});

test("locateOnPage returns null when no target locates — the pinpoint-failure case", () => {
  const page = "This page is about something else entirely.";
  const found = locateOnPage(page, ["ninety days", "a whole different passage"]);
  assert.equal(found, null);
});


// --- which note the reader is owed ------------------------------------------

test("a page with no text layer is called a scan, not a failure", () => {
  // The ticket's own acceptance criterion, and a different case from the miss
  // below. Telling somebody their scanned contract could not be pinpointed
  // says it is broken, every time they open it.
  assert.equal(pageNote("", false), "scanned");
  assert.equal(pageNote("   \n  ", false), "scanned");
});

test("a page with text that did not match is a miss, which is worth reporting", () => {
  assert.equal(pageNote("Either party may terminate on ninety days notice.", false), "not-found");
});

test("a located passage gets no note at all", () => {
  assert.equal(pageNote("", true), "located");
  assert.equal(pageNote("some text", true), "located");
});
