import type { LeaderPair } from "@/components/ask/leader";

/**
 * Whether `key` (a claim key or a card key) should render raised, given
 * which key is currently hovered/focused and the live turn's claim-to-card
 * pairs. `M1-CITE-FE-044`.
 *
 * Pulled out of the hooks that call it (`leader.tsx`'s `LeaderCanvas`,
 * `provenance-margin.tsx`'s `useRaised`) so the matching rule itself —
 * "raised if this key is the hovered one, or paired with the hovered one" —
 * is checkable without a DOM or a React tree, the same reasoning
 * `segmentClaims` and `applyCitation` already follow for their own pure
 * cores.
 *
 * `key` matching a pair on the *other* side lets one claim raise two cards
 * (the ticket's own "claim with two cards" edge case) and one card raise
 * every claim ordinal it supports, symmetrically.
 */
export function isRaised(key: string, hovered: string | null, pairs: readonly LeaderPair[]): boolean {
  if (hovered === null) return false;
  return pairs.some(
    (pair) =>
      (pair.claimKey === key || pair.cardKey === key) &&
      (pair.claimKey === hovered || pair.cardKey === hovered),
  );
}
