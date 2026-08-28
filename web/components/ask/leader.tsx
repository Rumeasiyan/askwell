"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

/**
 * The hairline leader joining a cited claim to its margin card.
 * `M1-CITE-FE-043`.
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

interface Line {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  raised: boolean;
}

/**
 * The overlay itself: one `--rule-strong` line per pair whose both ends are
 * currently registered. `active` keeps a short poll running only while the
 * live turn is still streaming — tokens reflow the claim spans continuously,
 * a mount/unmount-driven recompute alone would leave the line trailing
 * behind the text it is meant to point at.
 *
 * Below the three-column breakpoint the margin column is CSS-hidden
 * (`shell.tsx`), so a line here would point at a collapsed, zero-size node —
 * `hidden @5xl:block` hides the canvas itself rather than skipping pairs
 * whose card has no layout to measure (`M1-CITE-FE-044`).
 */
export function LeaderCanvas({ pairs, active }: { pairs: LeaderPair[]; active: boolean }) {
  const store = useLeaderStore();
  const version = useSyncExternalStore(
    store.subscribe,
    () => store.version,
    () => store.version,
  );
  const hovered = useHoveredKey();
  const [lines, setLines] = useState<Line[]>([]);

  useEffect(() => {
    const recompute = (): void => {
      const next: Line[] = [];
      for (const { claimKey, cardKey } of pairs) {
        const claimNode = store.claims.get(claimKey);
        const cardNode = store.cards.get(cardKey);
        if (!claimNode || !cardNode) continue;
        const claimRect = claimNode.getBoundingClientRect();
        const cardRect = cardNode.getBoundingClientRect();
        next.push({
          key: `${claimKey}->${cardKey}`,
          x1: claimRect.right,
          y1: claimRect.top + claimRect.height / 2,
          x2: cardRect.left,
          y2: cardRect.top + cardRect.height / 2,
          raised: hovered !== null && (hovered === claimKey || hovered === cardKey),
        });
      }
      // Raised line drawn last so it sits on top of any it overlaps — the
      // ticket's own "overlapping leaders in a dense answer" edge case.
      next.sort((a, b) => Number(a.raised) - Number(b.raised));
      setLines(next);
    };

    recompute();
    window.addEventListener("resize", recompute);
    // Capture phase: an inner scroll container's `scroll` event does not
    // bubble, but it does fire on ancestors during the capture phase, which
    // is the only way a listener on `window` sees the centre column or the
    // margin rail scrolling independently.
    window.addEventListener("scroll", recompute, true);
    const interval = active ? window.setInterval(recompute, 150) : undefined;

    return () => {
      window.removeEventListener("resize", recompute);
      window.removeEventListener("scroll", recompute, true);
      if (interval !== undefined) window.clearInterval(interval);
    };
    // `version` re-runs this after a node newly registers — a card that
    // just mounted otherwise waits for the next resize/scroll to be found,
    // and `hovered` changing must repaint immediately, not on the next poll.
  }, [store, pairs, active, version, hovered]);

  if (lines.length === 0) return null;

  return (
    <svg
      aria-hidden
      className="pointer-events-none fixed inset-0 z-40 hidden @5xl:block"
      style={{ width: "100vw", height: "100vh" }}
    >
      {lines.map((line) => (
        <line
          key={line.key}
          x1={line.x1}
          y1={line.y1}
          x2={line.x2}
          y2={line.y2}
          stroke={line.raised ? "var(--provenance)" : "var(--rule-strong)"}
          strokeWidth={line.raised ? 2 : 1}
        />
      ))}
    </svg>
  );
}
