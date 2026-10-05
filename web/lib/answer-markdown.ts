/**
 * The Markdown a model writes into an answer, made readable (GH-936).
 *
 * The default model writes `**bold**`, `### headings`, `- lists` and `***`
 * rules on its own, and the Ask screen used to print them as literal
 * characters. This is deliberately not a Markdown renderer: an answer is one
 * run of prose split into claim spans (`lib/claims.ts`) whose numbering must
 * match the server's own `segment_claims` exactly, so nothing here may add,
 * move or remove a sentence terminator or a `[n]` marker.
 *
 * Two passes:
 *
 * - `normaliseAnswerLines` runs on the whole answer, before claims are
 *   segmented. It only rewrites line *prefixes* and drops rule lines: a
 *   heading becomes bold text, a `-`/`*`/`+` list marker becomes `•`, and a
 *   line that is only `***`/`---`/`___` disappears. Terminators and markers
 *   are untouched, so claim ordinals stay aligned with the server's.
 * - `inlineMarkdown` runs on each fragment `AnswerProse` renders — a claim's
 *   text, or the plain text between claims — and splits it into plain,
 *   strong, emphasis and code runs. A marker with no partner inside the same
 *   fragment is dropped rather than printed, so a bold run the claim split
 *   cut in half degrades to plain text, never to stray asterisks.
 *
 * No HTML is ever produced from the text: the caller maps each run to a
 * React element, so a model writing `<script>` gets the literal characters.
 */

export type InlineRun =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "em"; text: string }
  | { kind: "code"; text: string };

const RULE_LINE = /^[ \t]*([*_-])(?:[ \t]*\1){2,}[ \t]*$/;
const HEADING = /^([ \t]*)#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$/;
const BULLET = /^([ \t]*)[-*+][ \t]+(?=\S)/;

export function normaliseAnswerLines(text: string): string {
  const out: string[] = [];
  for (const line of text.split("\n")) {
    if (RULE_LINE.test(line)) continue;
    const heading = HEADING.exec(line);
    if (heading) {
      const [, indent = "", title = ""] = heading;
      out.push(`${indent}**${title.replace(/\*\*/g, "")}**`);
      continue;
    }
    out.push(line.replace(BULLET, "$1• "));
  }
  // A dropped rule line can leave three newlines where there were two
  // paragraphs; `pre-line` would show that as an extra blank line.
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}

// Order matters: `***x***` and `**x**` before `*x*`; code first so nothing
// inside backticks is read as emphasis.
const TOKEN =
  /`([^`\n]+)`|\*\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*\*|\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*|__(?=\S)([^_\n]+?)(?<=\S)__|\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*|(?<![\p{L}\p{N}_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\p{L}\p{N}_])/gu;

// Markers left over once every pair is consumed: a bold run cut in half by a
// claim boundary, or `***` the model never closed. Dropped, never printed.
const STRAY = /\*{2,}|(?<![\p{L}\p{N}])__|__(?![\p{L}\p{N}])/gu;

function plain(text: string, runs: InlineRun[]): void {
  const cleaned = text.replace(STRAY, "");
  if (cleaned === "") return;
  const last = runs[runs.length - 1];
  if (last !== undefined && last.kind === "text") {
    last.text += cleaned;
  } else {
    runs.push({ kind: "text", text: cleaned });
  }
}

export function inlineMarkdown(text: string): InlineRun[] {
  const runs: InlineRun[] = [];
  let cursor = 0;
  for (const match of text.matchAll(TOKEN)) {
    const start = match.index ?? 0;
    plain(text.slice(cursor, start), runs);
    const [, code, strongEm, strong, strongUnderscore, em, emUnderscore] = match;
    if (code !== undefined) runs.push({ kind: "code", text: code });
    else if (strongEm !== undefined) runs.push({ kind: "strong", text: strongEm });
    else if (strong !== undefined) runs.push({ kind: "strong", text: strong });
    else if (strongUnderscore !== undefined) runs.push({ kind: "strong", text: strongUnderscore });
    else if (em !== undefined) runs.push({ kind: "em", text: em });
    else if (emUnderscore !== undefined) runs.push({ kind: "em", text: emUnderscore });
    cursor = start + match[0].length;
  }
  plain(text.slice(cursor), runs);
  return runs;
}
