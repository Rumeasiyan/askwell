import Link from "next/link";

/**
 * Library — a placeholder.
 *
 * The screen itself arrives later. What is here is its empty state, because
 * `docs/states-and-edge-cases.md` requires every surface to have one and a
 * route stub with nothing in it teaches the next person that empty states are
 * optional.
 */
export default function LibraryPage() {
  return (
    <section className="flex flex-col gap-3">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>Library</h1>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Every source you have added lives here — files, spreadsheets, database dumps and live connections.
      </p>
      <div
        className="flex flex-col gap-3 px-4 py-3"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--radius)",
          border: "1px solid var(--rule)",
        }}
      >
        <p className="ask-prose">
          Nothing has been added yet. Drop files or a folder anywhere on this window, or add
          them from the add-source screen. What has been added is not readable yet —
          extraction and indexing are the next piece of work.
        </p>
        <div>
          <Link
            href="/sources/add/"
            className="ask-navigates inline-block px-4 py-2"
            style={{ border: "1px solid var(--rule-strong)", fontSize: "var(--t-ui)" }}
          >
            Add a source
          </Link>
        </div>
      </div>
    </section>
  );
}
