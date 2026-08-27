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
      <p
        className="ask-prose px-4 py-3"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--radius)",
          border: "1px solid var(--rule)",
        }}
      >
        Nothing has been added yet. Adding a source is the first thing Askwell asks you to do, and it arrives in M1.
      </p>
    </section>
  );
}
