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
 * A batch ends at `queued`. Nothing is extracted, embedded or made searchable:
 * the records and the background ingestion are `M1-ADD-BE-023` and
 * `M1-ADD-ING-025`, and this ticket is the screen. The screen says exactly
 * that rather than showing a spinner that will never finish, because a
 * progress bar that does not move is a bug report, and an honest sentence is
 * not.
 */

export type Phase = "detecting" | "locating" | "queued" | "refused";

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
  failure: string | null;
}

export interface AddApi {
  batches: Batch[];
  /** Sources added on this machine. Local, and there is nowhere to send it. */
  added: number;
  accept: (selection: Selection) => void;
  locate: (id: string, folder: string) => Promise<void>;
  nominateFolder: (id: string) => Promise<void>;
  forget: (id: string) => void;
}

/**
 * The local counter the ticket asks for.
 *
 * `window.localStorage` and nothing else. There is no transmission path for it
 * to take and none is being built (C1) — the number exists so the user can see
 * that Askwell has been given something, on the one machine that has it.
 */
const COUNTER = "askwell.sources.added";

/**
 * `localStorage` is the store, and React subscribes to it rather than copying
 * it into state on mount. Reading it in an effect and calling `setAdded` would
 * render the wrong number first and the right one a frame later; reading it
 * during render would disagree with the statically exported HTML, which is
 * what a hydration mismatch is. `useSyncExternalStore` is the shape React
 * provides for exactly this: `counterServerSnapshot` is what the export was
 * built with, and the real value arrives at hydration.
 */
const counterListeners = new Set<() => void>();

/**
 * `useSyncExternalStore` compares snapshots by identity and re-reads on every
 * render, so the read has to be memoised — parsing `localStorage` afresh each
 * time returns an equal number, but a store that re-reads on every render is
 * one storage hit per render for a value that only `addToCounter` changes.
 */
let counterCache: number | null = null;

function readCounter(): number {
  const raw = window.localStorage.getItem(COUNTER);
  const stored = raw === null ? 0 : Number.parseInt(raw, 10);
  return Number.isFinite(stored) && stored > 0 ? stored : 0;
}

function subscribeCounter(listener: () => void): () => void {
  counterListeners.add(listener);
  return () => {
    counterListeners.delete(listener);
  };
}

function counterSnapshot(): number {
  if (counterCache === null) counterCache = readCounter();
  return counterCache;
}

/** No storage on the server, and the export is built with none added yet. */
function counterServerSnapshot(): number {
  return 0;
}

function addToCounter(by: number): void {
  const next = counterSnapshot() + by;
  window.localStorage.setItem(COUNTER, String(next));
  counterCache = next;
  for (const listener of counterListeners) listener();
}

/** How many files are read at once before the loop hands the window back. */
const CHUNK = 25;

const breathe = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

const UNREADABLE: Detection = {
  format: "a file Askwell could not open",
  route: "files",
  supported: false,
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
  return batch.items.filter((item) => item.detection?.supported === true);
}

export function refusedIn(batch: Batch): Item[] {
  return batch.items.filter((item) => item.detection !== null && !item.detection.supported);
}

export function AddProvider({ children }: { children: ReactNode }) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const added = useSyncExternalStore(subscribeCounter, counterSnapshot, counterServerSnapshot);

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
    addToCounter(by);
  }, []);

  const accept = useCallback((selection: Selection): void => {
    if (selection.files.length === 0) return;
    const batch: Batch = {
      id: crypto.randomUUID(),
      phase: "detecting",
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

        setBatches((queue) =>
          queue.map((batch) =>
            batch.id !== id
              ? batch
              : { ...batch, phase: supportedIn(batch).length === 0 ? "refused" : "locating" },
          ),
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
      const first = supportedIn(batch)[0];
      if (first === undefined) return;

      // Counted once. Re-checking a queued batch — which happens when the user
      // corrects the folder — must not add its files to the counter twice.
      const alreadyCounted = batch.phase === "queued";
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
                  phase: answer.covered ? "queued" : "locating",
                },
          ),
        );
        if (answer.covered && !alreadyCounted) countUp(supportedIn(batch).length);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Askwell could not check that folder.";
        setBatches((queue) =>
          queue.map((one) => (one.id !== id ? one : { ...one, folder: base, failure: message })),
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
    () => ({ batches, added, accept, locate, nominateFolder, forget }),
    [batches, added, accept, locate, nominateFolder, forget],
  );

  return <AddContext.Provider value={api}>{children}</AddContext.Provider>;
}
