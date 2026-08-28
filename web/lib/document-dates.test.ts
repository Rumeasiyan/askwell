/**
 * The pure label formatting `M2-PARTIAL-FE-058`'s conflict card uses.
 * `useDocumentDate` itself is a fetch-backed hook and is exercised by the
 * component tests that render it, not here.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { addedDateLabel, supersededDateLabel } from "./document-dates.ts";

test("no added date yet renders nothing", () => {
  assert.equal(addedDateLabel({ addedAt: null }), null);
});

test("an added date is labelled, since no other date source exists yet", () => {
  const label = addedDateLabel({ addedAt: "2026-08-28T00:00:00Z" });
  assert.match(label ?? "", /^Added /);
});

test("a live document has no superseded label", () => {
  assert.equal(supersededDateLabel({ supersededBy: null, supersededAt: null }), null);
});

test("a superseded document is labelled with its own supersession date", () => {
  const label = supersededDateLabel({
    supersededBy: "11111111-1111-1111-1111-111111111111",
    supersededAt: "2026-08-01T00:00:00Z",
  });
  assert.match(label ?? "", /^Superseded /);
});

test("a superseded document with no known supersession date still labels as superseded", () => {
  const label = supersededDateLabel({
    supersededBy: "11111111-1111-1111-1111-111111111111",
    supersededAt: null,
  });
  assert.equal(label, "Superseded");
});
