/**
 * The escalation offer's client side. `M6.5-WEB-FE-186`, `docs/ux/web-search.md` §2.
 *
 * `askwell.websearch` (server) does the escalation itself — the egress
 * grant, the provider call, the interaction record. This module is the one
 * thing the offer needs before that: whether a "search the web" click has
 * anywhere to go at all (`webSearchAvailable`), and the call that fires it
 * (`escalateWebSearch`). Rendering what the search actually found is
 * `M6.5-WEB-FE-192`'s own ticket — this module stops at "sent" or "could not
 * be sent," which is all `EscalationOffer` needs to update its own caption.
 */

export interface WebSearchEscalationOutcome {
  status: "ok" | "no_results" | "unavailable";
  reason: string | null;
  resultCount: number;
}

interface RawEscalationOutcome {
  status: "ok" | "no_results" | "unavailable";
  reason: string | null;
  result_count: number;
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
  return { status: body.status, reason: body.reason, resultCount: body.result_count };
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
