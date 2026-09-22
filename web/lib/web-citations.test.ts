/**
 * Pure formatting rules for the web results region. `M6.5-WEB-FE-190`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { retrievedDateLabel, truncate, truncatedTitle, truncatedUrl } from "./web-citations.ts";

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
