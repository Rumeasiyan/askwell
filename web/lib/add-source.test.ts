/**
 * The add-source decisions, exercised without a browser.
 *
 * Node 22 runs TypeScript directly, so this needs no bundler, no jsdom and no
 * test framework beyond the one in the standard library:
 *
 *   pnpm test        (scripts/dev.sh web-run pnpm test)
 *
 * What is covered is what the ticket states and what a passing build cannot
 * see: that a file is judged by its contents, that a mislabelled one is
 * reported rather than quietly re-routed, that a program is refused by name,
 * and that expanding a dropped folder counts rather than freezes.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MAX_FILES,
  describeBatch,
  detect,
  extensionOf,
  flatten,
  formatSize,
  type TreeEntry,
} from "./add-source.ts";

function head(text: string): Uint8Array {
  return Uint8Array.from([...text].map((character) => character.charCodeAt(0)));
}

function bytes(values: number[]): Uint8Array {
  return Uint8Array.from(values);
}

test("a PDF is recognised by its contents", () => {
  const result = detect("lease.pdf", head("%PDF-1.7\n%\xe2\xe3"), 90_000);
  assert.equal(result.format, "a PDF document");
  assert.equal(result.route, "files");
  assert.equal(result.supported, true);
  assert.equal(result.mismatch, null);
  assert.equal(result.refusal, null);
});

test("a mislabelled file is routed by its contents and the disagreement is said", () => {
  const result = detect("lease.pdf", bytes([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), 4_000);
  assert.equal(result.format, "a PNG image");
  assert.equal(result.supported, true);
  assert.match(result.mismatch ?? "", /Named \.pdf/);
  assert.match(result.mismatch ?? "", /a PNG image/);
});

test("a file with no extension is judged on contents alone, with nothing to disagree with", () => {
  const result = detect("contract", head("%PDF-1.4"), 10);
  assert.equal(result.format, "a PDF document");
  assert.equal(result.mismatch, null);
});

test("a zipped Office file is named by its extension, since every one of them is a zip", () => {
  const zip = bytes([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00]);
  assert.equal(detect("notes.docx", zip, 20_000).format, "a Word document");
  assert.equal(detect("figures.xlsx", zip, 20_000).format, "an Excel workbook");
  assert.equal(detect("deck.pptx", zip, 20_000).format, "a PowerPoint deck");
});

test("a plain zip is refused with what to do instead, not as 'unsupported'", () => {
  const result = detect("everything.zip", bytes([0x50, 0x4b, 0x03, 0x04]), 900);
  assert.equal(result.supported, false);
  assert.match(result.refusal ?? "", /Unpack it/);
});

test("a program is refused by name, and says nothing was run", () => {
  const result = detect("installer.pdf", bytes([0x7f, 0x45, 0x4c, 0x46, 0x02]), 4_000);
  assert.equal(result.supported, false);
  assert.equal(result.format, "a Linux program");
  assert.match(result.refusal ?? "", /Nothing has been run/);
});

test("an empty file is refused, and says nothing on disk changed", () => {
  const result = detect("blank.pdf", new Uint8Array(), 0);
  assert.equal(result.supported, false);
  assert.match(result.refusal ?? "", /Nothing was changed on disk/);
});

test("a CSV goes to the tabular route, by contents as well as by name", () => {
  assert.equal(detect("q3.csv", head("a,b,c\n1,2,3\n"), 12).route, "table");
  assert.equal(detect("export.txt", head("name,amount,date\nx,1,2026-01-01\n"), 40).route, "table");
});

test("a SQL dump goes to the dump route whether it is named .sql or not", () => {
  assert.equal(detect("db.sql", head("-- a dump\nSELECT 1;\n"), 20).route, "dump");
  assert.equal(
    detect("backup.txt", head("--\n-- PostgreSQL database dump\n--\n"), 40).route,
    "dump",
  );
  assert.equal(detect("db.dump", bytes([0x50, 0x47, 0x44, 0x4d, 0x50]), 900).route, "dump");
});

test("prose is plain text, not a CSV, because one comma is not a column", () => {
  const result = detect("letter.txt", head("Dear Anna, thank you for the contract.\n"), 40);
  assert.equal(result.format, "plain text");
  assert.equal(result.route, "files");
});

test("an unrecognised binary is refused with the supported list, never silently", () => {
  const result = detect("thing.bin", bytes([0x00, 0x01, 0x02, 0x00, 0x99]), 5);
  assert.equal(result.supported, false);
  assert.match(result.refusal ?? "", /PDF, Word, Excel/);
});

test("extensionOf ignores a leading dot and a trailing one", () => {
  assert.equal(extensionOf(".bashrc"), "");
  assert.equal(extensionOf("report."), "");
  assert.equal(extensionOf("Report.PDF"), "pdf");
});

// --- expanding a dropped folder ---------------------------------------------

interface Fake extends TreeEntry {
  children?: Fake[];
}

const readChildren = async (entry: Fake): Promise<Fake[]> => entry.children ?? [];

test("a dropped folder is expanded and its files keep the path within it", async () => {
  const tree: Fake[] = [
    {
      name: "clients",
      directory: true,
      children: [
        { name: "a.pdf", directory: false },
        {
          name: "2026",
          directory: true,
          children: [{ name: "b.pdf", directory: false }],
        },
      ],
    },
  ];

  const expansion = await flatten(tree, readChildren);

  assert.equal(expansion.files.length, 2);
  assert.equal(expansion.folders, 2);
  assert.equal(expansion.truncated, false);
  assert.deepEqual(
    expansion.files.map((found) => found.relativePath).sort(),
    ["clients/2026/b.pdf", "clients/a.pdf"],
  );
});

test("bare files dropped alongside a folder keep their own names", async () => {
  const expansion = await flatten(
    [
      { name: "one.pdf", directory: false },
      { name: "two.pdf", directory: false },
    ] as Fake[],
    readChildren,
  );
  assert.deepEqual(expansion.files.map((found) => found.relativePath), ["one.pdf", "two.pdf"]);
});

test("the cap stops the walk and says so rather than truncating quietly", async () => {
  const many: Fake[] = Array.from({ length: 12 }, (_, index) => ({
    name: `file-${index}.pdf`,
    directory: false,
  }));

  const expansion = await flatten(many, readChildren, 5);

  assert.equal(expansion.files.length, 5);
  assert.equal(expansion.truncated, true);
});

test("MAX_FILES is the default, so a drop of ordinary size is never capped", async () => {
  const expansion = await flatten(
    [{ name: "a.pdf", directory: false }] as Fake[],
    readChildren,
  );
  assert.equal(expansion.truncated, false);
  assert.ok(MAX_FILES > 1000);
});

// --- what the screen says ---------------------------------------------------

test("sizes read as a person would say them", () => {
  assert.equal(formatSize(12), "12 bytes");
  assert.equal(formatSize(2048), "2.0 KB");
  assert.equal(formatSize(52_428_800), "50 MB");
});

test("a batch is described by its count and size, and claims no duration", () => {
  const sentence = describeBatch(60, 60 * 1024 * 1024);
  assert.match(sentence, /60 files/);
  assert.match(sentence, /60 MB/);
  assert.doesNotMatch(sentence, /minute|hour|second/);
  assert.match(describeBatch(1, 10), /^1 file,/);
});
