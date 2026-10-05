/**
 * GH-936: the Markdown a model writes into an answer, made readable without
 * moving a single claim boundary.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { inlineMarkdown, normaliseAnswerLines } from "./answer-markdown.ts";
import { segmentClaims } from "./claims.ts";

test("bold, italic and code become their own runs, markers gone", () => {
  assert.deepEqual(inlineMarkdown("The **Chairman** is the *chief* executive, see `s.8`."), [
    { kind: "text", text: "The " },
    { kind: "strong", text: "Chairman" },
    { kind: "text", text: " is the " },
    { kind: "em", text: "chief" },
    { kind: "text", text: " executive, see " },
    { kind: "code", text: "s.8" },
    { kind: "text", text: "." },
  ]);
});

test("triple asterisks and double underscores read as bold", () => {
  assert.deepEqual(inlineMarkdown("***Forty-eight months*** and __twelve__"), [
    { kind: "strong", text: "Forty-eight months" },
    { kind: "text", text: " and " },
    { kind: "strong", text: "twelve" },
  ]);
});

test("a marker with no partner is dropped, never printed", () => {
  // A bold run the claim split cut in half: each fragment holds one side.
  assert.deepEqual(inlineMarkdown("**The term is forty-eight months"), [
    { kind: "text", text: "The term is forty-eight months" },
  ]);
  assert.deepEqual(inlineMarkdown("from commencement**"), [
    { kind: "text", text: "from commencement" },
  ]);
  assert.deepEqual(inlineMarkdown("an unclosed *** run"), [{ kind: "text", text: "an unclosed  run" }]);
});

test("ordinary asterisks and underscores in prose are left alone", () => {
  assert.deepEqual(inlineMarkdown("2 * 3 = 6 and snake_case_name"), [
    { kind: "text", text: "2 * 3 = 6 and snake_case_name" },
  ]);
});

test("text that looks like HTML stays text", () => {
  assert.deepEqual(inlineMarkdown("<b>not bold</b> <script>x</script>"), [
    { kind: "text", text: "<b>not bold</b> <script>x</script>" },
  ]);
});

test("headings become bold lines, list markers become bullets, rules vanish", () => {
  const input = [
    "### Term of office",
    "- The term is forty-eight months [1].",
    "* It may be extended [1].",
    "***",
    "",
    "1. Numbered items keep their numbers [2].",
  ].join("\n");
  assert.equal(
    normaliseAnswerLines(input),
    [
      "**Term of office**",
      "• The term is forty-eight months [1].",
      "• It may be extended [1].",
      "",
      "1. Numbered items keep their numbers [2].",
    ].join("\n"),
  );
});

test("a dropped rule line never leaves an extra blank line", () => {
  assert.equal(normaliseAnswerLines("First [1].\n\n---\n\nSecond [2]."), "First [1].\n\nSecond [2].");
});

test("normalising never changes which sentences are claims, or their ordinals", () => {
  const answer = [
    "## Who can dissolve an Urban Council",
    "",
    "The **Minister** can dissolve an Urban Council [1].",
    "",
    "***",
    "",
    "- He may *replace* it with a new Council [2].",
    "- He may dissolve it to constitute another authority [2][3].",
    "Note: nothing here names a court.",
  ].join("\n");
  // Rewrites touch line prefixes only, so each claim keeps its ordinal and
  // the end of its sentence.
  const shape = (text: string) =>
    segmentClaims(text).map((claim) => [claim.ordinal, claim.text.slice(-20), claim.terminator]);
  const before = shape(answer);
  const after = shape(normaliseAnswerLines(answer));
  assert.deepEqual(after, before);
  assert.equal(after.length, 3);
});
