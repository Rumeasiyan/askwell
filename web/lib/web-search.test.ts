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
        JSON.stringify({ status: "ok", reason: null, result_count: 3 }),
        { status: 200 },
      ),
    () =>
      escalateWebSearch("message-1", "what changed in the 2026 tariff schedule?").then(
        (outcome) => {
          assert.deepEqual(outcome, { status: "ok", reason: null, resultCount: 3 });
        },
      ),
  );
});

test("escalateWebSearch throws on a non-2xx response rather than folding it into an outcome", () => {
  return withFetch(
    () => new Response(JSON.stringify({ error: "not abstained" }), { status: 409 }),
    () => assert.rejects(() => escalateWebSearch("message-1", "q")),
  );
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
