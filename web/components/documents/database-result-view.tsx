"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAsk } from "@/components/ask/ask-state";
import { SqlResultTable } from "@/components/ask/sql-result-table";
import { readSseEvents } from "@/lib/ask";
import type { SqlResultData } from "@/lib/sql-result";

type LoadState = { kind: "loading" } | { kind: "error" } | { kind: "loaded"; result: SqlResultData };

/**
 * The source viewer's database row (`docs/ux/source-viewer.md` §2: "The
 * table with the query's rows, plus the query"). `M4-RESULT-FE-109`.
 *
 * Reads the live turn out of `AskProvider` first, exactly as `ContextRail`
 * does — the same in-memory snapshot the answer itself rendered from, so
 * "the page the user reads is internally consistent" (this ticket's own
 * assumption) holds here too, not just inline. A reload drops that
 * in-memory state (`AskProvider` lives above the router but not past a full
 * page reload), so the fallback replays `GET /ask/{message_id}/stream` —
 * `askwell.ask`'s own replay path for a finished turn — which answers with
 * the identical stored `sql_result`, never a fresh query.
 */
export function DatabaseResultView({
  messageId,
  turnId,
}: {
  messageId: string;
  turnId: string | null;
}) {
  const { turns } = useAsk();
  const liveTurn = turnId !== null ? (turns.find((turn) => turn.id === turnId) ?? null) : null;

  const [fetched, setFetched] = useState<{ messageId: string; state: LoadState } | null>(null);

  useEffect(() => {
    if (liveTurn?.sqlResult != null) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/ask/${messageId}/stream`, { cache: "no-store" });
        if (!response.ok) {
          if (!cancelled) setFetched({ messageId, state: { kind: "error" } });
          return;
        }
        for await (const event of readSseEvents(response)) {
          if (event.event === "done") {
            if (!cancelled) {
              setFetched(
                event.data.sql_result != null
                  ? { messageId, state: { kind: "loaded", result: event.data.sql_result } }
                  : { messageId, state: { kind: "error" } },
              );
            }
            return;
          }
        }
        if (!cancelled) setFetched({ messageId, state: { kind: "error" } });
      } catch {
        if (!cancelled) setFetched({ messageId, state: { kind: "error" } });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [messageId, liveTurn]);

  const fetchedState = fetched?.messageId === messageId ? fetched.state : { kind: "loading" as const };
  const result = liveTurn?.sqlResult ?? (fetchedState.kind === "loaded" ? fetchedState.result : null);

  if (result === null) {
    if (fetchedState.kind === "error") {
      return (
        <section className="flex flex-col gap-2 p-4">
          <p className="ask-prose">This result could not be opened.</p>
        </section>
      );
    }
    return <p className="ask-micro p-4">Opening…</p>;
  }

  return (
    <div className="flex min-w-0 flex-1 gap-4">
      <section className="flex min-w-0 flex-1 flex-col gap-3 p-4">
        <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
          Database result
        </h1>
        {liveTurn !== null ? (
          <p className="ask-micro" style={{ textTransform: "none", color: "var(--muted)" }}>
            {liveTurn.question}
          </p>
        ) : null}
        <SqlResultTable result={result} messageId={null} turnId={turnId ?? messageId} />
      </section>
      <aside
        className="hidden shrink-0 flex-col gap-4 overflow-y-auto p-4 @3xl:flex"
        style={{ width: "var(--margin-rail)", borderLeft: "1px solid var(--rule)" }}
      >
        <Link
          href="/"
          className="ask-navigates w-fit px-3 py-1"
          style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
        >
          Back to answer
        </Link>
      </aside>
    </div>
  );
}
