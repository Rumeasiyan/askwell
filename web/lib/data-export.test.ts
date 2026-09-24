/**
 * Export everything and export the log: copy and progress. `M7-DATA-FE-160`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EXPORT_CONTENTS,
  UNPROTECTED_EXPORT_WARNING,
  exportFinished,
  exportProgress,
  type ExportJob,
} from "./data-export.ts";

const job: ExportJob = {
  id: "j",
  status: "running",
  scope: "everything",
  decisions_total: 10,
  decisions_done: 4,
  interactions_total: 20,
  interactions_done: 0,
  file_bytes: null,
  error: null,
};

test("export everything names every part the ticket requires, and that files are not copied", () => {
  const copy = EXPORT_CONTENTS.everything;
  for (const part of ["sources", "memory", "conversations", "hash chain", "verifier", "Plain text"]) {
    assert.ok(copy.includes(part), part);
  }
  assert.match(copy, /own files are not copied/);
});

test("the passphrase warning says the export is not protected", () => {
  assert.match(UNPROTECTED_EXPORT_WARNING, /will not be protected/);
  assert.match(UNPROTECTED_EXPORT_WARNING, /plain text/);
});

test("progress counts log records while they are written", () => {
  assert.equal(exportProgress(job), "4 of 30 log records written…");
  assert.equal(exportProgress({ ...job, status: "queued" }), "Waiting to start…");
});

test("once the log is written, export everything says what it is doing next", () => {
  const logDone = { ...job, decisions_done: 10, interactions_done: 20 };
  assert.match(exportProgress(logDone), /Writing sources, memory and conversations/);
  assert.equal(exportProgress({ ...logDone, scope: "log" }), "30 of 30 log records written…");
});

test("done and failed both end the poll", () => {
  assert.equal(exportFinished(job), false);
  assert.equal(exportFinished({ ...job, status: "done" }), true);
  assert.equal(exportFinished({ ...job, status: "failed" }), true);
});
