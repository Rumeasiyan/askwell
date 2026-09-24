/**
 * Settings → About. `M7-SET-FE-149`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { afterEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  fetchBundledText,
  ISSUE_URL,
  LICENCE_TEXT,
  NOTICES_TEXT,
  REPO_URL,
  SECURITY_TEXT,
  setUpdateCheck,
  SUPPORT_TEXT,
  UPDATE_CHECK_PAYLOAD,
  updateCheckIsOn,
  updateCheckStatus,
  type UpdateCheckState,
} from "./about.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = join(WEB, "..");

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function state(answer: UpdateCheckState["answer"]): UpdateCheckState {
  return {
    answer,
    last_checked_at: null,
    latest_known_version: null,
    update_available: false,
    last_result: null,
  };
}

test("update checking is off unless the person said yes", () => {
  assert.equal(updateCheckIsOn(state("not_asked")), false);
  assert.equal(updateCheckIsOn(state("no")), false);
  assert.equal(updateCheckIsOn(state("yes")), true);
});

test("never-asked and turned-off both read as off, and say no request is made", () => {
  assert.match(updateCheckStatus(state("not_asked")), /^Off\..*no request/);
  assert.match(updateCheckStatus(state("no")), /^Off\..*no request/);
  assert.match(updateCheckStatus(state("yes")), /^On\./);
});

test("the payload is stated plainly: the version number and nothing else", () => {
  assert.match(UPDATE_CHECK_PAYLOAD, /your version number and nothing else/);
  assert.match(UPDATE_CHECK_PAYLOAD, /Off by default/);
});

test("turning the check on sends yes, turning it off sends no", async () => {
  const sent: unknown[] = [];
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    sent.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify(state("yes")), { status: 200 });
  }) as typeof fetch;
  await setUpdateCheck(true);
  await setUpdateCheck(false);
  assert.deepEqual(sent, [{ answer: "yes" }, { answer: "no" }]);
});

test("a refused change says the setting did not move", async () => {
  globalThis.fetch = (async () => new Response("", { status: 500 })) as typeof fetch;
  await assert.rejects(setUpdateCheck(true), /did not change the update check\. It is still off/);
});

test("a bundled text is returned whole, never cut short", async () => {
  const long = "line\n".repeat(20_000);
  globalThis.fetch = (async () => new Response(long, { status: 200 })) as typeof fetch;
  assert.equal(await fetchBundledText(NOTICES_TEXT), long);
});

test("a missing or empty bundled text is a named failure, not a blank panel", async () => {
  globalThis.fetch = (async () => new Response("not found", { status: 404 })) as typeof fetch;
  await assert.rejects(fetchBundledText(NOTICES_TEXT), /could not open the third-party notices/);
  globalThis.fetch = (async () => new Response("  \n", { status: 200 })) as typeof fetch;
  await assert.rejects(fetchBundledText(LICENCE_TEXT), /could not open the licence/);
});

test("every bundled text is copied into public/ from its one source at build time", () => {
  const copies = [
    readFileSync(join(WEB, "scripts", "copy-notices.mjs"), "utf8"),
    readFileSync(join(WEB, "scripts", "copy-support.mjs"), "utf8"),
  ].join("\n");
  for (const [text, source] of [
    [LICENCE_TEXT, "LICENSE"],
    [NOTICES_TEXT, "NOTICES.md"],
    [SUPPORT_TEXT, "SUPPORT.md"],
    [SECURITY_TEXT, "SECURITY.md"],
  ] as const) {
    assert.ok(existsSync(join(ROOT, source)), `${source} exists at the repository root`);
    assert.ok(copies.includes(`"${source}"`), `${source} is copied by a build script`);
    assert.ok(copies.includes(text.path.slice(1)), `${text.path} is written by a build script`);
  }
});

test("the notices name the bundled model weights and their licences", () => {
  const notices = readFileSync(join(ROOT, "NOTICES.md"), "utf8");
  assert.match(notices, /## Bundled model weights/);
  assert.match(notices, /\| Licence \|/);
});

test("the source and issue addresses point at the one repository", () => {
  assert.ok(ISSUE_URL.startsWith(`${REPO_URL}/`));
  assert.match(REPO_URL, /^https:\/\/github\.com\/[^/]+\/askwell$/);
});
