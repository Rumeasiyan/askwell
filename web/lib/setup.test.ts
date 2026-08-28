/**
 * Pure helpers for the welcome sequence's API surface. `M1-LIB-FE-052`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { formatBytes, isNoDiskSpaceError } from "./setup.ts";

test("formatBytes rounds a large download to one decimal of GB", () => {
  assert.equal(formatBytes(3_013_027_808), "3.0 GB");
});

test("formatBytes falls back to whole MB below a tenth of a GB", () => {
  assert.equal(formatBytes(50_000_000), "50 MB");
});

test("formatBytes never reports zero for a tiny nonzero amount", () => {
  assert.equal(formatBytes(1), "1 MB");
});

test("isNoDiskSpaceError recognises the 409 shape", () => {
  assert.equal(
    isNoDiskSpaceError({ error: "No disk space.", needed_bytes: 10, free_bytes: 1 }),
    true,
  );
});

test("isNoDiskSpaceError rejects an ordinary Error", () => {
  assert.equal(isNoDiskSpaceError(new Error("Askwell answered 500.")), false);
});

test("isNoDiskSpaceError rejects null and non-objects", () => {
  assert.equal(isNoDiskSpaceError(null), false);
  assert.equal(isNoDiskSpaceError("no disk space"), false);
});
