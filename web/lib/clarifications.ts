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
  /** How many of this source's candidates were inferred rather than asked,
   * ranked below the cap (`../ux/clarifications.md` §5's capped state). A
   * group can carry this with `items` empty — a source whose whole raised
   * queue has since been answered or skipped still owes this disclosure
   * (issue 297). */
  capped: number;
}

export interface ClarificationsState {
  groups: ClarificationGroup[];
  total: number;
  /** The configured cap (`askwell.clarify.get_clarification_cap`) — the
   * capped state names it: "Asking about the 5 that matter most." */
  cap: number;
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

/**
 * `../ux/clarifications.md` §5, "Capped" — honest about what was not asked,
 * and routes to where it can be corrected. Shown per source, whether or not
 * that source still has anything pending (issue 297).
 */
export function cappedSentence(cap: number): string {
  return `Asking about the ${cap} that matter most. Askwell inferred the rest — you can review them in Memory.`;
}

/**
 * `current_inference` — what `askwell.clarify.raise_candidates` merges onto
 * every kind of evidence (`M3-RAISE-BE-071`) — is Askwell's own guess, kept
 * if the item is skipped. `null` means there was nothing safe to guess, not
 * a missing field: `clarify.py` never invents one to fill the gap, and this
 * must not either (`../ux/clarifications.md` §3's own edge case — the
 * marker is absent, not a fake guess).
 */
export function currentInference(evidence: Record<string, unknown> | null): string | null {
  if (evidence === null) return null;
  const value = evidence.current_inference;
  return typeof value === "string" ? value : null;
}

interface EvidenceSample {
  document: string;
  page: number | null;
  text: string;
}

interface EvidenceValue {
  value: string;
  count: number;
}

interface EvidenceContradictionPassage {
  document: string;
  value: string;
  page: number | null;
  date: string | null;
  text: string;
}

export type EvidenceDisplay =
  | { kind: "distribution"; rowCount: number; values: EvidenceValue[]; remainderCount: number }
  | { kind: "passage"; samples: EvidenceSample[] }
  | { kind: "poor_scan"; pages: number[]; totalPages: number; extracted: EvidenceSample[] }
  | { kind: "contradiction"; passages: EvidenceContradictionPassage[] }
  | { kind: "unavailable"; reason: string };

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asSample(value: unknown): EvidenceSample {
  const record = (value ?? {}) as Record<string, unknown>;
  return { document: asString(record.document), page: asNullableNumber(record.page), text: asString(record.text) };
}

function asSampleArray(value: unknown): EvidenceSample[] {
  return Array.isArray(value) ? value.map(asSample) : [];
}

/**
 * Turns one of `askwell.clarify`'s evidence shapes (`EVIDENCE_KIND_*`) into
 * a display union the screen can render without knowing the wire shape.
 * `null` for evidence too sparse to be worth a block at all — the caller
 * falls back to "no evidence available" (`../ux/clarifications.md` §3's
 * named edge case), same as a genuinely missing `evidence` column.
 */
export function evidenceDisplay(evidence: Record<string, unknown> | null): EvidenceDisplay | null {
  if (evidence === null) return null;
  switch (evidence.kind) {
    case "column_distribution": {
      const values = Array.isArray(evidence.values)
        ? evidence.values.map((entry) => {
            const record = (entry ?? {}) as Record<string, unknown>;
            return { value: asString(record.value), count: asNumber(record.count) };
          })
        : [];
      return {
        kind: "distribution",
        rowCount: asNumber(evidence.row_count),
        values,
        remainderCount: asNumber(evidence.remainder_count),
      };
    }
    case "passage":
      return { kind: "passage", samples: asSampleArray(evidence.samples) };
    case "poor_scan":
      return {
        kind: "poor_scan",
        pages: Array.isArray(evidence.pages) ? evidence.pages.filter((p): p is number => typeof p === "number") : [],
        totalPages: asNumber(evidence.total_pages),
        extracted: asSampleArray(evidence.extracted_text),
      };
    case "contradiction": {
      const passages = Array.isArray(evidence.passages)
        ? evidence.passages.map((entry) => {
            const record = (entry ?? {}) as Record<string, unknown>;
            return {
              document: asString(record.document),
              value: asString(record.value),
              page: asNullableNumber(record.page),
              date: asNullableString(record.date),
              text: asString(record.text),
            };
          })
        : [];
      return { kind: "contradiction", passages };
    }
    case "unavailable":
      return { kind: "unavailable", reason: asString(evidence.reason) };
    default:
      return null;
  }
}

/** "40,112 rows" — the row count the value distribution sits beside
 * (`../ux/clarifications.md` §3's worked example). */
export function rowCountLabel(rowCount: number): string {
  return `${rowCount.toLocaleString("en-US")} row${rowCount === 1 ? "" : "s"}`;
}

// --- answering, skipping, dismissing and undoing ----------------------------
// `M3-REVIEW-FE-074`. Backend business logic (`askwell.review`) already
// enforces the invariants — one memory row per answer, refuse a second
// answer, undo only while the memory fact is still the active one; this only
// carries the calls and the shapes their responses come back in.

/** What `askwell.review.answer_clarification` names as affected material —
 * never a generic toast (`../ux/clarifications.md` §4, "After saving").
 * `kind` (issue 300) is "table" or "document" — every trigger built so far
 * is document-shaped, so this reads "document" today. */
export interface Reprocessing {
  count: number;
  label: string;
  kind: "table" | "document";
}

export interface AnswerResult {
  id: string;
  memoryId: string;
  reprocessing: Reprocessing;
  /** `null` when nothing needed re-processing. Feeds `ReapplyProgress`
   * (`../ux/clarifications.md` §5, "Answered, re-processing"). */
  reapplyJobId: string | null;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit =
    body !== undefined
      ? {
          method: "POST",
          headers: { accept: "application/json", "content-type": "application/json" },
          body: JSON.stringify(body),
        }
      : { method: "POST", headers: { accept: "application/json" } };
  const response = await fetch(path, init);
  const payload = (await response.json().catch(() => null)) as
    | { error?: string; [key: string]: unknown }
    | null;
  if (!response.ok) {
    throw new Error(payload?.error ?? `Askwell answered ${response.status}.`);
  }
  return payload as T;
}

/** Writes the fact and returns what is being re-read. `../ux/clarifications.md`
 * §4's own edge case — a blank answer is a skip, not an empty fact — is the
 * caller's decision (`skipClarification`), not this function's: it always
 * writes what it is given. */
export async function answerClarification(id: string, answer: string): Promise<AnswerResult> {
  const raw = await postJson<{
    memory_id: string;
    reprocessing: Reprocessing;
    reapply_job_id: string | null;
  }>(`/clarifications/${id}/answer`, { answer });
  return {
    id,
    memoryId: raw.memory_id,
    reprocessing: raw.reprocessing,
    reapplyJobId: raw.reapply_job_id,
  };
}

/** Keeps the inference as low-confidence; never raised again for this source. */
export async function skipClarification(id: string): Promise<void> {
  await postJson(`/clarifications/${id}/skip`);
}

/** Skip-all for one source: every pending item in the group, recorded one at
 * a time server-side so the dismissal rate stays countable. Returns the
 * dismissed ids so the caller can remove exactly those from the list. */
export async function dismissGroup(sourceId: string): Promise<string[]> {
  const result = await postJson<{ dismissed: string[] }>(
    `/sources/${sourceId}/clarifications/dismiss`,
  );
  return result.dismissed;
}

/** Reverses a save within its window. Refused once the fact has been
 * corrected or otherwise superseded (`askwell.review.CannotUndo`). */
export async function undoAnswer(id: string, memoryId: string): Promise<void> {
  await postJson(`/clarifications/${id}/undo`, { memory_id: memoryId });
}

/** "Saved. Re-reading 3 tables that use this column." — the confirmation
 * `../ux/clarifications.md` §4 names, never a generic toast. */
export function savedConfirmation(reprocessing: Reprocessing): string {
  return `Saved. Re-reading ${reprocessing.label}.`;
}

/** §4's own edge case: an answer of only whitespace is treated as a skip,
 * and the caller states that plainly rather than writing an empty fact. */
export function isBlankAnswer(answer: string): boolean {
  return answer.trim().length === 0;
}

export const SKIPPED_FOR_EMPTY_ANSWER_COPY = "No answer given — skipped.";

/** How many seconds an undo stays available after a save (`../ux/clarifications.md`
 * §4: "Available for 10s after saving"). */
export const UNDO_WINDOW_SECONDS = 10;

// --- re-processing progress ("Answered, re-processing", `../ux/clarifications.md` §5) --

export interface ReapplyItem {
  kind: string;
  target_id: string;
  label: string;
  status: string;
  error: string | null;
}

export interface ReapplyJob {
  id: string;
  subject: string;
  status: string;
  total_items: number;
  done_items: number;
  failed_items: number;
  items: ReapplyItem[];
}

/** Per-item progress for one answer's re-processing. Polled, not pushed —
 * `askwell.reapply` has no SSE stream of its own, unlike ingestion. */
export async function fetchReapplyJob(jobId: string): Promise<ReapplyJob> {
  const response = await fetch(`/reapply-jobs/${jobId}`, {
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about that re-processing job.`);
  }
  return (await response.json()) as ReapplyJob;
}

/** The edge case a stuck progress indicator must not be: a failure surfaced
 * with its reason and a retry (issue 299). */
export async function retryReapplyJob(jobId: string): Promise<number> {
  const result = await postJson<{ requeued: number }>(`/reapply-jobs/${jobId}/retry`);
  return result.requeued;
}

/** The first failed item's own reason — issue 299: a generic "stopped, not
 * stuck" line with no reason is exactly the stuck-indicator failure the
 * ticket's Edge Case rules out. */
export function reapplyFailureReason(job: ReapplyJob): string | null {
  return job.items.find((item) => item.status === "failed")?.error ?? null;
}

// --- the completion state ("5 answered. 2 tables and 14 documents re-read.") --
// `../ux/clarifications.md` §5. Session-local — this is a summary of what
// just happened in this browser tab, not a persisted record; the persisted
// facts are already in `memory` and `audit_decisions`.

export interface SessionTally {
  answered: number;
  skipped: number;
  tablesReRead: number;
  documentsReRead: number;
}

export function emptySessionTally(): SessionTally {
  return { answered: 0, skipped: 0, tablesReRead: 0, documentsReRead: 0 };
}

export function tallyAnswer(tally: SessionTally, reprocessing: Reprocessing): SessionTally {
  return {
    ...tally,
    answered: tally.answered + 1,
    tablesReRead: tally.tablesReRead + (reprocessing.kind === "table" ? reprocessing.count : 0),
    documentsReRead:
      tally.documentsReRead + (reprocessing.kind === "document" ? reprocessing.count : 0),
  };
}

export function tallySkip(tally: SessionTally, count = 1): SessionTally {
  return { ...tally, skipped: tally.skipped + count };
}

export function hasSessionActivity(tally: SessionTally): boolean {
  return tally.answered > 0 || tally.skipped > 0;
}

/**
 * `../ux/clarifications.md` §5's own worked example: "5 answered. 2 tables
 * and 14 documents re-read." Honest, not congratulatory, when nothing was
 * actually answered (the Edge Case: "all questions skipped rather than
 * answered").
 */
export function completionSentence(tally: SessionTally): string {
  if (tally.answered === 0) {
    const total = tally.skipped;
    return `${total} skipped. Nothing re-read.`;
  }

  const parts: string[] = [];
  if (tally.tablesReRead > 0) {
    parts.push(`${tally.tablesReRead} table${tally.tablesReRead === 1 ? "" : "s"}`);
  }
  if (tally.documentsReRead > 0) {
    parts.push(`${tally.documentsReRead} document${tally.documentsReRead === 1 ? "" : "s"}`);
  }
  // Always starts with a digit (a count), so no capitalisation step is needed.
  const material = parts.length > 0 ? `${parts.join(" and ")} re-read.` : "Nothing re-read.";
  const skippedNote = tally.skipped > 0 ? `, ${tally.skipped} skipped` : "";

  return `${tally.answered} answered${skippedNote}. ${material}`;
}

// A local counter of answered/skipped/dismissed (this ticket's own Analytics
// Events line) — in-memory only, never persisted or transmitted (C1). Module
// state, same shape as `citations.ts`'s `cardClickCount`.
let answeredCount = 0;
let skippedCount = 0;
let dismissedCount = 0;

export function recordAnswered(): void {
  answeredCount += 1;
}

export function recordSkipped(): void {
  skippedCount += 1;
}

export function recordDismissed(count: number): void {
  dismissedCount += count;
}

export function getClarificationCounters(): {
  answered: number;
  skipped: number;
  dismissed: number;
} {
  return { answered: answeredCount, skipped: skippedCount, dismissed: dismissedCount };
}

// --- picking up questions raised while the screen is open (issue 272) ------

/**
 * Adds items the fetch just returned that this state does not already have
 * — by id, never by replacing or reordering anything already present. A
 * blind replace would reset an uncontrolled answer input mid-keystroke or
 * clobber a card mid-undo-countdown, which is exactly the "disrupting an
 * in-progress answer" `M3-REVIEW-FE-072`'s own Edge Case rules out. Returns
 * the same reference when nothing new arrived, so a caller using this in
 * `setState` does not re-render on every poll.
 */
export function mergeIncoming(
  current: ClarificationsState,
  incoming: ClarificationsState,
): ClarificationsState {
  const knownItemIds = new Set(
    current.groups.flatMap((group) => group.items.map((item) => item.id)),
  );
  const knownGroupIds = new Set(current.groups.map((group) => group.source_id));
  let added = 0;

  const groups = current.groups.map((group) => {
    const match = incoming.groups.find((candidate) => candidate.source_id === group.source_id);
    if (!match) return group;
    const newItems = match.items.filter((item) => !knownItemIds.has(item.id));
    if (newItems.length === 0) return group;
    added += newItems.length;
    return { ...group, count: group.count + newItems.length, items: [...group.items, ...newItems] };
  });

  const newGroups = incoming.groups.filter((group) => !knownGroupIds.has(group.source_id));
  added += newGroups.reduce((sum, group) => sum + group.items.length, 0);

  if (added === 0) return current;
  return { groups: [...newGroups, ...groups], total: current.total + added, cap: incoming.cap };
}
