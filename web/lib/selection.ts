/**
 * Selecting files — the one seam the desktop shell replaces.
 *
 * `M7-TAURI-FE-182` swaps this module's two entry points for the platform's
 * own dialog and Tauri's drop event. Nothing else in the add flow knows how a
 * file was chosen: the queue, the detection and the folder check all take a
 * `Picked` and would not notice the change. That is the whole reason this file
 * exists separately from `add-source.ts`.
 *
 * **This is not an upload control and must never become one.** A file input is
 * used to *name* files; not one byte past `HEAD_BYTES` is read, nothing is
 * posted, and Askwell indexes where the file already is. The moment this
 * module sends a `File` anywhere, the product's central promise is gone.
 *
 * ## The assumption that turned out to be false
 *
 * `M1-ADD-FE-022` assumes "the browser's drop event gives usable paths under
 * every supported platform". It does not, on any of them: a browser exposes a
 * file's name and its path *within a dropped folder*, and deliberately never
 * its absolute path — that is a sandbox rule, not a gap in an API. So
 * `absolutePath` is null here and the screen asks once which folder the drop
 * came from, in the same typed form `docs/ux/add-source.md` §7 already uses for
 * nominating one. When the host can answer, it fills `absolutePath` in and that
 * question stops being asked.
 */

import { HEAD_BYTES, type TreeEntry, flatten } from "./add-source";

/**
 * Whether the host can say where a file actually lives.
 *
 * False in a browser, permanently. `M7-TAURI-FE-182` is what makes it true,
 * and the screen reads it rather than assuming the browser.
 */
export const HOST_GIVES_PATHS: boolean = false;

export interface Picked {
  name: string;
  /** Path within what was dropped — `clients/2026/lease.pdf`. */
  relativePath: string;
  size: number;
  /** Where it really is, when the host will say. A browser never will. */
  absolutePath: string | null;
  /** The first `HEAD_BYTES`, and nothing more, ever. */
  head(): Promise<Uint8Array>;
}

export interface Selection {
  files: Picked[];
  folders: number;
  truncated: boolean;
}

/** Whether a drag carries files at all, as opposed to selected text. */
export function carriesFiles(transfer: DataTransfer | null): boolean {
  if (transfer === null) return false;
  return [...transfer.types].includes("Files");
}

function pick(file: File, relativePath: string): Picked {
  return {
    name: file.name,
    relativePath,
    size: file.size,
    absolutePath: null,
    head: async () => new Uint8Array(await file.slice(0, HEAD_BYTES).arrayBuffer()),
  };
}

interface Walked extends TreeEntry {
  entry: FileSystemEntry;
}

/**
 * Read a directory to the end.
 *
 * `readEntries` returns a *batch* and must be called again until it returns an
 * empty one. Reading it once is the classic bug here, and its symptom is a
 * folder of 200 contracts quietly becoming 100 — a count that looks plausible,
 * which is the worst kind of wrong for a screen whose job is to show a count.
 */
function readAll(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const found: FileSystemEntry[] = [];
    const step = (): void => {
      reader.readEntries((batch) => {
        if (batch.length === 0) {
          resolve(found);
          return;
        }
        found.push(...batch);
        step();
      }, reject);
    };
    step();
  });
}

function fileOf(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

/**
 * Expand a drop into files.
 *
 * Folders are walked; bare files are taken as they are. Both arrive through
 * the same path so that "a folder of 60 contracts" and "60 contracts" behave
 * identically, which is what the user expects and is the edge case the ticket
 * names.
 *
 * The walk is asynchronous throughout, so a large tree does not freeze the
 * window: every `readEntries` yields to the event loop on its own.
 */
export async function fromDrop(transfer: DataTransfer): Promise<Selection> {
  // Indexed rather than iterated, and read before the first `await`: a
  // `DataTransferItemList` is not iterable, and it is emptied as soon as the
  // drop handler returns. Asking it anything afterwards gets nothing.
  const roots: Walked[] = [];
  for (let index = 0; index < transfer.items.length; index += 1) {
    const item = transfer.items[index];
    if (item === undefined || item.kind !== "file") continue;
    const entry = item.webkitGetAsEntry();
    if (entry === null) continue;
    roots.push({ name: entry.name, directory: entry.isDirectory, entry });
  }

  // Some browsers hand over files without entries. Losing the drop entirely
  // would be the wrong trade: a flat list of files is most drops.
  if (roots.length === 0) return fromFiles(transfer.files);

  const expansion = await flatten(roots, async (walked) => {
    const reader = (walked.entry as FileSystemDirectoryEntry).createReader();
    return (await readAll(reader)).map((entry) => ({
      name: entry.name,
      directory: entry.isDirectory,
      entry,
    }));
  });

  const files: Picked[] = [];
  for (const found of expansion.files) {
    const file = await fileOf(found.entry.entry as FileSystemFileEntry);
    files.push(pick(file, found.relativePath));
  }

  return { files, folders: expansion.folders, truncated: expansion.truncated };
}

/**
 * The browse alternative.
 *
 * `webkitRelativePath` is set when a directory was chosen and empty when files
 * were, so the same shape comes out of both and the queue cannot tell which
 * happened.
 */
export function fromFiles(list: FileList): Selection {
  const files = [...list].map((file) =>
    pick(file, file.webkitRelativePath === "" ? file.name : file.webkitRelativePath),
  );
  const folders = new Set(
    files
      .map((file) => file.relativePath.split("/").slice(0, -1).join("/"))
      .filter((folder) => folder !== ""),
  );
  return { files, folders: folders.size, truncated: false };
}
