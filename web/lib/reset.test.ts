/**
 * Reset's confirmation and outcome copy. `M7-DATA-FE-160`.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  RESET_IRREVERSIBLE,
  RESET_LOG_STATEMENT,
  resetDestroys,
  resetOutcome,
  type ResetPreview,
  type ResetResult,
} from "./reset.ts";

const preview: ResetPreview = {
  counts: {
    sources: 3,
    roots: 1,
    memory: 4,
    schema_notes: 1,
    clarifications: 2,
    conversations: 7,
    audit_decisions: 10,
    audit_interactions: 20,
  },
  total: 48,
  files: { traces: 5, exports: 1, backups: 0 },
  original_files_statement: "Your original files are never touched.",
};

test("the confirmation names every kind of thing destroyed, with its count", () => {
  const lines = resetDestroys(preview).join("\n");
  assert.match(lines, /3 sources/);
  assert.match(lines, /1 registered folder, which Askwell forgets/);
  assert.match(lines, /5 memory facts and 2 clarifications/);
  assert.match(lines, /7 conversations/);
  assert.match(lines, /30 log records/);
  assert.match(lines, /passphrase/);
  assert.match(lines, /6 files Askwell wrote/);
  assert.match(lines, /already downloaded is yours and stays/);
});

test("with no files on disk the file line is left out rather than saying zero", () => {
  const lines = resetDestroys({ ...preview, files: { traces: 0, exports: 0, backups: 0 } });
  assert.ok(!lines.some((line) => line.includes("Askwell wrote")));
});

test("the log destroying itself and the irreversibility are both stated", () => {
  assert.match(RESET_LOG_STATEMENT, /destroyed/);
  assert.match(RESET_IRREVERSIBLE, /cannot be undone/);
});

const result: ResetResult = {
  counts: preview.counts,
  total: 48,
  files_removed: { traces: 5, exports: 1, backups: 0 },
  files_not_removed: [],
  sandbox_databases_dropped: [],
  original_files_statement: "Your original files are never touched.",
};

test("a clean reset reports the count and nothing else", () => {
  assert.deepEqual(resetOutcome(result), ["Reset. 48 records removed."]);
});

test("a file that could not be removed is named, never hidden", () => {
  const lines = resetOutcome({ ...result, files_not_removed: ["/var/lib/askwell/exports/a.zip"] });
  assert.equal(lines[1], "1 file could not be removed and still exists: /var/lib/askwell/exports/a.zip");
});

test("an unreachable sandbox is stated, with when it will be cleared", () => {
  const lines = resetOutcome({ ...result, sandbox_databases_dropped: null });
  assert.match(lines[1] ?? "", /next time Askwell starts/);
});
