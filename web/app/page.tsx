import { VERSION } from "@/lib/version";

/**
 * Ask — the empty state.
 *
 * There is nothing to ask yet: retrieval arrives in M1. What is here is what
 * `docs/states-and-edge-cases.md` calls the first state a user meets, and it
 * says what to do next rather than showing a composer that cannot work.
 *
 * The token demonstration this replaced lives on in the design lab, which is
 * where a demonstration belongs.
 */
export default function AskPage() {
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
          Ask your own material
        </h1>
        <p className="ask-micro mt-1">Askwell {VERSION} · nothing leaves this machine</p>
      </div>

      <p className="ask-prose">
        Askwell answers from documents and databases you have added, and cites what it
        used. When nothing in your material answers a question, it says so instead of
        guessing — which is the whole reason it is worth pointing at a confidential
        corpus.
      </p>

      <div
        className="flex flex-col gap-2 px-4 py-3"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--rule)",
          borderRadius: "var(--radius)",
        }}
      >
        <p className="ask-micro">Nothing added yet</p>
        <p className="ask-prose" style={{ color: "var(--muted)" }}>
          There is nothing to ask about until you add a source. Adding files, a
          spreadsheet, a database dump or a live connection arrives in the next
          milestone — the shell, the stack and the assistant are what work today.
        </p>
      </div>
    </section>
  );
}
