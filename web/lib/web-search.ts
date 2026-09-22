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
 *
 * `signal`, when given, lets the caller abort mid-flight — `M6.5-WEB-FE-192`'s
 * own edge case, "the user stops generation while searching": aborting the
 * fetch disconnects the request, which is what lets `askwell.websearch`'s
 * cancelled-coroutine path (`M6.5-WEB-SEC-187`) close the egress grant the
 * same way an ordinary return or a provider failure does.
 */
export async function escalateWebSearch(
  messageId: string,
  question: string,
  signal?: AbortSignal,
): Promise<WebSearchEscalationOutcome> {
  const response = await fetch(`/ask/${messageId}/escalate/web`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ question }),
    ...(signal ? { signal } : {}),
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

/**
 * The remaining states — searching, nothing found, unavailable, closed —
 * `M6.5-WEB-FE-192` (`docs/ux/web-search.md` §4, `docs/web-search.md` §6).
 *
 * Fixed copy, exported rather than inlined at the call site, so the exact
 * wording the human-review pass checks against `docs/ux/` is asserted once
 * here rather than retyped (and silently drifting) wherever it renders.
 * `WEB_SEARCH_UNAVAILABLE` is `web-search.md` §6's own quote, verbatim.
 */
export const WEB_SEARCH_PROGRESS_LABEL =
  "Searching the web — your question has left this machine.";
export const WEB_SEARCH_NOTHING_FOUND = "Nothing found on the web either.";
export const WEB_SEARCH_UNAVAILABLE = "I can't reach the web right now.";
export const WEB_SEARCH_CLOSED_NOTE =
  "The search closed with this question — your next one starts local again.";

export type WebSearchDisplayStatus = "idle" | "sending" | "answered" | "nothing_found" | "unavailable";

/**
 * Collapses a fetch's lifecycle (`idle`/`sending`/`settled`) plus whatever
 * outcome it settled with into one of five display states.
 *
 * A settled `"ok"` with no `answerText` reads as `"nothing_found"`, not
 * `"answered"` — the ticket's own edge case: "search succeeds but every
 * result is dropped by the caps [`M6.5-WEB-BE-188`] — reads as nothing
 * usable came back, not as an answer." A missing answer is a missing
 * answer regardless of whether the provider called it `"ok"` or
 * `"no_results"`; the caller never has to know which of those two produced
 * this state, only that nothing came of it.
 */
export function webSearchDisplayStatus(
  phase: "idle" | "sending" | "settled",
  outcome: WebSearchEscalationOutcome | null,
): WebSearchDisplayStatus {
  if (phase === "idle" || phase === "sending") return phase;
  if (outcome === null) return "idle";
  if (outcome.status === "unavailable") return "unavailable";
  if (outcome.status === "no_results" || outcome.answerText === null) return "nothing_found";
  return "answered";
}

/**
 * The plain statement for a display state, `null` for `"idle"`/`"answered"` —
 * an answer speaks for itself (`WebAnswerBlock`) and an unattempted offer has
 * nothing to report yet.
 */
export function webSearchStatusMessage(status: WebSearchDisplayStatus): string | null {
  switch (status) {
    case "sending":
      return WEB_SEARCH_PROGRESS_LABEL;
    case "nothing_found":
      return WEB_SEARCH_NOTHING_FOUND;
    case "unavailable":
      return WEB_SEARCH_UNAVAILABLE;
    default:
      return null;
  }
}

/**
 * The escalation-closed note (`docs/ux/web-search.md` §4) is shown once a
 * search has actually run and settled — answered, nothing found, or
 * unavailable — and never while it is still `"sending"` or before it has
 * ever been tried. This is the "only turns that escalated get one" rule
 * from the ticket's own edge cases, expressed as one predicate rather than
 * duplicated at each call site.
 */
export function webSearchShowsClosedNote(status: WebSearchDisplayStatus): boolean {
  return status === "answered" || status === "nothing_found" || status === "unavailable";
}

/**
 * The escalation option's own cost caption, one line under its label
 * (`EscalationOption`, `ask-screen.tsx`) — kept separate from
 * `webSearchStatusMessage` because it must stay short enough to sit under a
 * button, and reads slightly differently once idle needs to say whether the
 * option is even configured.
 */
export function webSearchOptionCost(status: WebSearchDisplayStatus, available: boolean | null): string {
  switch (status) {
    case "sending":
      return "sending — your question has left this machine";
    case "answered":
      return "sent — this question only";
    case "nothing_found":
      return "sent — nothing usable came back";
    case "unavailable":
      return "could not reach the web";
    default:
      return available === false ? "not configured" : "sends your question out · this question only";
  }
}
