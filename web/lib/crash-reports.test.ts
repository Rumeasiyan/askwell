/**
 * Crash reports in Settings → About. `M7-OPS-DOC-165`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  CRASH_REPORT_CONTENTS,
  crashReportUrl,
  describeCrashReport,
  fetchCrashReports,
} from "./crash-reports.ts";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("a report name reads as its time and component", () => {
  assert.equal(
    describeCrashReport("crash-20260924T101500Z-worker-1a2b3c4d.json"),
    "2026-09-24 10:15 UTC, worker",
  );
});

test("an unexpected name is shown as it is, not guessed at", () => {
  assert.equal(describeCrashReport("something-else.json"), "something-else.json");
});

test("the download address stays inside the crash report route", () => {
  assert.equal(crashReportUrl("../x"), "/crash-reports/..%2Fx");
});

test("the contents sentence says it is never sent and is attached by the person", () => {
  assert.match(CRASH_REPORT_CONTENTS, /never sent/);
  assert.match(CRASH_REPORT_CONTENTS, /attach it yourself/);
});

test("the list is read only from Askwell's own origin", async () => {
  const seen: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    seen.push(String(input));
    return new Response(JSON.stringify({ directory: "/var/lib/askwell/crash-reports", reports: [] }));
  }) as typeof fetch;

  const result = await fetchCrashReports();

  assert.deepEqual(seen, ["/crash-reports"]);
  assert.deepEqual(result.reports, []);
});

test("a failed list is a named failure, not an empty list", async () => {
  globalThis.fetch = (async () => new Response("", { status: 500 })) as typeof fetch;

  await assert.rejects(fetchCrashReports(), /answered 500 listing crash reports/);
});
