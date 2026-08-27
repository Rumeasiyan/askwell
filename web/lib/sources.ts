/**
 * Handing a located batch to the API, and what comes back.
 *
 * The one thing this module must never become is an upload. Askwell indexes in
 * place: what crosses this boundary is a folder and a list of names under it,
 * and the server opens the user's own files where they are. A `FormData` body
 * here would be a different product — one that copies 40 GB of case files
 * somewhere, which is the thing the whole add flow promises it does not do.
 *
 * The server re-decides what every file is from its own read of the bytes. The
 * detection in `add-source.ts` is what the user watches while a drop is being
 * read; it is a courtesy, not a boundary, and where the two disagree the
 * outcomes here are the ones that are true of what was stored.
 */

/** What happened to one file. Four answers, and none of them is silence. */
export type Outcome = "added" | "duplicate" | "later" | "refused";

/** The document a duplicate turned out to be, with where it lives. */
export interface Existing {
  document_id: string;
  path: string;
  filename: string;
  source_id: string;
}

export interface FileOutcome {
  relative_path: string;
  path: string;
  filename: string;
  outcome: Outcome;
  /** What the *server* decided the file is, from its own read. */
  format: string | null;
  mime: string | null;
  mismatch: string | null;
  arrives: string | null;
  document_id: string | null;
  existing: Existing | null;
  sha256: string | null;
  size: number | null;
  reason: string | null;
}

export interface RecordedSource {
  id: string;
  name: string | null;
  root_path: string | null;
  status: string | null;
  created: boolean;
}

export interface Recorded {
  /** Null when nothing was added — every file was a duplicate, later or refused. */
  source: RecordedSource | null;
  added: number;
  duplicates: number;
  later: number;
  refused: number;
  files: FileOutcome[];
}

/**
 * Record a batch: one source, one document row per file Askwell kept.
 *
 * `folder` is absolute and `files` are relative to it, which is the shape a
 * browser can actually produce — it hands over names and a tree, never a
 * location, so the location is asked once per drop and typed.
 * `M7-TAURI-FE-182` replaces that question with the platform's own directory
 * dialog and sends the same two fields.
 */
export async function recordSource(folder: string, files: string[]): Promise<Recorded> {
  const response = await fetch("/sources", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ folder, files }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered with ${response.status}.`);
  }
  return (await response.json()) as Recorded;
}

export function withOutcome(recorded: Recorded, outcome: Outcome): FileOutcome[] {
  return recorded.files.filter((file) => file.outcome === outcome);
}

/**
 * One line about a file Askwell already had.
 *
 * Both paths, always. "Already present" without saying *where* leaves somebody
 * with three copies of a contract unsure which one Askwell is actually reading,
 * and that uncertainty is the thing duplicate detection exists to remove.
 */
export function duplicateLine(file: FileOutcome): string {
  const existing = file.existing;
  if (existing === null) return `${file.relative_path} — already present.`;
  return `${file.relative_path} — the same contents are already indexed, from ${existing.path}. It was not added a second time.`;
}
