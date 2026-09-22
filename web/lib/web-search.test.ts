/**
 * `lib/web-search.ts` — the escalation offer's client side. `M6.5-WEB-FE-186`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 *
 * Issue 535: this file existed once before without ever running under
 * `pnpm test` — `web/package.json`'s `test` script hardcodes an explicit
 * file list rather than globbing, so a new `*.test.ts` silently never
 * executes unless added there too. It is added in the same change as this
 * file.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  escalateWebSearch,
  getWebSearchOfferAcceptedCount,
  getWebSearchOfferMadeCount,
  recordWebSearchOfferAccepted,
  recordWebSearchOfferMade,
  webSearchAvailable,
  webSearchDisplayStatus,
  webSearchOptionCost,
  webSearchShowsClosedNote,
  webSearchStatusMessage,
  WEB_SEARCH_NOTHING_FOUND,
  WEB_SEARCH_UNAVAILABLE,
  type WebSearchEscalationOutcome,
} from "./web-search.ts";

function withFetch<T>(reply: () => Response, body: () => T): T {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => reply()) as typeof fetch;
  try {
    return body();
  } finally {
    globalThis.fetch = original;
  }
}

test("webSearchAvailable reflects a configured provider", () => {
  return withFetch(
    () => new Response(JSON.stringify({ available: true }), { status: 200 }),
    () => webSearchAvailable().then((available) => assert.equal(available, true)),
  );
});

test("webSearchAvailable reflects no provider configured", () => {
  return withFetch(
    () => new Response(JSON.stringify({ available: false }), { status: 200 }),
    () => webSearchAvailable().then((available) => assert.equal(available, false)),
  );
});

test("webSearchAvailable treats an unreachable server as unavailable, not a throw", () => {
  return withFetch(
    () => new Response("nope", { status: 500 }),
    () => webSearchAvailable().then((available) => assert.equal(available, false)),
  );
});

test("escalateWebSearch maps the server's snake_case outcome", () => {
  return withFetch(
    () =>
      new Response(
        JSON.stringify({
          status: "ok",
          reason: null,
          result_count: 3,
          answer_text: null,
          citations: [],
        }),
        { status: 200 },
      ),
    () =>
      escalateWebSearch("message-1", "what changed in the 2026 tariff schedule?").then(
        (outcome) => {
          assert.deepEqual(outcome, {
            status: "ok",
            reason: null,
            resultCount: 3,
            answerText: null,
            citations: [],
          });
        },
      ),
  );
});

test("escalateWebSearch maps a generated answer's citations, ordinal included", () => {
  return withFetch(
    () =>
      new Response(
        JSON.stringify({
          status: "ok",
          reason: null,
          result_count: 1,
          answer_text: "The statutory minimum is four weeks [1].",
          citations: [
            {
              claim_ordinal: 1,
              domain: "gov.example",
              title: "Notice periods",
              url: "https://gov.example/notice",
              passage: "Four weeks is the statutory minimum.",
              retrieved_at: "2026-09-22T10:00:00Z",
            },
          ],
        }),
        { status: 200 },
      ),
    () =>
      escalateWebSearch("message-1", "what is the statutory minimum notice?").then((outcome) => {
        assert.equal(outcome.answerText, "The statutory minimum is four weeks [1].");
        assert.deepEqual(outcome.citations, [
          {
            claimOrdinal: 1,
            domain: "gov.example",
            title: "Notice periods",
            url: "https://gov.example/notice",
            passage: "Four weeks is the statutory minimum.",
            retrievedAt: "2026-09-22T10:00:00Z",
          },
        ]);
      }),
  );
});

test("escalateWebSearch throws on a non-2xx response rather than folding it into an outcome", () => {
  return withFetch(
    () => new Response(JSON.stringify({ error: "not abstained" }), { status: 409 }),
    () => assert.rejects(() => escalateWebSearch("message-1", "q")),
  );
});

test("escalateWebSearch forwards an abort signal so stopping mid-search disconnects the request", () => {
  const controller = new AbortController();
  let capturedInit: RequestInit | undefined;
  const original = globalThis.fetch;
  globalThis.fetch = ((_url: string, init?: RequestInit) => {
    capturedInit = init;
    controller.abort();
    return Promise.reject(new DOMException("Aborted", "AbortError"));
  }) as typeof fetch;
  return escalateWebSearch("message-1", "q", controller.signal)
    .then(
      () => assert.fail("expected the aborted fetch to reject"),
      (error: unknown) => {
        assert.ok(error instanceof DOMException);
        assert.equal((error as DOMException).name, "AbortError");
      },
    )
    .finally(() => {
      globalThis.fetch = original;
      assert.equal(capturedInit?.signal, controller.signal);
    });
});

test("webSearchDisplayStatus: idle and sending pass through untouched", () => {
  assert.equal(webSearchDisplayStatus("idle", null), "idle");
  assert.equal(webSearchDisplayStatus("sending", null), "sending");
});

test("webSearchDisplayStatus: settled ok with a generated answer reads as answered", () => {
  const outcome: WebSearchEscalationOutcome = {
    status: "ok",
    reason: null,
    resultCount: 1,
    answerText: "The statutory minimum is four weeks [1].",
    citations: [],
  };
  assert.equal(webSearchDisplayStatus("settled", outcome), "answered");
});

test("webSearchDisplayStatus: settled ok with no generated answer reads as nothing_found, not answered", () => {
  // `M6.5-WEB-BE-188`'s caps can drop every fetched page, leaving a
  // provider-level "ok" with nothing left to cite — the ticket's own edge
  // case: this must read as nothing usable came back, never as an answer.
  const outcome: WebSearchEscalationOutcome = {
    status: "ok",
    reason: null,
    resultCount: 2,
    answerText: null,
    citations: [],
  };
  assert.equal(webSearchDisplayStatus("settled", outcome), "nothing_found");
});

test("webSearchDisplayStatus: settled no_results reads as nothing_found", () => {
  const outcome: WebSearchEscalationOutcome = {
    status: "no_results",
    reason: null,
    resultCount: 0,
    answerText: null,
    citations: [],
  };
  assert.equal(webSearchDisplayStatus("settled", outcome), "nothing_found");
});

test("webSearchDisplayStatus: settled unavailable stays unavailable", () => {
  const outcome: WebSearchEscalationOutcome = {
    status: "unavailable",
    reason: "timed out",
    resultCount: 0,
    answerText: null,
    citations: [],
  };
  assert.equal(webSearchDisplayStatus("settled", outcome), "unavailable");
});

test("webSearchStatusMessage: nothing_found and unavailable never share the same wording", () => {
  const nothingFound = webSearchStatusMessage("nothing_found");
  const unavailable = webSearchStatusMessage("unavailable");
  assert.equal(nothingFound, WEB_SEARCH_NOTHING_FOUND);
  assert.equal(unavailable, WEB_SEARCH_UNAVAILABLE);
  assert.notEqual(nothingFound, unavailable);
});

test("webSearchStatusMessage: the exact unavailable copy from docs/web-search.md §6", () => {
  assert.equal(webSearchStatusMessage("unavailable"), "I can't reach the web right now.");
});

test("webSearchStatusMessage: idle and answered say nothing extra — the answer or the button speaks for itself", () => {
  assert.equal(webSearchStatusMessage("idle"), null);
  assert.equal(webSearchStatusMessage("answered"), null);
});

test("webSearchShowsClosedNote: only a settled outcome closes — never while unattempted or still sending", () => {
  assert.equal(webSearchShowsClosedNote("idle"), false);
  assert.equal(webSearchShowsClosedNote("sending"), false);
  assert.equal(webSearchShowsClosedNote("answered"), true);
  assert.equal(webSearchShowsClosedNote("nothing_found"), true);
  assert.equal(webSearchShowsClosedNote("unavailable"), true);
});

test("webSearchOptionCost: unconfigured is distinguishable from every settled outcome", () => {
  const costs = new Set([
    webSearchOptionCost("idle", false),
    webSearchOptionCost("sending", null),
    webSearchOptionCost("answered", null),
    webSearchOptionCost("nothing_found", null),
    webSearchOptionCost("unavailable", null),
  ]);
  assert.equal(costs.size, 5);
});

test("offer counters count independently of each other", () => {
  const madeBefore = getWebSearchOfferMadeCount();
  const acceptedBefore = getWebSearchOfferAcceptedCount();
  recordWebSearchOfferMade();
  recordWebSearchOfferMade();
  assert.equal(getWebSearchOfferMadeCount(), madeBefore + 2);
  assert.equal(getWebSearchOfferAcceptedCount(), acceptedBefore);
  recordWebSearchOfferAccepted();
  assert.equal(getWebSearchOfferAcceptedCount(), acceptedBefore + 1);
});
