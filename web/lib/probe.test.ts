/**
 * `overrideConsequence` — the copy stated before a profile override is
 * submitted. `M7-PROBE-FE-138`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { PROFILES, overrideConsequence } from "./probe.ts";

test("every profile's consequence names that profile", () => {
  for (const tier of PROFILES) {
    assert.match(overrideConsequence(tier), new RegExp(`run as ${tier}`));
  }
});

test("the consequence names the failure mode and that search still works", () => {
  const text = overrideConsequence("workstation");
  assert.match(text, /report the failure clearly/);
  assert.match(text, /document search and indexing keep working/);
});

test("the consequence names that the change is recorded", () => {
  assert.match(overrideConsequence("light"), /decisions log/);
});
