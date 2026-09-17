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
