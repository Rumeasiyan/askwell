/**
 * Memory — a placeholder.
 *
 * The screen itself arrives later. What is here is its empty state, because
 * `docs/states-and-edge-cases.md` requires every surface to have one and a
 * route stub with nothing in it teaches the next person that empty states are
 * optional.
 */
export default function MemoryPage() {
  return (
    <section className="flex flex-col gap-3">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>Memory</h1>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        What Askwell has learned about your material, and where each fact came from.
      </p>
      <p
        className="ask-prose px-4 py-3"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--radius)",
          border: "1px solid var(--rule)",
        }}
      >
        Empty until Askwell has asked you something. Every fact here will say whether you supplied it or Askwell inferred it.
      </p>
    </section>
  );
}
