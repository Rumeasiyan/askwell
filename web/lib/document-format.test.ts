import { test } from "node:test";
import assert from "node:assert/strict";

import { documentFormat } from "./document-format.ts";

test("a PDF is its own kind", () => {
  assert.equal(documentFormat("application/pdf"), "pdf");
});

test("Word, PowerPoint, HTML, Markdown and plain text render as converted text", () => {
  for (const mime of [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/html",
    "text/markdown",
    "text/plain",
  ]) {
    assert.equal(documentFormat(mime), "converted-text");
  }
});

test("a workbook renders as a spreadsheet", () => {
  assert.equal(
    documentFormat("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "spreadsheet",
  );
});

test("an image, legacy Office or unknown mime has no renderer", () => {
  for (const mime of [null, "image/png", "application/msword", "application/zip"]) {
    assert.equal(documentFormat(mime), "unsupported");
  }
});
