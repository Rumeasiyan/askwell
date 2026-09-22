/**
 * Native dialogs and the scoped filesystem reads the desktop shell offers.
 *
 * `M7-TAURI-FE-182`. `web/src-tauri/src/main.rs` grants exactly five
 * commands to this window's one origin: `pick_folder` (root registration),
 * `pick_file` (relocating a moved document), `pick_files` (the add-source
 * screen's browse alternative), and `list_dir`/`read_head`, which let
 * `selection.ts` walk a chosen folder and detect what is inside it the same
 * way it already does for a browser drop.
 *
 * Talks to Tauri's IPC bridge directly (`globalThis.__TAURI_INTERNALS__`)
 * rather than through `@tauri-apps/api`: that package's own `invoke()` reads
 * `window` unconditionally, which does not exist under this repo's
 * `node --test` runner (no jsdom, `AGENTS.md` §6) — every test would need a
 * browser shim just to import it. `globalThis` is the same object as
 * `window` inside the real webview, so nothing about the production path
 * changes; only what a unit test has to fake does.
 *
 * `isNative()` is how every other module tells a desktop shell from a
 * browser tab. In a browser none of these functions can ever be called —
 * `invoke()` throws before naming a specific command that could never be
 * answered.
 */

interface TauriInternals {
  invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T>;
}

function internals(): TauriInternals | null {
  const value = (globalThis as { __TAURI_INTERNALS__?: TauriInternals }).__TAURI_INTERNALS__;
  return value ?? null;
}

export function isNative(): boolean {
  return internals() !== null;
}

/** Whether Askwell's own explanation belongs beside the OS permission prompt
 * (`docs/ux/add-source.md` §7) — macOS gates folder access outside a few
 * areas the way Windows and Linux do not. */
export function isMacOS(): boolean {
  return isNative() && typeof navigator !== "undefined" && /Mac/i.test(navigator.userAgent);
}

function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const bridge = internals();
  if (bridge === null) {
    throw new Error("Askwell is not running in the desktop shell.");
  }
  return bridge.invoke<T>(cmd, args);
}

/** A path plus the size the shell already had to stat to grant it. */
export interface NativePick {
  path: string;
  size: number;
}

/** Opens the platform's own directory dialog. `null` if the user cancelled —
 * the caller's flow returns to where it was, unchanged (this ticket's own
 * cancel edge case). */
export function pickFolder(): Promise<string | null> {
  return invoke<string | null>("pick_folder");
}

export function pickFile(): Promise<NativePick | null> {
  return invoke<NativePick | null>("pick_file");
}

export function pickFiles(): Promise<NativePick[]> {
  return invoke<NativePick[]>("pick_files");
}

export interface NativeDirEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
}

/** Refuses (rejects) for any path outside every folder or file a dialog has
 * already returned this session — enforced on the Rust side
 * (`AllowedRoots`), not trusted here. */
export function listNativeDir(path: string): Promise<NativeDirEntry[]> {
  return invoke<NativeDirEntry[]>("list_dir", { path });
}

/** The first `bytes` of a file, and nothing more — the same detection budget
 * a browser-picked file already gets (`add-source.ts`'s `HEAD_BYTES`). */
export async function readNativeHead(path: string, bytes: number): Promise<Uint8Array> {
  const raw = await invoke<number[]>("read_head", { path, bytes });
  return new Uint8Array(raw);
}

/** Separator-agnostic: a native dialog on Windows returns backslashes. */
export function basenameOfNativePath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const index = normalized.lastIndexOf("/");
  return index === -1 ? normalized : normalized.slice(index + 1);
}

export function dirnameOfNativePath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const index = normalized.lastIndexOf("/");
  return index <= 0 ? "" : normalized.slice(0, index);
}
