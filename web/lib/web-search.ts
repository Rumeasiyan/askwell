import type { WebCitationEntry } from "@/lib/web-citations";

/**
 * The escalation offer's client side. `M6.5-WEB-FE-186`, `docs/ux/web-search.md` §2.
 *
 * `askwell.websearch` (server) does the escalation itself — the egress
 * grant, the provider call, the interaction record, and, when it has
 * something to generate from, the escalation's own answer and citations
 * (`M6.5-WEB-FE-191`). This module is the offer's one point of contact with
 * all of that: whether a "search the web" click has anywhere to go at all
 * (`webSearchAvailable`), and the call that fires it (`escalateWebSearch`).
 * The states this module does *not* attempt to narrate — searching,
 * unavailable, closed — are `M6.5-WEB-FE-192`'s own ticket; this module
 * returns what the server sent and leaves rendering it to the caller.
 */

export interface WebSearchEscalationOutcome {
  status: "ok" | "no_results" | "unavailable";
  reason: string | null;
  resultCount: number;
  /** The escalation's own generated answer, `null` when there was nothing to
   * generate from (`status !== "ok"`) or the model could not be reached —
   * `M6.5-WEB-FE-191`. */
  answerText: string | null;
  /** One entry per (claim, result) pair the answer actually cited, already
   * numbered past whatever claims the turn's own answer carries
   * (`askwell.websearch.ask_escalate_web`'s own offset) — empty whenever
   * `answerText` is `null`. */
  citations: WebCitationEntry[];
}

interface RawWebCitationEntry {
  claim_ordinal: number;
  domain: string;
  title: string;
  url: string;
  passage: string;
  retrieved_at: string;
}

interface RawEscalationOutcome {
  status: "ok" | "no_results" | "unavailable";
  reason: string | null;
  result_count: number;
  answer_text: string | null;
  citations: RawWebCitationEntry[];
}

/**
 * Whether the web option has a configured provider to reach at all —
 * `GET /settings/web-search` (`askwell.websearch`). Read once per render of
 * the offer rather than only discovered after a click, so "Search unavailable"
 * (`web-search.md` §4) can be stated on the option itself, per this ticket's
 * own edge case: "the web option states that plainly rather than disappearing."
 */
export async function webSearchAvailable(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch("/settings/web-search", {
      ...(signal ? { signal } : {}),
      headers: { accept: "application/json" },
    });
    if (!response.ok) return false;
    const body = (await response.json()) as { available: boolean };
    return body.available;
  } catch {
    // Unreachable app server reads the same as "no provider" — the offer
    // states the web option is unavailable rather than throwing the whole
    // abstention surface into an error state over one optional check.
    return false;
  }
}

/**
 * Escalates one question to the web, for the turn named by `messageId` —
 * `POST /ask/{message_id}/escalate/web`. The server independently verifies
 * the turn actually abstained or answered partially before this reaches
 * `askwell.websearch.escalate_web_search`; a 409 here means this offer was
 * shown somewhere it should not have been, which is this module's own bug
 * to surface, not the user's to work around, so it is thrown rather than
 * folded into `"unavailable"`.
 */
export async function escalateWebSearch(
  messageId: string,
  question: string,
): Promise<WebSearchEscalationOutcome> {
  const response = await fetch(`/ask/${messageId}/escalate/web`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    throw new Error(`Askwell answered ${response.status} when escalating to the web.`);
  }
  const body = (await response.json()) as RawEscalationOutcome;
  return {
    status: body.status,
    reason: body.reason,
    resultCount: body.result_count,
    answerText: body.answer_text,
    citations: body.citations.map((entry) => ({
      claimOrdinal: entry.claim_ordinal,
      domain: entry.domain,
      title: entry.title,
      url: entry.url,
      passage: entry.passage,
      retrievedAt: entry.retrieved_at,
    })),
  };
}

// Local counters of offers made and offers accepted — `web-search.md` §7's
// escalation rate, computed on demand from these two, nothing transmitted
// (C1). In-memory only, same pattern as `follow-ups.ts`'s
// `followUpUsedCount`.
let offersMadeCount = 0;
let offersAcceptedCount = 0;

export function recordWebSearchOfferMade(): void {
  offersMadeCount += 1;
}

export function getWebSearchOfferMadeCount(): number {
  return offersMadeCount;
}

export function recordWebSearchOfferAccepted(): void {
  offersAcceptedCount += 1;
}

export function getWebSearchOfferAcceptedCount(): number {
  return offersAcceptedCount;
}
