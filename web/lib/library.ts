/**
 * The library, as pure functions over the same `IngestState` the add screen
 * already watches. `docs/ux/library.md`.
 *
 * Nothing here fetches. `LibraryScreen` owns the `subscribeIngest` connection
 * — the shared one `web/lib/ingest.ts` already refcounts — and everything
 * below is what turns that one payload into rows, filters and reasons.
 */

import type { FailedDocument, FlaggedDocument, SourceCoverage } from "@/lib/ingest";

/** `docs/ux/library.md` §2: the label a row's kind column shows. Only `file`
 * is reachable before `M4`; the rest are named so a filter built against the
 * schema's own enum does not need revisiting when they arrive. */
export const KIND_LABELS: Record<string, string> = {
  file: "Files",
  csv: "Spreadsheet",
  dump: "Database dump",
  connection: "Connection",
};

/** `docs/ux/library.md` §2's five words — `deleted` included since
 * `M2-DELETE-FE-062`: a deleted source stays listed, greyed, filterable out
 * (§4/§5), rather than dropped the moment it is tombstoned. */
export const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  indexing: "Indexing",
  ready: "Ready",
  attention: "Needs attention",
  deleted: "Deleted",
};

export interface LibraryFilters {
  kind: string | "all";
  status: string | "all";
  onlyOpenClarifications: boolean;
  /** Deleted rows are hidden by default — "filtered out" is the resting
   * state `library.md` §4 describes, not merely an option to reach it. */
  showDeleted: boolean;
}

export const DEFAULT_FILTERS: LibraryFilters = {
  kind: "all",
  status: "all",
  onlyOpenClarifications: false,
  showDeleted: false,
};

export function matchesFilters(source: SourceCoverage, filters: LibraryFilters): boolean {
  if (source.status === "deleted" && !filters.showDeleted) {
    return false;
  }
  if (filters.kind !== "all" && source.kind !== filters.kind) {
    return false;
  }
  if (filters.status !== "all" && source.status !== filters.status) {
    return false;
  }
  if (filters.onlyOpenClarifications && source.open_clarifications === 0) {
    return false;
  }
  return true;
}

/** "Deleted 28 Aug 2026" — the library row's own date, `deletedSentence`
 * rather than reusing `addedSentence` under a misleading name, even though
 * the formatting is identical: the two dates answer different questions and
 * a shared name would blur that at every call site. */
export function deletedSentence(deletedAt: string): string {
  return `Deleted ${addedSentence(deletedAt)}`;
}

/** "Added 28 Aug 2026" — a plain date, not a relative one: someone scanning
 * twenty rows needs a stable order to eyeball, and "3 days ago" changes every
 * time they open the tab. */
export function addedSentence(addedAt: string): string {
  const date = new Date(addedAt);
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export interface AttentionCause {
  documentId: string;
  filename: string;
  sentence: string;
  /** A failure can be retried; a flagged scan is read-only information —
   * `M1-EXTRACT-ING-029`'s own distinction, carried into the fix action. */
  fixable: boolean;
}

/**
 * The specific reasons one source needs attention, named per document.
 *
 * The ticket's own acceptance criterion: a row does not say "something is
 * wrong", it expands to name *which* document and *why*. Both failures and
 * poor scans can be true of the same source at once, so this concatenates
 * rather than picking one.
 */
export function attentionCauses(
  sourceId: string,
  failures: readonly FailedDocument[],
  flagged: readonly FlaggedDocument[],
): AttentionCause[] {
  const own = failures
    .filter((failure) => failure.source_id === sourceId)
    .map((failure) => ({
      documentId: failure.document_id,
      filename: failure.filename,
      sentence: failureSentenceShort(failure),
      fixable: true,
    }));
  const poor = flagged
    .filter((document) => document.source_id === sourceId)
    .map((document) => ({
      documentId: document.document_id,
      filename: document.filename,
      sentence: flaggedSentenceShort(document),
      fixable: false,
    }));
  return [...own, ...poor];
}

function failureSentenceShort(failure: FailedDocument): string {
  const where = failure.stage === null ? "" : ` while ${failure.stage}`;
  const why = failure.error ?? "Askwell did not record a reason, which is itself a bug.";
  return `Could not be read${where}: ${why}`;
}

function flaggedSentenceShort(flagged: FlaggedDocument): string {
  const percent = Math.round(flagged.confidence * 100);
  const pages =
    flagged.poor_pages.length > 0
      ? ` — page${flagged.poor_pages.length > 1 ? "s" : ""} ${flagged.poor_pages.join(", ")} read worst`
      : "";
  return `Scanned poorly (about ${percent}% confidence)${pages}.`;
}
