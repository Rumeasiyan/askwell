/**
 * `nearMiss` — whether an abstention trace has anything to offer the
 * threshold control against. `M5-TRACE-FE-122`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { nearMiss } from "./retrieval-threshold.ts";

test("a below-threshold abstention with a hit reports its closest score and the threshold", () => {
  const result = nearMiss({
    steps: [
      { kind: "retrieve", threshold: 0.65, hits: [{ score: 0.61 }, { score: 0.4 }] },
      { kind: "abstain", reason_code: "below_threshold" },
    ],
  });
  assert.deepEqual(result, { score: 0.61, threshold: 0.65 });
});

test("an empty-corpus abstention has no near-miss even with a retrieve step present", () => {
  const result = nearMiss({
    steps: [
      { kind: "retrieve", threshold: 0.65, hits: [] },
      { kind: "abstain", reason_code: "empty_corpus" },
    ],
  });
  assert.equal(result, null);
});

test("a below-threshold abstention with nothing retrieved has no near-miss", () => {
  const result = nearMiss({
    steps: [
      { kind: "retrieve", threshold: 0.65, hits: [] },
      { kind: "abstain", reason_code: "below_threshold" },
    ],
  });
  assert.equal(result, null);
});

test("a normal, non-abstained turn has no near-miss", () => {
  const result = nearMiss({
    steps: [{ kind: "retrieve", threshold: 0.65, hits: [{ score: 0.9 }] }, { kind: "compose" }],
  });
  assert.equal(result, null);
});

test("the closest score is the highest below-threshold hit, not the first in the list", () => {
  const result = nearMiss({
    steps: [
      {
        kind: "retrieve",
        threshold: 0.65,
        hits: [{ score: 0.2 }, { score: 0.61 }, { score: 0.5 }],
      },
      { kind: "abstain", reason_code: "below_threshold" },
    ],
  });
  assert.equal(result?.score, 0.61);
});
