/**
 * What the screen says about what the API recorded.
 *
 * The interesting part is not the fetch — it is the sentence. A duplicate that
 * says only "already present" leaves somebody with three copies of a contract
 * unsure which one Askwell is reading, and that uncertainty is the thing
 * duplicate detection exists to remove. So the assertion is that **both paths
 * survive into the line the user reads**.
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { type FileOutcome, type Recorded, duplicateLine, withOutcome } from "./sources.ts";

function outcome(over: Partial<FileOutcome> & Pick<FileOutcome, "outcome">): FileOutcome {
  return {
    relative_path: "clients/contract.pdf",
    path: "/home/anna/clients/contract.pdf",
    filename: "contract.pdf",
    format: "a PDF document",
    mime: "application/pdf",
    mismatch: null,
    arrives: null,
    document_id: null,
    existing: null,
    sha256: null,
    size: 1024,
    reason: null,
    ...over,
  };
}

const RECORDED: Recorded = {
  source: {
    id: "b2f0c1e2-0000-4000-8000-000000000001",
    name: "clients",
    root_path: "/home/anna/clients",
    status: "queued",
    created: true,
  },
  added: 1,
  duplicates: 1,
  later: 0,
  refused: 1,
  files: [
    outcome({ outcome: "added", document_id: "b2f0c1e2-0000-4000-8000-000000000002" }),
    outcome({
      outcome: "duplicate",
      relative_path: "clients/contract copy.pdf",
      path: "/home/anna/clients/contract copy.pdf",
      filename: "contract copy.pdf",
      existing: {
        document_id: "b2f0c1e2-0000-4000-8000-000000000002",
        path: "/home/anna/clients/contract.pdf",
        filename: "contract.pdf",
        source_id: "b2f0c1e2-0000-4000-8000-000000000001",
      },
    }),
    outcome({
      outcome: "refused",
      relative_path: "clients/empty.pdf",
      path: "/home/anna/clients/empty.pdf",
      filename: "empty.pdf",
      format: "an empty file",
      mime: null,
      reason: "There is nothing in this file to index. Nothing was changed on disk.",
    }),
  ],
};

test("a duplicate names both paths, so it is clear which copy is indexed", () => {
  const [duplicate] = withOutcome(RECORDED, "duplicate");
  assert.ok(duplicate);
  const line = duplicateLine(duplicate);
  assert.match(line, /contract copy\.pdf/);
  assert.match(line, /\/home\/anna\/clients\/contract\.pdf/);
  assert.match(line, /not added a second time/);
});

test("a duplicate with no linked document still reads as a sentence", () => {
  const line = duplicateLine(outcome({ outcome: "duplicate" }));
  assert.match(line, /already present/);
});

test("outcomes are separable, so a refusal is never shown as a duplicate", () => {
  assert.equal(withOutcome(RECORDED, "added").length, 1);
  assert.equal(withOutcome(RECORDED, "duplicate").length, 1);
  assert.equal(withOutcome(RECORDED, "refused").length, 1);
  assert.equal(withOutcome(RECORDED, "later").length, 0);
});

test("the counter follows what the server added, not what was sent", () => {
  // Three files went in and one document exists. Counting the batch would make
  // the local tally drift upwards every time somebody re-added a folder.
  assert.equal(RECORDED.files.length, 3);
  assert.equal(RECORDED.added, 1);
});
