/**
 * The clarifications queue: what `/clarifications` reads, `docs/ux/clarifications.md`.
 *
 * Grouping happens on the server (`askwell.review.list_pending`) — this
 * module trusts the order it is given rather than re-sorting, so the screen
 * cannot disagree with the badge about what "newest source first" means.
 */

/**
 * `evidence` is whatever `askwell.clarify` stored to make the question
 * answerable — a value distribution, a row count, a passage — shaped
 * differently per question kind. Formatting it is `M3-REVIEW-FE-073`'s own
 * territory ("item anatomy", Out of Scope here); this only carries it.
 */
export interface ClarificationItem {
  id: string;
  subject: string;
  question: string;
  options: string[] | null;
  evidence: Record<string, unknown> | null;
}

export interface ClarificationGroup {
  source_id: string;
  source_name: string;
  count: number;
  items: ClarificationItem[];
}

export interface ClarificationsState {
  groups: ClarificationGroup[];
  total: number;
}

/** The pending queue, grouped by source, newest source first. */
export async function fetchClarifications(signal?: AbortSignal): Promise<ClarificationsState> {
  const response = await fetch("/clarifications", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about the clarifications queue.`);
  }
  return (await response.json()) as ClarificationsState;
}

/** "4 questions" / "1 question" — the rail badge's own title and the screen's total line. */
export function totalSentence(total: number): string {
  return `${total} question${total === 1 ? "" : "s"}`;
}

/** "3 questions" per group heading — same shape, kept distinct since a group's
 * count and the queue's total answer different questions at the same time. */
export function groupSentence(count: number): string {
  return totalSentence(count);
}

/**
 * `../ux/clarifications.md` §5, "None pending" — teaches the feature rather
 * than reporting an absence. Shown whenever the queue is empty, ingestion
 * running or not: an empty queue mid-ingestion is not a different state, it
 * just has not raised anything yet.
 */
export const NONE_PENDING_COPY =
  "Nothing to clarify. Askwell asks when it finds something it can't work out — an unlabelled column, a date format, two documents that disagree.";
