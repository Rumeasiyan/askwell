/**
 * Client-side mirror of `askwell.agent.claims.segment_claims`. `M1-CITE-FE-043`.
 *
 * The backend numbers claims by re-running this same rule against the
 * growing answer text (`api/src/askwell/agent/claims.py`) — a sentence is a
 * claim only if a `[n]` marker sits immediately before its own terminating
 * punctuation. Mirroring it here, on the same text the browser already has,
 * is what lets the margin's leader find *where in the rendered prose* a
 * `citation` event's `claim_ordinal` points, without the server having to
 * send offsets over the wire. Both sides run the identical deterministic
 * scan against the identical text, so the ordinals agree without needing to.
 */

const CLAIM_RE = /([^.!?]*?)((?:\s*\[\d+\])+)?([.!?])/g;
const MARKER_RE = /\[(\d+)\]/g;

export interface ClaimMatch {
  /** 1-based, counting only sentences that carried a marker — matches the
   * server's `Claim.ordinal` exactly when run against the same text. */
  ordinal: number;
  /** Index into the source string where this claim's sentence starts. */
  start: number;
  /** Index one past this claim's terminating punctuation. */
  end: number;
  /** The sentence with its markers and punctuation stripped. */
  text: string;
  /** The sentence's own terminating punctuation. */
  terminator: string;
}

export function segmentClaims(text: string): ClaimMatch[] {
  const claims: ClaimMatch[] = [];
  let ordinal = 0;
  CLAIM_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CLAIM_RE.exec(text)) !== null) {
    const [full, bodyRaw, markers, terminator] = match;
    const body = (bodyRaw ?? "").trim();
    if (body === "" || markers === undefined || terminator === undefined) continue;
    MARKER_RE.lastIndex = 0;
    const indices = new Set<number>();
    let markerMatch: RegExpExecArray | null;
    while ((markerMatch = MARKER_RE.exec(markers)) !== null) {
      indices.add(Number(markerMatch[1]));
    }
    if (indices.size === 0) continue;
    ordinal += 1;
    claims.push({
      ordinal,
      start: match.index,
      end: match.index + full.length,
      text: body,
      terminator,
    });
  }
  return claims;
}

/** One run of `AnswerProse`'s output: plain text between claims, or a claim. */
export type ProsePart = { kind: "text"; text: string } | { kind: "claim"; claim: ClaimMatch };

/**
 * The prose `AnswerProse` renders, in order: the text between claims and the
 * claims themselves. `M9-FIX-BE-202`, issue GH-726.
 *
 * A claim's match runs back to the previous sentence's terminator, so the
 * space or blank line between two cited sentences sits at the front of the
 * second match — and `text` is trimmed. Printing only `text` and the gaps
 * between matches dropped it, and "A is 1 [1]. B is 2 [2]." rendered as
 * "A is 1.B is 2.". The whitespace is emitted here as its own text part, in
 * front of the claim, so ordinals and `start`/`end` stay exactly what the
 * server computes (`askwell.agent.claims`).
 */
export function proseParts(text: string, claims: ClaimMatch[] = segmentClaims(text)): ProsePart[] {
  const parts: ProsePart[] = [];
  let cursor = 0;
  for (const claim of claims) {
    const leading = /^\s*/.exec(text.slice(claim.start, claim.end))![0];
    const gap = text.slice(cursor, claim.start) + leading;
    if (gap !== "") parts.push({ kind: "text", text: gap });
    parts.push({ kind: "claim", claim });
    cursor = claim.end;
  }
  if (cursor < text.length) parts.push({ kind: "text", text: text.slice(cursor) });
  return parts;
}
