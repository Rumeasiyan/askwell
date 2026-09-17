/**
 * The memory screen: everything Askwell believes, in one list.
 * `docs/ux/memory.md`, `M3-MEM-FE-083`.
 *
 * Grouping happens on the server (`askwell.memory.get_memory_screen`) —
 * one row per subject or schema position, already sorted inferred-first,
 * with its own supersession history nested in rather than a separate
 * group header. This module trusts that order rather than re-sorting, the
 * same reasoning `lib/clarifications.ts` gives for trusting its own server
 * order.
 */

export interface MemoryHistoryEntry {
  value: string;
  origin: string;
  createdAt: string | null;
}

export interface MemoryRow {
  factKind: "memory" | "schema_note";
  id: string;
  subject: string;
  value: string;
  origin: string;
  confidence: number | null;
  sourceId: string | null;
  sourceName: string | null;
  sourceDeleted: boolean;
  createdAt: string | null;
  usageCount: number;
  history: MemoryHistoryEntry[];
}

export interface MemoryScreenState {
  rows: MemoryRow[];
  /** How many active rows are inferred — the "pending review" count
   * `docs/ux/memory.md` §5 names for the "Inferred pending review" state. */
  inferredCount: number;
}

interface MemoryHistoryEntryWire {
  value: string;
  origin: string;
  created_at: string | null;
}

interface MemoryRowWire {
  fact_kind: "memory" | "schema_note";
  id: string;
  subject: string;
  value: string;
  origin: string;
  confidence: number | null;
  source_id: string | null;
  source_name: string | null;
  source_deleted: boolean;
  created_at: string | null;
  usage_count: number;
  history: MemoryHistoryEntryWire[];
}

interface MemoryScreenWire {
  rows: MemoryRowWire[];
  inferred_count: number;
}

function fromWire(wire: MemoryScreenWire): MemoryScreenState {
  return {
    rows: wire.rows.map((row) => ({
      factKind: row.fact_kind,
      id: row.id,
      subject: row.subject,
      value: row.value,
      origin: row.origin,
      confidence: row.confidence,
      sourceId: row.source_id,
      sourceName: row.source_name,
      sourceDeleted: row.source_deleted,
      createdAt: row.created_at,
      usageCount: row.usage_count,
      history: row.history.map((entry) => ({
        value: entry.value,
        origin: entry.origin,
        createdAt: entry.created_at,
      })),
    })),
    inferredCount: wire.inferred_count,
  };
}

export async function fetchMemoryScreen(signal?: AbortSignal): Promise<MemoryScreenState> {
  const response = await fetch("/memory", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} about memory.`);
  }
  return fromWire((await response.json()) as MemoryScreenWire);
}

/**
 * Confirm: promote an inferred row to user-supplied in one click, no
 * re-processing (`askwell.memory.confirm_fact` — the content did not
 * change, only how much Askwell trusts it). `M3-MEM-FE-084`.
 */
export async function confirmFact(
  factKind: "memory" | "schema_note",
  factId: string,
): Promise<{ alreadyConfirmed: boolean }> {
  const response = await fetch(`/memory/facts/${factKind}/${factId}/confirm`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} confirming that fact.`);
  }
  const body = (await response.json()) as { already_confirmed: boolean };
  return { alreadyConfirmed: body.already_confirmed };
}

/** What manual entry found — either the new fact's id, or the existing
 * active fact for that subject, offered as a correction instead
 * (`docs/ux/memory.md` §4's own edge case). */
export interface ManualAddResult {
  duplicate: boolean;
  factId: string | null;
  existing: { factId: string; subject: string; value: string } | null;
}

interface ManualAddWire {
  duplicate: boolean;
  fact_id?: string;
  existing?: { fact_id: string; subject: string; value: string };
}

export async function addManualFact(subject: string, fact: string): Promise<ManualAddResult> {
  const response = await fetch("/memory/facts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ subject, fact }),
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} adding that fact.`);
  }
  const wire = (await response.json()) as ManualAddWire;
  return {
    duplicate: wire.duplicate,
    factId: wire.fact_id ?? null,
    existing: wire.existing
      ? { factId: wire.existing.fact_id, subject: wire.existing.subject, value: wire.existing.value }
      : null,
  };
}

/** Delete-all-memory. `expectedCount` is the count the confirmation named —
 * checked server-side against what is active right now, so a stale
 * confirmation (memory changed since the dialog opened) is refused rather
 * than deleting a different set than the one the user confirmed. */
export async function deleteAllMemory(expectedCount: number): Promise<{ deletedCount: number }> {
  const response = await fetch("/memory/delete-all", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ expected_count: expectedCount }),
  });
  if (response.status === 409) {
    throw new Error("Memory changed since you confirmed. Review the list again.");
  }
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} deleting memory.`);
  }
  const body = (await response.json()) as { deleted_count: number };
  return { deletedCount: body.deleted_count };
}

/** `docs/ux/memory.md` §2's three filters, applied client-side over the
 * already-fetched list — nothing here needs a round trip. */
export interface MemoryFilters {
  inferredOnly: boolean;
  unusedOnly: boolean;
  sourceId: string | null;
}

export const NO_FILTERS: MemoryFilters = {
  inferredOnly: false,
  unusedOnly: false,
  sourceId: null,
};

export function applyMemoryFilters(rows: readonly MemoryRow[], filters: MemoryFilters): MemoryRow[] {
  return rows.filter((row) => {
    if (filters.inferredOnly && row.origin !== "inferred") return false;
    if (filters.unusedOnly && row.usageCount !== 0) return false;
    if (filters.sourceId !== null && row.sourceId !== filters.sourceId) return false;
    return true;
  });
}

/** The sources a filter dropdown can offer — only rows that carry one,
 * de-duplicated, in first-seen order. */
export function memorySources(rows: readonly MemoryRow[]): { id: string; name: string | null }[] {
  const seen = new Set<string>();
  const sources: { id: string; name: string | null }[] = [];
  for (const row of rows) {
    if (row.sourceId === null || seen.has(row.sourceId)) continue;
    seen.add(row.sourceId);
    sources.push({ id: row.sourceId, name: row.sourceName });
  }
  return sources;
}

/** Delete-all-memory's confirmation copy — names the count and that it
 * cannot be undone, this ticket's own Validation Rule. */
export function deleteAllConfirmationCopy(count: number): string {
  const noun = count === 1 ? "fact" : "facts";
  return `Delete all ${count} ${noun} Askwell has learned? This cannot be undone.`;
}

/** "You told me" for anything the user actually said — clarification
 * answer, manual entry or a correction — "I guessed" for an inference.
 * Same wording `ask-screen.tsx`'s chip popover already uses. */
export function originLabel(origin: string): string {
  return origin === "inferred" ? "I guessed" : "You told me";
}

export function factDateLabel(iso: string | null): string | null {
  if (iso === null) return null;
  return new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

/** "used in 12 answers" / "used in 1 answer" — `docs/ux/memory.md` §3's own
 * "the number that makes this screen worth opening", so it always renders,
 * zero included, never hidden or auto-deleted for being unused. */
export function usageSentence(count: number): string {
  return `used in ${count} answer${count === 1 ? "" : "s"}`;
}

/** `docs/ux/memory.md` §5, "Fact from a deleted source" — only a general
 * fact can say this; a schema note's source is never soft-deleted while the
 * note survives (`askwell.sources.delete_source` removes its notes
 * outright), so `sourceDeleted` is always `false` for a schema note. */
export function deletedSourceNote(row: MemoryRow): string | null {
  if (!row.sourceDeleted) return null;
  return "learned from a source you deleted";
}

/** `docs/ux/memory.md` §5, "Inferred pending review" — a count, not an
 * alarm: guessing is normal and often right. */
export function inferredReviewSentence(count: number): string {
  return `${count} guess${count === 1 ? "" : "es"} to review`;
}

export const EMPTY_MEMORY_COPY =
  "Nothing here yet. Memory fills as Askwell asks about your material and you answer — every fact it holds will say whether you told it or it guessed.";

export const EMPTY_MEMORY_CTA = "Start in the clarification queue";
