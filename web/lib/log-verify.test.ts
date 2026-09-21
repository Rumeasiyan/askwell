/**
 * `isFinished` — the polling loop's own stop condition.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { isFinished } from "./log-verify.ts";

test("a queued job is not finished", () => {
  assert.equal(isFinished({ status: "queued" }), false);
});

test("a running job is not finished", () => {
  assert.equal(isFinished({ status: "running" }), false);
});

test("a done job is finished", () => {
  assert.equal(isFinished({ status: "done" }), true);
});

test("a failed job is finished", () => {
  assert.equal(isFinished({ status: "failed" }), true);
});

test("a cancelled job is finished", () => {
  assert.equal(isFinished({ status: "cancelled" }), true);
});
