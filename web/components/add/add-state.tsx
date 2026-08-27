"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { type Detection, detect } from "@/lib/add-source";
import { type CoveringPrompt, askCovering, nominate } from "@/lib/roots";
import type { Picked, Selection } from "@/lib/selection";
import { type Recorded, recordSource } from "@/lib/sources";

/**
 * The add queue, held once for the whole application.
 *
 * It lives above the router because drag-and-drop works anywhere
 * (`docs/ux/add-source.md` §1): a drop onto the Ask screen has to survive the
 * navigation to `/sources/add/` that it causes. A queue owned by the screen
 * would be created by that navigation and would therefore always be empty.
 *
 * **A drop while another is running is queued, never rejected.** Detection
 * runs one batch at a time — reading the head of several thousand files at
 * once is how a window stops responding — and a second drop simply waits its
 * turn with its own count shown. Rejecting it would punish the user for
 * Askwell being busy with their last instruction.
 *
 * ## Where this stops, today
 *
 * A batch ends at `queued`, and `queued` now means something durable: a source
 * row and a document row per file, recorded by `POST /sources`
 * (`M1-ADD-BE-023`). Nothing is extracted, embedded or searchable — that is
 * background ingestion, `M1-ADD-ING-025` — and the screen says exactly that
 * rather than showing a spinner that will never finish, because a progress bar
 * that does not move is a bug report and an honest sentence is not.
 */

/**
 * Where a batch has got to.
 *
 * `later` and `empty` are separate from `refused` because they are separate
 * things to the person who dropped the files. A drop of CSV exports has not
 * been rejected — its route is being built — and a drop that contained no
 * files at all is not a judgement about anything. Collapsing either into
 * "Refused" tells somebody Askwell will not handle their material, which is
 * the sentence this ticket exists to stop Askwell saying wrongly.
 */
export type Phase =
  | "detecting"
  | "locating"
  | "recording"
  | "queued"
  | "refused"
  | "later"
  | "empty";

export interface Item {
  id: string;
  name: string;
  relativePath: string;
  size: number;
  /** Null until its head has been read. */
  detection: Detection | null;
  picked: Picked;
}

export interface Batch {
  id: string;
  phase: Phase;
  items: Item[];
  folders: number;
  truncated: boolean;
  bytes: number;
  /** Where the user says these came from. Null until they have said. */
  folder: string | null;
  /** The API's question when no nominated folder covers them. */
  prompt: CoveringPrompt | null;
  /** What the API actually recorded. Null until it has answered. */
  recorded: Recorded | null;
  failure: string | null;
}

export interface AddApi {
  batches: Batch[];
  /** Sources added on this machine. Local, and there is nowhere to send it. */
  added: number;
  /** Files refused on this machine. Same store, same absence of a wire. */
  rejected: number;
  accept: (selection: Selection) => void;
  locate: (id: string, folder: string) => Promise<void>;
  nominateFolder: (id: string) => Promise<void>;
  forget: (id: string) => void;
}

/**
 * The local counters the ticket asks for.
 *
 * `window.localStorage` and nothing else. There is no transmission path for
 * either number to take and none is being built (C1) — they exist so the user
 * can see what Askwell has been given and what it turned away, on the one
 * machine that has them.
 *
 * `localStorage` is the store, and React subscribes to it rather than copying
 * it into state on mount. Reading it in an effect and calling `setAdded` would
 * render the wrong number first and the right one a frame later; reading it
 * during render would disagree with the statically exported HTML, which is
 * what a hydration mismatch is. `useSyncExternalStore` is the shape React
 * provides for exactly this: the server snapshot is what the export was built
 * with, and the real value arrives at hydration.
 */
interface Counter {
  subscribe: (listener: () => void) => () => void;
  snapshot: () => number;
  serverSnapshot: () => number;
  add: (by: number) => void;
}

/**
 * `useSyncExternalStore` compares snapshots by identity and re-reads on every
 * render, so each read has to be memoised — parsing `localStorage` afresh
 * every time returns an equal number, but a store that re-reads on every
 * render is one storage hit per render for a value only `add` changes.
 */
function makeCounter(key: string): Counter {
  const listeners = new Set<() => void>();
  let cache: number | null = null;

  const read = (): number => {
    const raw = window.localStorage.getItem(key);
    const stored = raw === null ? 0 : Number.parseInt(raw, 10);
    return Number.isFinite(stored) && stored > 0 ? stored : 0;
  };

  const snapshot = (): number => {
    if (cache === null) cache = read();
    return cache;
  };

  return {
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    snapshot,
    // No storage on the server, and the export is built with none of either.
    serverSnapshot: () => 0,
    add: (by) => {
      const next = snapshot() + by;
      window.localStorage.setItem(key, String(next));
      cache = next;
      for (const listener of listeners) listener();
    },
  };
}

const ADDED = makeCounter("askwell.sources.added");
const REJECTED = makeCounter("askwell.sources.rejected");

/** How many files are read at once before the loop hands the window back. */
const CHUNK = 25;

const breathe = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

const UNREADABLE: Detection = {
  format: "a file Askwell could not open",
  route: "files",
  verdict: "refused",
  arrives: null,
  mismatch: null,
  refusal:
    "Askwell could not read this file. It may have been moved or renamed since it was dropped. Nothing on disk was changed.",
};

const AddContext = createContext<AddApi | null>(null);

export function useAdd(): AddApi {
  const value = useContext(AddContext);
  if (value === null) throw new Error("useAdd was called outside AddProvider.");
  return value;
}

export function supportedIn(batch: Batch): Item[] {
  return batch.items.filter((item) => item.detection?.verdict === "supported");
}

export function refusedIn(batch: Batch): Item[] {
  return batch.items.filter((item) => item.detection?.verdict === "refused");
}

/** Recognised, and its route is being built. Never counted as added. */
export function laterIn(batch: Batch): Item[] {
  return batch.items.filter((item) => item.detection?.verdict === "later");
}

export function AddProvider({ children }: { children: ReactNode }) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const added = useSyncExternalStore(ADDED.subscribe, ADDED.snapshot, ADDED.serverSnapshot);
  const rejected = useSyncExternalStore(
    REJECTED.subscribe,
    REJECTED.snapshot,
    REJECTED.serverSnapshot,
  );

  // `locate` and `nominateFolder` read the queue as it is when the user acts,
  // not as it was when the callback was created. Without this they would close
  // over a stale queue and act on a batch whose detections had since landed.
  // Written from an effect, never during render: an event handler only ever
  // runs after the commit that wrote it.
  const current = useRef<Batch[]>([]);
  const working = useRef(false);

  useEffect(() => {
    current.current = batches;
  }, [batches]);

  const countUp = useCallback((by: number): void => {
    if (by <= 0) return;
    ADDED.add(by);
  }, []);

  const accept = useCallback((selection: Selection): void => {
    // A drop that expanded to nothing is only worth saying when there was
    // something to expand: an empty folder is a real gesture that deserves an
    // answer, whereas a cancelled file dialog hands back an empty list too and
    // must stay silent. `folders` is what tells the two apart.
    if (selection.files.length === 0 && selection.folders === 0) return;
    const batch: Batch = {
      id: crypto.randomUUID(),
      phase: selection.files.length === 0 ? "empty" : "detecting",
      items: selection.files.map((picked) => ({
        id: crypto.randomUUID(),
        name: picked.name,
        relativePath: picked.relativePath,
        size: picked.size,
        detection: null,
        picked,
      })),
      folders: selection.folders,
      truncated: selection.truncated,
      bytes: selection.files.reduce((total, file) => total + file.size, 0),
      folder: null,
      prompt: null,
      recorded: null,
      failure: null,
    };
    setBatches((queue) => [...queue, batch]);
  }, []);

  const forget = useCallback((id: string): void => {
    setBatches((queue) => queue.filter((batch) => batch.id !== id));
  }, []);

  // --- detection, one batch at a time --------------------------------------

  useEffect(() => {
    if (working.current) return;
    // The committed queue, not the ref: an effect body already runs after the
    // commit that scheduled it, so `batches` here *is* the current queue.
    const pending = batches.find((batch) => batch.phase === "detecting");
    if (pending === undefined) return;

    working.current = true;
    const id = pending.id;

    void (async () => {
      let refused = 0;
      try {
        const items = pending.items;
        for (let start = 0; start < items.length; start += CHUNK) {
          const slice = items.slice(start, start + CHUNK);
          const detections = await Promise.all(
            slice.map(async (item) => {
              try {
                return detect(item.name, await item.picked.head(), item.size);
              } catch {
                return UNREADABLE;
              }
            }),
          );
          refused += detections.filter((one) => one.verdict === "refused").length;
          setBatches((queue) =>
            queue.map((batch) =>
              batch.id !== id
                ? batch
                : {
                    ...batch,
                    items: batch.items.map((item, index) =>
                      index < start || index >= start + slice.length
                        ? item
                        : { ...item, detection: detections[index - start] ?? item.detection },
                    ),
                  },
            ),
          );
          // Hand the window back between chunks. A folder of several thousand
          // files is a supported drop, and a frozen window is what the ticket
          // names as the thing it must not be.
          await breathe();
        }

        // Counted here rather than inside the updater above: React may call an
        // updater more than once for the same state change, and a counter
        // incremented from one would drift upwards on its own.
        if (refused > 0) REJECTED.add(refused);

        setBatches((queue) =>
          queue.map((batch): Batch => {
            if (batch.id !== id) return batch;
            // A batch with nothing to add still ends somewhere specific. Only
            // a batch with files Askwell can index today goes on to ask where
            // they are — asking about a folder of CSV exports would be a
            // question whose answer changes nothing.
            const phase: Phase =
              supportedIn(batch).length > 0
                ? "locating"
                : laterIn(batch).length > 0
                  ? "later"
                  : "refused";
            return { ...batch, phase };
          }),
        );
      } finally {
        // Released before React commits the state change above, so the render
        // that change causes re-runs this effect and picks up whatever was
        // dropped while it was busy. That is the whole queueing mechanism:
        // a second drop waits, and is never turned away.
        working.current = false;
      }
    })();
  }, [batches]);

  // --- where the files actually are ----------------------------------------

  const locate = useCallback(
    async (id: string, folder: string): Promise<void> => {
      const batch = current.current.find((one) => one.id === id);
      if (batch === undefined) return;
      const supported = supportedIn(batch);
      const first = supported[0];
      if (first === undefined) return;

      // Recorded once. Re-checking a batch that has already been recorded —
      // which happens when the user corrects the folder — must not create the
      // documents a second time.
      if (batch.phase === "queued") return;
      const base = folder.trim().replace(/\/+$/, "");
      // One question, not one per file: a root covers a tree, so if it permits
      // the first file under this folder it permits all of them. Asking once
      // per file would be several thousand requests to learn one fact.
      const path = `${base}/${first.relativePath}`;

      try {
        const answer = await askCovering(path);
        setBatches((queue) =>
          queue.map((one) =>
            one.id !== id
              ? one
              : {
                  ...one,
                  folder: base,
                  failure: null,
                  prompt: answer.covered ? null : answer.prompt,
                  phase: answer.covered ? "recording" : "locating",
                },
          ),
        );
        if (!answer.covered) return;

        // The files are named, never sent. Askwell opens them where they are —
        // this request carries a folder and a list of relative paths, and if it
        // ever carries bytes it has become an upload, which is a different
        // product from the one this screen promises.
        const recorded = await recordSource(
          base,
          supported.map((item) => item.relativePath),
        );
        setBatches((queue) =>
          queue.map((one) =>
            one.id !== id ? one : { ...one, recorded, phase: "queued", failure: null },
          ),
        );
        // The server's count, not the screen's. A file the server recognised as
        // one it already has was not added, and counting it would make the
        // local tally drift upwards every time somebody re-added a folder.
        countUp(recorded.added);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Askwell could not check that folder.";
        setBatches((queue) =>
          queue.map((one) =>
            one.id !== id
              ? one
              : // Back to `locating`, not stuck on `recording`: the folder field
                // has to still be there for someone whose first answer was
                // wrong, and a spinner with no way out is the state this screen
                // is written to avoid.
                { ...one, folder: base, phase: "locating", failure: message },
          ),
        );
      }
    },
    [countUp],
  );

  const nominateFolder = useCallback(
    async (id: string): Promise<void> => {
      const batch = current.current.find((one) => one.id === id);
      if (batch === undefined || batch.prompt === null || batch.folder === null) return;
      try {
        await nominate(batch.prompt.suggested_root);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "That folder was not accepted.";
        setBatches((queue) =>
          queue.map((one) => (one.id !== id ? one : { ...one, failure: message })),
        );
        return;
      }
      await locate(id, batch.folder);
    },
    [locate],
  );

  const api = useMemo<AddApi>(
    () => ({ batches, added, rejected, accept, locate, nominateFolder, forget }),
    [batches, added, rejected, accept, locate, nominateFolder, forget],
  );

  return <AddContext.Provider value={api}>{children}</AddContext.Provider>;
}
