import { test } from "node:test";
import assert from "node:assert/strict";

import { buildPageText, itemsInRange } from "./pdf-text-map.ts";

test("buildPageText joins items and inserts a break only after hasEOL", () => {
  const { pageText, spans } = buildPageText([
    { text: "The term is", hasEOL: true },
    { text: "ninety days.", hasEOL: false },
  ]);
  assert.equal(pageText, "The term is\nninety days.");
  assert.deepEqual(spans, [
    { index: 0, start: 0, end: 11 },
    { index: 1, start: 12, end: 24 },
  ]);
});

test("a range within one item produces one hit at the right local offsets", () => {
  const { spans } = buildPageText([{ text: "ninety days.", hasEOL: false }]);
  const hits = itemsInRange(spans, { start: 0, end: 11 });
  assert.deepEqual(hits, [{ index: 0, localStart: 0, localEnd: 11 }]);
});

test("a range spanning two items produces one hit per item", () => {
  const { pageText, spans } = buildPageText([
    { text: "The term is", hasEOL: true },
    { text: "ninety days.", hasEOL: false },
  ]);
  const start = pageText.indexOf("is\nninety");
  const end = start + "is\nninety".length;
  const hits = itemsInRange(spans, { start, end });
  assert.deepEqual(hits, [
    { index: 0, localStart: 9, localEnd: 11 },
    { index: 1, localStart: 0, localEnd: 6 },
  ]);
});

test("an item entirely outside the range produces no hit", () => {
  const { spans } = buildPageText([
    { text: "Unrelated text.", hasEOL: true },
    { text: "ninety days.", hasEOL: false },
  ]);
  const hits = itemsInRange(spans, { start: 16, end: 28 });
  assert.deepEqual(hits, [{ index: 1, localStart: 0, localEnd: 12 }]);
});

test("an empty range produces no hits", () => {
  const { spans } = buildPageText([{ text: "ninety days.", hasEOL: false }]);
  assert.deepEqual(itemsInRange(spans, { start: 3, end: 3 }), []);
});
