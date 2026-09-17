/**
 * Folding `fact_citation` events into memory chips, and the popover's fetch
 * shapes. `M3-CORRECT-FE-081`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { AskFactCitationData } from "./ask.ts";
import { applyFactCitation, type FactChip } from "./memory-chips.ts";

function factCitation(over: Partial<AskFactCitationData> = {}): AskFactCitationData {
  return {
    message_id: "m1",
    index: 2,
    claim_ordinal: 1,
    fact_kind: "memory",
    fact_id: "f1",
    subject: "st_cd",
    fact: "student status code",
    origin: "clarification",
    confidence: 1.0,
    supplied_at: "2026-09-01T00:00:00+00:00",
    ...over,
  };
}

test("a first fact_citation becomes a new chip", () => {
  const chips = applyFactCitation([], factCitation());
  assert.equal(chips.length, 1);
  assert.equal(chips[0]?.factId, "f1");
  assert.equal(chips[0]?.claimOrdinal, 1);
  assert.equal(chips[0]?.subject, "st_cd");
});

test("the same (claim, fact) resent by a reconnect does not duplicate", () => {
  const first = applyFactCitation([], factCitation());
  const again = applyFactCitation(first, factCitation());
  assert.equal(again.length, 1);
});

test("the same fact cited by a different claim is a second, separate chip", () => {
  const first = applyFactCitation([], factCitation({ claim_ordinal: 1 }));
  const second = applyFactCitation(first, factCitation({ claim_ordinal: 3, index: 4 }));
  assert.equal(second.length, 2);
  assert.deepEqual(
    second.map((chip) => chip.claimOrdinal),
    [1, 3],
  );
});

test("a schema note chip carries its table.column subject through unchanged", () => {
  const chips = applyFactCitation(
    [],
    factCitation({ fact_kind: "schema_note", fact_id: "n1", subject: "invoices.st_cd" }),
  );
  const chip: FactChip | undefined = chips[0];
  assert.equal(chip?.factKind, "schema_note");
  assert.equal(chip?.subject, "invoices.st_cd");
});
