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
  conversationOf,
  applyAskEvent,
  type AskEvent,
  type AskModelIdentity,
  type BlockingClarification,
  liveTurnId,
  looksNonEnglish,
  nextToDispatch,
  stopAsk,
  streamAsk,
} from "@/lib/ask";
import { applyCitation, type CitationCard } from "@/lib/citations";
import { applyFactCitation, type FactChip } from "@/lib/memory-chips";
import type { SqlQueryDisclosure, SqlResultData } from "@/lib/sql-result";
import {
  createConversation,
  fetchOnlineState,
  type OnlineConversationState,
  SEND_REFUSED,
  sendAllowed,
} from "@/lib/online-conversation";
import { applyWebCitation, type WebCitationEntry, type WebResult } from "@/lib/web-citations";

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
 * **One conversation per page load.** Every event names its
 * `conversation_id` (issue 156, fixed), and the first one adopted is sent
 * back with every later question. Since `M8-ONLINE-FE-171` the conversation
 * can also be created before its first question (`ensureConversation`), so
 * it can be switched to online AI before anything is sent. A reload starts
 * a new conversation, and a new conversation is always local.
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
  steps: { label: string; kind: string; callId?: string }[];
  answer: string;
  /** One card per cited chunk, grouped by `applyCitation` (`lib/citations.ts`)
   * as `citation` events arrive — the provenance margin's own data, not
   * rendered by this module (`ProvenanceMargin`, `M1-CITE-FE-043`). */
  citations: CitationCard[];
  /** One chip per `fact_citation` event, unlike `citations` never grouped —
   * `M3-CORRECT-FE-081`, rendered inline next to the claim that cited it
   * rather than in the margin (`applyFactCitation`, `lib/memory-chips.ts`). */
  factChips: FactChip[];
  reason: string | null;
  /** When this turn was asked, for grouping under a time divider
   * (`conversation.md` §4) — never rendered per-turn, only compared between
   * turns. */
  createdAt: number;
  /** The stored one-line summary a collapsed turn shows (`M1-CONV-BE-177`).
   * `null` until the `done` event carries it, and permanently `null` for
   * the client-only non-English rejection below, which never reaches the
   * server to be summarised there. */
  summary: string | null;
  /** Distinct documents cited, or `null` if the turn abstained — never `0`.
   * A collapsed turn with `null` here renders no count at all
   * (`conversation.md` §2, §5). */
  sourceCount: number | null;
  /** A database-answered turn's row snapshot (`M4-SQL-BE-108a`), `null` for
   * everything else — a document-grounded answer, an abstention, or a
   * turn whose SQL was rejected/failed before ever executing. Set once,
   * from the `done` event, same lifecycle as `summary`/`sourceCount`.
   * `M4-RESULT-FE-109`. */
  sqlResult: SqlResultData | null;
  /** The query and outcome for a database turn that never reached
   * `sqlResult` — rejected, a failed dry run, timed out, a query-time
   * failure, or the source gone, `null` for every other turn. Mutually
   * exclusive with `sqlResult`, same `done`-event lifecycle. `M4-RESULT-FE-110`. */
  sqlQuery: SqlQueryDisclosure | null;
  /** Which database-routing state, if any, overrode this turn's abstention
   * wording — `null` for an ordinary document abstention. Set once, from
   * the `done` event, same lifecycle as `sqlResult`/`sqlQuery`.
   * `M4-RESULT-FE-111`. */
  dbState: string | null;
  /** Which model produced this turn, `null` until the `done` event carries
   * it — same lifecycle as `sqlResult`/`dbState`. `M7-SET-FE-146a`'s own
   * source for the persistent unvalidated-model marker: captured once, at
   * question time, so a turn's marking never changes after the fact even if
   * the active model is swapped again before the next question. */
  modelIdentity: AskModelIdentity | null;
  /** `M3-INLINE-FE-085`: set from a `clarification` event while this turn is
   * paused waiting for it to be answered or skipped, `null` the rest of the
   * time — including once a `clarification_resolved` event clears it and
   * composition continues. The only place a clarification interrupts is
   * this field being non-`null` on the live turn (`ask-screen.tsx`'s
   * `InlineClarification`); the queue itself is unaffected either way. */
  blocking: BlockingClarification | null;
  /** The escalation's own answer text, generated from web results alone and
   * kept apart from `answer` rather than appended to it — `answer`'s
   * emptiness is exactly what `isAbstained` reads (`lib/ask.ts`), and this
   * turn's abstention is real and must keep rendering as one even once a
   * web answer exists beside it (`M6.5-WEB-FE-191`). `null` until
   * `POST /ask/{id}/escalate/web` returns one; a second escalation on the
   * same turn appends to it rather than replacing it, so nothing already
   * rendered — and already claim-numbered — moves. */
  webAnswer: string | null;
  /** One card per cited web result, grouped by URL (`applyWebCitation`,
   * `lib/web-citations.ts`) the same way `citations` groups by chunk —
   * `WebResultsRegion`'s own data (`web-result.tsx`), never the margin's. */
  webCitations: WebResult[];
}

export interface AskApi {
  turns: AskTurn[];
  /** The turn actually streaming right now, as opposed to merely queued
   * behind one — what the composer's stop control acts on. */
  running: AskTurn | null;
  ask: (question: string, sourceId?: string | null) => void;
  stop: () => void;
  /** Which turn's trace panel is open, `null` when none is (`trace-panel.tsx`'s
   * `TraceToggle`). Held here rather than as that component's own local
   * state because it must survive the round trip through the source viewer
   * (`M5-TRACE-FE-121`'s own assumption: "returning from the viewer restores
   * the trace panel rather than closing it") — a page component, including
   * the one this toggle lives in, unmounts on every route change, and
   * `AskProvider` is the one thing here that does not (same reason `turns`
   * itself lives here, above). */
  openTraceTurnId: string | null;
  openTrace: (turnId: string) => void;
  closeTrace: () => void;
  /** Folds an escalation's own answer into `turnId`'s turn — `EscalationOffer`
   * (`ask-screen.tsx`)'s only way to reach turn state, since it is handed a
   * turn as a prop rather than the provider's own internals. Appends to any
   * `webAnswer` already there (a second escalation) rather than replacing it,
   * and folds every entry into `webCitations` via `applyWebCitation`
   * (`M6.5-WEB-FE-191`). */
  applyWebAnswer: (turnId: string, text: string, citations: readonly WebCitationEntry[]) => void;
  /** `M8-ONLINE-FE-171`: the conversation these turns belong to, `null`
   * until the server names one or `ensureConversation` creates it. */
  conversationId: string | null;
  /** The conversation's id, creating an empty local one first if there is
   * none yet, so it can be switched online before its first question. */
  ensureConversation: () => Promise<string>;
  /** Its online state as the server holds it, `null` before there is a
   * conversation to ask about. Read by the marker, the composer's gate and
   * each turn's backend label, so all three agree. */
  online: OnlineConversationState | null;
  setOnline: (state: OnlineConversationState) => void;
}

const AskContext = createContext<AskApi | null>(null);

export function useAsk(): AskApi {
  const value = useContext(AskContext);
  if (value === null) throw new Error("useAsk was called outside AskProvider.");
  return value;
}

/**
 * The turn the provenance margin belongs to (`ask.md` §8, settled): the
 * margin only ever shows one answer's citations, so it tracks whichever
 * turn `M1-CONV-FE-178`'s own collapse rule (`liveTurnId`, `lib/ask.ts`)
 * renders full rather than always the newest — the same "streaming turn
 * stays live" edge case applies to the margin beside it.
 */
export function useLiveTurn(): AskTurn | null {
  const { turns } = useAsk();
  const id = liveTurnId(turns);
  return turns.find((turn) => turn.id === id) ?? null;
}

const NON_ENGLISH_REASON =
  "Askwell answers in English in this version. Ask again in English, and it will search your files.";

function blankTurn(
  question: string,
  status: TurnStatus,
  reason: string | null = null,
  sourceId: string | null = null,
  summary: string | null = null,
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
    factChips: [],
    reason,
    createdAt: Date.now(),
    summary,
    sourceCount: null,
    sqlResult: null,
    sqlQuery: null,
    dbState: null,
    modelIdentity: null,
    blocking: null,
    webAnswer: null,
    webCitations: [],
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
  // The conversation every question after the first belongs to. Null until the
  // server names one: it resolves or creates the conversation, so the browser
  // cannot know the id until an event carries it back. A ref rather than state
  // because nothing renders from it and a re-render per token is the cost.
  const conversation = useRef<string | null>(null);
  // The same id as state, for what renders from it: the marker and the
  // switch (`M8-ONLINE-FE-171`). Set once per conversation, not per token.
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [online, setOnlineState] = useState<OnlineConversationState | null>(null);
  const onlineRef = useRef<OnlineConversationState | null>(null);

  useEffect(() => {
    current.current = turns;
  }, [turns]);

  const setOnline = useCallback((state: OnlineConversationState): void => {
    onlineRef.current = state;
    setOnlineState(state);
  }, []);

  const adoptConversation = useCallback((id: string): void => {
    if (conversation.current !== null) return;
    conversation.current = id;
    setConversationId(id);
  }, []);

  const ensureConversation = useCallback(async (): Promise<string> => {
    if (conversation.current !== null) return conversation.current;
    const id = await createConversation();
    adoptConversation(id);
    return conversation.current ?? id;
  }, [adoptConversation]);

  const refreshOnline = useCallback(async (): Promise<void> => {
    const id = conversation.current;
    if (id === null) return;
    try {
      setOnline(await fetchOnlineState(id));
    } catch {
      // Unreadable is not "online": the server refuses a send it cannot
      // authorise on its own, so the marker keeps its last reading rather
      // than inventing one.
    }
  }, [setOnline]);

  // Read when the conversation is first known, and again every minute while
  // it is online, so a lapsed authorisation reads as local without anyone
  // having to reload (`states-and-edge-cases.md` §1).
  useEffect(() => {
    if (conversationId === null) return;
    void refreshOnline();
  }, [conversationId, refreshOnline]);

  const isOnline = online?.ai_backend === "online";
  useEffect(() => {
    if (!isOnline) return;
    const timer = window.setInterval(() => void refreshOnline(), 60_000);
    return () => window.clearInterval(timer);
  }, [isOnline, refreshOnline]);

  const patch = useCallback((id: string, changes: Partial<AskTurn>): void => {
    setTurns((queue) => queue.map((turn) => (turn.id !== id ? turn : { ...turn, ...changes })));
  }, []);

  const ask = useCallback((question: string, sourceId: string | null = null): void => {
    const trimmed = question.trim();
    // No request for an empty question — the edge case named explicitly.
    if (trimmed === "") return;

    if (looksNonEnglish(trimmed)) {
      setTurns((queue) => [
        ...queue,
        blankTurn(trimmed, "failed", NON_ENGLISH_REASON, sourceId, NON_ENGLISH_REASON),
      ]);
      return;
    }

    // `M8-ONLINE-FE-171`: the composer already holds a question back while
    // the disclosure is unanswered. This is for any other caller. The
    // question is shown as not sent rather than dropped, and the server
    // would refuse it anyway.
    if (!sendAllowed(onlineRef.current)) {
      setTurns((queue) => [
        ...queue,
        blankTurn(trimmed, "failed", SEND_REFUSED, sourceId, SEND_REFUSED),
      ]);
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
      let finalSummary: string | null = null;
      let finalSourceCount: number | null = null;
      let finalSqlResult: SqlResultData | null = null;
      let finalSqlQuery: SqlQueryDisclosure | null = null;
      let finalDbState: string | null = null;
      let finalModelIdentity: AskModelIdentity | null = null;
      try {
        await streamAsk(
          next.question,
          { conversationId: conversation.current, sourceId: next.sourceId },
          (event: AskEvent) => {
            const named = conversationOf(event);
            if (named !== null) adoptConversation(named);
          if (event.event === "done") {
              finalStatus = event.data.status;
              finalReason = event.data.reason;
              finalSummary = event.data.summary ?? null;
              finalSourceCount = event.data.source_count ?? null;
              finalSqlResult = event.data.sql_result ?? null;
              finalSqlQuery = event.data.sql_query ?? null;
              finalDbState = event.data.db_state ?? null;
              finalModelIdentity = event.data.model_identity ?? null;
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
                if (event.event === "fact_citation") {
                  return { ...turn, factChips: applyFactCitation(turn.factChips, event.data) };
                }
                if (event.event === "clarification") {
                  return {
                    ...turn,
                    serverId: turn.serverId ?? event.data.message_id,
                    blocking: {
                      id: event.data.clarification_id,
                      subject: event.data.subject,
                      question: event.data.question,
                      options: event.data.options,
                      evidence: event.data.evidence,
                      deferredCount: event.data.deferred_count,
                    },
                  };
                }
                if (event.event === "clarification_resolved") {
                  return { ...turn, blocking: null };
                }
                if (event.event === "answer_reset") {
                  // issue 733: the withdrawn online half takes its cards and
                  // chips with it. The local answer starts clean.
                  return { ...turn, ...applyAskEvent(turn, event), citations: [], factChips: [] };
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
      patch(id, {
        status: finalStatus,
        reason: finalReason,
        summary: finalSummary,
        sourceCount: finalSourceCount,
        sqlResult: finalSqlResult,
        sqlQuery: finalSqlQuery,
        dbState: finalDbState,
        modelIdentity: finalModelIdentity,
      });
      dispatching.current = false;
      // A turn is when a lapse is most likely to be noticed server-side.
      void refreshOnline();
    })();
  }, [turns, patch, refreshOnline]);

  const running = turns.find((turn) => turn.status === "running") ?? null;

  const [openTraceTurnId, setOpenTraceTurnId] = useState<string | null>(null);
  const openTrace = useCallback((turnId: string): void => setOpenTraceTurnId(turnId), []);
  const closeTrace = useCallback((): void => setOpenTraceTurnId(null), []);

  const applyWebAnswer = useCallback(
    (turnId: string, text: string, citations: readonly WebCitationEntry[]): void => {
      setTurns((queue) =>
        queue.map((turn) => {
          if (turn.id !== turnId) return turn;
          const webAnswer = turn.webAnswer === null ? text : `${turn.webAnswer}\n\n${text}`;
          const webCitations = citations.reduce(applyWebCitation, turn.webCitations);
          return { ...turn, webAnswer, webCitations };
        }),
      );
    },
    [],
  );

  const api = useMemo<AskApi>(
    () => ({
      turns,
      running,
      ask,
      stop,
      openTraceTurnId,
      openTrace,
      closeTrace,
      applyWebAnswer,
      conversationId,
      ensureConversation,
      online,
      setOnline,
    }),
    [
      turns,
      running,
      ask,
      stop,
      openTraceTurnId,
      openTrace,
      closeTrace,
      applyWebAnswer,
      conversationId,
      ensureConversation,
      online,
      setOnline,
    ],
  );

  return <AskContext.Provider value={api}>{children}</AskContext.Provider>;
}
