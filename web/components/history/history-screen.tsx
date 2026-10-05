"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAsk } from "@/components/ask/ask-state";
import {
  type ConversationSummary,
  fetchConversations,
  fetchConversationTurns,
  turnFromHistory,
} from "@/lib/conversations";
import { switchLocal } from "@/lib/online-conversation";

/**
 * `/history` — past conversations, newest first (issue 199).
 *
 * Opening one reads its turns back with their citations, hands them to the
 * Ask screen and goes there; the next question continues it. A conversation
 * that used online AI is switched back to local *before* it is shown, and is
 * not opened at all if that fails (C1: online is a deliberate act for a
 * conversation, never inherited by reopening it later).
 *
 * States (`states-and-edge-cases.md` §7.1): reading, nothing yet, the list
 * could not be read (said, with a retry — never an empty list that reads as
 * "no history"), older ones could not be read, a conversation could not be
 * opened.
 */
export function HistoryScreen() {
  const router = useRouter();
  const { openConversation, conversationId } = useAsk();
  const [rows, setRows] = useState<ConversationSummary[] | null>(null);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreFailure, setMoreFailure] = useState<string | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [openFailure, setOpenFailure] = useState<{ id: string; message: string } | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    fetchConversations(null, signal)
      .then((page) => {
        setRows(page.conversations);
        setNextBefore(page.next_before);
      })
      .catch((error: unknown) => {
        if (signal?.aborted) return;
        setFailure(error instanceof Error ? error.message : "Askwell is not answering.");
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const retry = () => {
    setFailure(null);
    setRows(null);
    load();
  };

  const loadOlder = async () => {
    if (nextBefore === null) return;
    setLoadingMore(true);
    setMoreFailure(null);
    try {
      const page = await fetchConversations(nextBefore);
      setRows((existing) => [...(existing ?? []), ...page.conversations]);
      setNextBefore(page.next_before);
    } catch (error) {
      setMoreFailure(error instanceof Error ? error.message : "Askwell is not answering.");
    } finally {
      setLoadingMore(false);
    }
  };

  const open = async (row: ConversationSummary) => {
    setOpening(row.id);
    setOpenFailure(null);
    try {
      if (row.ai_backend === "online") {
        const state = await switchLocal(row.id);
        if (state.ai_backend !== "local") throw new Error("It could not be switched back to local.");
      }
      const body = await fetchConversationTurns(row.id);
      openConversation(row.id, body.turns.map(turnFromHistory));
      router.push("/");
    } catch (error) {
      setOpenFailure({
        id: row.id,
        message: error instanceof Error ? error.message : "Askwell is not answering.",
      });
    } finally {
      setOpening(null);
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>History</h1>
        <p className="ask-prose mt-1" style={{ color: "var(--muted)" }}>
          Your earlier conversations. Open one to read it again or carry on asking.
        </p>
      </div>

      {failure !== null ? (
        <div className="flex flex-col gap-2">
          <p className="ask-prose" style={{ color: "var(--alarm)" }}>
            Askwell could not read your earlier conversations. {failure}
          </p>
          <div>
            <button
              type="button"
              onClick={retry}
              className="ask-navigates px-3 py-1"
              style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
            >
              Try again
            </button>
          </div>
        </div>
      ) : rows === null ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          Reading your conversations…
        </p>
      ) : rows.length === 0 ? (
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          No conversations yet. Questions you ask on the Ask screen appear here.
        </p>
      ) : (
        <>
          <ul className="flex flex-col gap-2 list-none p-0">
            {rows.map((row) => (
              <li key={row.id}>
                <button
                  type="button"
                  onClick={() => void open(row)}
                  disabled={opening !== null}
                  aria-current={row.id === conversationId ? "true" : undefined}
                  className="ask-navigates flex w-full flex-col items-start gap-1 px-3 py-2 text-left"
                  style={{
                    border: "1px solid var(--rule)",
                    background: row.id === conversationId ? "var(--sunk)" : "transparent",
                  }}
                >
                  <span className="ask-prose" style={{ color: "var(--ink)" }}>
                    {row.title}
                  </span>
                  <span className="ask-micro" style={{ color: "var(--muted)" }}>
                    {when(row.last_activity_at)} · {questions(row.question_count)}
                    {row.id === conversationId ? " · open now" : ""}
                    {opening === row.id ? " · opening…" : ""}
                  </span>
                </button>
                {openFailure?.id === row.id ? (
                  <p className="ask-micro mt-1" style={{ color: "var(--alarm)" }}>
                    Could not open this conversation. {openFailure.message}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>

          {nextBefore !== null ? (
            <div className="flex flex-col gap-1">
              <div>
                <button
                  type="button"
                  onClick={() => void loadOlder()}
                  disabled={loadingMore}
                  className="ask-navigates px-3 py-1"
                  style={{ border: "1px solid var(--rule)", fontSize: "var(--t-ui)" }}
                >
                  {loadingMore ? "Reading…" : "Show older conversations"}
                </button>
              </div>
              {moreFailure !== null ? (
                <p className="ask-micro" style={{ color: "var(--alarm)" }}>
                  Older conversations could not be read. {moreFailure}
                </p>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function questions(count: number): string {
  return count === 1 ? "1 question" : `${count} questions`;
}

function when(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
