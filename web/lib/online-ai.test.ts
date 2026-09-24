/**
 * Settings → Online AI, before it exists. `M7-SET-FE-150`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  attemptToEnable,
  ONLINE_AI_INITIAL,
  ONLINE_AI_KEY,
  ONLINE_AI_NOT_AVAILABLE,
  ONLINE_AI_PAYLOAD,
  ONLINE_AI_PER_CONVERSATION,
  ONLINE_AI_STATUS,
  ONLINE_AI_WHAT,
} from "./online-ai.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const COMPONENT = readFileSync(join(WEB, "components", "settings", "online-ai.tsx"), "utf8");
const PAGE = readFileSync(join(WEB, "app", "settings", "page.tsx"), "utf8");

test("the section starts off and says it is not available", () => {
  assert.equal(ONLINE_AI_INITIAL.on, false);
  assert.equal(ONLINE_AI_INITIAL.notice, null);
  assert.match(ONLINE_AI_STATUS, /^Off\. Not available yet\.$/);
});

test("trying to turn it on, any number of times, leaves it off with a plain statement", () => {
  const once = attemptToEnable();
  const twice = attemptToEnable();
  assert.equal(once.on, false);
  assert.equal(twice.on, false);
  assert.equal(once.notice, ONLINE_AI_NOT_AVAILABLE);
  assert.match(ONLINE_AI_NOT_AVAILABLE, /not available yet/);
  assert.match(ONLINE_AI_NOT_AVAILABLE, /nothing to sign up for and no list to join/);
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
  for (const text of [ONLINE_AI_WHAT, ONLINE_AI_KEY, ONLINE_AI_PER_CONVERSATION, ONLINE_AI_NOT_AVAILABLE]) {
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
  // The switch is marked disabled but stays clickable, so an attempt gets the statement.
  assert.match(COMPONENT, /aria-disabled="true"/);
  assert.match(COMPONENT, /onClick=\{\(\) => setView\(attemptToEnable\(\)\)\}/);
});

test("the section is on the settings page, second, after model and speed", () => {
  const model = PAGE.indexOf("<ModelAndSpeed />");
  const online = PAGE.indexOf("<OnlineAi />");
  assert.ok(model >= 0 && online > model, "OnlineAi renders after ModelAndSpeed");
  const between = PAGE.slice(model + "<ModelAndSpeed />".length, online);
  assert.doesNotMatch(between, /<[A-Z]\w* \/>/, "nothing renders between them");
});
