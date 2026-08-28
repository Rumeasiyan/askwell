/**
 * The client-side mirror of `askwell.agent.partial.split_partial_answer`
 * and `askwell.agent.conflict.split_conflict_answer`. `M2-PARTIAL-FE-058`.
 * Fixtures chosen to match `api/tests/test_partial.py` and
 * `api/tests/test_conflict.py` exactly, so a divergence between the server
 * and this mirror shows up here rather than only as a card missing its
 * date in a browser.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { isConflict, isPartial, parseAnswerAnnotations } from "./answer-annotations.ts";

test("a covered and an uncovered aspect split apart", () => {
  const text = "Payment terms are 45 days [1].\nNot covered: the termination notice period for this supplier.";
  const result = parseAnswerAnnotations(text);
  assert.equal(isPartial(result), true);
  assert.deepEqual(result.uncovered, ["the termination notice period for this supplier"]);
  assert.equal(result.cleanedText, "Payment terms are 45 days [1].");
});

test("every aspect covered has nothing uncovered", () => {
  const result = parseAnswerAnnotations("Payment terms are 45 days [1].");
  assert.equal(isPartial(result), false);
  assert.deepEqual(result.uncovered, []);
  assert.equal(result.cleanedText, "Payment terms are 45 days [1].");
});

test("more than one uncovered aspect is kept in order", () => {
  const text =
    "Payment terms are 45 days [1].\n" +
    "Not covered: the termination notice period.\n" +
    "Not covered: the renewal clause.\n";
  const result = parseAnswerAnnotations(text);
  assert.deepEqual(result.uncovered, ["the termination notice period", "the renewal clause"]);
});

test("two positions on the same fact are detected as a conflict", () => {
  const text =
    "Conflicting sources on the notice period:\n" +
    "- Notice must be given ninety days in advance [1].\n" +
    "- Notice must be given sixty days in advance [2].\n";
  const result = parseAnswerAnnotations(text);
  assert.equal(isConflict(result), true);
  assert.equal(result.conflictTopic, "the notice period");
  assert.equal(
    result.cleanedText,
    "- Notice must be given ninety days in advance [1].\n- Notice must be given sixty days in advance [2].",
  );
});

test("a single consistent answer is not a conflict", () => {
  const result = parseAnswerAnnotations("Notice must be given ninety days in advance [1].");
  assert.equal(isConflict(result), false);
  assert.equal(result.conflictTopic, null);
});

test("wording differences without a substance disagreement are not a conflict", () => {
  const result = parseAnswerAnnotations("Notice must be given ninety days in advance [1][2].");
  assert.equal(isConflict(result), false);
});

test("conflict and uncovered aspect coexist", () => {
  const text =
    "Conflicting sources on the notice period:\n" +
    "- Notice must be given ninety days in advance [1].\n" +
    "- Notice must be given sixty days in advance [2].\n" +
    "Not covered: the renewal clause.\n";
  const result = parseAnswerAnnotations(text);
  assert.equal(isConflict(result), true);
  assert.equal(isPartial(result), true);
  assert.deepEqual(result.uncovered, ["the renewal clause"]);
});

test("no memory resolution by default", () => {
  const result = parseAnswerAnnotations("Notice must be given ninety days in advance [1].");
  assert.equal(result.resolvedByMemory, null);
});

test("memory resolution line is read back, and a resolved conflict is not an unresolved one", () => {
  const text =
    "Notice must be given ninety days in advance, per the correction you gave [1].\n" +
    "Resolved by memory: the notice period.\n";
  const result = parseAnswerAnnotations(text);
  assert.equal(result.resolvedByMemory, "the notice period");
  assert.equal(isConflict(result), false);
});

test("cleaning collapses the gap an annotation line leaves behind, front and back", () => {
  const text = "Not covered: everything.\nAnswered nothing else.\nNot covered: something else.";
  const result = parseAnswerAnnotations(text);
  assert.equal(result.cleanedText, "Answered nothing else.");
});
