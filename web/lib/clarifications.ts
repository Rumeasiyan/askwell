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
