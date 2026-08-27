"use client";

import { useEffect, useRef, useState } from "react";

import {
  ROUTES,
  SUPPORTED_SUMMARY,
  describeBatch,
  laterLine,
  plural,
  refusalLine,
} from "@/lib/add-source";
import { HOST_GIVES_PATHS, fromFiles } from "@/lib/selection";
import { type Batch, type Item, laterIn, refusedIn, supportedIn, useAdd } from "./add-state";

/**
 * Add a source. `docs/ux/add-source.md` §1, §2 and §5.
 *
 * Four routes, one of which works today. The other three are **present and
 * dated** rather than hidden: someone whose material is a MySQL export needs to
 * know it has a home here eventually, and a screen that shows only what is
 * finished tells them it does not.
 *
 * The in-place statement is made once, at the top, before anything is dropped.
 * Someone about to add 40 GB of case files needs it before they start — after
 * is where it becomes an apology.
 */
export function AddScreen() {
  const { batches, added, rejected } = useAdd();

  return (
    <section className="flex flex-col gap-5">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
          Add a source
        </h1>
        <p className="ask-micro mt-1">
          {added === 0
            ? "Nothing added on this machine yet"
            : `${plural(added, "file", "files")} added on this machine`}
          {rejected === 0 ? "" : `, ${plural(rejected, "file", "files")} turned away`}{" "}
          · these counts are local and go nowhere
        </p>
      </div>

      {/* The statement. Said once, in prose, at full size — not as a footnote,
          because it is the thing that decides whether adding 40 GB is safe. */}
      <p className="ask-prose">
        <strong>Askwell indexes your files where they are.</strong> Nothing is copied, moved
        or uploaded, so adding a large library costs no disk space beyond the index — and
        every citation opens the file you already have. It does mean Askwell has to be told
        which folders it may open, which it will ask about the first time you add something
        from a new one.
      </p>

      <FilesRoute />

      {batches.length > 0 ? (
        <div className="flex flex-col gap-3" aria-live="polite">
          {batches.map((batch) => (
            <BatchCard key={batch.id} batch={batch} />
          ))}
        </div>
      ) : null}

      <LaterRoutes />
    </section>
  );
}

// --- the files route --------------------------------------------------------

function FilesRoute() {
  const { accept } = useAdd();
  const files = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);

  // `webkitdirectory` is how every browser offers a directory chooser and it
  // is not in React's typed attributes, so it is set on the element instead of
  // cast onto the props. Without it the folder button is a second file button.
  useEffect(() => {
    folder.current?.setAttribute("webkitdirectory", "");
  }, []);

  return (
    <div
      className="flex flex-col gap-3 px-5 py-4"
      style={{
        background: "var(--surface)",
        border: "1px dashed var(--rule-strong)",
        borderRadius: "var(--radius)",
      }}
    >
      <div>
        <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>Files</h2>
        <p className="ask-micro mt-1">{SUPPORTED_SUMMARY}</p>
      </div>

      <p className="ask-prose">
        Drop files or a folder anywhere in this window — you do not have to be on this
        screen. Askwell works out what each file is from its contents.
      </p>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => files.current?.click()}
          className="ask-action-primary px-4"
          style={{ fontSize: "var(--t-ui)" }}
        >
          Choose files
        </button>
        <button
          type="button"
          onClick={() => folder.current?.click()}
          className="ask-navigates px-4"
          style={{
            border: "1px solid var(--rule-strong)",
            minHeight: "var(--control-height-primary)",
            fontSize: "var(--t-ui)",
          }}
        >
          Choose a folder
        </button>
      </div>

      {/* Named, not uploaded. These inputs exist because a browser has no other
          way to let someone point at a file; nothing is posted anywhere, and
          only the first few kilobytes of each file are ever read. */}
      <input
        ref={files}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => {
          if (event.target.files !== null) accept(fromFiles(event.target.files));
          event.target.value = "";
        }}
      />
      <input
        ref={folder}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => {
          if (event.target.files !== null) accept(fromFiles(event.target.files));
          event.target.value = "";
        }}
      />

      {HOST_GIVES_PATHS ? null : (
        <p className="ask-micro">
          A browser will not tell Askwell where a file lives, only what it is called — so it
          asks once, per drop, which folder they came from. The desktop application answers
          that itself.
        </p>
      )}
    </div>
  );
}

// --- a batch ----------------------------------------------------------------

function BatchCard({ batch }: { batch: Batch }) {
  const { forget } = useAdd();
  const detected = batch.items.filter((item) => item.detection !== null).length;
  const supported = supportedIn(batch);
  const refused = refusedIn(batch);
  const later = laterIn(batch);
  const mismatches = batch.items.filter(
    (item) => item.detection !== null && item.detection.mismatch !== null,
  );

  return (
    <article
      className="flex flex-col gap-2 px-5 py-4"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--rule)",
        borderRadius: "var(--radius)",
      }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="ask-micro">{PHASE_LABELS[batch.phase]}</span>
        <button
          type="button"
          onClick={() => forget(batch.id)}
          className="ask-navigates px-2 py-1"
          style={{ border: "1px solid var(--rule)", color: "var(--muted)", fontSize: "var(--t-meta)" }}
        >
          {batch.phase === "queued" ? "Clear" : "Cancel"}
        </button>
      </div>

      <p style={{ fontSize: "var(--t-ui)", lineHeight: "var(--t-ui-lh)" }}>
        {describeBatch(batch.items.length, batch.bytes)}
        {batch.folders > 0 ? ` From ${plural(batch.folders, "folder", "folders")}.` : ""}
      </p>

      {batch.phase === "detecting" ? (
        <p style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
          Working out what each one is — {detected} of {batch.items.length} so far. Only the
          first few kilobytes of each file are read.
        </p>
      ) : null}

      {batch.truncated ? (
        <Note tone="inferred" heading="More than Askwell will take in one go">
          The first {batch.items.length} files were taken and the rest were left. Nothing was
          changed on disk. Add the remainder as a second drop, or nominate the folder and add
          it in parts.
        </Note>
      ) : null}

      {supported.length > 0 ? (
        <p style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
          {summarise(supported)}
        </p>
      ) : null}

      {refused.length > 0 ? <Refusals items={refused} /> : null}
      {later.length > 0 ? <Later items={later} /> : null}
      {mismatches.length > 0 ? <Mismatches items={mismatches} /> : null}

      {batch.phase === "empty" ? (
        <Note tone="muted" heading="Nothing in that drop">
          Askwell found no files — an empty folder, or one holding only other empty folders.
          Nothing was changed on disk. {SUPPORTED_SUMMARY}
        </Note>
      ) : null}

      {batch.phase === "locating" ? <Locate batch={batch} /> : null}

      {batch.phase === "queued" ? (
        <Note tone="provenance" heading="Queued">
          {plural(supported.length, "file is", "files are")} queued from{" "}
          <code>{batch.folder}</code>. Reading and indexing them is the next piece of work —
          it arrives with background ingestion, and nothing in your material is searchable
          until it does. Nothing has been copied.
        </Note>
      ) : null}

      {batch.phase === "refused" ? (
        <Note tone="alarm" heading="Nothing here could be added">
          Each file is listed above with the reason, and nothing was added for any of them.
          Nothing on disk was changed.
        </Note>
      ) : null}

      {batch.phase === "later" ? (
        <Note tone="inferred" heading="Askwell recognised these, and cannot read them yet">
          Nothing was added, and nothing on disk was changed. These are not the wrong kind of
          file — their route is being built, and the date is above.
        </Note>
      ) : null}

      {batch.failure === null ? null : (
        <Note tone="alarm" heading="Askwell is not answering">
          {batch.failure}
        </Note>
      )}
    </article>
  );
}

const PHASE_LABELS: Record<Batch["phase"], string> = {
  detecting: "Detecting",
  locating: "Where are these?",
  queued: "Queued",
  refused: "Refused",
  later: "Arrives later",
  empty: "Empty",
};

/**
 * "12 × a PDF document · 3 × a Word document", by what the contents said.
 *
 * Only ever given the files Askwell will index today — the ones for a later
 * milestone are listed separately with their date, and mixing the two into one
 * tally is what made the queue and the four-route list contradict each other.
 */
function summarise(items: Item[]): string {
  const counts = new Map<string, number>();
  for (const item of items) {
    const format = item.detection?.format ?? "an unrecognised file";
    counts.set(format, (counts.get(format) ?? 0) + 1);
  }
  return [...counts.entries()].map(([format, count]) => `${count} × ${format}`).join(" · ");
}

function Mismatches({ items }: { items: Item[] }) {
  return (
    <Note tone="inferred" heading="Named one thing, contains another">
      {items.slice(0, 5).map((item) => (
        <span key={item.id} className="block">
          {item.relativePath} — {item.detection?.mismatch}
        </span>
      ))}
      {items.length > 5 ? <span className="block">and {items.length - 5} more.</span> : null}
    </Note>
  );
}

/**
 * The rejection, per file, with the supported list once beneath.
 *
 * Per file because one bad file in a drop of sixty must not take the other
 * fifty-nine with it — that is the whole of this ticket's third scope line, and
 * it is why this is a list rather than a batch-level verdict. Each line names
 * the file *and* what its contents turned out to be, because "not added" with
 * no type is indistinguishable from a bug.
 *
 * The supported list sits at the bottom, once. Five files refused should not
 * mean the same sentence five times: repetition is how the one line worth
 * reading gets skipped.
 */
function Refusals({ items }: { items: Item[] }) {
  return (
    <Note tone="alarm" heading={`${plural(items.length, "file", "files")} not added`}>
      {items.slice(0, 5).map((item) => (
        <span key={item.id} className="block">
          {item.detection === null ? item.relativePath : refusalLine(item.relativePath, item.detection)}
        </span>
      ))}
      {items.length > 5 ? <span className="block">and {items.length - 5} more.</span> : null}
      <span className="block mt-2">{SUPPORTED_SUMMARY}</span>
    </Note>
  );
}

/**
 * Recognised, and its route has not been built yet.
 *
 * Kept apart from `Refusals` in colour and in wording. A CSV listed under
 * "not added" alongside a Windows executable tells somebody whose material is
 * mostly exports that Askwell is not for them, which is false — and it is the
 * one thing the four-route screen below is arranged to avoid saying.
 */
function Later({ items }: { items: Item[] }) {
  return (
    <Note tone="inferred" heading={`${plural(items.length, "file", "files")} for a later milestone`}>
      {items.slice(0, 5).map((item) => (
        <span key={item.id} className="block">
          {item.detection === null ? item.relativePath : laterLine(item.relativePath, item.detection)}
        </span>
      ))}
      {items.length > 5 ? <span className="block">and {items.length - 5} more.</span> : null}
    </Note>
  );
}

// --- saying where they are --------------------------------------------------

/**
 * The one question the browser forces.
 *
 * The typed path is the same seam `docs/ux/add-source.md` §7 uses for
 * nominating a folder, and `M7-TAURI-FE-182` removes this step entirely rather
 * than improving it — the desktop shell knows the path already.
 */
function Locate({ batch }: { batch: Batch }) {
  const { locate, nominateFolder } = useAdd();
  const [path, setPath] = useState(batch.folder ?? "");
  const [busy, setBusy] = useState(false);

  const first = supportedIn(batch)[0];
  const top =
    first !== undefined && first.relativePath.includes("/")
      ? (first.relativePath.split("/")[0] ?? null)
      : null;

  async function submit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    setBusy(true);
    try {
      await locate(batch.id, path);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {batch.prompt === null ? null : (
        <Note tone="inferred" heading={batch.prompt.headline}>
          {batch.prompt.explanation}
          <span className="mt-2 block">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void nominateFolder(batch.id).finally(() => setBusy(false));
              }}
              className="ask-navigates px-3 py-1"
              style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
            >
              Nominate {batch.prompt.suggested_root}
            </button>
          </span>
        </Note>
      )}

      <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-2">
        <label htmlFor={`folder-${batch.id}`} style={{ fontSize: "var(--t-ui)" }}>
          {top === null
            ? "Which folder are these files in?"
            : `Which folder is “${top}” in?`}
        </label>
        <div className="flex gap-2">
          <input
            id={`folder-${batch.id}`}
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder="/home/you/clients"
            spellCheck={false}
            autoComplete="off"
            className="ask-input flex-1 px-3"
            style={{ fontFamily: "var(--font-app)", fontSize: "var(--t-ui)" }}
          />
          <button
            type="submit"
            disabled={busy || path.trim() === ""}
            className="ask-action-primary px-4"
            style={{ fontSize: "var(--t-ui)" }}
          >
            Add them
          </button>
        </div>
        <p className="ask-micro">
          The whole path. Askwell needs it because it opens the file where it is rather than
          keeping a copy.
        </p>
      </form>
    </div>
  );
}

// --- the three that arrive later --------------------------------------------

function LaterRoutes() {
  return (
    <div className="flex flex-col gap-2">
      <h2 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
        The other three routes
      </h2>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Shown rather than hidden, so you can see whether your material has a home here.
        None of them does anything yet.
      </p>
      {ROUTES.filter((route) => route.arrives !== null).map((route) => (
        <article
          key={route.id}
          className="flex flex-col gap-1 px-5 py-3"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--rule)",
            borderRadius: "var(--radius)",
          }}
        >
          <div className="flex items-baseline justify-between gap-3">
            <span style={{ fontSize: "var(--t-ui)" }}>{route.title}</span>
            <span className="ask-micro" style={{ color: "var(--inferred)" }}>
              Arrives in {route.arrives}
            </span>
          </div>
          <p style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
            {route.accepts}
          </p>
        </article>
      ))}
    </div>
  );
}

function Note({
  tone,
  heading,
  children,
}: {
  tone: "muted" | "alarm" | "inferred" | "provenance";
  heading: string;
  children: React.ReactNode;
}) {
  const colour =
    tone === "muted"
      ? "var(--muted)"
      : tone === "alarm"
        ? "var(--alarm)"
        : tone === "inferred"
          ? "var(--inferred)"
          : "var(--provenance)";
  return (
    <div
      role="status"
      className="ask-carries-meaning px-4 py-3"
      style={{
        background: "var(--sunk)",
        borderLeftColor: colour,
        borderRadius: "var(--radius)",
      }}
    >
      <p className="ask-micro" style={{ color: colour }}>
        {heading}
      </p>
      <p className="mt-1" style={{ fontSize: "var(--t-meta)", lineHeight: "var(--t-meta-lh)" }}>
        {children}
      </p>
    </div>
  );
}
