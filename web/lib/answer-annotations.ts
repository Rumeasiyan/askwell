/**
 * Client-side mirror of `askwell.agent.partial.split_partial_answer` and
 * `askwell.agent.conflict.split_conflict_answer`. `M2-PARTIAL-FE-058`.
 *
 * Both server modules read a fixed, deliberately-not-fuzzy line back out of
 * the composed answer rather than re-detecting partial coverage or a
 * conflict — see their own docstrings. They leave those lines in the stored
 * `messages.content` / streamed `turn.answer` text rather than stripping
 * them (`conflict.py`'s own comment: "not scaffolding to strip out"), which
 * is what lets this module read the exact same signal client-side with no
 * new wire field: the browser already has the full answer text as it
 * streams. Mirroring the regex here, on the same text `AnswerProse` already
 * renders, is the same approach `lib/claims.ts` takes for citation ordinals.
 */

import { segmentClaims } from "./claims.ts";

const NOT_COVERED_RE = /^Not covered:\s*(.+?)\s*\.?\s*$/;
const CONFLICT_RE = /^Conflicting sources on\s*(.+?):\s*$/;
const RESOLVED_BY_MEMORY_RE = /^Resolved by memory:\s*(.+?)\s*\.?\s*$/;

export interface AnswerAnnotations {
  /** In the order the model wrote them; not de-duplicated — matches
   * `PartialAnswer.uncovered` exactly. */
  uncovered: string[];
  /** The fact named on the "Conflicting sources on ...:" line, or `null`
   * when this answer presents no conflict. */
  conflictTopic: string | null;
  /** The fact named on the "Resolved by memory:" line — always `null` in
   * M2, since nothing composes a `<memory-fact>` block yet
   * (`agent/conflict.py`'s own M3 hook). Read anyway so the FE does not
   * need a second pass once M3 wires it up. */
  resolvedByMemory: string | null;
  /** `text`, with every annotation line removed and the remaining blank
   * lines collapsed. The ordinary prose and, for a conflict, the cited
   * position sentences (which carry `[n]` markers and must stay in the
   * normal claim flow) are untouched — only the three fixed label lines
   * are lifted out, to be rendered as their own distinct elements instead
   * of unstyled prose. */
  cleanedText: string;
  /** Where in `cleanedText` the "Conflicting sources on ...:" line stood —
   * the offset of whatever followed it — or `null` when there is no
   * conflict. `M7-FIX-FE-170`: the positions the model wrote under that line
   * start here, and `layoutConflict` needs to know where, because once the
   * line is lifted out nothing else in the text marks the boundary (a
   * preamble ending in ":" and the first position otherwise read as one
   * sentence). */
  conflictAt: number | null;
}

export function isPartial(annotations: Pick<AnswerAnnotations, "uncovered">): boolean {
  return annotations.uncovered.length > 0;
}

export function isConflict(annotations: Pick<AnswerAnnotations, "conflictTopic">): boolean {
  return annotations.conflictTopic !== null;
}

// A local counter of conflicts presented — the ticket's own Analytics
// Events line: "Local counter of conflicts presented — nothing transmitted
// (C1)." In-memory only, module state rather than component state for the
// same reason `citations.ts`'s `cardClickCount` is: it should survive the
// turn that produced it collapsing away, not reset on every re-render.
let conflictsPresentedCount = 0;

export function recordConflictPresented(): void {
  conflictsPresentedCount += 1;
}

export function getConflictsPresentedCount(): number {
  return conflictsPresentedCount;
}

export function parseAnswerAnnotations(text: string): AnswerAnnotations {
  const uncovered: string[] = [];
  let conflictTopic: string | null = null;
  let resolvedByMemory: string | null = null;
  const kept: string[] = [];
  let conflictLine: number | null = null;

  for (const line of text.split("\n")) {
    const stripped = line.trim();

    const notCovered = NOT_COVERED_RE.exec(stripped);
    if (notCovered !== null) {
      uncovered.push(notCovered[1]!.trim());
      continue;
    }

    if (conflictTopic === null) {
      const conflict = CONFLICT_RE.exec(stripped);
      if (conflict !== null) {
        conflictTopic = conflict[1]!.trim();
        conflictLine = kept.length;
        continue;
      }
    }

    if (resolvedByMemory === null) {
      const resolved = RESOLVED_BY_MEMORY_RE.exec(stripped);
      if (resolved !== null) {
        resolvedByMemory = resolved[1]!.trim();
        continue;
      }
    }

    kept.push(line);
  }

  // Collapse runs of blank lines the removed annotation lines leave behind,
  // and trim the leading/trailing ones entirely — an annotation line was
  // always alone on its own line, so removing it otherwise leaves a gap
  // exactly where it stood. Done line by line rather than with a regex over
  // the joined text so the conflict line's offset survives the collapse: an
  // empty line directly after another empty line is dropped, which is
  // exactly what `/\n{3,}/g → "\n\n"` did.
  const collapsed: string[] = [];
  let conflictOffset: number | null = null;
  let offset = 0;
  for (const [index, line] of kept.entries()) {
    if (index === conflictLine) conflictOffset = offset;
    if (line === "" && collapsed.length > 0 && collapsed[collapsed.length - 1] === "") continue;
    collapsed.push(line);
    offset += line.length + 1;
  }
  if (conflictLine !== null && conflictLine >= kept.length) conflictOffset = offset;
  const joined = collapsed.join("\n");
  const cleanedText = joined.trim();
  const leading = joined.length - joined.trimStart().length;
  const conflictAt =
    conflictOffset === null ? null : Math.min(Math.max(conflictOffset - leading, 0), cleanedText.length);

  return { uncovered, conflictTopic, resolvedByMemory, cleanedText, conflictAt };
}

/** One side of a conflict: the cited sentence the model wrote for it, and
 * the claim ordinal the provenance margin's cards and leader lines already
 * know it by. */
export interface ConflictPosition {
  ordinal: number;
  /** The sentence with its `[n]` markers, any list bullet and surrounding
   * whitespace removed; keeps its own closing punctuation. */
  text: string;
}

export interface ConflictLayout {
  /** Everything before the "Conflicting sources on ...:" line. Its claims
   * are numbered from 1, exactly as they are in the full text. */
  before: string;
  positions: ConflictPosition[];
  /** Text inside the positions' paragraph that is not itself a cited
   * position — kept and shown, never dropped (C4: an uncited line is still
   * something the answer said, and hiding it would be a silent edit). */
  unplaced: string;
  /** Everything after the positions' paragraph. */
  after: string;
  /** The claim ordinal `after`'s own first claim is numbered from, minus
   * one — `AnswerProse`'s `ordinalOffset`. */
  afterOffset: number;
}

const MARKERS_RE = /\s*(?:\[\d+\]\s*)+(?=[.!?]$)/;
const BULLET_RE = /^(?:[-*•]|\d+[.)])\s+/;
const BULLET_LINE_RE = /\n[ \t]*(?:[-*•]|\d+[.)])\s/g;

const CITED_LINE_RE = /\[\d+\]\s*[.!?]$/;

/**
 * Split a conflict answer's `cleanedText` into the prose around it and the
 * positions themselves, so each position renders as its own record rather
 * than as one run of prose. `M7-FIX-FE-170`, issue GH-643.
 *
 * The positions are cited sentences next to the conflict line. The prompt
 * asks for them in the paragraph after it, so that is looked at first: from
 * the first non-blank text after `conflictAt` to the next blank line. The
 * local model often writes them *before* the line instead — the live answer
 * GH-643 was filed against did — so when the paragraph after holds no cited
 * sentence at all, the run of lines directly above the line is used, as long
 * as every one of them is blank or ends in a cited sentence. Only then: a
 * cited paragraph below means the model followed the prompt, and reaching
 * above it too would turn an ordinary cited sentence into a position. Fewer than two
 * positions either way is `null`, and the answer renders as prose, as it did
 * before: one cited sentence beside an uncited one is not two records.
 *
 * Sentences, not lines, because a model that forgets the line break between
 * two positions would otherwise put both in one block, which is the run-on
 * this exists to remove.
 *
 * Claims are numbered by `segmentClaims` over the whole text and never
 * re-derived, so every ordinal here is the one the server gave the same
 * sentence (`askwell.agent.claims`) and the margin's cards still pair with it.
 * `segmentClaims` is prefix-stable — a claim's match depends only on the text
 * up to its own end — which is what makes rendering `before` on its own, and
 * `after` with `afterOffset`, number their claims identically to the whole.
 */
export function layoutConflict(text: string, conflictAt: number): ConflictLayout | null {
  const claims = segmentClaims(text);

  const afterStart = conflictAt + (text.slice(conflictAt).length - text.slice(conflictAt).trimStart().length);
  const blank = /\n[ \t]*\n/.exec(text.slice(afterStart));
  const afterEnd = blank === null ? text.length : afterStart + blank.index;
  if (claims.some((claim) => claim.end > afterStart && claim.end <= afterEnd)) {
    return placePositions(text, claims, afterStart, afterEnd);
  }

  const head = text.slice(0, conflictAt);
  let aboveStart = head.length;
  const lines = head.split("\n");
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const trimmed = lines[index]!.trim();
    if (trimmed !== "" && !CITED_LINE_RE.test(trimmed)) break;
    aboveStart = lines.slice(0, index).join("\n").length + (index > 0 ? 1 : 0);
  }
  aboveStart += text.slice(aboveStart).length - text.slice(aboveStart).trimStart().length;
  return placePositions(text, claims, Math.min(aboveStart, conflictAt), head.trimEnd().length);
}

function placePositions(
  text: string,
  claims: ReturnType<typeof segmentClaims>,
  regionStart: number,
  regionEnd: number,
): ConflictLayout | null {
  const inRegion = claims.filter((claim) => claim.end > regionStart && claim.end <= regionEnd);
  if (inRegion.length < 2) return null;

  const positions: ConflictPosition[] = [];
  const unplacedParts: string[] = [];
  let cursor = regionStart;
  for (const claim of inRegion) {
    // A claim's match runs back to the previous sentence's terminator, so an
    // uncited bullet with no full stop of its own ("- Opening hours vary")
    // would otherwise be swallowed into the next position and read as cited.
    // Start at the last bullet inside the match instead; a sentence the model
    // merely wrapped onto a second line has no bullet there and stays whole.
    const matchStart = Math.max(claim.start, regionStart);
    let start = matchStart;
    for (const bullet of text.slice(matchStart, claim.end).matchAll(BULLET_LINE_RE)) {
      start = matchStart + (bullet.index ?? 0) + 1;
    }
    if (start > cursor) unplacedParts.push(text.slice(cursor, start));
    const sentence = text.slice(start, claim.end).trim().replace(MARKERS_RE, "").replace(BULLET_RE, "");
    positions.push({ ordinal: claim.ordinal, text: sentence });
    cursor = claim.end;
  }
  unplacedParts.push(text.slice(cursor, regionEnd));

  return {
    before: text.slice(0, regionStart).trim(),
    positions,
    unplaced: unplacedParts
      .map((part) => part.trim().replace(BULLET_RE, ""))
      .filter((part) => part !== "")
      .join(" "),
    after: text.slice(regionEnd).trim(),
    afterOffset: claims.filter((claim) => claim.end <= regionEnd).length,
  };
}
