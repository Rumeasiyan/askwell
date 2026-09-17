"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { fetchClarifications, totalSentence } from "@/lib/clarifications";
import { subscribeIngest, type IngestState } from "@/lib/ingest";

/**
 * The second entry point `docs/ux/clarifications.md` names: "a prompt after
 * ingestion finishes" (§"Entry points"; `M3-REVIEW-FE-072`'s own Scope).
 *
 * Not a modal — a line in the same banner slot `StatusBanner` uses, shown
 * once per finish and gone the moment the user acts or leaves. §6 rules out
 * "repeated prompting": this watches for the queue going idle *while
 * mounted*, so a page load onto an already-idle queue with old pending
 * questions never triggers it — that is what the rail badge is for.
 */
export function ClarificationsPrompt() {
  const pathname = usePathname();
  const [pending, setPending] = useState<number | null>(null);
  const wasActive = useRef(false);

  useEffect(() => {
    const stop = subscribeIngest((state: IngestState) => {
      const active = state.counts.queued > 0 || state.counts.running > 0;
      if (wasActive.current && !active) {
        fetchClarifications()
          .then((clarifications) => {
            if (clarifications.total > 0) setPending(clarifications.total);
          })
          .catch(() => {
            // No prompt is the safe failure — the rail badge still has it.
          });
      }
      wasActive.current = active;
    });
    return stop;
  }, []);

  // Derived, not an effect: clearing state from a pathname change is exactly
  // the synchronous setState-in-effect React's own rules warn against, and
  // "already on the screen this points at" has no need to be stored state.
  if (pending === null || pathname.startsWith("/clarifications")) return null;

  return (
    <div
      role="status"
      className="ask-carries-meaning flex items-center justify-between px-4 py-3"
      style={{
        background: "var(--surface)",
        borderLeftColor: "var(--provenance)",
        borderRadius: "var(--radius)",
      }}
    >
      <p style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
        {totalSentence(pending)} came up while adding sources.
      </p>
      <div className="flex items-center gap-3">
        <Link href="/clarifications/" className="ask-navigates" onClick={() => setPending(null)}>
          Review
        </Link>
        <button
          type="button"
          onClick={() => setPending(null)}
          className="ask-navigates"
          style={{ color: "var(--muted)" }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
