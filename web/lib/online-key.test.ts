/**
 * Settings → Online AI → the key. `M8-KEY-FE-174`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { afterEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  entryProblem,
  fetchKeyStatus,
  KEY_COST,
  KEY_PURPOSE,
  KEY_STORAGE,
  KEY_UNSET,
  KeyLocked,
  keySetLine,
  LOCKED_FIRST,
  REMOVE_CONSEQUENCE,
  REMOVED,
  removeKey,
  REPLACE_CONSEQUENCE,
  SAVED,
  storeKey,
  type KeyStatus,
} from "./online-key.ts";
import { unlockPassphrase } from "./passphrase.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const CONTROL = readFileSync(join(WEB, "components", "settings", "online-key.tsx"), "utf8");
const SECTION = readFileSync(join(WEB, "components", "settings", "online-ai.tsx"), "utf8");

const SENTINEL = "sk-SENTINEL-4f9c2a7e1b";

const SET: KeyStatus = {
  set: true,
  provider: { destination: "api.provider.example:443", model: "big-model-1" },
  available: false,
  unavailable_reason: null,
};

const UNSET: KeyStatus = { set: false, provider: null, available: false, unavailable_reason: "No key." };

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const realFetch = globalThis.fetch;
let calls: Call[] = [];

function answer(status: number, body: unknown): void {
  calls = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as typeof fetch;
}

afterEach(() => {
  globalThis.fetch = realFetch;
});

// --- entry ---------------------------------------------------------------------

test("a key is stored with a PUT whose body carries it, never the URL", async () => {
  answer(200, SET);
  const status = await storeKey("api.provider.example:443", "big-model-1", SENTINEL);
  assert.equal(calls.length, 1);
  assert.equal(calls[0]!.url, "/settings/online-key");
  assert.doesNotMatch(calls[0]!.url, new RegExp(SENTINEL));
  assert.equal(calls[0]!.init?.method, "PUT");
  assert.deepEqual(JSON.parse(String(calls[0]!.init?.body)), {
    destination: "api.provider.example:443",
    model: "big-model-1",
    api_key: SENTINEL,
  });
  assert.equal(status.set, true);
});

test("the set state names the provider and never holds the key", async () => {
  answer(200, SET);
  const status = await fetchKeyStatus();
  assert.doesNotMatch(JSON.stringify(status), new RegExp(SENTINEL));
  assert.equal(keySetLine(status.provider), "A key is set for api.provider.example:443, asking for big-model-1.");
  assert.match(KEY_UNSET, /No key is set/);
});

test("remove is a DELETE, and the section returns to its unset state", async () => {
  answer(200, UNSET);
  const status = await removeKey();
  assert.equal(calls[0]!.init?.method, "DELETE");
  assert.equal(calls[0]!.url, "/settings/online-key");
  assert.equal(status.set, false);
  assert.match(REMOVED, /no longer on this machine/);
});

test("a locked install is its own error, so the form can ask for the passphrase", async () => {
  answer(423, { error: "Online AI is not available until Askwell is unlocked." });
  await assert.rejects(storeKey("api.provider.example:443", "m", SENTINEL), KeyLocked);
  assert.match(LOCKED_FIRST, /passphrase is needed first/);
});

test("unlocking from the key form posts the passphrase in the body, and a wrong one is refused as the server says", async () => {
  answer(200, { locked: false });
  const status = await unlockPassphrase("correct horse");
  assert.equal(calls[0]!.url, "/settings/passphrase/unlock");
  assert.equal(calls[0]!.init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0]!.init?.body)), { passphrase: "correct horse" });
  assert.deepEqual(status, { enabled: true, locked: false });
  answer(401, { error: "That passphrase is not correct." });
  await assert.rejects(unlockPassphrase("wrong"), /That passphrase is not correct\./);
});

test("the server's refusal is shown as it comes", async () => {
  answer(400, { error: "The model name must be 1 to 128 letters." });
  await assert.rejects(storeKey("api.provider.example:443", "m", SENTINEL), (error: Error) => {
    assert.ok(!(error instanceof KeyLocked));
    assert.equal(error.message, "The model name must be 1 to 128 letters.");
    return true;
  });
});

// --- refused at entry, with the reason -------------------------------------------

test("whitespace is refused before anything is sent, and the reason is named", () => {
  const ok = ["api.provider.example:443", "big-model-1"] as const;
  assert.match(entryProblem(...ok, "   ") ?? "", /only spaces or line breaks/);
  assert.match(entryProblem(...ok, "\n\t") ?? "", /only spaces or line breaks/);
  assert.match(entryProblem(...ok, ` ${SENTINEL}\n`) ?? "", /space or line break in it/);
  assert.match(entryProblem(...ok, "sk-abc def") ?? "", /space or line break in it/);
  assert.match(entryProblem(...ok, "") ?? "", /Paste the key/);
  assert.equal(entryProblem(...ok, SENTINEL), null);
});

test("a refusal never repeats the key", () => {
  const padded = ` ${SENTINEL} `;
  const reason = entryProblem("api.provider.example:443", "big-model-1", padded);
  assert.ok(reason !== null);
  assert.doesNotMatch(reason, new RegExp(SENTINEL));
});

test("the provider address and model are required and have no spaces", () => {
  assert.match(entryProblem("", "m", SENTINEL) ?? "", /provider's address/);
  assert.match(entryProblem("api.example .com:443", "m", SENTINEL) ?? "", /address has a space/);
  assert.match(entryProblem("api.example.com:443", " ", SENTINEL) ?? "", /name of the model/);
  assert.match(entryProblem("api.example.com:443", "big model", SENTINEL) ?? "", /model name has a space/);
});

// --- what it is for ------------------------------------------------------------

test("the explanation names what is sent, where, and when", () => {
  assert.match(KEY_PURPOSE, /only in a conversation you have switched to online yourself/);
  assert.match(KEY_PURPOSE, /only after that conversation has told you exactly what a question will send/);
  assert.match(KEY_PURPOSE, /provider address you enter below and nowhere else/);
  assert.match(KEY_PURPOSE, /stays on this machine/);
});

test("Askwell takes no part in the cost", () => {
  assert.match(KEY_COST, /between you and your provider/);
  assert.match(KEY_COST, /Askwell sells nothing/);
  assert.match(KEY_COST, /takes no part/);
  for (const text of [KEY_PURPOSE, KEY_COST, KEY_STORAGE]) {
    assert.doesNotMatch(text, /credit|purchase|balance|spending limit|price/i);
  }
});

test("storage says it is never shown again, logged or exported, and not checked with the provider", () => {
  assert.match(KEY_STORAGE, /encrypted on this machine/);
  assert.match(KEY_STORAGE, /never shown again/);
  assert.match(KEY_STORAGE, /never logged and never exported/);
  assert.match(KEY_STORAGE, /does not check it with the provider/);
  assert.match(SAVED, /will not be shown again/);
});

test("replace and remove state what they do to online conversations before they are pressed", () => {
  assert.match(REMOVE_CONSEQUENCE, /goes back to local at once/);
  assert.match(REPLACE_CONSEQUENCE, /different provider address/);
  assert.match(CONTROL, /\{REMOVE_CONSEQUENCE\}/);
  assert.match(CONTROL, /\{REPLACE_CONSEQUENCE\}/);
});

test("the explanation is above the field, so it is read before a paste", () => {
  const purpose = SECTION.indexOf("{KEY_PURPOSE}");
  const control = SECTION.indexOf("<OnlineKey />");
  assert.ok(purpose >= 0 && control > purpose);
});

// --- never shown again ---------------------------------------------------------

test("the key field is a password field, emptied once the save returns", () => {
  const keyInput = CONTROL.match(/<input(?:(?!\/>).)*value=\{apiKey\}(?:(?!\/>).)*\/>/s)?.[0] ?? "";
  assert.match(keyInput, /type="password"/);
  assert.match(keyInput, /autoComplete="off"/);
  const save = CONTROL.slice(CONTROL.indexOf("const save ="), CONTROL.indexOf("if (locked === null)"));
  const saved = save.slice(save.indexOf(".then("));
  assert.ok(saved.indexOf('setApiKey("")') >= 0 && saved.indexOf('setApiKey("")') < saved.indexOf("onSaved("));
});

test("the key is never rendered, kept in the browser, or put in a URL", () => {
  // Rendered only as the password field's value, never as text.
  const rendered = [...CONTROL.matchAll(/(\w*=)?\{apiKey\}/g)].map((match) => match[0]);
  assert.deepEqual(rendered, ["value={apiKey}"]);
  assert.doesNotMatch(CONTROL, /localStorage|sessionStorage|document\.cookie|searchParams|URLSearchParams/);
  assert.doesNotMatch(CONTROL, /console\./);
  assert.doesNotMatch(readFileSync(join(WEB, "lib", "online-key.ts"), "utf8"), /fetch\(`/);
});
