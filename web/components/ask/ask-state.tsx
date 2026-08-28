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

import { type AskEvent, looksNonEnglish, nextToDispatch, stopAsk, streamAsk } from "@/lib/ask";

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
  status: TurnStatus;
  steps: { label: string; kind: string }[];
  answer: string;
  citationCount: number;
  reason: string | null;
}

export interface AskApi {
  turns: AskTurn[];
  /** The turn actually streaming right now, as opposed to merely queued
   * behind one — what the composer's stop control acts on. */
  running: AskTurn | null;
  ask: (question: string) => void;
  stop: () => void;
}

const AskContext = createContext<AskApi | null>(null);

export function useAsk(): AskApi {
  const value = useContext(AskContext);
  if (value === null) throw new Error("useAsk was called outside AskProvider.");
  return value;
}

const NON_ENGLISH_REASON =
  "Askwell answers in English in this version. Ask again in English, and it will search your files.";

function blankTurn(question: string, status: TurnStatus, reason: string | null = null): AskTurn {
  return {
    id: crypto.randomUUID(),
    serverId: null,
    question,
    status,
    steps: [],
    answer: "",
    citationCount: 0,
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

  const ask = useCallback((question: string): void => {
    const trimmed = question.trim();
    // No request for an empty question — the edge case named explicitly.
    if (trimmed === "") return;

    if (looksNonEnglish(trimmed)) {
      setTurns((queue) => [...queue, blankTurn(trimmed, "failed", NON_ENGLISH_REASON)]);
      return;
    }

    // Queued, not interleaved (`conversation.md` §5): a question asked while
    // one is running still renders as its own turn immediately — nothing
    // submitted is silently dropped — but does not start streaming until the
    // one ahead of it finishes.
    setTurns((queue) => [...queue, blankTurn(trimmed, "queued")]);
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

    const seenCitations = new Set<number>();

    void (async () => {
      let finalStatus: TurnStatus = "failed";
      let finalReason: string | null = "Askwell could not reach the assistant.";
      try {
        await streamAsk(next.question, { conversationId: null }, (event: AskEvent) => {
          const found = current.current.find((turn) => turn.id === id);
          switch (event.event) {
            case "step":
              patch(id, {
                serverId: found?.serverId ?? event.data.message_id,
                steps: [...(found?.steps ?? []), { label: event.data.label, kind: event.data.kind }],
              });
              break;
            case "token":
              patch(id, { answer: (found?.answer ?? "") + event.data.text });
              break;
            case "citation":
              if (seenCitations.has(event.data.index)) return;
              seenCitations.add(event.data.index);
              patch(id, { citationCount: (found?.citationCount ?? 0) + 1 });
              break;
            case "done":
              finalStatus = event.data.status;
              finalReason = event.data.reason;
              break;
          }
        });
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
