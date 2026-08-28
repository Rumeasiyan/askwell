"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  applyAskEvent,
  type AskEvent,
  looksNonEnglish,
  nextToDispatch,
  stopAsk,
  streamAsk,
} from "@/lib/ask";
import { applyCitation, type CitationCard } from "@/lib/citations";

/**
 * The conversation, held once for the whole application. `M1-ASK-FE-039`.
 *
 * It lives above the router for the same reason `AddProvider` does
 * (`add-state.tsx`): the acceptance criteria include "navigate away
 * mid-answer and back — the completed answer is present", and a page
 * component unmounts on every route change. A turn owned by the Ask screen
 * would be recreated empty by that navigation.
 *
 * **This is the live turn, not the conversation.** `docs/ux/conversation.md`
 * is a separate ticket (`CONV`, M1-CONV-BE-177 onward): past turns collapse
 * to a stored one-line summary and a source count there. Here every turn
 * simply stacks, unstyled by collapse rules — `AskTurn` is deliberately a
 * container that later ticket can wrap without this one being rewritten.
 *
 * **`conversation_id` is not threaded across turns.** `POST /ask` accepts
 * one, but `askwell.ask` never returns the id it resolved or created — not
 * in an SSE event, not in a header — so there is nothing here to capture and
 * send on the next question. Filed as issue 156 rather than guessed at:
 * every question lands in its own conversation server-side until that's
 * fixed. It does not affect this ticket's own acceptance criteria, which
 * only requires a second question to render as a second turn.
 */

export type TurnStatus = "queued" | "running" | "completed" | "stopped" | "failed";

export interface AskTurn {
  /** Client-generated, and what every list key and `patch` call uses. The
   * server's own `message_id` (`serverId`) is captured separately because it
   * is what `POST /ask/{message_id}/stop` needs, and it does not exist until
   * the first SSE event names it. */
  id: string;
  serverId: string | null;
  question: string;
  /** `null` for an ordinary question against the whole corpus. Set from the
   * context rail's "ask about this source" (`M1-VIEW-FE-048`), which is the
   * one place a question is deliberately scoped before it is even typed. */
  sourceId: string | null;
  status: TurnStatus;
  steps: { label: string; kind: string }[];
  answer: string;
  /** One card per cited chunk, grouped by `applyCitation` (`lib/citations.ts`)
   * as `citation` events arrive — the provenance margin's own data, not
   * rendered by this module (`ProvenanceMargin`, `M1-CITE-FE-043`). */
  citations: CitationCard[];
  reason: string | null;
}

export interface AskApi {
  turns: AskTurn[];
  /** The turn actually streaming right now, as opposed to merely queued
   * behind one — what the composer's stop control acts on. */
  running: AskTurn | null;
  ask: (question: string, sourceId?: string | null) => void;
  stop: () => void;
}

const AskContext = createContext<AskApi | null>(null);

export function useAsk(): AskApi {
  const value = useContext(AskContext);
  if (value === null) throw new Error("useAsk was called outside AskProvider.");
  return value;
}

/**
 * The turn the provenance margin belongs to (`ask.md` §8, settled): past
 * turns do not collapse yet (`M1-CONV-FE-180`), but the margin only ever
 * shows one answer's citations, so it tracks the most recently asked turn
 * rather than every turn on screen.
 */
export function useLiveTurn(): AskTurn | null {
  const { turns } = useAsk();
  return turns.length > 0 ? turns[turns.length - 1]! : null;
}

const NON_ENGLISH_REASON =
  "Askwell answers in English in this version. Ask again in English, and it will search your files.";

function blankTurn(
  question: string,
  status: TurnStatus,
  reason: string | null = null,
  sourceId: string | null = null,
): AskTurn {
  return {
    id: crypto.randomUUID(),
    serverId: null,
    question,
    sourceId,
    status,
    steps: [],
    answer: "",
    citations: [],
    reason,
  };
}

export function AskProvider({ children }: { children: ReactNode }) {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  // Read by the dispatch effect without adding `turns` to its own dependency
  // list, which would re-open a connection on every token. Kept current from
  // an effect — `AddProvider.current` in `add-state.tsx` is the same fix for
  // the same reason: an event handler only ever runs after the commit that
  // scheduled it.
  const current = useRef<AskTurn[]>([]);
  const dispatching = useRef(false);

  useEffect(() => {
    current.current = turns;
  }, [turns]);

  const patch = useCallback((id: string, changes: Partial<AskTurn>): void => {
    setTurns((queue) => queue.map((turn) => (turn.id !== id ? turn : { ...turn, ...changes })));
  }, []);

  const ask = useCallback((question: string, sourceId: string | null = null): void => {
    const trimmed = question.trim();
    // No request for an empty question — the edge case named explicitly.
    if (trimmed === "") return;

    if (looksNonEnglish(trimmed)) {
      setTurns((queue) => [...queue, blankTurn(trimmed, "failed", NON_ENGLISH_REASON, sourceId)]);
      return;
    }

    // Queued, not interleaved (`conversation.md` §5): a question asked while
    // one is running still renders as its own turn immediately — nothing
    // submitted is silently dropped — but does not start streaming until the
    // one ahead of it finishes.
    setTurns((queue) => [...queue, blankTurn(trimmed, "queued", null, sourceId)]);
  }, []);

  const stop = useCallback((): void => {
    const running = current.current.find((turn) => turn.status === "running");
    if (running === null || running === undefined || running.serverId === null) return;
    void stopAsk(running.serverId);
  }, []);

  // --- dispatch: one turn streaming at a time ------------------------------

  useEffect(() => {
    if (dispatching.current) return;
    const id = nextToDispatch(current.current);
    if (id === null) return;
    const next = current.current.find((turn) => turn.id === id);
    if (next === undefined) return;

    dispatching.current = true;
    patch(id, { status: "running" });

    void (async () => {
      let finalStatus: TurnStatus = "failed";
      let finalReason: string | null = "Askwell could not reach the assistant.";
      try {
        await streamAsk(
          next.question,
          { conversationId: null, sourceId: next.sourceId },
          (event: AskEvent) => {
            if (event.event === "done") {
              finalStatus = event.data.status;
              finalReason = event.data.reason;
              return;
            }
            // Derived from the previous turn inside the updater, never from a ref.
            // `current` is refreshed by an effect, so it lags a render behind: two
            // tokens in one frame would both read the same answer and the second
            // would overwrite the first, losing words the user was watching arrive.
            setTurns((queue) =>
              queue.map((turn) => {
                if (turn.id !== id) return turn;
                if (event.event === "citation") {
                  return { ...turn, citations: applyCitation(turn.citations, event.data) };
                }
                return { ...turn, ...applyAskEvent(turn, event) };
              }),
            );
          },
        );
      } catch (error) {
        finalStatus = "failed";
        finalReason = error instanceof Error ? error.message : finalReason;
      }
      patch(id, { status: finalStatus, reason: finalReason });
      dispatching.current = false;
    })();
  }, [turns, patch]);

  const running = turns.find((turn) => turn.status === "running") ?? null;

  const api = useMemo<AskApi>(() => ({ turns, running, ask, stop }), [turns, running, ask, stop]);

  return <AskContext.Provider value={api}>{children}</AskContext.Provider>;
}
