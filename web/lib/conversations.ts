import type { AskTurn } from "@/components/ask/ask-state";
import type { AskModelIdentity } from "@/lib/ask";
import { applyCitation, type CitationCard } from "./citations.ts";
import type { SqlResultData } from "@/lib/sql-result";

/**
 * Past conversations, read back (issue 199). `GET /conversations` lists them;
 * `GET /conversations/{id}/turns` returns one in the shape the Ask screen's
 * own turns take, citations included, so a reopened answer still shows where
 * every claim came from (C4).
 */

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  last_activity_at: string;
  question_count: number;
  ai_backend: "local" | "online";
}

export interface ConversationPage {
  conversations: ConversationSummary[];
  next_before: string | null;
}

export interface HistoryCitation {
  claim_ordinal: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  anchor_kind: string | null;
  heading: string | null;
  page_from: number | null;
  page_to: number | null;
  passage: string | null;
  quoted_span: string | null;
  /** Why `passage` is null: the document was deleted, Askwell is locked, or
   * the stored passage no longer decrypts. */
  passage_unavailable: "deleted" | "locked" | "unreadable" | null;
}

export interface HistoryTurn {
  question_id: string;
  message_id: string | null;
  question: string;
  asked_at: string;
  answer: string;
  status: string;
  reason: string | null;
  db_state: string | null;
  summary: string | null;
  source_count: number | null;
  sql_result: SqlResultData | null;
  model_identity: AskModelIdentity | null;
  citations: HistoryCitation[];
}

export interface ConversationTurns {
  conversation: { id: string; created_at: string; ai_backend: "local" | "online" };
  turns: HistoryTurn[];
}

/** What a card says in place of a passage it can no longer show. The card
 * itself stays: the claim was cited, and that must stay visible. */
export function unavailablePassage(reason: HistoryCitation["passage_unavailable"]): string {
  if (reason === "deleted") {
    return "This document has since been removed from Askwell, so its passage can no longer be shown.";
  }
  if (reason === "locked") {
    return "Askwell is locked. Unlock it in Settings to see this passage.";
  }
  return "This passage could not be read back.";
}

const STATUSES: readonly AskTurn["status"][] = ["completed", "stopped", "failed"];

/** One stored turn as the Ask screen holds a live one, finished. */
export function turnFromHistory(turn: HistoryTurn): AskTurn {
  const citations = turn.citations.reduce<CitationCard[]>(
    (cards, citation) =>
      applyCitation(cards, {
        message_id: turn.message_id ?? "",
        index: citation.claim_ordinal,
        claim_ordinal: citation.claim_ordinal,
        chunk_id: citation.chunk_id,
        document_id: citation.document_id,
        filename: citation.filename,
        anchor_kind: citation.anchor_kind,
        heading: citation.heading,
        page_from: citation.page_from,
        page_to: citation.page_to,
        passage: citation.passage ?? unavailablePassage(citation.passage_unavailable),
        quoted_span: citation.passage === null ? null : citation.quoted_span,
      }),
    [],
  );
  const status = (STATUSES as readonly string[]).includes(turn.status)
    ? (turn.status as AskTurn["status"])
    : "failed";
  return {
    id: turn.question_id,
    serverId: turn.message_id,
    question: turn.question,
    sourceId: null,
    status,
    steps: [],
    answer: turn.answer,
    citations,
    factChips: [],
    reason: turn.reason ?? (status === "failed" ? "This answer did not finish." : null),
    createdAt: Date.parse(turn.asked_at),
    summary: turn.summary,
    sourceCount: turn.source_count,
    sqlResult: turn.sql_result,
    sqlQuery: null,
    dbState: turn.db_state,
    modelIdentity: turn.model_identity,
    blocking: null,
    webAnswer: null,
    webCitations: [],
  };
}

function isPage(body: unknown): body is ConversationPage {
  return (
    typeof body === "object" &&
    body !== null &&
    Array.isArray((body as ConversationPage).conversations) &&
    "next_before" in body
  );
}

function isTurns(body: unknown): body is ConversationTurns {
  return (
    typeof body === "object" &&
    body !== null &&
    Array.isArray((body as ConversationTurns).turns) &&
    typeof (body as ConversationTurns).conversation?.id === "string"
  );
}

export async function fetchConversations(
  before: string | null = null,
  signal?: AbortSignal,
): Promise<ConversationPage> {
  const query = before === null ? "" : `?before=${encodeURIComponent(before)}`;
  const response = await fetch(`/conversations${query}`, {
    headers: { accept: "application/json" },
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) throw new Error(`Askwell answered ${response.status} when listing conversations.`);
  const body: unknown = await response.json();
  if (!isPage(body)) throw new Error("Askwell sent a conversation list it could not read.");
  return body;
}

export async function fetchConversationTurns(
  id: string,
  signal?: AbortSignal,
): Promise<ConversationTurns> {
  const response = await fetch(`/conversations/${encodeURIComponent(id)}/turns`, {
    headers: { accept: "application/json" },
    ...(signal ? { signal } : {}),
  });
  if (response.status === 404) throw new Error("This conversation no longer exists.");
  if (!response.ok) throw new Error(`Askwell answered ${response.status} when opening the conversation.`);
  const body: unknown = await response.json();
  if (!isTurns(body)) throw new Error("Askwell sent a conversation it could not read.");
  return body;
}
