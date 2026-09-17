/**
 * `M3-REVIEW-FE-072`: the pure clarifications logic — sentence formatting,
 * which is the only part here that can silently disagree with itself between
 * the badge and the screen.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { NONE_PENDING_COPY, groupSentence, totalSentence } from "./clarifications.ts";

test("totalSentence singular", () => {
  assert.equal(totalSentence(1), "1 question");
});

test("totalSentence plural, including zero", () => {
  assert.equal(totalSentence(4), "4 questions");
  assert.equal(totalSentence(0), "0 questions");
});

test("groupSentence matches totalSentence's own shape", () => {
  assert.equal(groupSentence(3), totalSentence(3));
  assert.equal(groupSentence(1), totalSentence(1));
});

test("the empty state teaches the feature rather than reporting an absence", () => {
  assert.ok(NONE_PENDING_COPY.toLowerCase().includes("askwell asks when"));
  assert.ok(!NONE_PENDING_COPY.toLowerCase().startsWith("no items"));
});
