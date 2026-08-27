/**
 * Settings — a placeholder.
 *
 * The screen itself arrives later. What is here is its empty state, because
 * `docs/states-and-edge-cases.md` requires every surface to have one and a
 * route stub with nothing in it teaches the next person that empty states are
 * optional.
 */
export default function SettingsPage() {
  return (
    <section className="flex flex-col gap-3">
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>Settings</h1>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Deployment profile, retention, and what Askwell has been refused from doing.
      </p>
      <p
        className="ask-prose px-4 py-3"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--radius)",
          border: "1px solid var(--rule)",
        }}
      >
        The settings that exist today are environment variables. The surface for them arrives in M7.
      </p>
    </section>
  );
}
