/**
 * Settings → About. `M7-SET-FE-149`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { afterEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  checkNowOutcome,
  dismissUpdate,
  fetchBundledText,
  ISSUE_URL,
  LICENCE_TEXT,
  NOTICES_TEXT,
  REPO_URL,
  SECURITY_TEXT,
  setUpdateCheck,
  SUPPORT_TEXT,
  UPDATE_CHECK_PAYLOAD,
  UPGRADE_DATA_SAFETY,
  updateCheckIsOn,
  updateMarker,
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
    latest_known_since: null,
    dismissed_version: null,
    dismissed: false,
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

// --- a newer version: `M7-UPDATE-FE-162` ---------------------------------

function found(overrides: Partial<UpdateCheckState>): UpdateCheckState {
  return {
    ...state("yes"),
    last_checked_at: "2026-09-01T10:00:00+00:00",
    latest_known_version: "1.2.0",
    latest_known_since: "2026-09-03T10:00:00+00:00",
    update_available: true,
    last_result: "ok",
    ...overrides,
  };
}

test("a known newer version is one marker naming the version and when it was found", () => {
  const marker = updateMarker(found({}));
  assert.ok(marker !== null);
  assert.equal(marker.version, "1.2.0");
  assert.match(marker.found ?? "", /^Found .*2026/);
});

test("never checked shows no marker at all, and nothing that reads as a failure", () => {
  assert.equal(updateMarker(state("not_asked")), null);
  assert.equal(checkNowOutcome(state("not_asked")), null);
});

test("a dismissed version shows no marker; a further version is the server's to un-dismiss", () => {
  assert.equal(updateMarker(found({ dismissed: true, dismissed_version: "1.2.0" })), null);
  assert.ok(updateMarker(found({ latest_known_version: "1.3.0", dismissed_version: "1.2.0" })) !== null);
});

test("turning checking off keeps a version already found", () => {
  assert.ok(updateMarker(found({ answer: "no" })) !== null);
});

test("a version found before its date was recorded is shown without a made-up date", () => {
  const marker = updateMarker(found({ latest_known_since: null }));
  assert.ok(marker !== null);
  assert.equal(marker.found, null);
});

test("running the newest version shows no marker", () => {
  assert.equal(updateMarker(found({ update_available: false })), null);
});

test("the data-safety statement names every store an upgrade keeps", () => {
  assert.match(UPGRADE_DATA_SAFETY, /indexes/);
  assert.match(UPGRADE_DATA_SAFETY, /remembers/);
  assert.match(UPGRADE_DATA_SAFETY, /audit log/);
  assert.match(UPGRADE_DATA_SAFETY, /kept/);
});

test("the data-safety statement matches what every installer does with a previous install", () => {
  for (const installer of ["linux/install.sh", "macos/install.sh", "windows/install.ps1"]) {
    const script = readFileSync(join(ROOT, "deploy", installer), "utf8");
    assert.match(script, /Its data is left untouched; upgrading application files in place\./, installer);
  }
});

test("a manual check says what it found, or that it could not reach the file", () => {
  assert.equal(checkNowOutcome(found({ update_available: false })), "This is the newest version.");
  assert.match(checkNowOutcome(found({ last_result: "unreachable" })) ?? "", /could not reach the file/);
  assert.match(checkNowOutcome(found({})) ?? "", /^1\.2\.0 is available\. It is shown under the version above/);
  assert.match(checkNowOutcome(found({ dismissed: true })) ?? "", /You dismissed its notice/);
});

test("dismissing names the version the marker showed", async () => {
  const sent: unknown[] = [];
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    sent.push([url, JSON.parse(String(init?.body))]);
    return new Response(JSON.stringify(found({ dismissed: true })), { status: 200 });
  }) as typeof fetch;
  await dismissUpdate("1.2.0");
  assert.deepEqual(sent, [["/settings/update-check/dismiss", { version: "1.2.0" }]]);
});

test("a refused dismissal says the notice is still shown", async () => {
  globalThis.fetch = (async () => new Response("", { status: 500 })) as typeof fetch;
  await assert.rejects(dismissUpdate("1.2.0"), /did not dismiss the notice\. It is still shown/);
});

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !name.endsWith(".test.ts") ? [path] : [];
  });
}

test("the marker appears in settings and nowhere else", () => {
  const users = [...sourceFiles(join(WEB, "app")), ...sourceFiles(join(WEB, "components"))]
    .filter((path) => readFileSync(path, "utf8").includes("updateMarker"))
    .map((path) => path.slice(WEB.length + 1));
  assert.deepEqual(users, ["components/settings/about.tsx"]);
});
