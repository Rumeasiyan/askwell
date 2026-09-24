/**
 * Export everything, and export the log alone — `docs/ux/settings.md` §6,
 * `M7-DATA-FE-160`. Both are one background job (`askwell.log_export`,
 * `POST /log-export`); `scope` says whether the zip holds only the two
 * audit logs and their verifier, or those plus sources, memory,
 * conversations and traces.
 *
 * With a passphrase set the export is plaintext, outside the library's
 * protection. The screen warns before anything is written (this ticket's
 * Edge Case), and the backend refuses independently until the caller says
 * the warning was read — `acknowledged` is that answer, never defaulted.
 */

export type ExportScope = "log" | "everything";

export interface ExportJob {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  scope: ExportScope;
  decisions_total: number;
  decisions_done: number;
  interactions_total: number;
  interactions_done: number;
  file_bytes: number | null;
  error: string | null;
}

export async function startExport(scope: ExportScope, acknowledged: boolean): Promise<ExportJob> {
  const response = await fetch("/log-export", {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ scope, acknowledged_decrypted_export: acknowledged }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? `Askwell answered ${response.status} starting the export.`);
  }
  return (await response.json()) as ExportJob;
}

export async function fetchExportJob(id: string, signal?: AbortSignal): Promise<ExportJob> {
  const response = await fetch(`/log-export/${id}`, {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} reading the export.`);
  }
  return (await response.json()) as ExportJob;
}

export function exportDownloadUrl(id: string): string {
  return `/log-export/${id}/download`;
}

export function exportFinished(job: ExportJob): boolean {
  return job.status === "done" || job.status === "failed";
}

/** What the export holds, said before it starts. */
export const EXPORT_CONTENTS: Record<ExportScope, string> = {
  everything:
    "Your sources list, memory, clarifications, conversations, and all three logs: both " +
    "audit logs with their hash chain, a verifier that checks it, and the recent answer " +
    "traces. Plain text: JSON Lines files and a README explaining each one. Your own files " +
    "are not copied.",
  log:
    "Both audit logs with their hash chain, and a verifier that checks it without Askwell, " +
    "for showing someone else what was asked.",
};

/** Shown before writing when a passphrase is set. The export is only useful
 * because it is readable, so it cannot also be protected. */
export const UNPROTECTED_EXPORT_WARNING =
  "A passphrase protects your library, but this export will not be protected. It is written " +
  "as plain text, so anyone who has the file can read it. Keep it somewhere you trust.";

/** Progress in the log's own units — the only part with a known total. */
export function exportProgress(job: ExportJob): string {
  if (job.status === "queued") return "Waiting to start…";
  const done = job.decisions_done + job.interactions_done;
  const total = job.decisions_total + job.interactions_total;
  if (job.scope === "everything" && total > 0 && done >= total) {
    return `${done} of ${total} log records written. Writing sources, memory and conversations…`;
  }
  return `${done} of ${total} log records written…`;
}
