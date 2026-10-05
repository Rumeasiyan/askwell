"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

/**
 * The pairing between a cited claim and its margin card: hovering or
 * focusing one raises the other. `M1-CITE-FE-043`. No line is drawn between
 * them (docs/decisions.md, 2026-10-05: the hairline was removed).
 *
 * The claim and its card are siblings under `ShellFrame` (`shell.tsx`) —
 * `Turn` renders in the centre column, `ProvenanceMargin` in the right
 * rail — so drawing a line between them needs a registry both sides can
 * reach, not a prop. `LeaderStore` is that registry: a claim span and a
 * card each register their own DOM node under a `${turnId}:…` key when they
 * mount, and `LeaderCanvas` looks both nodes up for every claim-to-card
 * pair the live turn's citations describe.
 *
 * A plain mutable store behind `useSyncExternalStore`, not React state on
 * the provider, because every token arriving during streaming can move a
 * claim span's position without any node being added or removed — state
 * that only changes on mount/unmount would miss that, so the canvas also
 * polls on a short interval while a turn is running (see `LeaderCanvas`).
 *
 * **Degrades, never disappears** (the ticket's own Assumption): if a node
 * has not registered yet — the answer has not rendered the claim, or the
 * card just mounted this frame — that pair is skipped for one render rather
 * than throwing. The card itself is never conditioned on the leader.
 *
 * `M1-CITE-FE-044` adds `hovered`: hovering or focusing a claim raises its
 * card and vice versa, so this store is also where "what is currently
 * paired" lives — the same cross-column reachability problem the claim/card
 * maps already solve, one field, not a second registry.
 */

interface LeaderStore {
  claims: Map<string, HTMLElement>;
  cards: Map<string, HTMLElement>;
  version: number;
  /** The claim or card key currently hovered or focused, either side —
   * `M1-CITE-FE-044`. A claim span and its card are DOM siblings, so this is
   * the same cross-column registry pattern `claims`/`cards` already use,
   * not new state on either component. */
  hovered: string | null;
  listeners: Set<() => void>;
  registerClaim(key: string, node: HTMLElement | null): void;
  registerCard(key: string, node: HTMLElement | null): void;
  setHovered(key: string | null): void;
  /** Only clears if `key` is still the hovered one — a fast mouse move that
   * enters the next target before this leaves the last must not blank out
   * the new hover. */
  clearHovered(key: string): void;
  subscribe(listener: () => void): () => void;
}

function createLeaderStore(): LeaderStore {
  const claims = new Map<string, HTMLElement>();
  const cards = new Map<string, HTMLElement>();
  const listeners = new Set<() => void>();
  const store: LeaderStore = {
    claims,
    cards,
    version: 0,
    hovered: null,
    listeners,
    registerClaim(key, node) {
      if (node) claims.set(key, node);
      else claims.delete(key);
      store.version += 1;
      listeners.forEach((listener) => listener());
    },
    registerCard(key, node) {
      if (node) cards.set(key, node);
      else cards.delete(key);
      store.version += 1;
      listeners.forEach((listener) => listener());
    },
    setHovered(key) {
      store.hovered = key;
      store.version += 1;
      listeners.forEach((listener) => listener());
    },
    clearHovered(key) {
      if (store.hovered !== key) return;
      store.hovered = null;
      store.version += 1;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  return store;
}

const LeaderContext = createContext<LeaderStore | null>(null);

export function LeaderProvider({ children }: { children: ReactNode }) {
  const [store] = useState<LeaderStore>(createLeaderStore);
  return <LeaderContext.Provider value={store}>{children}</LeaderContext.Provider>;
}

function useLeaderStore(): LeaderStore {
  const store = useContext(LeaderContext);
  if (store === null) throw new Error("useLeaderStore was called outside LeaderProvider.");
  return store;
}

/** Ref callback for the span wrapping one claim's rendered text. */
export function useClaimRef(key: string): (node: HTMLElement | null) => void {
  const store = useLeaderStore();
  return useCallback((node: HTMLElement | null) => store.registerClaim(key, node), [store, key]);
}

/** Ref callback for one provenance card. */
export function useCardRef(key: string): (node: HTMLElement | null) => void {
  const store = useLeaderStore();
  return useCallback((node: HTMLElement | null) => store.registerCard(key, node), [store, key]);
}

/**
 * Scrolls a registered claim span into view, if it is currently mounted.
 * `M1-VIEW-FE-048`'s "back to answer": the context rail's return link names
 * a claim key (`${turnId}:${ordinal}`), and this is the one place that
 * already tracks where that claim's node lives, so returning to the exact
 * claim reuses the leader-line registry rather than a second lookup. Returns
 * whether a node was found, so the caller can tell "landed" from "the answer
 * that produced this claim is no longer on screen" without inventing a
 * second signal for the same fact.
 */
export function useScrollToClaim(): (key: string) => boolean {
  const store = useLeaderStore();
  return useCallback(
    (key: string) => {
      const node = store.claims.get(key);
      if (node === undefined) return false;
      node.scrollIntoView({ block: "center" });
      return true;
    },
    [store],
  );
}

/** The currently hovered/focused claim or card key, either side, or `null`. */
export function useHoveredKey(): string | null {
  const store = useLeaderStore();
  return useSyncExternalStore(
    store.subscribe,
    () => store.hovered,
    () => store.hovered,
  );
}

/**
 * Mouse and focus handlers for one claim span or card — hovering or
 * focusing either end raises both (`ClaimSpan`, `SourceCard`). `blur`/
 * `mouseLeave` only clear if this key is still the one hovered, so moving
 * the pointer directly from a claim onto its card does not flicker the
 * raised state off between the two.
 */
export function useHoverHandlers(key: string): {
  onHover: () => void;
  onUnhover: () => void;
} {
  const store = useLeaderStore();
  return {
    onHover: useCallback(() => store.setHovered(key), [store, key]),
    onUnhover: useCallback(() => store.clearHovered(key), [store, key]),
  };
}

export interface LeaderPair {
  claimKey: string;
  cardKey: string;
}
