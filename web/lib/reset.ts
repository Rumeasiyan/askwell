/**
 * Reset Askwell — `GET /reset/preview`, `POST /reset` (`askwell.reset`,
 * `docs/ux/settings.md` §6, `M7-DATA-FE-160`).
 *
 * No job to poll. A reset is one database transaction plus a file sweep,
 * and it resolves once it is done. Ingestion running at the time is not
 * refused: reset's table locks wait for its in-flight write and leave
 * nothing for it to continue with (`askwell.reset`'s module docstring).
 */

export interface ResetFiles {
  traces: number;
  exports: number;
  backups: number;
}

export interface ResetPreview {
  counts: Record<string, number>;
  total: number;
  files: ResetFiles;
  original_files_statement: string;
}

export interface ResetResult {
  counts: Record<string, number>;
  total: number;
  files_removed: ResetFiles;
  files_not_removed: string[];
  sandbox_databases_dropped: string[] | null;
  original_files_statement: string;
}

export async function fetchResetPreview(signal?: AbortSignal): Promise<ResetPreview> {
  const response = await fetch("/reset/preview", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} reading what a reset would remove.`);
  }
  return (await response.json()) as ResetPreview;
}

export async function performReset(): Promise<ResetResult> {
  const response = await fetch("/reset", { method: "POST", headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(
      `Askwell answered ${response.status} and did not reset. Nothing was removed.`,
    );
  }
  return (await response.json()) as ResetResult;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** What is destroyed, in the user's own nouns — never table names. */
export function resetDestroys(preview: ResetPreview): string[] {
  const c = (table: string): number => preview.counts[table] ?? 0;
  const lines = [
    `${plural(c("sources"), "source", "sources")} and everything indexed from them`,
    `${plural(c("roots"), "registered folder", "registered folders")}, which Askwell forgets`,
    `${plural(c("memory") + c("schema_notes"), "memory fact", "memory facts")} and ${plural(
      c("clarifications"),
      "clarification",
      "clarifications",
    )}`,
    `${plural(c("conversations"), "conversation", "conversations")}`,
    `${plural(
      c("audit_decisions") + c("audit_interactions"),
      "log record",
      "log records",
    )}, including the record of earlier exports and deletions`,
    "your settings, including any passphrase",
  ];
  const files = preview.files.traces + preview.files.exports + preview.files.backups;
  if (files > 0) {
    lines.push(
      `${plural(files, "file", "files")} Askwell wrote: answer traces, and exports or backups ` +
        "still held inside Askwell. Anything you already downloaded is yours and stays",
    );
  }
  return lines;
}

/** The log destroys itself here, which the confirmation says (the ticket's
 * Audit Requirement) rather than leave the user to find out. */
export const RESET_LOG_STATEMENT =
  "The log that records this reset is destroyed with everything else. One record survives: " +
  "that a reset happened and how much it removed, as the first entry of a new log.";

export const RESET_IRREVERSIBLE = "This cannot be undone. Export everything first if you may want any of it.";

export function resetOutcome(result: ResetResult): string[] {
  const lines = [`Reset. ${plural(result.total, "record", "records")} removed.`];
  if (result.files_not_removed.length > 0) {
    lines.push(
      `${plural(result.files_not_removed.length, "file", "files")} could not be removed and ` +
        `still ${result.files_not_removed.length === 1 ? "exists" : "exist"}: ` +
        result.files_not_removed.join(", "),
    );
  }
  if (result.sandbox_databases_dropped === null) {
    lines.push(
      "Imported database copies could not be reached just now. They are removed the next " +
        "time Askwell starts.",
    );
  }
  return lines;
}
