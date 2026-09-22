import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  basenameOfNativePath,
  dirnameOfNativePath,
  isMacOS,
  isNative,
  listNativeDir,
  pickFile,
  pickFiles,
  pickFolder,
  readNativeHead,
} from "./native.ts";

type Bridge = { __TAURI_INTERNALS__?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> } };

function fakeBridge(invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>): void {
  (globalThis as Bridge).__TAURI_INTERNALS__ = { invoke };
}

afterEach(() => {
  delete (globalThis as Bridge).__TAURI_INTERNALS__;
});

test("isNative is false without a Tauri bridge", () => {
  assert.equal(isNative(), false);
});

test("isNative is true once the bridge is present", () => {
  fakeBridge(async () => null);
  assert.equal(isNative(), true);
});

test("isMacOS is false in a browser regardless of user agent", () => {
  assert.equal(isMacOS(), false);
});

test("pickFolder throws outside the desktop shell", () => {
  assert.throws(() => pickFolder(), /desktop shell/);
});

test("pickFolder resolves null on cancel", async () => {
  fakeBridge(async (cmd) => {
    assert.equal(cmd, "pick_folder");
    return null;
  });
  assert.equal(await pickFolder(), null);
});

test("pickFolder returns the chosen path", async () => {
  fakeBridge(async () => "/home/anna/clients");
  assert.equal(await pickFolder(), "/home/anna/clients");
});

test("pickFile returns the picked path and size", async () => {
  fakeBridge(async (cmd) => {
    assert.equal(cmd, "pick_file");
    return { path: "/home/anna/clients/lease.pdf", size: 4096 };
  });
  assert.deepEqual(await pickFile(), { path: "/home/anna/clients/lease.pdf", size: 4096 });
});

test("pickFiles returns an empty array on cancel", async () => {
  fakeBridge(async () => []);
  assert.deepEqual(await pickFiles(), []);
});

test("pickFiles passes through every picked file", async () => {
  fakeBridge(async (cmd) => {
    assert.equal(cmd, "pick_files");
    return [
      { path: "/home/anna/a.pdf", size: 10 },
      { path: "/home/anna/b.pdf", size: 20 },
    ];
  });
  const picked = await pickFiles();
  assert.equal(picked.length, 2);
  assert.equal(picked[1]?.size, 20);
});

test("listNativeDir passes the path through and returns entries", async () => {
  fakeBridge(async (cmd, args) => {
    assert.equal(cmd, "list_dir");
    assert.deepEqual(args, { path: "/home/anna/clients" });
    return [{ name: "lease.pdf", path: "/home/anna/clients/lease.pdf", is_dir: false, size: 4096 }];
  });
  const entries = await listNativeDir("/home/anna/clients");
  assert.equal(entries.length, 1);
  assert.equal(entries[0]?.name, "lease.pdf");
});

test("listNativeDir rejects with the refusal the shell reports", async () => {
  fakeBridge(async () => {
    throw new Error("That path is outside every folder or file you chose.");
  });
  await assert.rejects(() => listNativeDir("/etc"), /outside every folder/);
});

test("readNativeHead turns the returned bytes into a Uint8Array", async () => {
  fakeBridge(async (cmd, args) => {
    assert.equal(cmd, "read_head");
    assert.deepEqual(args, { path: "/home/anna/clients/lease.pdf", bytes: 4096 });
    return [0x25, 0x50, 0x44, 0x46];
  });
  const head = await readNativeHead("/home/anna/clients/lease.pdf", 4096);
  assert.ok(head instanceof Uint8Array);
  assert.deepEqual([...head], [0x25, 0x50, 0x44, 0x46]);
});

test("basenameOfNativePath handles Unix paths", () => {
  assert.equal(basenameOfNativePath("/home/anna/clients/lease.pdf"), "lease.pdf");
});

test("basenameOfNativePath handles Windows paths", () => {
  assert.equal(basenameOfNativePath("C:\\Users\\anna\\clients\\lease.pdf"), "lease.pdf");
});

test("basenameOfNativePath strips a trailing separator", () => {
  assert.equal(basenameOfNativePath("/home/anna/clients/"), "clients");
});

test("dirnameOfNativePath handles Unix paths", () => {
  assert.equal(dirnameOfNativePath("/home/anna/clients/lease.pdf"), "/home/anna/clients");
});

test("dirnameOfNativePath handles Windows paths", () => {
  assert.equal(dirnameOfNativePath("C:\\Users\\anna\\clients\\lease.pdf"), "C:/Users/anna/clients");
});

test("dirnameOfNativePath returns empty for a bare name", () => {
  assert.equal(dirnameOfNativePath("lease.pdf"), "");
});
