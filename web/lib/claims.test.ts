/**
 * The client-side mirror of `askwell.agent.claims.segment_claims`.
 * `M1-CITE-FE-043`. Fixtures chosen to match `api/tests/test_claims.py`
 * exactly, so a divergence between the two implementations shows up here
 * rather than only as a leader pointing at the wrong sentence in a browser.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { proseParts, segmentClaims } from "./claims.ts";

test("a marked sentence is one claim, markers and punctuation stripped", () => {
  const claims = segmentClaims("The notice period is ninety days [1].");
  assert.equal(claims.length, 1);
  assert.equal(claims[0]?.ordinal, 1);
  assert.equal(claims[0]?.text, "The notice period is ninety days");
  assert.equal(claims[0]?.terminator, ".");
});

test("an unmarked sentence is not a claim at all", () => {
  const claims = segmentClaims("Let me know if you have other questions.");
  assert.equal(claims.length, 0);
});

test("a restatement ahead of a marked sentence does not shift its ordinal", () => {
  const claims = segmentClaims(
    "Here is what I found. The notice period is ninety days [1]. Anything else?",
  );
  assert.equal(claims.length, 1);
  assert.equal(claims[0]?.ordinal, 1);
});

test("three marked sentences number in order", () => {
  const claims = segmentClaims(
    "Rent is $1000 [1]. Notice is ninety days [2]. Pets are not allowed [3].",
  );
  assert.deepEqual(
    claims.map((c) => c.ordinal),
    [1, 2, 3],
  );
  assert.deepEqual(
    claims.map((c) => c.text),
    ["Rent is $1000", "Notice is ninety days", "Pets are not allowed"],
  );
});

test("a claim naming two indices is still one claim", () => {
  const claims = segmentClaims("Payment is due within forty-five days [1][2].");
  assert.equal(claims.length, 1);
});

test("start and end slice the original text back to the full marked sentence", () => {
  const text = "Rent is $1000 [1]. Notice is ninety days [2].";
  const claims = segmentClaims(text);
  assert.equal(text.slice(claims[0]!.start, claims[0]!.end), "Rent is $1000 [1].");
  assert.equal(text.slice(claims[1]!.start, claims[1]!.end), " Notice is ninety days [2].");
});

test("an incomplete trailing sentence, still streaming, produces no claim yet", () => {
  const claims = segmentClaims("Rent is $1000 [1]. Notice is ninety");
  assert.equal(claims.length, 1);
  assert.equal(claims[0]?.text, "Rent is $1000");
});

test("empty text yields no claims", () => {
  assert.deepEqual(segmentClaims(""), []);
});

// `proseParts` — issue GH-726, `M9-FIX-BE-202`. What `AnswerProse` renders is
// every text part plus each claim's `text` and `terminator`, so rendering
// must round-trip the input with only the citation markers removed.
function rendered(text: string): string {
  return proseParts(text)
    .map((part) => (part.kind === "text" ? part.text : part.claim.text + part.claim.terminator))
    .join("");
}

test("three cited claims render with the space between them kept", () => {
  assert.equal(
    rendered("The store opens at 9 AM [1]. It closes at 9 PM on weekdays [2]. Sundays close at 6 PM [3]."),
    "The store opens at 9 AM. It closes at 9 PM on weekdays. Sundays close at 6 PM.",
  );
});

test("a blank line between two cited paragraphs survives", () => {
  assert.equal(
    rendered("Stores close at 9 PM on weekdays [1].\n\nRetail stores close at 8 PM on Sundays [2]."),
    "Stores close at 9 PM on weekdays.\n\nRetail stores close at 8 PM on Sundays.",
  );
});

test("a final claim with no punctuation is still separated from the one before", () => {
  assert.equal(rendered("A is 1 [1]. B is 2 [2]"), "A is 1. B is 2 [2]");
});

test("uncited sentences between claims keep their own spacing", () => {
  assert.equal(
    rendered("Here is what I found. A is 1 [1]. That is all. B is 2 [2]."),
    "Here is what I found. A is 1. That is all. B is 2.",
  );
});

test("claim parts carry the same ordinals segmentClaims gives", () => {
  const text = "Intro. A is 1 [1]. B is 2 [2].";
  const ordinals = proseParts(text).flatMap((part) => (part.kind === "claim" ? [part.claim.ordinal] : []));
  assert.deepEqual(
    ordinals,
    segmentClaims(text).map((claim) => claim.ordinal),
  );
});
