/**
 * Suggested follow-ups after a completed answer. `M1-CONV-FE-180`.
 *
 * `conversation.md` §3: up to three, each derived from what was just
 * answered, that **fill the composer rather than sending**. No model call —
 * the same reasoning `askwell.suggestions.suggested_questions` already
 * settled for the empty-state suggestions (`M1-LIB-FE-051`): this is exactly
 * the moment a slow local model must not delay, since the answer the user is
 * reading is already on screen. Pure, so "fewer than three, or none, rather
 * than padding" is checkable without a browser.
 */

import type { CitationCard } from "@/lib/citations";

const MAX_FOLLOW_UPS = 3;

// The same short, non-linguistic stopword list `askwell.suggestions` uses
// server-side — good enough for a heuristic that exists to be cheap, not to
// be right every time.
const STOPWORDS = new Set(
  `the a an and or but if then else for of to in on at by with from as is
   are was were be been being this that these those it its it's he she they
   we you your our their his her them him us not no do does did done have
   has had can could will would should may might must into over under
   about above below between among per via than also such only more most
   other same each any all both few some such only own so too very just`
    .split(/\s+/)
    .filter((word) => word !== ""),
);

const WORD = /[A-Za-z][A-Za-z'-]{3,}/g;

function distinctiveTerm(text: string): string | null {
  const counts = new Map<string, number>();
  for (const match of text.matchAll(WORD)) {
    const word = match[0].toLowerCase();
    if (STOPWORDS.has(word)) continue;
    counts.set(word, (counts.get(word) ?? 0) + 1);
  }
  if (counts.size === 0) return null;
  let best: string | null = null;
  let bestCount = 0;
  for (const [word, count] of counts) {
    if (count > bestCount) {
      best = word;
      bestCount = count;
    }
  }
  return best;
}

/**
 * Up to `MAX_FOLLOW_UPS` questions about the answer just given, or fewer —
 * never padded with anything generic (`conversation.md` §3's own edge case).
 * `null` `sourceCount` (abstained) or an unfinished turn produces none; the
 * caller is expected to gate on that already (`AskScreen`), this stays pure
 * either way.
 */
export function followUpSuggestions(turn: {
  status: string;
  sourceCount: number | null;
  citations: readonly CitationCard[];
  answer: string;
}): string[] {
  // No citations at all — nothing to derive a sensible follow-up from
  // (`conversation.md` §3's own example: a single-date answer gets no row,
  // not a term plucked out of thin air). Abstained turns already carry
  // `sourceCount: null` and are covered by that check.
  if (turn.status !== "completed" || turn.sourceCount === null || turn.citations.length === 0) {
    return [];
  }

  const suggestions: string[] = [];
  const seenFilenames = new Set<string>();
  let termUsed = false;
  for (const card of turn.citations) {
    if (suggestions.length >= MAX_FOLLOW_UPS) break;
    if (seenFilenames.has(card.filename)) continue;
    seenFilenames.add(card.filename);
    const heading = card.heading?.trim();
    if (heading !== undefined && heading !== "") {
      suggestions.push(`What else does ${card.filename} say about ${heading}?`);
      continue;
    }
    if (termUsed) continue;
    const term = distinctiveTerm(turn.answer);
    if (term !== null) {
      termUsed = true;
      suggestions.push(`What else mentions ${term}?`);
    }
  }

  // No padding. Three is a maximum, not a quota — the ticket says so twice, in
  // its acceptance criterion ("clearly derived from that answer rather than
  // generic") and again in its own edge case. A fixed string appended to reach
  // the count is derived from nothing: it reads the same under every answer,
  // and a row that is right twice and filler once teaches the reader to skip
  // the row. One good suggestion is worth more than one good suggestion and two
  // that were there to make up the number.
  return suggestions.slice(0, MAX_FOLLOW_UPS);
}

// A local counter of suggestions used (this ticket's own Analytics Events
// line) — in-memory only, never persisted or sent anywhere (C1). Same
// pattern as `citations.ts`'s `cardClickCount`.
let followUpUsedCount = 0;

export function recordFollowUpUsed(): void {
  followUpUsedCount += 1;
}

export function getFollowUpUsedCount(): number {
  return followUpUsedCount;
}
