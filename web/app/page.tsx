import { ThemeToggle } from "@/components/ui/theme-toggle";

/**
 * The token demonstration. Not a screen — screens arrive with M0-SHELL-FE-017.
 *
 * It exists so that the affordances in `docs/ux/design-system.md` §7 can be
 * seen to survive a theme switch. Reading the CSS does not tell you whether a
 * raised surface still reads as raised on a dark ground; looking at it does.
 */
export default function TokenDemonstration() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-8 p-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 style={{ fontSize: "var(--t-display)", lineHeight: "var(--t-display-lh)" }}>
            Askwell
          </h1>
          <p className="ask-micro mt-1">Design tokens · not a screen</p>
        </div>
        <ThemeToggle />
      </header>

      <section className="ask-prose">
        Serif is for language. This is the face an answer, a document excerpt, or a question put
        to the user is set in. Everything else on this page is mono, because everything else is
        the machine talking about itself.
      </section>

      {/* A source card: the margin unit. Its left edge is the meaning-carrying
          line, which is why --rule-strong and --provenance exist separately
          from --rule. */}
      <section
        className="ask-carries-meaning p-4"
        style={{ background: "var(--surface)", borderRadius: "var(--radius)" }}
      >
        <p className="ask-micro">contract.pdf · p.14</p>
        <p className="ask-prose mt-2">
          The exact retrieved passage sits here, in serif, because it is language the user can
          go and check.
        </p>
      </section>

      {/* §7 affordance: an input is inset, a primary action is filled. Both
          use depth tokens, so both survive the theme switch. */}
      <section className="flex flex-col gap-3">
        <label className="ask-micro" htmlFor="demo">
          An input is inset
        </label>
        <input id="demo" className="ask-input w-full px-3" placeholder="Ask a question" />
        <button type="button" className="ask-action-primary px-4">
          A primary action is filled
        </button>
        <a href="#" className="ask-navigates inline-block w-fit border px-3 py-2">
          A navigating control lifts on hover
        </a>
      </section>

      {/* Colour encodes epistemics. Each swatch is labelled in words as well as
          hue, because §8 forbids colour being the only signal. */}
      <section className="flex flex-col gap-2">
        <p className="ask-micro">Colour encodes epistemics</p>
        <p style={{ color: "var(--provenance)" }}>Traceable to a source</p>
        <p style={{ color: "var(--inferred)" }}>Askwell guessed — correct me</p>
        <p style={{ color: "var(--muted)" }}>Labels, metadata, timestamps</p>
        <p style={{ color: "var(--alarm)" }}>Something broke — never abstention</p>
      </section>

      <hr style={{ borderTop: "1px solid var(--rule)" }} />
      <p className="ask-micro">
        Decorative hairline above. The card&rsquo;s left edge is not decorative.
      </p>
    </main>
  );
}
