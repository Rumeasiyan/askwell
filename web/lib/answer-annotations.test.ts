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

import { isConflict, isPartial, layoutConflict, parseAnswerAnnotations } from "./answer-annotations.ts";
import { segmentClaims } from "./claims.ts";

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

/**
 * `M7-FIX-FE-170`, issue GH-643: a conflict renders each position as its own
 * record, so the parser has to say where the positions start and the layout
 * has to find them without renumbering a single claim.
 */

// The live answer GH-643 was filed against, as stored in `messages.content`.
const STORE_HOURS =
  "Based on the retrieved content, there is a conflict regarding the closing hours for Meridian Loom retail stores on weekdays:\n" +
  "\n" +
  "Conflicting sources on weekday closing times:\n" +
  "\n" +
  "- Stores close at 9 PM on weekdays [1].\n" +
  "- Stores close at 8 PM on weekdays [2].\n" +
  "\n" +
  "The retrieved content does not provide information on store opening hours.\n" +
  "\n" +
  "Not covered: store opening hours.";

function layout(text: string) {
  const annotations = parseAnswerAnnotations(text);
  assert.notEqual(annotations.conflictAt, null);
  return { annotations, layout: layoutConflict(annotations.cleanedText, annotations.conflictAt!) };
}

test("a non-conflict answer has no conflict offset", () => {
  assert.equal(parseAnswerAnnotations("Notice is ninety days [1].").conflictAt, null);
});

test("removing annotation lines still collapses blank runs exactly as before", () => {
  const result = parseAnswerAnnotations(STORE_HOURS);
  assert.equal(
    result.cleanedText,
    "Based on the retrieved content, there is a conflict regarding the closing hours for Meridian Loom retail stores on weekdays:\n" +
      "\n" +
      "- Stores close at 9 PM on weekdays [1].\n" +
      "- Stores close at 8 PM on weekdays [2].\n" +
      "\n" +
      "The retrieved content does not provide information on store opening hours.",
  );
});

test("two conflicting claims become two positions, not one run of prose", () => {
  const { layout: result } = layout(STORE_HOURS);
  assert.notEqual(result, null);
  assert.deepEqual(result!.positions, [
    { ordinal: 1, text: "Stores close at 9 PM on weekdays." },
    { ordinal: 2, text: "Stores close at 8 PM on weekdays." },
  ]);
  assert.equal(
    result!.before,
    "Based on the retrieved content, there is a conflict regarding the closing hours for Meridian Loom retail stores on weekdays:",
  );
  assert.equal(result!.after, "The retrieved content does not provide information on store opening hours.");
  assert.equal(result!.unplaced, "");
});

test("positions the model wrote on one line are still two positions", () => {
  const { layout: result } = layout(
    "Conflicting sources on store closing times:\n" +
      "Meridian Loom retail stores close at 9 PM on weekdays [1].Meridian Loom retail stores close at 8 PM on weekdays [2].",
  );
  assert.deepEqual(
    result!.positions.map((position) => position.text),
    [
      "Meridian Loom retail stores close at 9 PM on weekdays.",
      "Meridian Loom retail stores close at 8 PM on weekdays.",
    ],
  );
});

test("three sources disagreeing give three positions", () => {
  const { layout: result } = layout(
    "Conflicting sources on the notice period:\n" +
      "- Notice is ninety days [1].\n" +
      "- Notice is sixty days [2].\n" +
      "- Notice is thirty days [3].",
  );
  assert.deepEqual(
    result!.positions.map((position) => position.ordinal),
    [1, 2, 3],
  );
});

test("claim ordinals match the whole text's numbering on both sides of the positions", () => {
  const text =
    "Payment is due in 45 days [1].\n" +
    "Conflicting sources on the notice period:\n" +
    "- Notice is ninety days [2].\n" +
    "- Notice is sixty days [3].\n" +
    "\n" +
    "Renewal is annual [4].";
  const { annotations, layout: result } = layout(text);
  const whole = segmentClaims(annotations.cleanedText);
  assert.equal(whole.length, 4);
  assert.deepEqual(
    result!.positions.map((position) => position.ordinal),
    [2, 3],
  );
  assert.equal(segmentClaims(result!.before).length, 1);
  assert.equal(result!.afterOffset, 3);
  assert.deepEqual(
    segmentClaims(result!.after).map((claim) => claim.ordinal + result!.afterOffset),
    [4],
  );
});

test("a position citing two passages keeps both markers out of its text", () => {
  const { layout: result } = layout(
    "Conflicting sources on the notice period:\n- Notice is ninety days [1][2].\n- Notice is sixty days [3].",
  );
  assert.equal(result!.positions[0]!.text, "Notice is ninety days.");
});

test("an uncited line among the positions is kept, and never merged into a cited one", () => {
  const { layout: result } = layout(
    "Conflicting sources on the notice period:\n" +
      "- Notice is ninety days [1].\n" +
      "- Some offices may differ\n" +
      "- Notice is sixty days [2].",
  );
  assert.deepEqual(
    result!.positions.map((position) => position.text),
    ["Notice is ninety days.", "Notice is sixty days."],
  );
  assert.equal(result!.unplaced, "Some offices may differ");
});

test("a conflict line with no cited position under it lays out nothing", () => {
  const { layout: result } = layout("Conflicting sources on the notice period:\nThe files disagree.");
  assert.equal(result, null);
});

test("a conflict line mid-stream, with nothing after it yet, lays out nothing", () => {
  const { layout: result } = layout("Conflicting sources on the notice period:\n");
  assert.equal(result, null);
});

// The live answer from 0.7.37 on the fixture corpus: the model wrote the two
// positions first and the conflict line last.
const STORE_HOURS_LINE_LAST =
  "Meridian Loom retail stores close at 9 PM on weekdays [1].\n" +
  "\n" +
  "Meridian Loom retail stores close at 8 PM on weekdays [2].\n" +
  "\n" +
  "Conflicting sources on store closing times:";

test("positions written above the conflict line are laid out too", () => {
  const { layout: result } = layout(STORE_HOURS_LINE_LAST);
  assert.deepEqual(result!.positions, [
    { ordinal: 1, text: "Meridian Loom retail stores close at 9 PM on weekdays." },
    { ordinal: 2, text: "Meridian Loom retail stores close at 8 PM on weekdays." },
  ]);
  assert.equal(result!.before, "");
  assert.equal(result!.after, "");
  assert.equal(result!.afterOffset, 2);
});

test("lines above the conflict line stop at the first uncited one", () => {
  const { layout: result } = layout(
    "The files disagree about this.\n" +
      "Stores close at 9 PM [1].\n" +
      "Stores close at 8 PM [2].\n" +
      "Conflicting sources on store closing times:",
  );
  assert.equal(result!.before, "The files disagree about this.");
  assert.deepEqual(
    result!.positions.map((position) => position.ordinal),
    [1, 2],
  );
});

test("a cited paragraph below the conflict line is never extended upwards", () => {
  const { layout: result } = layout(
    "Payment is due in 45 days [1].\n" +
      "Conflicting sources on the notice period:\n" +
      "- Notice is ninety days [2].\n" +
      "- Memory says sixty days.",
  );
  assert.equal(result, null);
});
