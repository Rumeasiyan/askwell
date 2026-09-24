/**
 * Settings → Online AI. `M7-SET-FE-150`, and `M8-ONLINE-FE-171` for the
 * absence of a global switch.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  ONLINE_AI_KEY,
  ONLINE_AI_PAYLOAD,
  ONLINE_AI_PER_CONVERSATION,
  ONLINE_AI_WHAT,
  ONLINE_AI_WHERE,
} from "./online-ai.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const COMPONENT = readFileSync(join(WEB, "components", "settings", "online-ai.tsx"), "utf8");
const PAGE = readFileSync(join(WEB, "app", "settings", "page.tsx"), "utf8");

test("there is no global online setting: no switch, and it says where the switch is", () => {
  // M8-ONLINE-FE-171's acceptance criterion. A switch here would be the
  // setting nobody remembers turning on.
  assert.doesNotMatch(COMPONENT, /role="switch"/);
  assert.doesNotMatch(COMPONENT, /<button\b/);
  assert.match(ONLINE_AI_WHERE, /no switch here/);
  assert.match(ONLINE_AI_WHERE, /one conversation at a time/);
  assert.match(ONLINE_AI_WHERE, /every new conversation starts local/);
});

test("it explains what the feature will be", () => {
  assert.match(ONLINE_AI_WHAT, /larger cloud model/);
  assert.match(ONLINE_AI_WHAT, /works completely without it/);
});

test("it states the choice is per conversation, never global", () => {
  assert.match(ONLINE_AI_PER_CONVERSATION, /per conversation/);
  assert.match(ONLINE_AI_PER_CONVERSATION, /no setting that turns it on everywhere/);
});

test("the key statement follows the 2026-09-23 decision: the person's own key, no sale", () => {
  assert.match(ONLINE_AI_KEY, /provider you already pay/);
  assert.match(ONLINE_AI_KEY, /Askwell sells nothing/);
  assert.match(ONLINE_AI_KEY, /Nothing on this screen asks for a key today/);
  // The cancelled credit tier must not come back through this section.
  for (const text of [ONLINE_AI_WHAT, ONLINE_AI_KEY, ONLINE_AI_PER_CONVERSATION, ONLINE_AI_WHERE]) {
    assert.doesNotMatch(text, /credit|purchase|balance|spending limit|price/i);
  }
});

test("the payload is promised before sending rather than guessed", () => {
  assert.match(ONLINE_AI_PAYLOAD, /before anything is sent/);
  assert.match(ONLINE_AI_PAYLOAD, /Until then, nothing leaves/);
});

test("no field in the section can collect anything, and nothing in it makes a request", () => {
  for (const forbidden of [/<input\b/, /<textarea\b/, /<select\b/, /<form\b/, /\bfetch\(/, /https?:\/\//]) {
    assert.doesNotMatch(COMPONENT, forbidden, `online-ai.tsx contains ${forbidden}`);
  }
});

test("the section is on the settings page, second, after model and speed", () => {
  const model = PAGE.indexOf("<ModelAndSpeed />");
  const online = PAGE.indexOf("<OnlineAi />");
  assert.ok(model >= 0 && online > model, "OnlineAi renders after ModelAndSpeed");
  const between = PAGE.slice(model + "<ModelAndSpeed />".length, online);
  assert.doesNotMatch(between, /<[A-Z]\w* \/>/, "nothing renders between them");
});
