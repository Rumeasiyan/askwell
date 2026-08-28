/**
 * What the queue is doing, and how the screen says it honestly.
 *
 * Ingestion is not something a page owns. It runs on the worker, it survives
 * the tab being closed, and this module's whole job is to *watch* it — so
 * everything here is read-only and nothing here can cancel anything. That is
 * the point of the ticket: somebody adds five hundred papers and goes to make
 * tea, and the import must not be holding their browser hostage.
 *
 * Two rules shape the sentences below.
 *
 * **Never a progress bar that has not started.** `docs/states-and-edge-cases.md`
 * §3 is explicit: files queued with nothing indexed yet get an honest sentence
 * naming what has to arrive first, not a spinner. The API says which stage is
 * missing, and `queueSentence` renders that rather than inventing motion.
 *
 * **Never an estimate nobody measured.** On a first import there is no
 * throughput history, so the API answers `null` with its reason and the screen
 * repeats the reason. A made-up "about 5 minutes" is worse than no figure: it
 * is what somebody plans their afternoon around.
 */

export interface IngestCounts {
  queued: number;
  running: number;
  parked: number;
  failed: number;
  done: number;
}

export interface IngestEstimate {
  /** Null when nothing has finished on this machine yet. Then `basis` says so. */
  seconds: number | null;
  basis: string;
}

export interface ActiveDocument {
  document_id: string;
  filename: string;
  source_id: string;
  stage: string | null;
  attempt: number;
  bytes_done: number | null;
  bytes_total: number | null;
  /** Progress *within* the file, so one enormous scan does not look hung. */
  fraction: number | null;
}

export interface QueuedDocument {
  document_id: string;
  filename: string;
  /** 1 is next. What "queued behind a backlog" needs to stop being a spinner. */
  position: number;
}

export interface FailedDocument {
  document_id: string;
  filename: string;
  source_id: string;
  stage: string | null;
  error: string | null;
  attempts: number;
}

/**
 * A document whose OCR read poorly. `M1-EXTRACT-ING-029`.
 *
 * Never a failure — the document indexed, and stays listed as such. This is
 * what lets the library say *why* an answer about it might be thin, which is
 * the whole point of measuring confidence in the first place.
 */
export interface FlaggedDocument {
  document_id: string;
  filename: string;
  source_id: string;
  /** 0–1, Tesseract's own mean word confidence for the pages it OCR'd. */
  confidence: number;
  /** Specific pages below the threshold — named, not just counted. */
  poor_pages: number[];
}

export interface SourceCoverage {
  id: string;
  name: string | null;
  status: string;
  /** A folder, spreadsheet, dump or live connection. `M4` adds kinds beyond `file`. */
  kind: string;
  added_at: string;
  /** The specific needs-attention cause, in a sentence. `null` when nothing is wrong. */
  last_error: string | null;
  /** When this source was deleted, `null` otherwise. `status === "deleted"`
   * is the filterable fact; this is the date the library's own deleted row
   * shows beside it (`docs/ux/library.md` §5). */
  deleted_at: string | null;
  /** Always 0 until `M3` builds the clarification loop — a stub, not a lie. */
  open_clarifications: number;
  total: number;
  ready: number;
  failed: number;
  running: number;
  outstanding: number;
  /** Read poorly by OCR. Never subtracted from `ready` — these are askable too. */
  flagged: number;
  /** One indexed file is enough to ask. Waiting for all five hundred is the bug. */
  askable: boolean;
  fraction: number;
}

export interface AwaitingStage {
  stage: string;
  ticket: string;
  documents: number;
}

export interface PipelineStage {
  name: string;
  ticket: string;
  built: boolean;
}

export interface IngestState {
  counts: IngestCounts;
  documents_ingested: number;
  documents_failed: number;
  documents_flagged: number;
  queue_length: number;
  concurrency: number;
  estimate: IngestEstimate;
  active: ActiveDocument[];
  next: QueuedDocument[];
  failures: FailedDocument[];
  flagged: FlaggedDocument[];
  sources: SourceCoverage[];
  awaiting: AwaitingStage | null;
  stages: PipelineStage[];
}

/** The queue as it stands right now. What a page loading needs before changes. */
export async function fetchIngest(signal?: AbortSignal): Promise<IngestState> {
  const response = await fetch("/ingest", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} when asked about the queue.`);
  }
  return (await response.json()) as IngestState;
}

/**
 * Watch the queue for as long as this page is open.
 *
 * Returns the unsubscribe. Calling it stops the *watching* and nothing else —
 * the ingestion is on the worker and does not notice, which is exactly what
 * "navigating away does not cancel it" means.
 *
 * Server-sent events rather than a socket: this is one direction. A
 * bidirectional channel arrives with voice and would buy nothing here.
 */
type StateListener = (state: IngestState) => void;
type ErrorListener = (error: Event) => void;

/**
 * One connection for the whole page, however many things are watching.
 *
 * This is shared rather than per-caller because the queue is one thing and a
 * browser's patience is finite. `Progress` renders inside every queued batch
 * card, and a queued card stays until the user dismisses it — so a
 * connection-per-subscriber means the number of open streams is the number of
 * drops nobody has cleared away. Browsers allow six concurrent connections per
 * origin over HTTP/1.1, which is what uvicorn serves on loopback, so the
 * seventh request from that tab — `POST /sources`, a route's own JavaScript —
 * waits for a slot that a permanently-open stream never gives back. The tab
 * stops responding with no error anywhere, which is precisely the failure this
 * ticket exists to prevent.
 *
 * Refcounted rather than opened once and left: a page with nothing to watch
 * should hold no connection at all.
 */
const listeners = new Set<StateListener>();
const errorListeners = new Set<ErrorListener>();
let shared: EventSource | null = null;

function openShared(): EventSource {
  const source = new EventSource("/ingest/stream");
  source.addEventListener("progress", (event) => {
    const state = JSON.parse((event as MessageEvent<string>).data) as IngestState;
    // Copied before iterating: a listener may unsubscribe on the state it just
    // received, and mutating the set mid-iteration would skip its neighbour.
    for (const listener of [...listeners]) {
      listener(state);
    }
  });
  source.addEventListener("error", (event) => {
    for (const listener of [...errorListeners]) {
      listener(event);
    }
  });
  return source;
}

export function subscribeIngest(
  onState: StateListener,
  onError?: ErrorListener,
): () => void {
  listeners.add(onState);
  if (onError) {
    errorListeners.add(onError);
  }
  shared ??= openShared();

  let stopped = false;
  return () => {
    // Idempotent: React may run a cleanup twice, and a second call must not
    // decide the last watcher has gone while one is still watching.
    if (stopped) {
      return;
    }
    stopped = true;
    listeners.delete(onState);
    if (onError) {
      errorListeners.delete(onError);
    }
    if (listeners.size === 0 && errorListeners.size === 0 && shared !== null) {
      shared.close();
      shared = null;
    }
  };
}

/**
 * Ask for one failed document to be read again.
 *
 * The API forgives the attempt count rather than continuing it, which is why
 * this exists as a control and not merely as a message: the user has looked at
 * the reason, reconnected the drive or closed the file, and starting from the
 * third attempt would fail it again on the first hiccup.
 *
 * Throws with the API's own sentence. A retry that quietly does nothing is the
 * silently-dropped file this whole surface exists to prevent.
 */
export async function retryDocument(documentId: string): Promise<void> {
  const response = await fetch(`/ingest/documents/${documentId}/retry`, {
    method: "POST",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered ${response.status} to the retry.`);
  }
}

/**
 * Ask for every live document in a source to be read again — extraction,
 * chunking and embedding, from the front, regardless of what state each
 * document is currently in.
 *
 * `docs/ux/library.md` §3: "confirms first — it can take hours." The
 * confirmation is the caller's job (`LibraryScreen`); this is only the call
 * once the user has already agreed.
 */
export async function reindexSource(sourceId: string): Promise<number> {
  const response = await fetch(`/sources/${sourceId}/reindex`, {
    method: "POST",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered ${response.status} to the re-index.`);
  }
  const result = (await response.json()) as { documents: number };
  return result.documents;
}

/**
 * Tombstone a source. `docs/ux/library.md` §4, `M2-DELETE-FE-062`.
 *
 * The confirmation — naming the source and stating the three facts — is the
 * caller's job (`LibraryScreen`), same division as `reindexSource` above;
 * this is only the call once the user has already agreed. The file on disk
 * is never touched by this request or by the endpoint it calls
 * (`askwell.sources.delete_source`) — only what Askwell kept is cleared.
 */
export async function deleteSource(sourceId: string): Promise<number> {
  const response = await fetch(`/sources/${sourceId}`, {
    method: "DELETE",
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `Askwell answered ${response.status} to the deletion.`);
  }
  const result = (await response.json()) as { documents_deleted: number };
  sourceDeletionCount += 1;
  return result.documents_deleted;
}

// A local counter of confirmed deletions (this ticket's own Analytics
// Events line) — in-memory only, never persisted or sent anywhere (C1).
// Same pattern as `citations.ts`'s `cardClickCount`.
let sourceDeletionCount = 0;

export function getSourceDeletionCount(): number {
  return sourceDeletionCount;
}

/**
 * Why one file could not be read, in a sentence with the file's name in it.
 *
 * The name first, because a user with sixty contracts and two failures needs to
 * know *which* two before anything else. The stage is named when there is one:
 * "while reading it" and "while working out what it says" send somebody to
 * different places.
 */
export function failureSentence(failure: FailedDocument): string {
  const where = failure.stage === null ? "" : ` while ${failure.stage}`;
  const why = failure.error ?? "Askwell did not record a reason, which is itself a bug.";
  const tries =
    failure.attempts > 1 ? ` Tried ${failure.attempts} times.` : "";
  return `${failure.filename} could not be read${where}: ${why}${tries}`;
}

/**
 * Why one document reads thin, in a sentence naming the file and the pages.
 *
 * The pages are named rather than only counted — `M1-EXTRACT-ING-029`'s own
 * edge case is a mixed document, and "read poorly" without saying which pages
 * leaves someone with a sixty-page scan no way to know whether page one or
 * page fifty-nine is the one to re-scan.
 */
export function flaggedSentence(flagged: FlaggedDocument): string {
  const percent = Math.round(flagged.confidence * 100);
  const pages =
    flagged.poor_pages.length > 0
      ? ` — page${flagged.poor_pages.length > 1 ? "s" : ""} ${flagged.poor_pages.join(", ")} read worst`
      : "";
  return (
    `${flagged.filename} scanned poorly (about ${percent}% confidence)${pages}. ` +
    `It is indexed and searchable, but answers about it may be thin.`
  );
}

/**
 * How long the rest will take, said the way the API measured it.
 *
 * Deliberately not "calculating" anything: the API knows what it extrapolated
 * from and this repeats it. A screen that rounds a measured 4,100 seconds to
 * "about an hour" and drops the basis has thrown away the only thing that made
 * the number trustworthy.
 */
export function estimateSentence(estimate: IngestEstimate): string {
  if (estimate.seconds === null) {
    return estimate.basis;
  }
  if (estimate.seconds === 0) {
    return "Nothing is waiting.";
  }
  return `About ${duration(estimate.seconds)} left — ${estimate.basis}.`;
}

/** A rough, honestly rounded duration. Never more precise than it is. */
export function duration(seconds: number): string {
  if (seconds < 90) {
    return `${Math.max(1, Math.round(seconds))} seconds`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) {
    return `${minutes} minutes`;
  }
  return `${Math.round(minutes / 60)} hours`;
}

/**
 * What is happening to a drop, in one sentence the user can act on.
 *
 * The order of the cases is the argument. A stage that has not been built is
 * checked *before* the queue length, because "3 files queued" beside a queue
 * that cannot move is a spinner in prose. And a file being indexed is checked
 * before a file waiting, because the one that is moving is the one somebody is
 * looking at.
 */
export function queueSentence(state: IngestState): string {
  const missing = state.stages.find((stage) => !stage.built);

  const first = state.active[0];
  if (first !== undefined) {
    const within =
      first.fraction === null ? "" : ` — ${Math.round(first.fraction * 100)}% of the way through`;
    const behind =
      state.queue_length > 1 ? `, ${state.queue_length - 1} waiting behind it` : "";
    return `Indexing ${first.filename}${within}${behind}.`;
  }

  if (state.counts.parked > 0 && missing) {
    return (
      `${countOf(state.counts.parked, "file is", "files are")} recorded and waiting. ` +
      `Nothing is searchable yet: reading them needs ${missing.name}, which is not built ` +
      `yet (${missing.ticket}). Nothing has been copied.`
    );
  }

  if (state.queue_length > 0) {
    return `${countOf(state.queue_length, "file is", "files are")} queued.`;
  }

  if (state.counts.failed > 0) {
    return `${countOf(state.counts.failed, "file", "files")} could not be indexed.`;
  }

  return "Nothing is waiting.";
}

/** How much of a source can be asked about while the rest continues. */
export function coverageSentence(coverage: SourceCoverage): string {
  if (coverage.total === 0) {
    return "Nothing in this source yet.";
  }
  if (coverage.ready === coverage.total) {
    return `All ${coverage.total} indexed.`;
  }
  if (coverage.ready === 0) {
    return `None of ${coverage.total} indexed yet — nothing here can be asked about.`;
  }
  return (
    `${coverage.ready} of ${coverage.total} indexed. You can ask about those now; ` +
    `the rest are still being read.`
  );
}

function countOf(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}
