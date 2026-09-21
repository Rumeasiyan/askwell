/**
 * `cappedByFreeDisk` — whether the 5%-of-free-disk ceiling is what the
 * settings screen's budget figure is really showing (issue 484).
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { cappedByFreeDisk } from "./storage.ts";

test("the effective budget matching what was set is not capped", () => {
  assert.equal(cappedByFreeDisk({ budget_bytes: 2_000_000_000, configured_bytes: 2_000_000_000 }), false);
});

test("an effective budget smaller than the configured cap is capped by free disk", () => {
  assert.equal(cappedByFreeDisk({ budget_bytes: 500_000_000, configured_bytes: 10_000_000_000 }), true);
});
