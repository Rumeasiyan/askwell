import { test } from "node:test";
import assert from "node:assert/strict";

import { isRaised } from "./pairing.ts";

const PAIRS = [
  { claimKey: "t:1", cardKey: "t:chunk-a" },
  { claimKey: "t:2", cardKey: "t:chunk-a" },
  { claimKey: "t:2", cardKey: "t:chunk-b" },
];

test("nothing is raised when nothing is hovered", () => {
  assert.equal(isRaised("t:1", null, PAIRS), false);
  assert.equal(isRaised("t:chunk-a", null, PAIRS), false);
});

test("hovering a claim raises exactly its card", () => {
  assert.equal(isRaised("t:1", "t:1", PAIRS), true);
  assert.equal(isRaised("t:chunk-a", "t:1", PAIRS), true);
  assert.equal(isRaised("t:chunk-b", "t:1", PAIRS), false);
});

test("hovering a card raises its claim", () => {
  assert.equal(isRaised("t:chunk-a", "t:chunk-a", PAIRS), true);
  assert.equal(isRaised("t:1", "t:chunk-a", PAIRS), true);
});

test("a claim with two cards raises both", () => {
  assert.equal(isRaised("t:chunk-a", "t:2", PAIRS), true);
  assert.equal(isRaised("t:chunk-b", "t:2", PAIRS), true);
});

test("hovering one claim never raises an unrelated claim's card", () => {
  assert.equal(isRaised("t:chunk-b", "t:1", PAIRS), false);
});
