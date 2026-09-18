/**
 * Handing one dump file to the API, and what comes back. `M4-DUMP-FE-090`.
 *
 * The same non-negotiable as `sources.ts`: this must never become an upload.
 * What crosses this boundary is a folder and one name under it, and the
 * server opens the user's own file where it is — `docs/data-sources.md` §3's
 * sandbox isolation is what makes running it safe, not keeping a copy of it.
 *
 * One file, not a batch. `docs/ux/add-source.md` §3 is a single sealed
 * database per dump, so there is exactly one thing to name and exactly one
 * detection to render, never a list.
 */

import type { Detection } from "./add-source";

export interface DumpSource {
  id: string;
  name: string | null;
  status: string;
}

export interface DumpAddResult {
  /** What the *server* decided the file is, from its own read. Null only
   * when the path itself could not be resolved — outside every nominated
   * root, missing, unreadable. */
  detection: Detection | null;
  /** Why nothing was queued. Null when a source was created. */
  refusal: string | null;
  /** Null when the dump was refused. */
  source: DumpSource | null;
}

/**
 * Register one dump file for import.
 *
 * `folder` is absolute and `file` is relative to it — the same shape
 * `recordSource` uses for files, for the same reason: a browser hands over a
 * name and a tree, never a location, so the location is asked once and typed.
 */
export async function addDumpSource(folder: string, file: string): Promise<DumpAddResult> {
  const response = await fetch("/sources/dump", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ folder, file }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered with ${response.status}.`);
  }
  return (await response.json()) as DumpAddResult;
}
