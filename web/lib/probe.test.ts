/**
 * `overrideConsequence` — the copy stated before a profile override is
 * submitted. `M7-PROBE-FE-138`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { PROFILES, accelerationLine, overrideConsequence } from "./probe.ts";

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

test("the acceleration line states where answers really run", () => {
  assert.equal(accelerationLine(true, "gpu", null), "Answers run on the graphics card.");
  assert.equal(accelerationLine(true, "cpu", null), "Answers run on the processor.");
});

test("a partial offload or a fallback carries its reason", () => {
  assert.equal(
    accelerationLine(true, "gpu", "20 of 33 layers are on the card."),
    "Answers run on the graphics card. 20 of 33 layers are on the card.",
  );
  assert.match(
    accelerationLine(true, "cpu", "The driver is too old.") ?? "",
    /processor\. The driver is too old\./,
  );
});

test("nothing is claimed while the assistant is not running", () => {
  assert.equal(accelerationLine(false, null, null), null);
  assert.equal(accelerationLine(false, "gpu", null), null);
});
