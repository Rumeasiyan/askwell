"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchClarifications } from "@/lib/clarifications";

/**
 * The rail badge's own number. `docs/ux/clarifications.md` §6: "a badge
 * with a count. No modal on launch, no repeated prompting, no red dot" — so
 * this only ever produces a number, never a reason to interrupt anything.
 *
 * Polled rather than pushed: the queue changes when raising finishes
 * (`M3-RAISE-BE-*`) or an item is answered, neither of which this screen's
 * dependencies expose as a stream yet. `null` while unread, so the rail can
 * render nothing rather than a wrong zero before the first read lands.
 */
export function useClarificationsTotal(intervalMs = 10000): number | null {
  const [total, setTotal] = useState<number | null>(null);

  const read = useCallback(async (): Promise<void> => {
    try {
      const state = await fetchClarifications();
      setTotal(state.total);
    } catch {
      // Left as it stood: a rail badge that blanks itself on a single
      // missed poll is more alarming than a stale number for a few seconds.
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(() => void read(), 0);
    const repeating = setInterval(() => void read(), intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(repeating);
    };
  }, [read, intervalMs]);

  return total;
}
