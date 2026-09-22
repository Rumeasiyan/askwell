"use client";

import { useHoveredKey, type LeaderPair } from "@/components/ask/leader";
import { useLiveTurn } from "@/components/ask/ask-state";
import { isRaised } from "@/lib/pairing";

/**
 * Claim-to-web-card pairs, `useLiveLeaderPairs`'s own shape
 * (`provenance-margin.tsx`) built over the live turn's web citations instead
 * of its document ones. `M6.5-WEB-FE-191`.
 *
 * **Its own file, not `provenance-margin.tsx`.** `web-result.tsx`
 * (`M6.5-WEB-FE-190`) states plainly that it shares no implementation with
 * the margin — "a shared component with a flag is exactly how the
 * distinction erodes" (`design-system.md` §7) — and that applies to the
 * pairing logic behind the two exactly as it does to the card markup, so
 * this stays a third module both can import without either importing the
 * other.
 *
 * **Deliberately never fed to `LeaderCanvas`.** These pairs exist only so a
 * web card and its claim can raise together (`useWebRaised`, `ClaimSpan`);
 * no leader line is ever drawn to the web region (`web-result.tsx`'s own
 * `WebResultCard` — no `useCardRef` call), so nothing here registers into
 * the DOM-node registry a line would be drawn between.
 */
export function useLiveWebPairs(): { pairs: LeaderPair[] } {
  const turn = useLiveTurn();
  if (turn === null) return { pairs: [] };
  const pairs: LeaderPair[] = turn.webCitations.flatMap((result) =>
    result.claimOrdinals.map((ordinal) => ({
      claimKey: `${turn.id}:${ordinal}`,
      cardKey: `web:${turn.id}:${result.url}`,
    })),
  );
  return { pairs };
}

/**
 * Whether `key` (a web claim key or a web card key) should render raised —
 * `useRaised`'s own rule (`provenance-margin.tsx`), against web pairs
 * instead of document ones. A claim ordinal only ever appears in one of the
 * two pairing lists (`ask-screen.tsx`'s `ClaimSpan` ORs both), so a web
 * claim hovered here never raises a margin card and a document claim
 * hovered there never raises a web one — `M6.5-WEB-FE-191`'s own "never
 * across them" acceptance criterion, true by construction rather than by a
 * check either hook makes.
 */
export function useWebRaised(key: string): boolean {
  const hovered = useHoveredKey();
  const { pairs } = useLiveWebPairs();
  return isRaised(key, hovered, pairs);
}
