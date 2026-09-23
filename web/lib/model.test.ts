/**
 * `fetchModelState` and `selectModel` — the two calls `model-swap.tsx`
 * makes against `GET`/`POST /model`. `M7-SET-FE-146`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { fetchModelState, getModelSwapCount, recordModelSwapped, selectModel } from "./model.ts";

function withFetch<T>(reply: () => Response, body: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => reply()) as typeof fetch;
  return body().finally(() => {
    globalThis.fetch = original;
  });
}

test("fetchModelState returns the parsed model state", () => {
  return withFetch(
    () =>
      new Response(
        JSON.stringify({
          source: "shipped",
          display_name: "Test model",
          user_model_path: null,
          expected_path: "/models/model.gguf",
          alternatives: [],
          active_model_size_gb: 1.5,
        }),
        { status: 200 },
      ),
    () =>
      fetchModelState().then((state) => {
        assert.equal(state.source, "shipped");
        assert.equal(state.active_model_size_gb, 1.5);
      }),
  );
});

test("fetchModelState throws with the status code when the request fails", () => {
  return withFetch(
    () => new Response("nope", { status: 500 }),
    () => assert.rejects(fetchModelState(), /500/),
  );
});

test("selectModel throws the server's own reason on a 422 rejection", () => {
  return withFetch(
    () => new Response(JSON.stringify({ error: "not a GGUF file" }), { status: 422 }),
    () => assert.rejects(selectModel("/tmp/not-a-model.txt"), /not a GGUF file/),
  );
});

test("selectModel returns the outcome, including a failed swap's reason", () => {
  return withFetch(
    () =>
      new Response(
        JSON.stringify({
          ok: false,
          reason: "out of memory",
          model_path: "/models/big.gguf",
          size_warning: null,
        }),
        { status: 409 },
      ),
    () =>
      selectModel("/models/big.gguf").then((outcome) => {
        assert.equal(outcome.ok, false);
        assert.equal(outcome.reason, "out of memory");
      }),
  );
});

test("the swap counter is local, in-memory, and counts every recorded swap", () => {
  const before = getModelSwapCount();
  recordModelSwapped();
  recordModelSwapped();
  assert.equal(getModelSwapCount(), before + 2);
});
