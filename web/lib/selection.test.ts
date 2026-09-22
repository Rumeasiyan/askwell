import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { fromNativeFiles, fromNativeFolder } from "./selection.ts";

type Bridge = { __TAURI_INTERNALS__?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> } };

interface FakeNode {
  is_dir: boolean;
  size: number;
  children?: string[];
}

/** A tiny fake filesystem `list_dir`/`read_head` answer from, standing in for
 * the Rust side's `AllowedRoots`-scoped reads. `fromNativeFolder` is only
 * ever exercised against this fake — it never touches a real filesystem. */
function fakeFilesystem(tree: Record<string, FakeNode>): void {
  (globalThis as Bridge).__TAURI_INTERNALS__ = {
    invoke: async (cmd, args) => {
      if (cmd === "list_dir") {
        const path = args?.path as string;
        const node = tree[path];
        if (node === undefined) throw new Error(`no such path: ${path}`);
        return (node.children ?? []).map((childPath) => {
          const child = tree[childPath];
          if (child === undefined) throw new Error(`no such path: ${childPath}`);
          const name = childPath.slice(childPath.lastIndexOf("/") + 1);
          return { name, path: childPath, is_dir: child.is_dir, size: child.size };
        });
      }
      if (cmd === "read_head") {
        return [0x25, 0x50, 0x44, 0x46];
      }
      throw new Error(`unexpected command: ${cmd}`);
    },
  };
}

afterEach(() => {
  delete (globalThis as Bridge).__TAURI_INTERNALS__;
});

test("fromNativeFolder walks a flat folder", async () => {
  fakeFilesystem({
    "/clients": { is_dir: true, size: 0, children: ["/clients/lease.pdf", "/clients/invoice.pdf"] },
    "/clients/lease.pdf": { is_dir: false, size: 100 },
    "/clients/invoice.pdf": { is_dir: false, size: 200 },
  });

  const selection = await fromNativeFolder("/clients");

  assert.equal(selection.files.length, 2);
  assert.equal(selection.truncated, false);
  const byName = new Map(selection.files.map((file) => [file.name, file]));
  assert.equal(byName.get("lease.pdf")?.size, 100);
  assert.equal(byName.get("lease.pdf")?.absolutePath, "/clients/lease.pdf");
  assert.equal(byName.get("lease.pdf")?.relativePath, "clients/lease.pdf");
});

test("fromNativeFolder walks nested subfolders and counts them", async () => {
  fakeFilesystem({
    "/clients": { is_dir: true, size: 0, children: ["/clients/2026"] },
    "/clients/2026": { is_dir: true, size: 0, children: ["/clients/2026/lease.pdf"] },
    "/clients/2026/lease.pdf": { is_dir: false, size: 50 },
  });

  const selection = await fromNativeFolder("/clients");

  assert.equal(selection.files.length, 1);
  assert.equal(selection.files[0]?.relativePath, "clients/2026/lease.pdf");
  assert.equal(selection.folders, 2);
});

test("fromNativeFolder reports an empty folder with no files", async () => {
  fakeFilesystem({
    "/empty": { is_dir: true, size: 0, children: [] },
  });

  const selection = await fromNativeFolder("/empty");

  assert.equal(selection.files.length, 0);
  assert.equal(selection.folders, 1);
});

test("a native file's head() reads through the bridge", async () => {
  fakeFilesystem({
    "/clients": { is_dir: true, size: 0, children: ["/clients/lease.pdf"] },
    "/clients/lease.pdf": { is_dir: false, size: 4 },
  });

  const selection = await fromNativeFolder("/clients");
  const head = await selection.files[0]?.head();

  assert.deepEqual([...(head ?? [])], [0x25, 0x50, 0x44, 0x46]);
});

test("fromNativeFiles maps picked files without a folder count", () => {
  const selection = fromNativeFiles([
    { path: "/home/anna/a.pdf", size: 10 },
    { path: "/home/anna/b.pdf", size: 20 },
  ]);

  assert.equal(selection.files.length, 2);
  assert.equal(selection.folders, 0);
  assert.equal(selection.truncated, false);
  assert.equal(selection.files[0]?.name, "a.pdf");
  assert.equal(selection.files[0]?.relativePath, "a.pdf");
  assert.equal(selection.files[1]?.size, 20);
  assert.equal(selection.files[1]?.absolutePath, "/home/anna/b.pdf");
});

test("fromNativeFiles handles an empty pick (cancel)", () => {
  const selection = fromNativeFiles([]);
  assert.deepEqual(selection, { files: [], folders: 0, truncated: false });
});
