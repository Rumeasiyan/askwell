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
