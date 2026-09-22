/**
 * Pure formatting rules for the web results region (`M6.5-WEB-FE-190`), plus
 * `applyWebCitation`'s own grouping rule (`M6.5-WEB-FE-191`).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  applyWebCitation,
  retrievedDateLabel,
  truncate,
  truncatedTitle,
  truncatedUrl,
  type WebCitationEntry,
} from "./web-citations.ts";

function entry(over: Partial<WebCitationEntry> = {}): WebCitationEntry {
  return {
    claimOrdinal: 1,
    domain: "gov.example",
    title: "Notice periods",
    url: "https://gov.example/notice",
    passage: "Four weeks is the statutory minimum.",
    retrievedAt: "2026-09-22T10:00:00Z",
    ...over,
  };
}

test("a value at or under the limit is unchanged", () => {
  assert.equal(truncate("short", 90), "short");
  assert.equal(truncate("x".repeat(90), 90), "x".repeat(90));
});

test("a value over the limit is truncated with a visible ellipsis, never past the limit", () => {
  const result = truncate("x".repeat(120), 90);
  assert.equal(result, `${"x".repeat(90)}…`);
  assert.ok(result.length <= 91);
});

test("truncation never silently drops the ellipsis — the reader can always tell it was cut", () => {
  const result = truncate("a very long page title ".repeat(10), 90);
  assert.ok(result.endsWith("…"));
});

test("a long title is truncated by truncatedTitle", () => {
  const title = "A".repeat(200);
  const result = truncatedTitle(title);
  assert.ok(result.length < title.length);
  assert.ok(result.endsWith("…"));
});

test("a long URL is truncated from the end, keeping the scheme and domain intact", () => {
  const url = `https://example.com/${"a".repeat(200)}`;
  const result = truncatedUrl(url);
  assert.ok(result.startsWith("https://example.com/"));
  assert.ok(result.endsWith("…"));
});

test("a short URL is not truncated", () => {
  assert.equal(truncatedUrl("https://example.com/page"), "https://example.com/page");
});

test("retrievedDateLabel names the retrieval, not a generic date", () => {
  const label = retrievedDateLabel("2026-09-22T10:00:00Z");
  assert.ok(label.startsWith("Retrieved "));
});

test("a first citation for a URL becomes a new card", () => {
  const results = applyWebCitation([], entry());
  assert.equal(results.length, 1);
  assert.equal(results[0]?.url, "https://gov.example/notice");
  assert.deepEqual(results[0]?.claimOrdinals, [1]);
});

test("a second claim citing the same URL adds an ordinal rather than a second card", () => {
  const once = applyWebCitation([], entry({ claimOrdinal: 1 }));
  const twice = applyWebCitation(once, entry({ claimOrdinal: 2 }));
  assert.equal(twice.length, 1);
  assert.deepEqual(twice[0]?.claimOrdinals, [1, 2]);
});

test("the same claim ordinal for a URL already carrying it is not added twice", () => {
  const once = applyWebCitation([], entry({ claimOrdinal: 1 }));
  const again = applyWebCitation(once, entry({ claimOrdinal: 1 }));
  assert.deepEqual(again[0]?.claimOrdinals, [1]);
});

test("two different URLs become two cards", () => {
  const first = applyWebCitation([], entry({ url: "https://a.example/", claimOrdinal: 1 }));
  const both = applyWebCitation(
    first,
    entry({ url: "https://b.example/", claimOrdinal: 2 }),
  );
  assert.equal(both.length, 2);
});
