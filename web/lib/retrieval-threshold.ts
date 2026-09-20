/**
 * The retrieval threshold, read and changed at runtime — `GET`/`POST
 * /settings/retrieval-threshold` (`askwell.retrieve.register_retrieval_
 * threshold`, `M5-TRACE-FE-122`).
 *
 * One backend endpoint, reached from two surfaces (the abstention trace's
 * near-miss control, `docs/ux/trace.md` §4, and the settings screen,
 * `docs/ux/settings.md` §2) so the two cannot drift apart — a change made
 * from either place is the same change, recorded once in the decisions log.
 */

export async function fetchRetrievalThreshold(signal?: AbortSignal): Promise<number> {
  const response = await fetch("/settings/retrieval-threshold", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about the retrieval threshold.`);
  }
  const body = (await response.json()) as { threshold: number };
  return body.threshold;
}

/** The only way the threshold changes from the browser — always a decisions
 * record on the server (`set_retrieval_threshold`), never a side effect of
 * anything else (this ticket's own Validation Rule). Rejects the same
 * `[0, 1]` range the server does, surfaced as a thrown error rather than a
 * silently clamped value. */
export async function setRetrievalThreshold(value: number, signal?: AbortSignal): Promise<number> {
  const response = await fetch("/settings/retrieval-threshold", {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ threshold: value }),
  });
  if (!response.ok) {
    throw new Error(`Askwell could not change the retrieval threshold (${response.status}).`);
  }
  const body = (await response.json()) as { threshold: number };
  return body.threshold;
}

/** The closest passage an abstained turn found, next to the threshold it
 * missed — only meaningful when the trace's own `abstain` step says
 * `below_threshold`: `empty_corpus`/`source_indexing` have no real "closest"
 * to name, and offering the control there would misleadingly suggest
 * loosening the threshold could have helped (the ticket's own Edge Case).
 * `null` for every other case, including a normal, non-abstained turn. */
export interface NearMiss {
  score: number;
  threshold: number;
}

export function nearMiss(trace: {
  steps: { kind: string; [key: string]: unknown }[];
}): NearMiss | null {
  const abstainStep = trace.steps.find((step) => step.kind === "abstain");
  if (abstainStep === undefined || abstainStep.reason_code !== "below_threshold") return null;

  const retrieveStep = trace.steps.find((step) => step.kind === "retrieve");
  if (retrieveStep === undefined) return null;
  const hits = Array.isArray(retrieveStep.hits)
    ? (retrieveStep.hits as { score: number }[])
    : [];
  const threshold = typeof retrieveStep.threshold === "number" ? retrieveStep.threshold : null;
  if (hits.length === 0 || threshold === null) return null;

  const closest = Math.max(...hits.map((hit) => hit.score));
  return { score: closest, threshold };
}

// A local counter of threshold changes (this ticket's own Analytics Events
// line) — in-memory only, never persisted or transmitted (C1), same shape as
// `lib/trace.ts`'s own counters.
let thresholdChangesCount = 0;

export function recordThresholdChanged(): void {
  thresholdChangesCount += 1;
}

export function getThresholdChangesCount(): number {
  return thresholdChangesCount;
}
