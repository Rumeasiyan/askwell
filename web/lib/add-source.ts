/**
 * What a dropped file is, and which of the four routes it belongs to.
 *
 * `docs/ux/add-source.md` §1 and §2. Askwell picks the route from the file
 * itself so the user rarely has to choose, and the ticket is explicit that the
 * choice is made **by content as well as extension** — a `.pdf` that is really
 * a PNG is handled honestly rather than sent to a PDF extractor that will fail
 * later with a message about the wrong thing.
 *
 * Content wins where the two disagree. The extension is kept for two jobs it
 * is genuinely better at: telling the four zipped Office formats apart, which
 * would otherwise mean reading a zip central directory to find out, and saying
 * what the user *thought* the file was so the mismatch can be reported in
 * their own terms.
 *
 * Everything here is pure: bytes and a name in, a description out. No DOM, no
 * fetch, no clock. That is what makes it testable with `node --test`, and it is
 * why the browser-facing half lives in `selection.ts` instead.
 */

export type Route = "files" | "table" | "dump" | "connection";

/**
 * The four routes, as the screen shows them.
 *
 * Three of them say when they arrive rather than being hidden. A route that is
 * absent reads as "Askwell cannot do this"; a route that is present and dated
 * reads as "not yet", and those are different products to somebody deciding
 * whether their CSV exports have a home here.
 */
export const ROUTES: {
  id: Route;
  title: string;
  accepts: string;
  arrives: string | null;
}[] = [
  {
    id: "files",
    title: "Files",
    accepts:
      "PDF, Word, Excel, PowerPoint, plain text, Markdown, HTML and images. Drag them anywhere, or browse.",
    arrives: null,
  },
  {
    id: "table",
    title: "Spreadsheet or CSV",
    accepts:
      "Tabular exports. Askwell shows the types and headers it detected for review, and never guesses a date format.",
    arrives: "M4",
  },
  {
    id: "dump",
    title: "Database dump",
    accepts: "PostgreSQL .sql, .dump and .backup files, imported into a sealed database.",
    arrives: "M4",
  },
  {
    id: "connection",
    title: "Connect a database",
    accepts: "PostgreSQL, MySQL or SQL Server, read-only. Askwell refuses credentials that can write.",
    arrives: "M4",
  },
];

/**
 * What Askwell will do with a file, which is three things and not two.
 *
 * `supported` was a boolean and that was wrong in a way the screen made
 * visible: a CSV is not unsupported, it is unsupported *yet*, and collapsing
 * those two into one flag either enrols it in a queue that will never take it
 * or tells the user their spreadsheets have no home here. Both are false, and
 * they are false in opposite directions. `later` is the third answer.
 */
export type Verdict = "supported" | "later" | "refused";

export interface Detection {
  /** What it is, in words the user can read. */
  format: string;
  route: Route;
  /** Indexed today, arriving in a later milestone, or refused outright. */
  verdict: Verdict;
  /** The milestone the route arrives in. Set only when the verdict is `later`. */
  arrives: string | null;
  /** Set when the bytes and the name disagree. Content is what was believed. */
  mismatch: string | null;
  /** Why it was refused, when it was. Never a bare rejection. */
  refusal: string | null;
}

/**
 * How much of a file is read to decide what it is.
 *
 * Enough for every signature below plus a run of text to judge, and small
 * enough that reading it for several thousand files does not mean reading
 * several thousand files. Nothing beyond this is touched at add time — Askwell
 * indexes in place, so the bytes stay where they are.
 */
export const HEAD_BYTES = 4096;

/**
 * The most files one drop will expand to.
 *
 * A cap that silently truncates is worse than no cap, so `flatten` reports
 * that it stopped and the screen says so with the number. The limit exists
 * because a folder dropped by mistake can be a home directory, and walking one
 * entry at a time through the browser's directory reader is not free.
 */
export const MAX_FILES = 5000;

/**
 * The supported list, as one sentence.
 *
 * Every rejection carries it, because a rejection that says only "no" is how
 * somebody decides the product does not handle their material and stops. The
 * second half is the same sentence doing the opposite job: CSV and dumps are
 * named as *arriving*, which is a different statement from "unsupported" to
 * anyone whose material is mostly exports.
 */
export const SUPPORTED_SUMMARY =
  "PDF, Word, Excel, PowerPoint, plain text, Markdown, HTML and images are read today. " +
  "CSV, database dumps and live connections arrive in M4.";

/** When each route starts working, from the one place that already says so. */
const ARRIVES: Record<Route, string | null> = Object.fromEntries(
  ROUTES.map((route) => [route.id, route.arrives]),
) as Record<Route, string | null>;

/**
 * The verdict for a file that Askwell recognised and did not refuse.
 *
 * Derived from `ROUTES` rather than written down a second time: when M4 lands
 * and `arrives` becomes null for the table and dump routes, every CSV already
 * detected becomes `supported` with no second edit. A hardcoded milestone here
 * is the copy that would be forgotten.
 */
function onRoute(format: string, route: Route): Pick<Detection, "format" | "route" | "verdict" | "arrives"> {
  const arrives = ARRIVES[route] ?? null;
  return { format, route, verdict: arrives === null ? "supported" : "later", arrives };
}

// --- signatures -------------------------------------------------------------

function bytesOf(text: string): number[] {
  return [...text].map((character) => character.charCodeAt(0));
}

function leads(head: Uint8Array, signature: number[], at = 0): boolean {
  if (head.length < at + signature.length) return false;
  return signature.every((byte, index) => head[at + index] === byte);
}

/**
 * What the bytes said.
 *
 * No verdict here on purpose: `refusal` present means refused, and everything
 * else is decided by its route in `onRoute`. Carrying a verdict alongside a
 * route would let the two disagree, and the case where they disagree is
 * exactly the CSV.
 */
interface Content {
  format: string;
  route: Route;
  refusal?: string;
  /** The zip and OLE containers hold four different things; the name decides. */
  container?: "ooxml" | "ole";
}

const IMAGE_SIGNATURES: { signature: number[]; format: string; at?: number }[] = [
  { signature: [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], format: "a PNG image" },
  { signature: [0xff, 0xd8, 0xff], format: "a JPEG image" },
  { signature: bytesOf("GIF8"), format: "a GIF image" },
  { signature: [0x49, 0x49, 0x2a, 0x00], format: "a TIFF image" },
  { signature: [0x4d, 0x4d, 0x00, 0x2a], format: "a TIFF image" },
  { signature: bytesOf("BM"), format: "a BMP image" },
];

/** A program, not a document. Named as such rather than as "unsupported". */
const EXECUTABLES: { signature: number[]; format: string }[] = [
  { signature: [0x7f, 0x45, 0x4c, 0x46], format: "a Linux program" },
  { signature: bytesOf("MZ"), format: "a Windows program" },
  { signature: [0xca, 0xfe, 0xba, 0xbe], format: "a macOS program" },
  { signature: [0xcf, 0xfa, 0xed, 0xfe], format: "a macOS program" },
  { signature: bytesOf("#!"), format: "a script" },
];

const REFUSED_PROGRAM =
  "Askwell indexes documents, and this is a program. Nothing has been run and nothing has been read past its first few bytes.";

/**
 * The archive refusal, which is the one the ticket is named after.
 *
 * It names the way out rather than the rule. "Unsupported format" tells
 * someone their zip of contracts has no home here; "unpack it and add what is
 * inside" tells them what to do in the next thirty seconds, and the reason —
 * each document keeps its own name in citations — is true and is why Askwell
 * would rather they did.
 */
const REFUSED_ARCHIVE =
  "Askwell does not open archives. Unpack it and add what is inside — that way each document keeps its own name in your citations.";

function fromBytes(head: Uint8Array): Content | null {
  if (leads(head, bytesOf("%PDF-"))) {
    return { format: "a PDF document", route: "files" };
  }
  if (leads(head, bytesOf("PGDMP"))) {
    return { format: "a PostgreSQL dump", route: "dump" };
  }
  for (const image of IMAGE_SIGNATURES) {
    if (leads(head, image.signature)) {
      return { format: image.format, route: "files" };
    }
  }
  if (leads(head, bytesOf("RIFF")) && leads(head, bytesOf("WEBP"), 8)) {
    return { format: "a WebP image", route: "files" };
  }
  for (const program of EXECUTABLES) {
    if (leads(head, program.signature)) {
      return { format: program.format, route: "files", refusal: REFUSED_PROGRAM };
    }
  }
  if (leads(head, [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1])) {
    return { format: "an older Microsoft Office file", route: "files", container: "ole" };
  }
  if (leads(head, [0x50, 0x4b, 0x03, 0x04])) {
    return { format: "a zip archive", route: "files", container: "ooxml" };
  }
  if (leads(head, [0x1f, 0x8b])) {
    return { format: "a gzip archive", route: "files", refusal: REFUSED_ARCHIVE };
  }
  return null;
}

/**
 * Whether the head reads as text.
 *
 * A NUL byte settles it: no text encoding Askwell supports produces one, and
 * every binary format that got past the signatures above has them early. The
 * printable ratio catches the rest. Both are judged on the head alone, so a
 * text file with a stray control character deep inside is still text.
 */
function looksTextual(head: Uint8Array): boolean {
  if (head.length === 0) return false;
  let printable = 0;
  for (const byte of head) {
    if (byte === 0) return false;
    const readable = byte >= 0x20 || byte === 0x09 || byte === 0x0a || byte === 0x0d;
    if (readable) printable += 1;
  }
  return printable / head.length > 0.9;
}

/**
 * HTML, judged on its opening rather than on its name.
 *
 * There is no byte signature for HTML — it is text — so this is the content
 * check for it, and it runs *before* the delimiter and SQL checks because a
 * saved page full of tables would otherwise read as a CSV. A leading byte-order
 * mark and leading whitespace are skipped. The BOM is matched in both forms
 * because `decode` reads bytes one at a time: a UTF-8 BOM arrives as three
 * separate characters, not as U+FEFF.
 *
 * No nested quantifier, deliberately. A pattern that can backtrack runs on
 * every text file in a several-thousand-file drop, and the head it runs over
 * is attacker-supplied in the only sense that matters here — it is whatever
 * was on disk.
 */
const HTML_MARKERS = /^(﻿|ï»¿)?[\s\r\n]*(<!doctype\s+html|<html[\s>]|<head[\s>])/i;

const SQL_MARKERS =
  /(PostgreSQL database dump|^\s*(CREATE|INSERT INTO|COPY|ALTER TABLE|DROP TABLE|SET )\b)/im;

function decode(head: Uint8Array): string {
  let text = "";
  for (const byte of head) text += String.fromCharCode(byte);
  return text;
}

/** Comma or tab separated, judged on the first line having repeated separators. */
function looksDelimited(text: string): boolean {
  const first = text.split(/\r?\n/, 1)[0] ?? "";
  if (first.length === 0) return false;
  const commas = (first.match(/,/g) ?? []).length;
  const tabs = (first.match(/\t/g) ?? []).length;
  return commas >= 2 || tabs >= 2;
}

// --- extensions -------------------------------------------------------------

const BY_EXTENSION: Record<string, { format: string; route: Route }> = {
  pdf: { format: "a PDF document", route: "files" },
  doc: { format: "a Word document", route: "files" },
  docx: { format: "a Word document", route: "files" },
  xls: { format: "an Excel workbook", route: "files" },
  xlsx: { format: "an Excel workbook", route: "files" },
  ppt: { format: "a PowerPoint deck", route: "files" },
  pptx: { format: "a PowerPoint deck", route: "files" },
  txt: { format: "plain text", route: "files" },
  md: { format: "a Markdown document", route: "files" },
  markdown: { format: "a Markdown document", route: "files" },
  html: { format: "an HTML page", route: "files" },
  htm: { format: "an HTML page", route: "files" },
  csv: { format: "a CSV file", route: "table" },
  tsv: { format: "a tab-separated file", route: "table" },
  sql: { format: "a SQL dump", route: "dump" },
  dump: { format: "a database dump", route: "dump" },
  backup: { format: "a database dump", route: "dump" },
  png: { format: "a PNG image", route: "files" },
  jpg: { format: "a JPEG image", route: "files" },
  jpeg: { format: "a JPEG image", route: "files" },
  gif: { format: "a GIF image", route: "files" },
  webp: { format: "a WebP image", route: "files" },
  tif: { format: "a TIFF image", route: "files" },
  tiff: { format: "a TIFF image", route: "files" },
  bmp: { format: "a BMP image", route: "files" },
};

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return "";
  return name.slice(dot + 1).toLowerCase();
}

/** What the four zipped Office formats are called, from the name alone. */
const OOXML: Record<string, string> = {
  docx: "a Word document",
  xlsx: "an Excel workbook",
  pptx: "a PowerPoint deck",
  odt: "an OpenDocument text file",
  ods: "an OpenDocument spreadsheet",
  odp: "an OpenDocument presentation",
};

const OLE: Record<string, string> = {
  doc: "a Word document",
  xls: "an Excel workbook",
  ppt: "a PowerPoint deck",
};

// --- the decision -----------------------------------------------------------

/**
 * Decide what a file is from its first bytes and its name.
 *
 * `size` is separate from `head.length` because a head is a slice: a 400 MB
 * PDF and a 4 KB one have the same head, and an empty file is the only case
 * where the difference matters.
 */
export function detect(name: string, head: Uint8Array, size: number): Detection {
  const extension = extensionOf(name);
  const claimed = BY_EXTENSION[extension] ?? null;

  if (size === 0) {
    return {
      format: "an empty file",
      route: claimed?.route ?? "files",
      verdict: "refused",
      arrives: null,
      mismatch: null,
      refusal: "There is nothing in this file to index. Nothing was changed on disk.",
    };
  }

  const content = fromBytes(head);

  if (content?.container === "ooxml") {
    const named = OOXML[extension];
    if (named === undefined) {
      return {
        format: "a zip archive",
        route: "files",
        verdict: "refused",
        arrives: null,
        mismatch: null,
        refusal: REFUSED_ARCHIVE,
      };
    }
    return { ...onRoute(named, "files"), mismatch: null, refusal: null };
  }

  if (content?.container === "ole") {
    return { ...onRoute(OLE[extension] ?? content.format, "files"), mismatch: null, refusal: null };
  }

  if (content !== null) {
    if (content.refusal !== undefined) {
      return {
        format: content.format,
        route: content.route,
        verdict: "refused",
        arrives: null,
        mismatch: disagreement(claimed?.format ?? null, content.format, extension),
        refusal: content.refusal,
      };
    }
    return {
      ...onRoute(content.format, content.route),
      mismatch: disagreement(claimed?.format ?? null, content.format, extension),
      refusal: null,
    };
  }

  if (looksTextual(head)) {
    const text = decode(head);
    // HTML first: a saved page is full of rows and would otherwise read as a
    // CSV, and one of those two routes works today while the other does not.
    if (extension === "html" || extension === "htm" || HTML_MARKERS.test(text)) {
      return {
        ...onRoute("an HTML page", "files"),
        mismatch: disagreement(claimed?.format ?? null, "an HTML page", extension),
        refusal: null,
      };
    }
    if (extension === "sql" || extension === "dump" || extension === "backup" || SQL_MARKERS.test(text)) {
      return { ...onRoute("a SQL dump", "dump"), mismatch: null, refusal: null };
    }
    if (extension === "csv" || extension === "tsv" || looksDelimited(text)) {
      const format = extension === "tsv" ? "a tab-separated file" : "a CSV file";
      return { ...onRoute(format, "table"), mismatch: null, refusal: null };
    }
    // Markdown is plain text with conventions, and no byte distinguishes it —
    // so the name decides, which is the one place the extension is the better
    // evidence. Getting it wrong costs nothing: both go to the same extractor,
    // and the user is told which one Askwell believed.
    const format = extension === "md" || extension === "markdown" ? "a Markdown document" : "plain text";
    return {
      ...onRoute(format, "files"),
      mismatch: disagreement(claimed?.format ?? null, format, extension),
      refusal: null,
    };
  }

  return {
    format: "an unrecognised file",
    route: claimed?.route ?? "files",
    verdict: "refused",
    arrives: null,
    mismatch: null,
    refusal: "Askwell could not tell what this file is from its contents.",
  };
}

/**
 * One line about one refused file: what it is called, what it turned out to
 * be, and why that stops here.
 *
 * The supported list is *not* in here. It is shown once beneath the whole
 * block instead — repeating the same sentence after each of five files is how
 * the one thing worth reading gets skipped. Composed here rather than in the
 * screen so that it is testable without a browser, which is the same reason
 * the rest of this module is pure.
 */
export function refusalLine(name: string, detection: Detection): string {
  const reason = detection.refusal === null ? "" : ` ${detection.refusal}`;
  return `${name} — ${detection.format}.${reason}`;
}

/**
 * One line about a file whose route is real but has not been built yet.
 *
 * Deliberately not a refusal, and worded so it cannot be read as one. Somebody
 * whose material is a folder of CSV exports needs to know that Askwell will
 * take them, and when — telling them "unsupported format" is a lie that costs
 * the product a user who was a good fit.
 */
export function laterLine(name: string, detection: Detection): string {
  return `${name} — ${detection.format}. Askwell reads these from ${detection.arrives}; nothing was added for it now.`;
}

/**
 * The sentence for a file whose name and contents disagree.
 *
 * Said plainly and in the user's own terms — they named it `.pdf`, so the
 * message starts there. Silence here is the dishonest option: the file would
 * be indexed as what it really is and the user would never learn that one of
 * their documents is not what its name says, which is worth knowing on its own.
 */
function disagreement(claimed: string | null, actual: string, extension: string): string | null {
  if (claimed === null || extension === "") return null;
  if (claimed === actual) return null;
  return `Named .${extension}, but the contents are ${actual}. Askwell goes by the contents.`;
}

// --- counting a drop --------------------------------------------------------

export interface TreeEntry {
  name: string;
  directory: boolean;
}

export interface Found<E> {
  entry: E;
  /** Path within what was dropped. Empty for a bare file. */
  relativePath: string;
}

export interface Expansion<E> {
  files: Found<E>[];
  folders: number;
  /** True when `MAX_FILES` stopped the walk. Never silently. */
  truncated: boolean;
}

/**
 * Expand a drop into the files it actually contains.
 *
 * Breadth-first, so a wide shallow folder — which is what a folder of
 * contracts is — is counted before Askwell descends into whatever deep tree
 * happens to be sitting beside it.
 *
 * The reader is a parameter rather than the browser's own directory reader
 * because that one is callback-based, batched, and impossible to exercise
 * outside a browser. Here the walk is the part with the interesting behaviour
 * (nesting, ordering, the cap) and it is tested; `selection.ts` holds the thin
 * adapter that is not.
 */
export async function flatten<E extends TreeEntry>(
  roots: E[],
  children: (entry: E) => Promise<E[]>,
  limit: number = MAX_FILES,
): Promise<Expansion<E>> {
  const files: Found<E>[] = [];
  let folders = 0;
  let truncated = false;

  let level: Found<E>[] = roots.map((entry) => ({ entry, relativePath: entry.name }));

  while (level.length > 0) {
    const next: Found<E>[] = [];
    for (const found of level) {
      if (!found.entry.directory) {
        if (files.length >= limit) {
          truncated = true;
          continue;
        }
        files.push(found);
        continue;
      }
      folders += 1;
      for (const child of await children(found.entry)) {
        next.push({ entry: child, relativePath: `${found.relativePath}/${child.name}` });
      }
    }
    level = next;
  }

  return { files, folders, truncated };
}

// --- what the screen says about a batch -------------------------------------

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * The count and the size, before anything starts.
 *
 * The ticket asks for "a count and an honest estimate". The count is here; the
 * estimate deliberately is not a duration, because nothing in this repository
 * has yet measured how long embedding a megabyte takes on a CPU and a number
 * invented here would be read as measured. What is honest today is the size of
 * what was dropped and the fact that the timing arrives with the thing that can
 * actually observe it (`M1-ADD-ING-025`). A wrong estimate is worse than a
 * missing one: it is the number someone plans their afternoon around.
 */
export function describeBatch(count: number, bytes: number): string {
  return `${plural(count, "file", "files")}, ${formatSize(bytes)}.`;
}
