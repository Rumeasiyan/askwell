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
  // exactly where it stood.
  const cleanedText = kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();

  return { uncovered, conflictTopic, resolvedByMemory, cleanedText };
}
